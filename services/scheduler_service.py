from __future__ import annotations

import logging
from urllib.parse import urlparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.config import Settings
from services.consolidated_document_service import ConsolidatedDocumentService
from services.backoffice_service import BackofficeService
from services.docusign_service import DocusignError, DocusignService
from services.sheets_service import SheetsService
from services.statuses import CaseStatus, RendicionStatus, normalize_rendicion_status
from services.whatsapp_service import WhatsAppService
from utils.helpers import json_loads, normalize_whatsapp_phone, parse_float, parse_iso_date, utc_now_iso


logger = logging.getLogger(__name__)

WAIT_SUBMISSION_CLOSURE_CONFIRMATION = "WAIT_SUBMISSION_CLOSURE_CONFIRMATION"
SUBMISSION_CLOSURE_STEP = "submission_closure_confirmation"
SUBMISSION_CLOSURE_TIMEOUT_HOURS = 24
ACTIVE_RECEIPT_STATES = {"PROCESSING", "NEEDS_INFO", "CONFIRM_SUMMARY"}

_COUNTRY_TIMEZONE_MAP = {
    "CHILE": "America/Santiago",
    "PERU": "America/Lima",
    "PERÚ": "America/Lima",
    "CHINA": "Asia/Shanghai",
    "MEXICO": "America/Mexico_City",
    "MÉXICO": "America/Mexico_City",
    "ARGENTINA": "America/Argentina/Buenos_Aires",
    "COLOMBIA": "America/Bogota",
    "BRAZIL": "America/Sao_Paulo",
    "BRASIL": "America/Sao_Paulo",
    "SPAIN": "Europe/Madrid",
    "ESPAÑA": "Europe/Madrid",
    "FRANCE": "Europe/Paris",
    "ITALY": "Europe/Rome",
    "GERMANY": "Europe/Berlin",
    "DEUTSCHLAND": "Europe/Berlin",
    "UNITED STATES": "America/New_York",
    "USA": "America/New_York",
    "U.S.A.": "America/New_York",
    "ESTADOS UNIDOS": "America/New_York",
}

_DESTINATION_TIMEZONE_MAP = {
    "santiago": "America/Santiago",
    "lima": "America/Lima",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "cdmx": "America/Mexico_City",
    "mexico city": "America/Mexico_City",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "bogota": "America/Bogota",
    "bogotá": "America/Bogota",
    "sao paulo": "America/Sao_Paulo",
    "são paulo": "America/Sao_Paulo",
    "madrid": "Europe/Madrid",
    "paris": "Europe/Paris",
    "rome": "Europe/Rome",
    "roma": "Europe/Rome",
    "berlin": "Europe/Berlin",
    "new york": "America/New_York",
    "miami": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
}


