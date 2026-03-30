from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request, Response, status

from app.config import settings
from services.consolidated_document_service import ConsolidatedDocumentService
from services.conversation_service import ConversationService
from services.docusign_service import DocusignError, DocusignService
from services.expense_service import ExpenseService
from services.llm_service import LLMService
from services.ocr_service import OCRService
from services.scheduler_service import SchedulerService
from services.sheets_service import SheetsService
from services.storage_service import GCSStorageService
from services.travel_service import TravelService
from services.whatsapp_service import TwilioDailyLimitExceededError, WhatsAppService
from utils.helpers import normalize_whatsapp_phone, utc_now_iso

logger = logging.getLogger(__name__)


STICKY_CONTEXT_KEYS = ("scheduler", "pending_receipts", "trip_closure")
ACTIVE_RECEIPT_STATES = {"PROCESSING", "NEEDS_INFO", "CONFIRM_SUMMARY"}


@dataclass
class ServiceContainer:
    sheets: SheetsService
    travel: TravelService
    storage: GCSStorageService
    consolidated_document: ConsolidatedDocumentService
    docusign: DocusignService
    ocr: OCRService
    expense: ExpenseService
    conversation: ConversationService
    whatsapp: WhatsAppService
    scheduler: SchedulerService


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug)

    sheets_service = SheetsService(settings=settings)
    llm_service = LLMService(settings=settings)
    expense_service = ExpenseService(sheets_service=sheets_service, llm_service=llm_service)
    whatsapp_service = WhatsAppService(settings=settings)
    storage_service = GCSStorageService(settings=settings)
    docusign_service = DocusignService(settings=settings)
    container = ServiceContainer(
        sheets=sheets_service,
        travel=TravelService(sheets_service=sheets_service),
        storage=storage_service,
        consolidated_document=ConsolidatedDocumentService(
            sheets_service=sheets_service,
            storage_service=storage_service,
        ),
        docusign=docusign_service,
        ocr=OCRService(settings=settings),
        expense=expense_service,
        conversation=ConversationService(expense_service=expense_service),
        whatsapp=whatsapp_service,
        scheduler=SchedulerService(
            settings=settings,
            sheets_service=sheets_service,
            whatsapp_service=whatsapp_service,
        ),
    )
    app.state.services = container

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "app": settings.app_name,
            "sheets_enabled": container.sheets.enabled,
            "category_llm_flag": settings.expense_category_llm_enabled,
            "chat_assistant_flag": settings.chat_assistant_enabled,
            "openai_api_key_present": bool(settings.openai_api_key),
            "category_llm_enabled": llm_service.category_classification_enabled,
            "chat_assistant_enabled": llm_service.chat_assistant_enabled,
            "openai_model": settings.openai_model if llm_service.category_classification_enabled else None,
            "scheduler_window_minutes": settings.scheduler_reminder_window_minutes,
            "scheduler_morning_hour_local": settings.scheduler_morning_hour_local,
            "scheduler_evening_hour_local": settings.scheduler_evening_hour_local,
            "gcs_storage_enabled": container.storage.enabled,
            "gcs_bucket_name": settings.gcs_bucket_name if container.storage.enabled else None,
            "docusign_enabled": settings.docusign_enabled,
            "docusign_ready": container.docusign.enabled,
            "docusign_account_id": (
                settings.docusign_account_id if container.docusign.enabled else None
            ),
            "env": settings.app_env,
        }

    @app.post("/jobs/reminders/run")
    async def run_trip_reminders(
        dry_run: bool = False,
        x_scheduler_token: Optional[str] = Header(default=None, alias="X-Scheduler-Token"),
    ) -> dict[str, Any]:
        configured_token = (settings.scheduler_endpoint_token or "").strip()
        if configured_token and x_scheduler_token != configured_token:
            raise HTTPException(status_code=401, detail="Unauthorized scheduler token")
        return container.scheduler.run_trip_reminders(dry_run=dry_run)

    @app.post("/jobs/documents/consolidated/generate")
    async def generate_consolidated_document(
        phone: str = Query(..., description="Telefono del empleado en formato E.164"),
        trip_id: str = Query(..., description="Identificador del viaje"),
        include_signed_url: bool = Query(
            True, description="Incluye URL temporal firmada para descarga"
        ),
        x_scheduler_token: Optional[str] = Header(default=None, alias="X-Scheduler-Token"),
    ) -> dict[str, Any]:
        configured_token = (settings.scheduler_endpoint_token or "").strip()
        if configured_token and x_scheduler_token != configured_token:
            raise HTTPException(status_code=401, detail="Unauthorized scheduler token")
        try:
            return container.consolidated_document.generate_for_trip(
                phone=phone,
                trip_id=trip_id,
                include_signed_url=include_signed_url,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/jobs/documents/signature/start")
    async def start_docusign_signature(
        phone: str = Query(..., description="Telefono del empleado en formato E.164"),
        trip_id: str = Query(..., description="Identificador del viaje"),
        signer_email: str = Query(..., description="Email del firmante"),
        signer_name: str = Query("", description="Nombre del firmante (opcional)"),
        embedded_signing: bool = Query(
            True, description="Genera URL embebida de firma si es true"
        ),
        x_scheduler_token: Optional[str] = Header(default=None, alias="X-Scheduler-Token"),
    ) -> dict[str, Any]:
        configured_token = (settings.scheduler_endpoint_token or "").strip()
        if configured_token and x_scheduler_token != configured_token:
            raise HTTPException(status_code=401, detail="Unauthorized scheduler token")
        if not container.storage.enabled:
            raise HTTPException(status_code=503, detail="Storage privado no habilitado")
        if not container.docusign.enabled:
            raise HTTPException(status_code=503, detail="DocuSign no esta configurado")

        latest_document = container.sheets.get_latest_trip_document_by_phone_trip(phone, trip_id)
        if not latest_document:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No existe documento consolidado para ese phone/trip_id. "
                    "Primero genera el consolidado."
                ),
            )

        document_id = str(latest_document.get("document_id", "") or "").strip()
        object_key = str(latest_document.get("object_key", "") or "").strip()
        if not object_key:
            raise HTTPException(status_code=400, detail="Documento sin object_key en storage")

        signer_name_final = str(signer_name or "").strip()
        if not signer_name_final:
            employee = container.sheets.get_employee_by_phone(phone) or {}
            signer_name_final = str(employee.get("name", "") or "").strip()
        if not signer_name_final:
            raise HTTPException(status_code=400, detail="Debes indicar signer_name")

        try:
            document_url = container.storage.generate_signed_url(
                object_key=object_key,
                ttl_seconds=max(settings.docusign_document_url_ttl_seconds, 600),
            )
            envelope = container.docusign.create_envelope_from_remote_pdf(
                signer_name=signer_name_final,
                signer_email=signer_email,
                document_name=f"Reporte viaticos {trip_id}",
                document_url=document_url,
                client_user_id=phone if embedded_signing else None,
            )
            envelope_id = str(envelope.get("envelopeId", "") or "").strip()
            if not envelope_id:
                raise DocusignError("DocuSign no devolvio envelopeId")

            signing_url = ""
            if embedded_signing:
                signing_url = container.docusign.create_recipient_view(
                    envelope_id=envelope_id,
                    signer_name=signer_name_final,
                    signer_email=signer_email,
                    client_user_id=phone,
                )

            status_time = str(envelope.get("statusDateTime", "") or "").strip() or utc_now_iso()
            container.sheets.update_trip_document(
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

            return {
                "document_id": document_id,
                "trip_id": str(latest_document.get("trip_id", "") or ""),
                "signature_provider": "docusign",
                "signature_status": "pending",
                "docusign_envelope_id": envelope_id,
                "signing_url": signing_url or None,
            }
        except DocusignError as exc:
            if document_id:
                container.sheets.update_trip_document(
                    document_id,
                    {
                        "signature_provider": "docusign",
                        "signature_status": "error",
                        "signature_error": str(exc),
                    },
                )
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/webhook")
    async def twilio_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
        try:
            form = await request.form()
            payload = {key: form.get(key) for key in form.keys()}
            num_media = int(payload.get("NumMedia") or 0)
            body = (payload.get("Body") or "").strip()
            from_raw = payload.get("From") or ""
            phone = normalize_whatsapp_phone(from_raw)
            signature = request.headers.get("X-Twilio-Signature")
            request_url = str(request.url)

            if not container.whatsapp.validate_incoming_request(
                request_url, payload, signature
            ):
                xml = container.whatsapp.build_twiml_message("Firma Twilio inválida.")
                return Response(content=xml, media_type="application/xml", status_code=403)

            if not phone:
                xml = container.whatsapp.build_twiml_message(
                    "No pude identificar tu número. Intenta nuevamente."
                )
                return Response(content=xml, media_type="application/xml")

            employee = container.sheets.get_employee_by_phone(phone)
            if not employee:
                xml = container.whatsapp.build_twiml_message(
                    "Tu número no está registrado como empleado activo."
                )
                return Response(content=xml, media_type="application/xml")

            if num_media > 0:
                media_entries = _extract_media_entries(payload)
                if not media_entries:
                    xml = container.whatsapp.build_twiml_message(
                        "No pude leer las imágenes adjuntas. Reenvía la boleta, por favor."
                    )
                    return Response(
                        content=xml,
                        media_type="application/xml",
                        status_code=status.HTTP_200_OK,
                    )

                conversation = container.conversation.ensure_conversation(
                    container.sheets.get_conversation(phone)
                )
                context = conversation.get("context_json", {})
                pending_receipts = _get_pending_receipts(context)
                state = str(conversation.get("state", "WAIT_RECEIPT") or "WAIT_RECEIPT")

                if state in ACTIVE_RECEIPT_STATES:
                    queued_count = _enqueue_media_entries(container, phone, media_entries)
                    xml = container.whatsapp.build_twiml_message(
                        "Recibí tu boleta y la dejé en cola. "
                        f"Tienes {queued_count} boleta(s) pendientes; "
                        "las revisaré una por una."
                    )
                    return Response(
                        content=xml,
                        media_type="application/xml",
                        status_code=status.HTTP_200_OK,
                    )

                if pending_receipts:
                    _enqueue_media_entries(container, phone, media_entries)
                    started = _maybe_schedule_next_pending_media(
                        background_tasks=background_tasks,
                        container=container,
                        phone=phone,
                    )
                    xml = (
                        container.whatsapp.build_empty_twiml()
                        if started
                        else container.whatsapp.build_twiml_message(
                            "Recibí tu boleta y la dejé en cola para procesarla."
                        )
                    )
                    return Response(
                        content=xml,
                        media_type="application/xml",
                        status_code=status.HTTP_200_OK,
                    )

                first_entry = media_entries[0]
                extra_entries = media_entries[1:]
                if extra_entries:
                    _enqueue_media_entries(container, phone, extra_entries)
                _set_processing_lock(container, phone)
                background_tasks.add_task(
                    _process_media_message_async,
                    container,
                    phone,
                    {
                        "MediaUrl0": first_entry.get("media_url", ""),
                        "MediaContentType0": first_entry.get("media_content_type"),
                    },
                )
                xml = container.whatsapp.build_empty_twiml()
                return Response(
                    content=xml,
                    media_type="application/xml",
                    status_code=status.HTTP_200_OK,
                )
            else:
                response_text = _handle_text_message(container, phone, body)
                _maybe_schedule_next_pending_media(
                    background_tasks=background_tasks,
                    container=container,
                    phone=phone,
                )

            xml = container.whatsapp.build_twiml_message(response_text)
            return Response(content=xml, media_type="application/xml", status_code=status.HTTP_200_OK)
        except Exception as exc:  # pragma: no cover - runtime dependency/errors
            logger.exception("Webhook processing failed")
            message = (
                "Estoy con alta carga temporal y no pude procesar tu mensaje. "
                "Intenta nuevamente en 1 minuto."
            )
            if settings.debug:
                message += f"\nDetalle técnico: {exc}"
            xml = container.whatsapp.build_twiml_message(message)
            return Response(content=xml, media_type="application/xml", status_code=status.HTTP_200_OK)

    return app


def _handle_media_message(container: ServiceContainer, phone: str, payload: dict[str, Any]) -> str:
    media_url = payload.get("MediaUrl0") or ""
    media_content_type = payload.get("MediaContentType0")
    ocr_warning = ""
    storage_result: dict[str, str] = {}
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    base_context = conversation.get("context_json", {})
    processing_context = _merge_context_preserving_sticky(
        base_context,
        container.conversation.default_context(),
    )

    container.sheets.update_conversation(
        phone,
        {
            "phone": phone,
            "state": "PROCESSING",
            "current_step": "",
            "context_json": processing_context,
        },
    )

    try:
        ocr_data = container.ocr.extract_receipt_data(media_url, media_content_type)
    except Exception as exc:  # pragma: no cover - depende de red/API externa
        logger.exception("OCR processing failed for phone=%s", phone)
        ocr_data = {}
        ocr_warning = (
            "No pude extraer datos automáticamente de la boleta. "
            "Te pediré los datos manualmente."
        )
        if settings.debug:
            ocr_warning += f"\nDetalle técnico: {exc}"

    if container.storage.enabled and media_url:
        try:
            storage_result = container.storage.upload_receipt_from_url(
                phone=phone,
                media_url=media_url,
                media_content_type=media_content_type,
            )
        except Exception as exc:  # pragma: no cover - depende de red/API externa
            logger.exception("GCS upload failed for phone=%s", phone)
            if settings.debug:
                logger.warning("Receipt upload to GCS failed phone=%s error=%s", phone, exc)
            container.sheets.update_conversation(
                phone,
                {
                    "state": "WAIT_RECEIPT",
                    "current_step": "",
                    "context_json": _merge_context_preserving_sticky(
                        _get_latest_context(container, phone),
                        container.conversation.default_context(),
                    ),
                },
            )
            return (
                "No pude almacenar la boleta en el storage privado. "
                "Inténtalo nuevamente en unos segundos."
            )

    ocr_data["receipt_storage_provider"] = storage_result.get("receipt_storage_provider", "")
    ocr_data["receipt_object_key"] = storage_result.get("receipt_object_key", "")

    trip = container.travel.get_active_trip_for_phone(phone)
    transition = container.conversation.process_ocr_result(phone, ocr_data, trip)

    container.sheets.update_conversation(
        phone,
        {
            "state": transition["state"],
            "current_step": transition.get("current_step", ""),
            "context_json": _merge_context_preserving_sticky(
                _get_latest_context(container, phone),
                transition.get("context_json", {}),
            ),
        },
    )
    reply = transition.get(
        "reply",
        "Recibí tu boleta. Estoy procesándola.",
    )
    if ocr_warning:
        reply = f"{ocr_warning}\n\n{reply}"
    return reply


def _handle_text_message(container: ServiceContainer, phone: str, body: str) -> str:
    conversation = container.sheets.get_conversation(phone)
    if not conversation:
        conversation = container.sheets.update_conversation(
            phone,
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": container.conversation.default_context(),
            },
        )

    closure_reply = container.scheduler.handle_trip_closure_user_response(
        phone=phone,
        message=body,
    )
    if closure_reply:
        return closure_reply

    result = container.conversation.handle_text_message(conversation, body)

    if result.get("action") == "save_expense":
        draft = result.get("context_json", {}).get("draft_expense", {})
        try:
            saved = container.expense.save_confirmed_expense(phone, draft)
            has_pending_receipts = bool(_get_pending_receipts(_get_latest_context(container, phone)))
            budget_section = ""
            closing_line = "Envíame otra boleta cuando quieras."
            if has_pending_receipts:
                closing_line = "Recibido. Ahora voy con la siguiente boleta."
            else:
                budget_message = container.expense.build_budget_progress_message(
                    phone=phone,
                    trip_id=str(saved.get("trip_id", "") or ""),
                )
                budget_section = f"{budget_message}\n\n" if budget_message else ""
            reply = (
                "Gasto guardado con éxito.\n"
                f"ID: {saved.get('expense_id')}\n"
                f"Estado: {saved.get('status')}\n\n"
                f"{budget_section}"
                f"{closing_line}"
            )
            container.sheets.update_conversation(
                phone,
                {
                    "state": "WAIT_RECEIPT",
                    "current_step": "",
                    "context_json": _merge_context_preserving_sticky(
                        _get_latest_context(container, phone),
                        container.conversation.default_context(),
                    ),
                },
            )
            return reply
        except Exception as exc:  # pragma: no cover - runtime dependency/errors
            result = {
                "state": "CONFIRM_SUMMARY",
                "current_step": "confirm_summary",
                "context_json": result.get("context_json", {}),
                "reply": f"No pude guardar el gasto: {exc}",
            }

    container.sheets.update_conversation(
        phone,
        {
            "state": result.get("state", conversation.get("state", "WAIT_RECEIPT")),
            "current_step": result.get("current_step", conversation.get("current_step", "")),
            "context_json": _merge_context_preserving_sticky(
                _get_latest_context(container, phone),
                result.get("context_json", conversation.get("context_json", {})),
            ),
        },
    )
    return result.get("reply", "No pude procesar tu mensaje.")


def _process_media_message_async(
    container: ServiceContainer,
    phone: str,
    payload: dict[str, Any],
) -> None:
    try:
        response_text = _handle_media_message(container, phone, payload)
    except Exception as exc:  # pragma: no cover - runtime dependency/errors
        logger.exception("Async media processing failed for phone=%s", phone)
        response_text = (
            "No pude procesar tu boleta en este intento. "
            "Por favor reenvíala o escribe 'reiniciar'."
        )
        if settings.debug:
            response_text += f"\nDetalle técnico: {exc}"
    try:
        container.whatsapp.send_outbound_text(phone, response_text)
    except TwilioDailyLimitExceededError:
        logger.warning(
            "No se pudo enviar respuesta por WhatsApp: límite diario de Twilio alcanzado phone=%s",
            phone,
        )
    except Exception:  # pragma: no cover - runtime dependency/errors
        logger.exception("Failed to send outbound WhatsApp reply phone=%s", phone)


def _extract_media_entries(payload: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    num_media = int(payload.get("NumMedia") or 0)
    for index in range(max(1, num_media)):
        media_url = str(payload.get(f"MediaUrl{index}") or "").strip()
        if not media_url:
            continue
        media_content_type = str(payload.get(f"MediaContentType{index}") or "").strip()
        entries.append(
            {
                "media_url": media_url,
                "media_content_type": media_content_type,
            }
        )
    return entries


def _merge_context_preserving_sticky(
    base_context: dict[str, Any] | None,
    new_context: dict[str, Any] | None,
) -> dict[str, Any]:
    base = base_context if isinstance(base_context, dict) else {}
    merged = dict(new_context) if isinstance(new_context, dict) else {}
    for key in STICKY_CONTEXT_KEYS:
        if key not in merged and key in base:
            merged[key] = base[key]
    if "pending_receipts" not in merged:
        merged["pending_receipts"] = []
    return merged


def _get_latest_context(container: ServiceContainer, phone: str) -> dict[str, Any]:
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    context = conversation.get("context_json", {})
    return context if isinstance(context, dict) else {}


def _get_pending_receipts(context: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(context, dict):
        return []
    raw = context.get("pending_receipts")
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        media_url = str(item.get("media_url") or "").strip()
        if not media_url:
            continue
        media_content_type = str(item.get("media_content_type") or "").strip()
        entries.append(
            {
                "media_url": media_url,
                "media_content_type": media_content_type,
            }
        )
    return entries


def _enqueue_media_entries(
    container: ServiceContainer,
    phone: str,
    media_entries: list[dict[str, str]],
) -> int:
    if not media_entries:
        return 0
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    context = conversation.get("context_json", {})
    pending = _get_pending_receipts(context)
    pending.extend(media_entries)
    merged_context = _merge_context_preserving_sticky(
        context,
        {**context, "pending_receipts": pending},
    )
    container.sheets.update_conversation(
        phone,
        {
            "state": conversation.get("state", "WAIT_RECEIPT"),
            "current_step": conversation.get("current_step", ""),
            "context_json": merged_context,
        },
    )
    return len(pending)


def _maybe_schedule_next_pending_media(
    *,
    background_tasks: BackgroundTasks,
    container: ServiceContainer,
    phone: str,
) -> bool:
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    state = str(conversation.get("state", "WAIT_RECEIPT") or "WAIT_RECEIPT")
    if state in ACTIVE_RECEIPT_STATES:
        return False
    context = conversation.get("context_json", {})
    pending = _get_pending_receipts(context)
    if not pending:
        return False
    next_media = pending.pop(0)
    updated_context = _merge_context_preserving_sticky(
        context,
        {**context, "pending_receipts": pending},
    )
    processing_context = _merge_context_preserving_sticky(
        updated_context,
        container.conversation.default_context(),
    )
    container.sheets.update_conversation(
        phone,
        {
            "state": "PROCESSING",
            "current_step": "",
            "context_json": processing_context,
        },
    )
    background_tasks.add_task(
        _process_media_message_async,
        container,
        phone,
        {
            "MediaUrl0": next_media.get("media_url", ""),
            "MediaContentType0": next_media.get("media_content_type", ""),
        },
    )
    return True


def _set_processing_lock(container: ServiceContainer, phone: str) -> None:
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    context = conversation.get("context_json", {})
    processing_context = _merge_context_preserving_sticky(
        context,
        container.conversation.default_context(),
    )
    container.sheets.update_conversation(
        phone,
        {
            "state": "PROCESSING",
            "current_step": "",
            "context_json": processing_context,
        },
    )


app = create_app()