@dataclass
class SchedulerService:
    settings: Settings
    sheets_service: SheetsService
    whatsapp_service: WhatsAppService
    consolidated_document_service: ConsolidatedDocumentService
    docusign_service: DocusignService

    def start(self) -> None:
        # MVP: se ejecuta por endpoint + cron externo/job scheduler.
        return None

    def run_submission_reminders(
        self,
        *,
        dry_run: bool = False,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        now = self._ensure_utc(now_utc)
        report: dict[str, Any] = {
            "ok": True,
            "dry_run": dry_run,
            "now_utc": now.isoformat(),
            "window_minutes": self._window_minutes,
            "processed_cases": 0,
            "due_cases": 0,
            "sent_count": 0,
            "skipped_count": 0,
            "submission_closure_prompted_count": 0,
            "submission_closure_closed_count": 0,
            "errors": [],
            "items": [],
        }

        for expense_case in self.sheets_service.list_active_expense_cases():
            report["processed_cases"] += 1

            reminder_item = self._evaluate_case_reminder(
                expense_case=expense_case,
                now_utc=now,
                dry_run=dry_run,
            )
            report["items"].append(reminder_item)
            if reminder_item.get("due"):
                report["due_cases"] += 1
            reminder_outcome = reminder_item.get("outcome")
            if reminder_outcome == "sent":
                report["sent_count"] += 1
            elif reminder_outcome != "not_due":
                report["skipped_count"] += 1
            if reminder_item.get("error"):
                report["errors"].append(reminder_item["error"])

            closure_item = self._evaluate_submission_closure(
                expense_case=expense_case,
                now_utc=now,
                dry_run=dry_run,
            )
            report["items"].append(closure_item)
            closure_outcome = closure_item.get("outcome")
            if closure_outcome == "sent_closure_prompt":
                report["submission_closure_prompted_count"] += 1
            elif closure_outcome in {"closed_timeout", "closed_timeout_no_notify"}:
                report["submission_closure_closed_count"] += 1
            elif closure_outcome != "not_due":
                report["skipped_count"] += 1
            if closure_item.get("error"):
                report["errors"].append(closure_item["error"])

        return report

    def run_trip_reminders(
        self,
        *,
        dry_run: bool = False,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        return self.run_submission_reminders(dry_run=dry_run, now_utc=now_utc)

    def handle_submission_closure_user_response(
        self,
        *,
        phone: str,
        message: str,
        now_utc: datetime | None = None,
    ) -> str | None:
        now = self._ensure_utc(now_utc)
        conversation = self.sheets_service.get_conversation(phone) or {}
        state = str(conversation.get("state", "") or "")
        if state in ACTIVE_RECEIPT_STATES:
            return None

        context = self._normalize_conversation_context(conversation.get("context_json"))
        pending = self._get_latest_pending_submission_closure(context)
        if not pending:
            return None

        case_id = str(pending.get("case_id", pending.get("trip_id", "")) or "").strip()
        if not case_id:
            return None

        entry = pending["entry"]
        deadline = self._parse_datetime_utc(entry.get("deadline_at_utc"))
        if deadline and now >= deadline:
            self._close_submission(
                phone=phone,
                case_id=case_id,
                context=context,
                closure_status="closed_timeout",
                closure_reason="timeout_24h_no_response",
                closure_response="timeout",
                responded_at=now,
                closed_at=now,
            )
            return (
                "Cerré esta rendición automáticamente porque la ventana de 24 horas ya expiró. "
                "Si necesitas registrar más documentos, avisa a soporte para reabrirla."
            )

        response = self._parse_submission_closure_response(message)
        if response is None:
            return (
                "Para cerrar correctamente la rendición necesito una respuesta explícita. "
                "Por favor responde solo *SI* o *NO* a: ¿tienes más documentos por enviar?"
            )

        if response == "yes":
            responded_at_iso = now.isoformat()
            updated_entry = {
                **entry,
                "status": "kept_open_by_user",
                "response": "yes",
                "responded_at_utc": responded_at_iso,
                "deadline_at_utc": None,
            }
            self._upsert_submission_closure_context(
                phone=phone,
                context=context,
                case_id=case_id,
                submission_closure_entry=updated_entry,
                state="WAIT_RECEIPT",
                current_step="",
            )
            self.sheets_service.update_expense_case(
                case_id,
                {
                    "closure_status": "kept_open_by_user",
                    "closure_response": "yes",
                    "closure_responded_at": responded_at_iso,
                    "closure_deadline_at": "",
                },
            )
            return (
                "Perfecto, dejo la rendición abierta para que sigas enviando documentos. "
                "Cuando ya no tengas más, responde *NO* y la cierro."
            )

        self._close_submission(
            phone=phone,
            case_id=case_id,
            context=context,
            closure_status="closed_by_user",
            closure_reason="user_confirmed_no_more_receipts",
            closure_response="no",
            responded_at=now,
            closed_at=now,
        )
        return self._deliver_submission_closure_package(phone=phone, case_id=case_id)

    def handle_simple_document_confirmation_user_response(
        self,
        *,
        phone: str,
        message: str,
        now_utc: datetime | None = None,
    ) -> str | None:
        now = self._ensure_utc(now_utc)
        conversation = self.sheets_service.get_conversation(phone) or {}
        state = str(conversation.get("state", "") or "")
        if state in ACTIVE_RECEIPT_STATES:
            return None

        expense_case = self._get_latest_pending_simple_confirmation_case(phone)
        if not expense_case:
            return None

        response = self._parse_submission_closure_response(message)
        if response is None:
            return (
                "Para confirmar el cierre documental de tu rendición responde solo *SI* o *NO*.\n"
                "Responde *SI* si estás de acuerdo con el consolidado.\n"
                "Responde *NO* si necesitas que la empresa lo revise antes de continuar."
            )

        case_id = str(expense_case.get("case_id", expense_case.get("trip_id", "")) or "").strip()
        completed_at = now.isoformat()
        latest_document = self.sheets_service.get_latest_expense_case_document_by_phone_case(phone, case_id) or {}
        document_id = str(latest_document.get("document_id", "") or "").strip()

        if response == "yes":
            backoffice = BackofficeService(self.sheets_service)
            if document_id:
                self.sheets_service.update_expense_case_document(
                    document_id,
                    {
                        "updated_at": completed_at,
                        "signature_provider": "simple_closure",
                        "signature_status": "completed",
                        "signature_completed_at": completed_at,
                        "signature_error": "",
                    },
                )
            self.sheets_service.update_expense_case(
                case_id,
                {
                    "user_confirmed_at": completed_at,
                    "user_confirmation_status": "confirmed_simple",
                    "rendicion_status": RendicionStatus.APPROVED,
                    "updated_at": completed_at,
                },
            )
            finalized_case = backoffice.sync_case_settlement(case_id)
            primary_message = backoffice.build_case_settlement_whatsapp_message(finalized_case)
            follow_up_message = backoffice.build_case_settlement_bank_details_message(finalized_case)
            if follow_up_message:
                self.whatsapp_service.send_outbound_text(phone, follow_up_message)
            return primary_message

        if document_id:
            self.sheets_service.update_expense_case_document(
                document_id,
                {
                    "updated_at": completed_at,
                    "signature_provider": "simple_closure",
                    "signature_status": "declined",
                    "signature_declined_at": completed_at,
                    "signature_error": "",
                },
            )
        self.sheets_service.update_expense_case(
            case_id,
            {
                "user_confirmation_status": "rejected_simple",
                "updated_at": completed_at,
            },
        )
        return (
            "Entendido. Dejé la rendición sin confirmación final por ahora. "
            "Un operador podrá revisarla y reenviarte la confirmación cuando corresponda."
        )

    def handle_direct_submission_close_command(
        self,
        *,
        phone: str,
        message: str,
        now_utc: datetime | None = None,
    ) -> str | None:
        if not self._is_direct_close_command(message):
            return None

        now = self._ensure_utc(now_utc)
        conversation = self.sheets_service.get_conversation(phone) or {}
        state = str(conversation.get("state", "") or "")
        context = self._normalize_conversation_context(conversation.get("context_json"))
        pending_receipts = self._pending_receipts_count(context)

        if pending_receipts > 0 or state in ACTIVE_RECEIPT_STATES:
            return (
                "Todavía estoy procesando documentos de esta rendición. "
                "Espera a que termine y luego vuelve a enviar *CERRAR*."
            )

        expense_case = self.sheets_service.get_active_expense_case_by_phone(phone) or {}
        case_id = str(expense_case.get("case_id", expense_case.get("trip_id", "")) or "").strip()
        if not case_id:
            return "No encontré una rendición activa para cerrar."

        self._close_submission(
            phone=phone,
            case_id=case_id,
            context=context,
            closure_status="closed_by_user",
            closure_reason="user_requested_close_command",
            closure_response="no",
            responded_at=now,
            closed_at=now,
        )
        return self._deliver_submission_closure_package(phone=phone, case_id=case_id)

    def handle_trip_closure_user_response(
        self,
        *,
        phone: str,
        message: str,
        now_utc: datetime | None = None,
    ) -> str | None:
        return self.handle_submission_closure_user_response(
            phone=phone,
            message=message,
            now_utc=now_utc,
        )

    @property
    def _window_minutes(self) -> int:
        return max(1, int(getattr(self.settings, "scheduler_reminder_window_minutes", 10) or 10))

    def _ensure_utc(self, value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _evaluate_case_reminder(
        self,
        *,
        expense_case: dict[str, Any],
        now_utc: datetime,
        dry_run: bool,
    ) -> dict[str, Any]:
        phone = normalize_whatsapp_phone(expense_case.get("phone"))
        case_id = str(expense_case.get("case_id", expense_case.get("trip_id", "")) or "").strip()
        timezone_name = self._resolve_case_timezone(expense_case)
        local_now = now_utc.astimezone(ZoneInfo(timezone_name))
        local_date = local_now.date()
        context_label = str(expense_case.get("context_label", expense_case.get("destination", "")) or "").strip()

        item: dict[str, Any] = {
            "item_type": "reminder",
            "case_id": case_id,
            "phone": phone,
            "context_label": context_label,
            "country": expense_case.get("country"),
            "timezone": timezone_name,
            "local_now": local_now.isoformat(),
            "due": False,
            "outcome": "not_due",
        }

        if not phone:
            item["outcome"] = "skipped_invalid_phone"
            return item

        if normalize_rendicion_status(expense_case.get("rendicion_status")) != RendicionStatus.OPEN:
            item["outcome"] = "skipped_non_open_case"
            return item

        if not self._case_is_active_on_local_date(expense_case, local_date):
            item["outcome"] = "skipped_outside_submission_window"
            return item

        start_intro_key = self._submission_start_intro_key(case_id=case_id, local_date=local_date.isoformat())
        if self._submission_start_intro_due(expense_case=expense_case, local_now=local_now) and not self._reminder_already_sent(
            phone, start_intro_key
        ):
            item["due"] = True
            item["slot"] = "submission_start_intro"
            item["reminder_key"] = start_intro_key
            messages = self._build_submission_start_intro_messages(expense_case=expense_case)
            message = "\n".join(messages)
            item["message"] = message
            item["messages"] = messages

            if dry_run:
                item["outcome"] = "sent"
                item["dry_run"] = True
                return item

            try:
                send_results = [
                    self.whatsapp_service.send_outbound_text(phone, outbound_message)
                    for outbound_message in messages
                ]
            except Exception as exc:  # pragma: no cover - depends on Twilio/network
                logger.exception("Submission start intro send failed case_id=%s phone=%s", case_id, phone)
                item["outcome"] = "error"
                item["error"] = str(exc)
                return item

            self._mark_reminder_sent(
                phone=phone,
                reminder_key=start_intro_key,
                payload={
                    "sent_at_utc": utc_now_iso(),
                    "slot": "submission_start_intro",
                    "case_id": case_id,
                    "timezone": timezone_name,
                    "twilio_message_sid": send_results[-1].get("sid") if send_results else None,
                },
            )
            item["outcome"] = "sent"
            item["send_result"] = send_results[-1] if send_results else {}
            item["send_results"] = send_results
            return item

        reminder_slot = self._current_slot(local_now)
        if not reminder_slot:
            return item

        item["due"] = True
        item["slot"] = reminder_slot
        reminder_key = self._reminder_key(case_id=case_id, local_date=local_date.isoformat(), slot=reminder_slot)
        item["reminder_key"] = reminder_key

        if self._reminder_already_sent(phone, reminder_key):
            item["outcome"] = "skipped_already_sent"
            return item

        message = self._build_submission_reminder_message(expense_case=expense_case, slot=reminder_slot)
        item["message"] = message

        if dry_run:
            item["outcome"] = "sent"
            item["dry_run"] = True
            return item

        try:
            send_result = self.whatsapp_service.send_outbound_text(phone, message)
        except Exception as exc:  # pragma: no cover - depends on Twilio/network
            logger.exception("Submission reminder send failed case_id=%s phone=%s", case_id, phone)
            item["outcome"] = "error"
            item["error"] = str(exc)
            return item

        self._mark_reminder_sent(
            phone=phone,
            reminder_key=reminder_key,
            payload={
                "sent_at_utc": utc_now_iso(),
                "slot": reminder_slot,
                "case_id": case_id,
                "timezone": timezone_name,
                "twilio_message_sid": send_result.get("sid"),
            },
        )
        item["outcome"] = "sent"
        item["send_result"] = send_result
        return item

    def _evaluate_trip_reminder(self, *, trip: dict[str, Any], now_utc: datetime, dry_run: bool) -> dict[str, Any]:
        return self._evaluate_case_reminder(expense_case=trip, now_utc=now_utc, dry_run=dry_run)

    def _evaluate_submission_closure(
        self,
        *,
        expense_case: dict[str, Any],
        now_utc: datetime,
        dry_run: bool,
    ) -> dict[str, Any]:
        phone = normalize_whatsapp_phone(expense_case.get("phone"))
        case_id = str(expense_case.get("case_id", expense_case.get("trip_id", "")) or "").strip()
        timezone_name = self._resolve_case_timezone(expense_case)
        local_now = now_utc.astimezone(ZoneInfo(timezone_name))
        local_date = local_now.date()
        due_date = parse_iso_date(expense_case.get("due_date", expense_case.get("end_date")))

        item: dict[str, Any] = {
            "item_type": "submission_closure",
            "case_id": case_id,
            "phone": phone,
            "timezone": timezone_name,
            "local_now": local_now.isoformat(),
            "local_date": local_date.isoformat(),
            "due_date": due_date.isoformat() if due_date else None,
            "due": False,
            "outcome": "not_due",
        }

        if not phone:
            item["outcome"] = "skipped_invalid_phone"
            return item
        if not case_id:
            item["outcome"] = "skipped_missing_case_id"
            return item
        if not due_date:
            item["outcome"] = "skipped_missing_due_date"
            return item
        if local_date <= due_date:
            return item

        conversation = self.sheets_service.get_conversation(phone) or {}
        context = self._normalize_conversation_context(conversation.get("context_json"))
        pending_receipts = self._pending_receipts_count(context)
        state = str(conversation.get("state", "") or "")
        if pending_receipts > 0 or state in ACTIVE_RECEIPT_STATES:
            item["outcome"] = "skipped_user_in_receipt_flow"
            item["pending_receipts"] = pending_receipts
            item["conversation_state"] = state
            return item

        submission_closure = self._get_submission_closure_entry(context, case_id)
        closure_status = str(submission_closure.get("status", "") or "")
        deadline = self._parse_datetime_utc(submission_closure.get("deadline_at_utc"))

        if closure_status == "awaiting_user_response" and deadline and now_utc >= deadline:
            item["due"] = True
            item["closure_deadline_at_utc"] = deadline.isoformat()
            if dry_run:
                item["outcome"] = "closed_timeout"
                item["dry_run"] = True
                return item

            self._close_submission(
                phone=phone,
                case_id=case_id,
                context=context,
                closure_status="closed_timeout",
                closure_reason="timeout_24h_no_response",
                closure_response="timeout",
                responded_at=now_utc,
                closed_at=now_utc,
            )
            try:
                self.whatsapp_service.send_outbound_text(
                    phone,
                    self._build_submission_closed_timeout_message(expense_case=expense_case),
                )
                item["outcome"] = "closed_timeout"
            except Exception as exc:  # pragma: no cover - depends on Twilio/network
                logger.exception("Submission close timeout notice failed case_id=%s phone=%s", case_id, phone)
                item["outcome"] = "closed_timeout_no_notify"
                item["error"] = str(exc)
            return item

        if closure_status == "awaiting_user_response":
            item["outcome"] = "awaiting_user_response"
            item["closure_deadline_at_utc"] = submission_closure.get("deadline_at_utc")
            return item

        if closure_status in {"closed_timeout", "closed_by_user"}:
            item["outcome"] = "already_closed"
            return item

        item["due"] = True
        prompt_message = self._build_submission_closure_prompt_message(
            expense_case=expense_case,
            deadline_utc=now_utc + timedelta(hours=SUBMISSION_CLOSURE_TIMEOUT_HOURS),
            timezone_name=timezone_name,
        )
        if dry_run:
            item["outcome"] = "sent_closure_prompt"
            item["dry_run"] = True
            item["message"] = prompt_message
            return item

        try:
            send_result = self.whatsapp_service.send_outbound_buttons(
                phone,
                body=prompt_message,
                buttons=[
                    {"id": "closure_no_finish_submission", "title": "Cerrar rendición"},
                    {"id": "closure_yes_more_documents", "title": "Tengo más documentos"},
                ],
            )
        except Exception as exc:  # pragma: no cover - depends on Twilio/network
            logger.exception("Submission close prompt send failed case_id=%s phone=%s", case_id, phone)
            item["outcome"] = "error"
            item["error"] = str(exc)
            return item

        prompted_at_iso = now_utc.isoformat()
        deadline_iso = (now_utc + timedelta(hours=SUBMISSION_CLOSURE_TIMEOUT_HOURS)).isoformat()
        self._upsert_submission_closure_context(
            phone=phone,
            context=context,
            case_id=case_id,
            submission_closure_entry={
                "status": "awaiting_user_response",
                "prompted_at_utc": prompted_at_iso,
                "deadline_at_utc": deadline_iso,
                "timezone": timezone_name,
            },
            state=WAIT_SUBMISSION_CLOSURE_CONFIRMATION,
            current_step=SUBMISSION_CLOSURE_STEP,
        )
        self.sheets_service.update_expense_case(
            case_id,
            {
                "closure_status": "awaiting_user_response",
                "closure_prompted_at": prompted_at_iso,
                "closure_deadline_at": deadline_iso,
                "closure_response": "",
                "closure_responded_at": "",
                "closure_reason": "",
            },
        )

        item["outcome"] = "sent_closure_prompt"
        item["send_result"] = send_result
        item["closure_deadline_at_utc"] = deadline_iso
        return item

    def _evaluate_trip_closure(self, *, trip: dict[str, Any], now_utc: datetime, dry_run: bool) -> dict[str, Any]:
        return self._evaluate_submission_closure(expense_case=trip, now_utc=now_utc, dry_run=dry_run)

    def _case_is_active_on_local_date(self, expense_case: dict[str, Any], local_date) -> bool:
        start_date = parse_iso_date(expense_case.get("opened_at", expense_case.get("start_date")))
        end_date = parse_iso_date(expense_case.get("due_date", expense_case.get("end_date")))
        if start_date and end_date:
            return start_date <= local_date <= end_date
        return str(expense_case.get("status", "")).strip().lower() == "active"

    def _trip_is_active_on_local_date(self, trip: dict[str, Any], local_date) -> bool:
        return self._case_is_active_on_local_date(trip, local_date)

    def _submission_start_intro_due(self, *, expense_case: dict[str, Any], local_now: datetime) -> bool:
        start_date = parse_iso_date(expense_case.get("opened_at", expense_case.get("start_date")))
        if not start_date or local_now.date() != start_date:
            return False
        morning_hour = int(getattr(self.settings, "scheduler_morning_hour_local", 9) or 9)
        return local_now.hour == morning_hour and local_now.minute < self._window_minutes

    def _trip_start_intro_due(self, *, trip: dict[str, Any], local_now: datetime) -> bool:
        return self._submission_start_intro_due(expense_case=trip, local_now=local_now)

    def _current_slot(self, local_now: datetime) -> str | None:
        target_hours = {
            int(getattr(self.settings, "scheduler_morning_hour_local", 9) or 9): "morning_0900",
            int(getattr(self.settings, "scheduler_evening_hour_local", 20) or 20): "evening_2000",
        }
        slot = target_hours.get(local_now.hour)
        if not slot:
            return None
        if local_now.minute >= self._window_minutes:
            return None
        return slot

    def _resolve_case_timezone(self, expense_case: dict[str, Any]) -> str:
        destination = str(
            expense_case.get("context_label", expense_case.get("destination", "")) or ""
        ).strip().lower()
        for key, tz_name in _DESTINATION_TIMEZONE_MAP.items():
            if key in destination:
                return tz_name

        country = str(expense_case.get("country", "") or "").strip().upper()
        if country in _COUNTRY_TIMEZONE_MAP:
            return _COUNTRY_TIMEZONE_MAP[country]

        default_tz = (getattr(self.settings, "default_timezone", "") or "America/Santiago").strip()
        try:
            ZoneInfo(default_tz)
            return default_tz
        except Exception:
            return "America/Santiago"

    def _resolve_trip_timezone(self, trip: dict[str, Any]) -> str:
        return self._resolve_case_timezone(trip)

    def _build_submission_reminder_message(self, *, expense_case: dict[str, Any], slot: str) -> str:
        context_label = str(
            expense_case.get("context_label", expense_case.get("destination", "")) or ""
        ).strip()
        context_text = f" ({context_label})" if context_label else ""
        if slot.startswith("morning"):
            return (
                f"Buen día. Recordatorio de rendición{context_text}:\n"
                "Guarda tus boletas, facturas o comprobantes de hoy y envíalos por este chat cuando puedas."
            )
        return (
            f"Cierre del día{context_text}:\n"
            "Si tienes documentos pendientes, envíalos ahora por este chat para dejar tu rendición al día."
        )

    def _build_trip_reminder_message(self, *, trip: dict[str, Any], slot: str) -> str:
        return self._build_submission_reminder_message(expense_case=trip, slot=slot)

    def _build_submission_start_intro_messages(self, *, expense_case: dict[str, Any]) -> list[str]:
        context_label = str(
            expense_case.get("context_label", expense_case.get("destination", "")) or ""
        ).strip()
        context_text = f" para {context_label}" if context_label else ""
        budget_value = parse_float(expense_case.get("fondos_entregados"))
        if budget_value is None:
            budget_value = parse_float(expense_case.get("policy_limit", expense_case.get("budget")))
        budget_text = (
            f"Tu presupuesto disponible para esta rendición es de ${budget_value:,.0f} CLP."
            if budget_value is not None and budget_value > 0
            else ""
        )
        greeting_name = self._get_case_greeting_name(expense_case)
        greeting = (
            f"Hola, {greeting_name}. Soy tu asistente de rendición de gastos{context_text}."
            if greeting_name
            else f"Hola, soy tu asistente de rendición de gastos{context_text}."
        )
        first_message_lines = [greeting]
        if budget_text:
            first_message_lines.append(budget_text)
        return [
            "\n".join(first_message_lines),
            "Puedes enviarme una o varias boletas, facturas o comprobantes por este chat.",
        ]

    def _build_submission_start_intro_message(self, *, expense_case: dict[str, Any]) -> str:
        return "\n".join(
            self._build_submission_start_intro_messages(expense_case=expense_case)
        )

    def _build_trip_start_intro_message(self, *, trip: dict[str, Any]) -> str:
        return self._build_submission_start_intro_message(expense_case=trip)

    def _get_case_greeting_name(self, expense_case: dict[str, Any]) -> str:
        case_phone = str(
            expense_case.get("employee_phone", expense_case.get("phone", "")) or ""
        ).strip()
        if not case_phone:
            return ""
        employee = self.sheets_service.get_employee_by_phone(case_phone) or {}
        first_name = str(employee.get("first_name", "") or "").strip()
        if first_name:
            return first_name
        full_name = str(employee.get("name", "") or "").strip()
        if full_name:
            return full_name.split()[0]
        return ""

    def _build_submission_closure_prompt_message(
        self,
        *,
        expense_case: dict[str, Any],
        deadline_utc: datetime,
        timezone_name: str,
    ) -> str:
        local_deadline = deadline_utc.astimezone(ZoneInfo(timezone_name)).strftime("%Y-%m-%d %H:%M")
        return (
            "Tu rendición está lista para cierre.\n"
            "¿Qué quieres hacer?\n"
            f"Si no respondes antes de {local_deadline} ({timezone_name}), cerraré la rendición automáticamente."
        )

    def _build_trip_closure_prompt_message(
        self,
        *,
        trip: dict[str, Any],
        deadline_utc: datetime,
        timezone_name: str,
    ) -> str:
        return self._build_submission_closure_prompt_message(
            expense_case=trip,
            deadline_utc=deadline_utc,
            timezone_name=timezone_name,
        )

    def _build_submission_closed_timeout_message(self, *, expense_case: dict[str, Any]) -> str:
        case_id = str(expense_case.get("case_id", expense_case.get("trip_id", "")) or "").strip()
        return (
            f"Cerré automáticamente tu rendición {case_id} porque no recibí respuesta dentro de 24 horas. "
            "Si necesitas reabrirla, escríbenos por soporte."
        )

    def _build_trip_closed_timeout_message(self, *, trip: dict[str, Any]) -> str:
        return self._build_submission_closed_timeout_message(expense_case=trip)

    def _reminder_key(self, *, case_id: str, local_date: str, slot: str) -> str:
        case_id_safe = case_id or "NO_CASE"
        return f"submission_reminder:{case_id_safe}:{local_date}:{slot}"

    def _submission_start_intro_key(self, *, case_id: str, local_date: str) -> str:
        case_id_safe = case_id or "NO_CASE"
        return f"submission_intro:{case_id_safe}:{local_date}"

    def _trip_start_intro_key(self, *, trip_id: str, local_date: str) -> str:
        return self._submission_start_intro_key(case_id=trip_id, local_date=local_date)

    def _reminder_already_sent(self, phone: str, reminder_key: str) -> bool:
        conversation = self.sheets_service.get_conversation(phone) or {}
        context = conversation.get("context_json")
        if not isinstance(context, dict):
            return False
        scheduler_ctx = context.get("scheduler")
        if not isinstance(scheduler_ctx, dict):
            return False
        sent = scheduler_ctx.get("sent_reminders")
        if not isinstance(sent, dict):
            return False
        return reminder_key in sent

    def _mark_reminder_sent(self, *, phone: str, reminder_key: str, payload: dict[str, Any]) -> None:
        conversation = self.sheets_service.get_conversation(phone) or {}
        context = self._normalize_conversation_context(conversation.get("context_json"))

        scheduler_ctx = context.get("scheduler")
        if not isinstance(scheduler_ctx, dict):
            scheduler_ctx = {}
        sent = scheduler_ctx.get("sent_reminders")
        if not isinstance(sent, dict):
            sent = {}

        sent[reminder_key] = payload
        scheduler_ctx["sent_reminders"] = sent
        context["scheduler"] = scheduler_ctx

        self.sheets_service.update_conversation(
            phone,
            {
                "state": conversation.get("state", "WAIT_RECEIPT"),
                "current_step": conversation.get("current_step", ""),
                "context_json": context,
            },
        )

    def _normalize_conversation_context(self, context_raw: Any) -> dict[str, Any]:
        context = context_raw
        if isinstance(context_raw, str):
            context = json_loads(context_raw, default={})
        if not isinstance(context, dict):
            context = {}

        scheduler_ctx = context.get("scheduler")
        if not isinstance(scheduler_ctx, dict):
            scheduler_ctx = {}
        sent = scheduler_ctx.get("sent_reminders")
        if not isinstance(sent, dict):
            sent = {}
        scheduler_ctx["sent_reminders"] = sent

        submission_closure = context.get("submission_closure", context.get("trip_closure"))
        if not isinstance(submission_closure, dict):
            submission_closure = {}

        context["scheduler"] = scheduler_ctx
        context["submission_closure"] = submission_closure
        context["trip_closure"] = submission_closure
        context.setdefault("draft_expense", {})
        context.setdefault("missing_fields", [])
        context.setdefault("last_question", None)
        context.setdefault("pending_receipts", [])
        return context

    def _pending_receipts_count(self, context: dict[str, Any]) -> int:
        pending = context.get("pending_receipts")
        if not isinstance(pending, list):
            return 0
        return len([entry for entry in pending if isinstance(entry, dict) and entry.get("media_url")])

    def _parse_submission_closure_response(self, message: str) -> str | None:
        normalized = str(message or "").strip().lower()
        normalized = normalized.strip(" .,!?:;*\"'")
        if not normalized:
            return None
        if normalized in {
            "si",
            "sí",
            "s",
            "yes",
            "y",
            "1",
            "tengo mas boletas",
            "tengo más boletas",
            "tengo mas documentos",
            "tengo más documentos",
            "tengo mas comprobantes",
            "tengo más comprobantes",
            "closure_yes_more_receipts",
            "closure_yes_more_documents",
            "confirmar consolidado",
            "simple_confirmation_yes_confirm_consolidated",
        }:
            return "yes"
        if normalized in {
            "no",
            "n",
            "0",
            "2",
            "terminar rendicion",
            "terminar rendición",
            "cerrar rendicion",
            "cerrar rendición",
            "terminar viaje",
            "cerrar viaje",
            "closure_no_finish_trip",
            "closure_no_finish_submission",
            "revisar con empresa",
            "simple_confirmation_no_review_company",
        }:
            return "no"
        return None

    def _parse_trip_closure_response(self, message: str) -> str | None:
        return self._parse_submission_closure_response(message)

    def _is_direct_close_command(self, message: str) -> bool:
        normalized = str(message or "").strip().lower()
        normalized = normalized.strip(" .,!?:;*\"'")
        return normalized == "cerrar"

    def _get_submission_closure_entry(self, context: dict[str, Any], case_id: str) -> dict[str, Any]:
        submission_closure = context.get("submission_closure")
        if not isinstance(submission_closure, dict):
            return {}
        entry = submission_closure.get(case_id)
        if not isinstance(entry, dict):
            return {}
        return dict(entry)

    def _get_trip_closure_entry(self, context: dict[str, Any], trip_id: str) -> dict[str, Any]:
        return self._get_submission_closure_entry(context, trip_id)

    def _get_latest_pending_submission_closure(self, context: dict[str, Any]) -> dict[str, Any] | None:
        submission_closure = context.get("submission_closure")
        if not isinstance(submission_closure, dict):
            return None
        best_case_id = ""
        best_entry: dict[str, Any] | None = None
        best_prompted: datetime | None = None

        for case_id, entry in submission_closure.items():
            if not isinstance(entry, dict):
                continue
            if str(entry.get("status", "") or "") != "awaiting_user_response":
                continue
            prompted_at = self._parse_datetime_utc(entry.get("prompted_at_utc"))
            if best_entry is None:
                best_case_id = str(case_id)
                best_entry = dict(entry)
                best_prompted = prompted_at
                continue
            if prompted_at and (best_prompted is None or prompted_at > best_prompted):
                best_case_id = str(case_id)
                best_entry = dict(entry)
                best_prompted = prompted_at

        if best_entry is None:
            return None
        return {"case_id": best_case_id, "entry": best_entry}

    def _get_latest_pending_trip_closure(self, context: dict[str, Any]) -> dict[str, Any] | None:
        pending = self._get_latest_pending_submission_closure(context)
        if not pending:
            return None
        pending["trip_id"] = pending.get("case_id", "")
        return pending

    def _parse_datetime_utc(self, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _upsert_submission_closure_context(
        self,
        *,
        phone: str,
        context: dict[str, Any],
        case_id: str,
        submission_closure_entry: dict[str, Any],
        state: str,
        current_step: str,
    ) -> None:
        submission_closure = context.get("submission_closure")
        if not isinstance(submission_closure, dict):
            submission_closure = {}
        submission_closure[case_id] = submission_closure_entry
        context["submission_closure"] = submission_closure

        self.sheets_service.update_conversation(
            phone,
            {
                "state": state,
                "current_step": current_step,
                "context_json": context,
            },
        )

    def _upsert_trip_closure_context(
        self,
        *,
        phone: str,
        context: dict[str, Any],
        trip_id: str,
        trip_closure_entry: dict[str, Any],
        state: str,
        current_step: str,
    ) -> None:
        self._upsert_submission_closure_context(
            phone=phone,
            context=context,
            case_id=trip_id,
            submission_closure_entry=trip_closure_entry,
            state=state,
            current_step=current_step,
        )

    def _close_submission(
        self,
        *,
        phone: str,
        case_id: str,
        context: dict[str, Any],
        closure_status: str,
        closure_reason: str,
        closure_response: str,
        responded_at: datetime,
        closed_at: datetime,
    ) -> None:
        responded_at_iso = responded_at.isoformat()
        closed_at_iso = closed_at.isoformat()
        current_entry = self._get_submission_closure_entry(context, case_id)
        updated_entry = {
            **current_entry,
            "status": closure_status,
            "response": closure_response,
            "responded_at_utc": responded_at_iso,
            "deadline_at_utc": None,
            "closed_at_utc": closed_at_iso,
            "closure_reason": closure_reason,
        }
        self._upsert_submission_closure_context(
            phone=phone,
            context=context,
            case_id=case_id,
            submission_closure_entry=updated_entry,
            state="WAIT_RECEIPT",
            current_step="",
        )
        self.sheets_service.update_expense_case(
            case_id,
            {
                "status": CaseStatus.CLOSED,
                "closure_status": closure_status,
                "closure_response": closure_response,
                "closure_responded_at": responded_at_iso,
                "closed_at": closed_at_iso,
                "closure_reason": closure_reason,
                "closure_deadline_at": "",
                "rendicion_status": RendicionStatus.PENDING_USER_CONFIRMATION,
            },
        )

    def _close_trip(
        self,
        *,
        phone: str,
        trip_id: str,
        context: dict[str, Any],
        closure_status: str,
        closure_reason: str,
        closure_response: str,
        responded_at: datetime,
        closed_at: datetime,
    ) -> None:
        self._close_submission(
            phone=phone,
            case_id=trip_id,
            context=context,
            closure_status=closure_status,
            closure_reason=closure_reason,
            closure_response=closure_response,
            responded_at=responded_at,
            closed_at=closed_at,
        )

    def _deliver_submission_closure_package(self, *, phone: str, case_id: str) -> str:
        expense_case = self.sheets_service.get_expense_case_by_id(case_id) or {}
        document_label = f"rendicion_{case_id}.pdf"
        closure_method = str(expense_case.get("closure_method", "") or "").strip().lower() or "docusign"

        if not self.consolidated_document_service.storage_service.enabled:
            return (
                "Rendición cerrada. Quedó registrada sin documentos pendientes.\n"
                "No pude enviarte el PDF porque el storage privado no está habilitado."
            )

        try:
            document = self.consolidated_document_service.generate_for_case(
                phone=phone,
                case_id=case_id,
                include_signed_url=True,
            )
        except Exception as exc:
            logger.exception("Consolidated document generation failed case_id=%s phone=%s", case_id, phone)
            return (
                "Rendición cerrada. Quedó registrada sin documentos pendientes.\n"
                "No pude generar el PDF consolidado en este momento."
                f"{self._debug_suffix(exc)}"
            )

        signed_url = str(document.get("signed_url", "") or "").strip()
        if signed_url:
            try:
                self.whatsapp_service.send_outbound_document(
                    phone,
                    signed_url,
                    filename=document_label,
                    caption="",
                )
            except Exception as exc:
                logger.exception("Submission closure PDF send failed case_id=%s phone=%s", case_id, phone)

        document_id = str(document.get("document_id", "") or "").strip()
        if closure_method == "simple":
            if document_id:
                self.sheets_service.update_expense_case_document(
                    document_id,
                    {
                        "signature_provider": "simple_closure",
                        "signature_status": "pending",
                        "signature_error": "",
                    },
                )
            self.sheets_service.update_expense_case(
                case_id,
                {
                    "rendicion_status": RendicionStatus.PENDING_USER_CONFIRMATION,
                    "user_confirmation_status": "pending_simple_confirmation",
                },
            )
            context_label = str(
                expense_case.get("context_label", expense_case.get("destination", "")) or ""
            ).strip()
            context_text = f" ({context_label})" if context_label else ""
            self.whatsapp_service.send_outbound_buttons(
                phone,
                body=f"Rendición cerrada{context_text}. Revisa el PDF consolidado y elige una opción.",
                buttons=[
                    {
                        "id": "simple_confirmation_yes_confirm_consolidated",
                        "title": "Confirmar consolidado",
                    },
                    {
                        "id": "simple_confirmation_no_review_company",
                        "title": "Revisar con empresa",
                    },
                ],
            )
            return ""

        signer_name, signer_email = self._resolve_case_signer(phone=phone)
        if not signer_email:
            return (
                "Rendición cerrada. Te envié el PDF consolidado por este chat.\n"
                "Aún no pude generar el link de firma porque el empleado no tiene email configurado."
            )
        if not self.docusign_service.enabled:
            return (
                "Rendición cerrada. Te envié el PDF consolidado por este chat.\n"
                "DocuSign no está configurado todavía, así que aún no pude enviarte el link de firma."
            )

        object_key = str(document.get("object_key", "") or "").strip()
        if not document_id or not object_key:
            return (
                "Rendición cerrada. Te envié el PDF consolidado por este chat.\n"
                "No pude iniciar la firma porque faltó metadata del documento consolidado."
            )

        try:
            document_url = self.consolidated_document_service.storage_service.generate_signed_url(
                object_key=object_key,
                ttl_seconds=max(self.settings.docusign_document_url_ttl_seconds, 600),
            )
            envelope = self.docusign_service.create_envelope_from_remote_pdf(
                signer_name=signer_name,
                signer_email=signer_email,
                document_name=f"Rendicion de gastos {case_id}",
                document_url=document_url,
                client_user_id=phone,
            )
            envelope_id = str(envelope.get("envelopeId", "") or "").strip()
            if not envelope_id:
                raise DocusignError("DocuSign no devolvio envelopeId")
            signing_url = self.docusign_service.create_recipient_view(
                envelope_id=envelope_id,
                signer_name=signer_name,
                signer_email=signer_email,
                client_user_id=phone,
                return_url=self._build_signing_return_url(document_id=document_id),
            )
            status_time = str(envelope.get("statusDateTime", "") or "").strip() or utc_now_iso()
            self.sheets_service.update_expense_case_document(
                document_id,
                {
                    "updated_at": status_time,
                    "signature_provider": "docusign",
                    "signature_status": "pending",
                    "docusign_envelope_id": envelope_id,
                    "signature_url": signing_url,
                    "signature_sent_at": status_time,
                    "signature_error": "",
                },
            )
            self.sheets_service.update_expense_case(
                case_id,
                {
                    "rendicion_status": RendicionStatus.PENDING_USER_CONFIRMATION,
                    "user_confirmation_status": "pending",
                },
            )
        except Exception as exc:
            logger.exception("DocuSign submission closure start failed case_id=%s phone=%s", case_id, phone)
            self.sheets_service.update_expense_case_document(
                document_id,
                {
                    "signature_provider": "docusign",
                    "signature_status": "error",
                    "signature_error": str(exc),
                },
            )
            if "access token invalido o expirado" in str(exc).lower():
                return (
                    "Rendición cerrada. Te envié el PDF consolidado por este chat.\n"
                    "No pude generar el link de firma porque el token de DocuSign está vencido o inválido."
                )
            return (
                "Rendición cerrada. Te envié el PDF consolidado por este chat.\n"
                "No pude generar el link de firma DocuSign en este momento."
                f"{self._debug_suffix(exc)}"
            )

        try:
            shareable_signing_url = self._build_shareable_signing_url(
                document_id=document_id,
                signing_url=signing_url,
            )
            context_label = str(
                expense_case.get("context_label", expense_case.get("destination", "")) or ""
            ).strip()
            context_text = f" ({context_label})" if context_label else ""
            link_message = self.whatsapp_service.send_outbound_text(
                phone,
                shareable_signing_url,
            )
            self.whatsapp_service.send_outbound_text(
                phone,
                (
                    f"Rendición cerrada{context_text}. "
                    "Te envié el PDF consolidado por este chat.\n"
                    "Abre el enlace para firmar el documento."
                ),
                reply_to_message_id=str(link_message.get("id", "") or "").strip() or None,
            )
        except Exception as exc:
            logger.exception("Submission closure signature link send failed case_id=%s phone=%s", case_id, phone)
            return (
                "Rendición cerrada. Te envié el PDF consolidado por este chat.\n"
                "El link de firma se generó correctamente, "
                f"pero no pude mandártelo por WhatsApp: {signing_url}"
            )

        return ""

    def _deliver_trip_closure_package(self, *, phone: str, trip_id: str) -> str:
        return self._deliver_submission_closure_package(phone=phone, case_id=trip_id)

    def _get_latest_pending_simple_confirmation_case(self, phone: str) -> dict[str, Any] | None:
        normalized_phone = normalize_whatsapp_phone(phone)
        candidates: list[dict[str, Any]] = []
        for expense_case in self.sheets_service.list_expense_cases():
            case_phone = normalize_whatsapp_phone(
                expense_case.get("employee_phone", expense_case.get("phone", ""))
            )
            if case_phone != normalized_phone:
                continue
            if str(expense_case.get("closure_method", "") or "").strip().lower() != "simple":
                continue
            if (
                str(expense_case.get("rendicion_status", "") or "").strip()
                != RendicionStatus.PENDING_USER_CONFIRMATION
            ):
                continue
            candidates.append(expense_case)
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
            reverse=True,
        )
        return candidates[0]

    def _resolve_case_signer(self, *, phone: str) -> tuple[str, str]:
        employee = self.sheets_service.get_employee_by_phone(phone) or {}
        signer_name = str(employee.get("name", "") or "").strip() or "Empleado"
        signer_email = str(employee.get("email", "") or "").strip()
        return signer_name, signer_email

    def _resolve_trip_signer(self, *, phone: str) -> tuple[str, str]:
        return self._resolve_case_signer(phone=phone)

    def _build_shareable_signing_url(self, *, document_id: str, signing_url: str) -> str:
        base_url = str(getattr(self.settings, "public_base_url", "") or "").strip().rstrip("/")
        if not base_url:
            return signing_url
        parsed = urlparse(base_url)
        hostname = (parsed.hostname or "").strip().lower()
        if hostname in {"127.0.0.1", "localhost"}:
            return signing_url
        return f"{base_url}/r/sign/{document_id}"

    def _build_signing_return_url(self, *, document_id: str) -> str:
        base_url = str(getattr(self.settings, "public_base_url", "") or "").strip().rstrip("/")
        if base_url:
            parsed = urlparse(base_url)
            hostname = (parsed.hostname or "").strip().lower()
            if hostname not in {"127.0.0.1", "localhost"}:
                return f"{base_url}/docusign/callback?source=signing_complete&document_id={document_id}"
        return str(getattr(self.settings, "docusign_return_url", "") or "").strip()

    def _debug_suffix(self, exc: Exception) -> str:
        if not self.settings.debug:
            return ""
        return f"\nDetalle técnico: {exc}"
