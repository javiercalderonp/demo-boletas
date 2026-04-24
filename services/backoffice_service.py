from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from services.sheets_service import SheetsService
from services.statuses import (
    CaseStatus,
    ExpenseStatus,
    ExpenseReviewStatus,
    EXPENSE_PENDING_STATUSES,
    REVIEW_NEEDS_ATTENTION_STATUSES,
    REVIEW_PRIORITY_ORDER,
    RENDICION_PENDING_REVIEW_STATUSES,
    RendicionStatus,
    SettlementDirection,
    SettlementStatus,
    is_resolved_expense_status,
    resolve_canonical_document_status,
    normalize_review_status,
    normalize_rendicion_status,
    normalize_state,
)
from utils.helpers import make_id, normalize_whatsapp_phone, parse_float, utc_now_iso

STALE_RENDICION_DAYS = 3


@dataclass
class BackofficeService:
    sheets_service: SheetsService

    @staticmethod
    def _format_case_reference(expense_case: dict[str, Any]) -> str:
        case_name = str(expense_case.get("context_label", "") or "").strip()
        case_id = str(expense_case.get("case_id", "") or "").strip()
        if case_name and case_id:
            return f"{case_name} ({case_id})"
        if case_name:
            return case_name
        if case_id:
            return case_id
        return "sin identificador"

    def _list_active_cases_for_phone(self, phone: str) -> list[dict[str, Any]]:
        normalized_phone = normalize_whatsapp_phone(phone)
        if not normalized_phone:
            return []

        list_active_by_phone = getattr(self.sheets_service, "list_active_expense_cases_by_phone", None)
        if callable(list_active_by_phone):
            return list_active_by_phone(normalized_phone)

        active_cases: list[dict[str, Any]] = []
        for expense_case in self.sheets_service.list_expense_cases():
            case_phone = normalize_whatsapp_phone(
                expense_case.get("employee_phone", expense_case.get("phone", ""))
            )
            if case_phone != normalized_phone:
                continue
            if normalize_state(expense_case.get("status")) != CaseStatus.ACTIVE:
                continue
            active_cases.append(expense_case)
        return active_cases

    @staticmethod
    def _format_clp(value: Any) -> str:
        try:
            amount = round(float(value or 0), 0)
        except (TypeError, ValueError):
            amount = 0
        return f"${amount:,.0f}".replace(",", ".")

    def build_case_settlement_whatsapp_message(self, expense_case: dict[str, Any]) -> str:
        settlement_direction = normalize_state(expense_case.get("settlement_direction"))
        settlement_amount = parse_float(expense_case.get("settlement_amount_clp")) or 0.0

        if settlement_direction == SettlementDirection.COMPANY_OWES_EMPLOYEE:
            return (
                "Tu rendición fue aprobada.\n"
                f"Te vamos a depositar {self._format_clp(settlement_amount)}."
            )
        if settlement_direction == SettlementDirection.EMPLOYEE_OWES_COMPANY:
            return (
                "Tu rendición fue aprobada.\n"
                f"Debes depositar {self._format_clp(settlement_amount)} a la empresa."
            )
        return (
            "Tu rendición fue aprobada.\n"
            "El saldo quedó cuadrado, así que no necesitas depositar y no corresponde reembolso."
        )

    def build_case_settlement_bank_details_message(self, expense_case: dict[str, Any]) -> str | None:
        settlement_direction = normalize_state(expense_case.get("settlement_direction"))
        if settlement_direction != SettlementDirection.EMPLOYEE_OWES_COMPANY:
            return None

        company = self._resolve_company_for_case(expense_case)
        if not company:
            return "Cuando realices el depósito, envíame el comprobante por este chat."

        company_name = str(company.get("name", "") or "").strip() or "la empresa"
        detail_lines = [
            line
            for line in (
                f"Banco: {str(company.get('bank_name', '') or '').strip()}",
                f"Tipo de cuenta: {str(company.get('account_type', '') or '').strip()}",
                f"Número de cuenta: {str(company.get('account_number', '') or '').strip()}",
                f"Titular: {str(company.get('account_holder', '') or '').strip()}",
                f"RUT: {str(company.get('account_holder_rut', '') or '').strip()}",
            )
            if not line.endswith(": ")
        ]

        if not detail_lines:
            return "Cuando realices el depósito, envíame el comprobante por este chat."

        return (
            f"Datos bancarios de {company_name}:\n"
            + "\n".join(detail_lines)
            + "\n\nCuando realices el depósito, envíame el comprobante por este chat."
        )

    def _resolve_company_for_case(self, expense_case: dict[str, Any]) -> dict[str, Any] | None:
        company_id = str(expense_case.get("company_id", "") or "").strip()
        if not company_id:
            employee_phone = expense_case.get("employee_phone", expense_case.get("phone", ""))
            get_employee = getattr(self.sheets_service, "get_employee_any_by_phone", None)
            if callable(get_employee):
                employee = get_employee(employee_phone) or {}
                company_id = str(employee.get("company_id", "") or "").strip()
        if not company_id:
            return None

        for company in self.sheets_service.list_companies():
            if str(company.get("company_id", "") or "").strip().lower() == company_id.lower():
                return company
        return None

    def get_dashboard(self) -> dict[str, Any]:
        employees = self.sheets_service.list_employees()
        cases = self.sheets_service.list_expense_cases()
        expenses = self.sheets_service.list_expenses()
        conversations = self.sheets_service.list_conversations()
        active_conversations = [
            item for item in conversations if str(item.get("state", "")).strip() not in {"DONE", ""}
        ]

        # Rendición-focused stats
        enriched_cases = self._enrich_cases(cases)
        active_cases = [
            c for c in enriched_cases if normalize_state(c.get("status")) == CaseStatus.ACTIVE
        ]
        rendiciones_open = [
            c
            for c in enriched_cases
            if normalize_rendicion_status(c.get("rendicion_status")) == RendicionStatus.OPEN
        ]
        rendiciones_pending_review = [
            c for c in enriched_cases
            if normalize_rendicion_status(c.get("rendicion_status"))
            in RENDICION_PENDING_REVIEW_STATUSES
        ]

        total_fondos = sum(parse_float(c.get("fondos_entregados")) or 0 for c in active_cases)
        total_rendido_aprobado = sum(c.get("monto_rendido_aprobado", 0) or 0 for c in active_cases)
        total_pendiente_revision = sum(c.get("monto_pendiente_revision", 0) or 0 for c in active_cases)
        total_saldo = round(total_fondos - total_rendido_aprobado, 2)

        docs_needs_review = len([
            e for e in expenses
            if normalize_review_status(e.get("review_status"), expense_status=e.get("status"))
            in REVIEW_NEEDS_ATTENTION_STATUSES
        ])

        # Alerts
        alerts: list[dict[str, Any]] = []
        for case in enriched_cases:
            saldo = case.get("saldo_restante", 0)
            if isinstance(saldo, (int, float)) and saldo < 0:
                name = case.get("employee", {}).get("name", "") if case.get("employee") else ""
                label = name or case.get("employee_phone", case.get("case_id", ""))
                alerts.append({
                    "type": "negative_balance",
                    "severity": "error",
                    "message": f"Rendición {case.get('case_id')} ({label}) tiene saldo negativo: ${abs(saldo):,.0f} CLP.",
                    "case_id": case.get("case_id"),
                })
        now_utc = datetime.now(timezone.utc)
        for case in rendiciones_pending_review:
            updated_at = str(case.get("updated_at", "") or "").strip()
            days_pending = None
            if (
                updated_at
                and normalize_rendicion_status(case.get("rendicion_status"))
                == RendicionStatus.PENDING_USER_CONFIRMATION
            ):
                try:
                    dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    days_pending = (now_utc - dt).days
                except (ValueError, TypeError):
                    pass

            if days_pending is not None and days_pending >= STALE_RENDICION_DAYS:
                alerts.append({
                    "type": "stale_rendicion",
                    "severity": "error",
                    "message": f"Rendición {case.get('case_id')} lleva {days_pending} días esperando confirmación del usuario.",
                    "case_id": case.get("case_id"),
                })
            else:
                alerts.append({
                    "type": "pending_rendicion",
                    "severity": "warning",
                    "message": f"Rendición {case.get('case_id')} esperando confirmación del usuario.",
                    "case_id": case.get("case_id"),
                })
        for expense in expenses:
            if (
                normalize_review_status(expense.get("review_status"), expense_status=expense.get("status"))
                == ExpenseReviewStatus.NEEDS_MANUAL_REVIEW
            ):
                alerts.append({
                    "type": "needs_manual_review",
                    "severity": "warning",
                    "message": f"Documento {expense.get('expense_id')} requiere revisión manual.",
                    "expense_id": expense.get("expense_id"),
                })
                if len(alerts) >= 10:
                    break

        # Rendiciones que necesitan atención (saldo negativo o docs sin aprobar)
        attention_cases = sorted(
            [c for c in enriched_cases if normalize_state(c.get("status")) == CaseStatus.ACTIVE],
            key=lambda c: c.get("saldo_restante", 0) if isinstance(c.get("saldo_restante"), (int, float)) else 0,
        )

        # Status distribution for chart
        status_counts: dict[str, int] = {}
        for case in enriched_cases:
            rs = normalize_rendicion_status(case.get("rendicion_status"))
            status_counts[rs] = status_counts.get(rs, 0) + 1

        return {
            "stats": {
                "active_employees": len([item for item in employees if item.get("active")]),
                "rendiciones_open": len(rendiciones_open),
                "rendiciones_pending": len(rendiciones_pending_review),
                "total_fondos": round(total_fondos, 2),
                "total_rendido_aprobado": round(total_rendido_aprobado, 2),
                "total_pendiente_revision": round(total_pendiente_revision, 2),
                "total_saldo": total_saldo,
                "docs_needs_review": docs_needs_review,
                "active_conversations": len(active_conversations),
            },
            "rendicion_status_distribution": status_counts,
            "rendiciones": attention_cases[:10],
            "latest_expenses": self._enrich_expenses(expenses[:5]),
            "latest_conversations": self._enrich_conversations(conversations[:5]),
            "alerts": alerts[:10],
        }

    def list_employees(self) -> list[dict[str, Any]]:
        employees = self.sheets_service.list_employees()
        cases = self.sheets_service.list_expense_cases()
        expenses = self.sheets_service.list_expenses()
        conversations = self.sheets_service.list_conversations()
        for employee in employees:
            phone = employee.get("phone", "")
            employee["case_count"] = len(
                [item for item in cases if item.get("employee_phone", item.get("phone")) == phone]
            )
            employee["expense_count"] = len([item for item in expenses if item.get("phone") == phone])
            employee["last_activity_at"] = employee.get("last_activity_at") or self._max_timestamp(
                [
                    item.get("updated_at")
                    for item in conversations
                    if item.get("phone") == phone
                ]
                + [
                    item.get("created_at")
                    for item in expenses
                    if item.get("phone") == phone
                ]
            )
        return employees

    def list_companies(self) -> list[dict[str, Any]]:
        return self.sheets_service.list_companies()

    def get_employee_detail(self, phone: str) -> dict[str, Any] | None:
        employee = self.sheets_service.get_employee_any_by_phone(phone)
        if not employee:
            return None
        phone_value = employee.get("phone", "")
        cases = [
            item
            for item in self.sheets_service.list_expense_cases()
            if item.get("employee_phone", item.get("phone")) == phone_value
        ]
        expenses = self._get_expenses_for_employee(phone_value)
        conversations = [
            item
            for item in self.sheets_service.list_conversations()
            if item.get("phone") == phone_value
        ]
        return {
            "employee": employee,
            "cases": cases,
            "expenses": self._enrich_expenses(expenses),
            "conversations": self._enrich_conversations(conversations),
        }

    def create_employee(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.sheets_service.create_employee(payload)

    def update_employee(self, phone: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.sheets_service.update_employee(phone, payload)

    def delete_employee(self, phone: str) -> dict[str, Any] | None:
        return self.sheets_service.delete_employee(phone)

    def delete_employee_with_related_data(
        self,
        phone: str,
        *,
        delete_cases: bool = False,
    ) -> dict[str, Any] | None:
        employee = self.sheets_service.get_employee_any_by_phone(phone)
        if employee is None:
            return None

        deleted_case_ids: set[str] = set()
        deleted_cases = 0
        deleted_expenses = 0

        if delete_cases:
            employee_phone = str(employee.get("phone", "") or "").strip()
            related_cases = [
                item
                for item in self.sheets_service.list_expense_cases()
                if item.get("employee_phone", item.get("phone")) == employee_phone
            ]
            deleted_case_ids = {
                str(item.get("case_id", "") or "").strip()
                for item in related_cases
                if str(item.get("case_id", "") or "").strip()
            }
            for case_id in deleted_case_ids:
                deleted_case = self.sheets_service.delete_expense_case(case_id)
                if deleted_case is not None:
                    deleted_cases += 1
            deleted_expenses = self.sheets_service.delete_expenses_for_employee_or_cases(
                employee_phone,
                deleted_case_ids,
            )

        deleted_employee = self.sheets_service.delete_employee(phone)
        if deleted_employee is None:
            return None

        return {
            "employee": deleted_employee,
            "deleted_cases": deleted_cases,
            "deleted_expenses": deleted_expenses,
        }

    def list_cases(self) -> list[dict[str, Any]]:
        return self._enrich_cases(self.sheets_service.list_expense_cases())

    def get_case_detail(self, case_id: str) -> dict[str, Any] | None:
        expense_case = self.sheets_service.get_expense_case_by_id(case_id)
        if not expense_case:
            return None
        employee = self.sheets_service.get_employee_any_by_phone(
            expense_case.get("employee_phone", expense_case.get("phone", ""))
        )
        expenses = [
            item
            for item in self.sheets_service.list_expenses()
            if item.get("case_id") == expense_case.get("case_id")
        ]
        conversations = [
            item
            for item in self.sheets_service.list_conversations()
            if item.get("case_id") == expense_case.get("case_id")
            or item.get("phone")
            == expense_case.get("employee_phone", expense_case.get("phone", ""))
        ]
        return {
            "case": self._enrich_cases([expense_case])[0],
            "employee": employee,
            "expenses": self._enrich_expenses(expenses),
            "conversations": self._enrich_conversations(conversations),
        }

    def create_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        employee_phone = normalize_whatsapp_phone(
            data.get("employee_phone", data.get("phone", ""))
        )
        context_label = str(data.get("context_label", "") or "").strip().lower()
        status = str(data.get("status", "active") or "active").strip().lower()
        company_id = str(data.get("company_id", "") or "").strip().lower()
        requested_case_id = str(data.get("case_id", "") or "").strip()

        if employee_phone and status == CaseStatus.ACTIVE:
            active_cases = self._list_active_cases_for_phone(employee_phone)
            conflicting_active_cases = [
                item
                for item in active_cases
                if str(item.get("case_id", "") or "").strip() != requested_case_id
            ]
            if conflicting_active_cases:
                active_case_references = ", ".join(
                    self._format_case_reference(item)
                    for item in conflicting_active_cases
                )
                raise ValueError(
                    "La persona ya tiene un caso activo: "
                    f"{active_case_references}. "
                    "Debes cerrarlo o resolver el conflicto antes de crear uno nuevo."
                )

        if employee_phone and context_label:
            for existing_case in self.sheets_service.list_expense_cases():
                existing_phone = normalize_whatsapp_phone(
                    existing_case.get("employee_phone", existing_case.get("phone", ""))
                )
                existing_label = str(existing_case.get("context_label", "") or "").strip().lower()
                existing_status = str(existing_case.get("status", "") or "").strip().lower()
                existing_company_id = str(existing_case.get("company_id", "") or "").strip().lower()
                if (
                    existing_phone == employee_phone
                    and existing_label == context_label
                    and existing_status == status
                    and existing_company_id == company_id
                ):
                    case_id = str(existing_case.get("case_id", "") or "").strip()
                    if case_id:
                        merged = dict(existing_case)
                        merged.update(data)
                        return self.sheets_service.update_expense_case(case_id, merged) or existing_case
        data.setdefault("case_id", make_id("case"))
        return self.sheets_service.create_expense_case(data)

    def update_case(self, case_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.sheets_service.update_expense_case(case_id, payload)

    def get_case_transition_gate(self, case_id: str) -> dict[str, Any]:
        expense_case = self.sheets_service.get_expense_case_by_id(case_id)
        if not expense_case:
            raise ValueError("Case not found")

        expenses = [
            item
            for item in self.sheets_service.list_expenses()
            if str(item.get("case_id", "") or "").strip() == str(case_id or "").strip()
        ]

        unresolved_expenses: list[dict[str, Any]] = []
        for expense in expenses:
            expense_status = normalize_state(expense.get("status"))
            review_status = normalize_review_status(
                expense.get("review_status"),
                expense_status=expense_status,
            )
            resolved = is_resolved_expense_status(expense_status) or review_status in {
                ExpenseReviewStatus.APPROVED,
                ExpenseReviewStatus.REJECTED,
            }
            if resolved:
                continue
            unresolved_expenses.append(
                {
                    "expense_id": expense.get("expense_id"),
                    "merchant": expense.get("merchant"),
                    "status": expense_status,
                    "review_status": review_status,
                    "canonical_document_status": resolve_canonical_document_status(
                        expense_status=expense_status,
                        review_status=review_status,
                    ),
                }
            )

        return {
            "case_id": case_id,
            "expense_count": len(expenses),
            "resolved_expense_count": len(expenses) - len(unresolved_expenses),
            "has_documents": bool(expenses),
            "all_documents_resolved": not unresolved_expenses,
            "unresolved_expenses": unresolved_expenses,
        }

    def ensure_case_ready_for_document_confirmation(self, case_id: str) -> dict[str, Any]:
        gate = self.get_case_transition_gate(case_id)
        if not gate["has_documents"]:
            raise ValueError(
                "No puedes solicitar confirmación del usuario porque la rendición no tiene documentos."
            )
        if not gate["all_documents_resolved"]:
            raise ValueError(self._build_unresolved_documents_error(gate["unresolved_expenses"]))
        return gate

    def ensure_case_ready_for_close(self, case_id: str) -> dict[str, Any]:
        gate = self.ensure_case_ready_for_document_confirmation(case_id)
        expense_case = self.sheets_service.get_expense_case_by_id(case_id) or {}
        current_rendicion_status = normalize_rendicion_status(expense_case.get("rendicion_status"))
        if current_rendicion_status != RendicionStatus.APPROVED:
            raise ValueError("La rendición solo se puede cerrar después de estar aprobada.")
        case_expenses = [
            item
            for item in self.sheets_service.list_expenses()
            if str(item.get("case_id", "") or "").strip() == str(case_id or "").strip()
        ]
        settlement_snapshot = self._get_case_settlement_snapshot(
            expense_case,
            case_expenses=case_expenses,
        )
        settlement_direction = settlement_snapshot["settlement_direction"]
        has_financial_inputs = (
            parse_float(expense_case.get("fondos_entregados")) is not None
            or any(parse_float(item.get("total_clp")) is not None for item in case_expenses)
        )
        if settlement_direction == SettlementDirection.BALANCED and has_financial_inputs:
            settlement_status = settlement_snapshot["settlement_status"]
        else:
            settlement_status = (
                normalize_state(expense_case.get("settlement_status"))
                or settlement_snapshot["settlement_status"]
            )
        if settlement_status != SettlementStatus.SETTLED:
            raise ValueError(
                "La rendición no se puede cerrar porque la liquidación financiera sigue pendiente."
            )
        return gate

    def ensure_case_ready_for_settlement_resolution(self, case_id: str) -> dict[str, Any]:
        gate = self.ensure_case_ready_for_document_confirmation(case_id)
        expense_case = self.sheets_service.get_expense_case_by_id(case_id) or {}
        current_rendicion_status = normalize_rendicion_status(expense_case.get("rendicion_status"))
        if current_rendicion_status != RendicionStatus.APPROVED:
            raise ValueError(
                "La liquidación solo se puede resolver después de aprobar la rendición."
            )
        settlement_snapshot = self._get_case_settlement_snapshot(expense_case)
        settlement_direction = normalize_state(
            expense_case.get("settlement_direction", settlement_snapshot["settlement_direction"])
        ) or settlement_snapshot["settlement_direction"]
        if settlement_direction == SettlementDirection.BALANCED:
            raise ValueError(
                "La rendición ya está cuadrada; no requiere resolución manual de liquidación."
            )
        return gate

    def sync_case_settlement(
        self,
        case_id: str,
        *,
        mark_settled: bool = False,
        resolved_at: str | None = None,
    ) -> dict[str, Any]:
        expense_case = self.sheets_service.get_expense_case_by_id(case_id)
        if not expense_case:
            raise ValueError("Case not found")

        case_expenses = [
            item
            for item in self.sheets_service.list_expenses()
            if str(item.get("case_id", "") or "").strip() == str(case_id or "").strip()
        ]
        settlement = self._get_case_settlement_snapshot(
            expense_case,
            case_expenses=case_expenses,
            mark_settled=mark_settled,
            resolved_at=resolved_at,
        )
        payload = {
            **settlement,
            "updated_at": utc_now_iso(),
        }
        updated = self.sheets_service.update_expense_case(case_id, payload)
        if not updated:
            raise ValueError("Case not found")
        return updated

    def list_expenses(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        expenses = self._enrich_expenses(self.sheets_service.list_expenses())
        filters = filters or {}
        status = str(filters.get("status", "") or "").strip().lower()
        review_status = normalize_state(filters.get("review_status"))
        employee_phone = str(filters.get("employee_phone", "") or "").strip()
        category = str(filters.get("category", "") or "").strip().lower()
        date_from = str(filters.get("date_from", "") or "").strip()
        date_to = str(filters.get("date_to", "") or "").strip()
        sort_by = str(filters.get("sort_by", "") or "").strip().lower()
        if status:
            expenses = [
                item for item in expenses if str(item.get("status", "")).strip().lower() == status
            ]
        if review_status:
            expenses = [
                item
                for item in expenses
                if normalize_review_status(
                    item.get("review_status"),
                    expense_status=item.get("status"),
                )
                == review_status
            ]
        if employee_phone:
            expenses = self._filter_expenses_by_employee_phone(expenses, employee_phone)
        if category:
            expenses = [
                item
                for item in expenses
                if str(item.get("category", "")).strip().lower() == category
            ]
        if date_from:
            expenses = [item for item in expenses if str(item.get("date", "")).strip() >= date_from]
        if date_to:
            expenses = [item for item in expenses if str(item.get("date", "")).strip() <= date_to]
        if sort_by == "review_priority":
            expenses.sort(
                key=lambda e: (
                    REVIEW_PRIORITY_ORDER.get(
                        normalize_review_status(
                            e.get("review_status"),
                            expense_status=e.get("status"),
                        ),
                        1,
                    ),
                    self._safe_review_score(e),
                )
            )
        return expenses

    @staticmethod
    def _safe_review_score(expense: dict[str, Any]) -> float:
        try:
            return float(expense.get("review_score", 50))
        except (TypeError, ValueError):
            return 50.0

    def get_expense_detail(self, expense_id: str) -> dict[str, Any] | None:
        expense = self.sheets_service.get_expense_by_id(expense_id)
        if not expense:
            return None
        case = self.sheets_service.get_expense_case_by_id(expense.get("case_id", ""))
        employee = self.sheets_service.get_employee_any_by_phone(expense.get("phone", ""))
        detail = self._enrich_expenses([expense])[0]
        return {"expense": detail, "case": case, "employee": employee}

    def update_expense(self, expense_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.sheets_service.get_expense_by_id(expense_id)
        if not existing:
            return None
        data = dict(payload)
        if "status" in data and "review_status" not in data:
            status = normalize_state(data.get("status"))
            if status == ExpenseStatus.APPROVED:
                data["review_status"] = ExpenseReviewStatus.APPROVED
            elif status == ExpenseStatus.REJECTED:
                data["review_status"] = ExpenseReviewStatus.REJECTED
            elif status == ExpenseStatus.OBSERVED:
                data["review_status"] = ExpenseReviewStatus.OBSERVED
            elif status == ExpenseStatus.NEEDS_MANUAL_REVIEW:
                data["review_status"] = ExpenseReviewStatus.NEEDS_MANUAL_REVIEW
            elif status == ExpenseStatus.PENDING_REVIEW:
                data["review_status"] = ExpenseReviewStatus.PENDING_REVIEW
            elif status == ExpenseStatus.PENDING_APPROVAL:
                data["review_status"] = ""
        updated = self.sheets_service.update_expense(expense_id, data)
        if not updated:
            return None
        case_id = str(updated.get("case_id", "") or "").strip()
        if case_id:
            expense_case = self.sheets_service.get_expense_case_by_id(case_id) or {}
            rendicion_status = normalize_rendicion_status(expense_case.get("rendicion_status"))
            if rendicion_status in {RendicionStatus.APPROVED, RendicionStatus.CLOSED}:
                existing_settlement_status = normalize_state(expense_case.get("settlement_status"))
                resolved_at = str(expense_case.get("settlement_resolved_at", "") or "").strip() or None
                self.sync_case_settlement(
                    case_id,
                    mark_settled=existing_settlement_status == SettlementStatus.SETTLED,
                    resolved_at=resolved_at,
                )
        enriched = self._enrich_expenses([updated])
        return enriched[0] if enriched else updated

    def list_conversations(self) -> list[dict[str, Any]]:
        return self._enrich_conversations(self.sheets_service.list_conversations())

    def get_conversation_detail(self, phone: str) -> dict[str, Any] | None:
        conversation = self.sheets_service.get_conversation(phone)
        if not conversation:
            return None
        employee = self.sheets_service.get_employee_any_by_phone(phone)
        expense_case = self.sheets_service.get_expense_case_by_id(conversation.get("case_id", ""))
        return {
            "conversation": self._enrich_conversations([conversation])[0],
            "employee": employee,
            "case": expense_case,
        }

    def update_conversation(self, phone: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload)
        if "state" in data and str(data.get("state", "")).strip().lower() == "resolved":
            data["state"] = "DONE"
        if not data.get("updated_at"):
            data["updated_at"] = utc_now_iso()
        return self.sheets_service.update_conversation(phone, data)

    @staticmethod
    def _build_unresolved_documents_error(unresolved_expenses: list[dict[str, Any]]) -> str:
        if not unresolved_expenses:
            return "Todavía hay documentos sin resolver."
        preview = ", ".join(
            (
                str(item.get("merchant") or item.get("expense_id") or "documento").strip()
                + f" [{str(item.get('canonical_document_status') or item.get('status') or 'pendiente').strip()}]"
            )
            for item in unresolved_expenses[:3]
        )
        extra = len(unresolved_expenses) - min(len(unresolved_expenses), 3)
        if extra > 0:
            preview += f" y {extra} más"
        return (
            "No puedes avanzar la rendición porque aún hay documentos no resueltos: "
            f"{preview}."
        )

    @staticmethod
    def _compute_rendicion_balance(
        fondos_entregados: float,
        case_expenses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        monto_aprobado = 0.0
        monto_pendiente = 0.0
        for exp in case_expenses:
            total_clp = parse_float(exp.get("total_clp")) or 0.0
            status = normalize_state(exp.get("status"))
            if status == ExpenseStatus.APPROVED:
                monto_aprobado += total_clp
            elif status in EXPENSE_PENDING_STATUSES or status == "pending":
                monto_pendiente += total_clp
        return {
            "monto_rendido_aprobado": round(monto_aprobado, 2),
            "monto_pendiente_revision": round(monto_pendiente, 2),
            "saldo_restante": round(fondos_entregados - monto_aprobado, 2),
        }

    @staticmethod
    def _compute_case_settlement(
        *,
        fondos_entregados: float,
        monto_aprobado: float,
        mark_settled: bool = False,
        resolved_at: str | None = None,
    ) -> dict[str, Any]:
        net = round((monto_aprobado or 0.0) - (fondos_entregados or 0.0), 2)
        amount = round(abs(net), 2)
        calculated_at = utc_now_iso()

        if net > 0:
            direction = SettlementDirection.COMPANY_OWES_EMPLOYEE
        elif net < 0:
            direction = SettlementDirection.EMPLOYEE_OWES_COMPANY
        else:
            direction = SettlementDirection.BALANCED

        if direction == SettlementDirection.BALANCED:
            settlement_status = SettlementStatus.SETTLED
            settlement_resolved_at = resolved_at or calculated_at
        elif mark_settled:
            settlement_status = SettlementStatus.SETTLED
            settlement_resolved_at = resolved_at or calculated_at
        else:
            settlement_status = SettlementStatus.PENDING
            settlement_resolved_at = ""

        return {
            "settlement_direction": direction,
            "settlement_status": settlement_status,
            "settlement_amount_clp": amount,
            "settlement_net_clp": net,
            "settlement_calculated_at": calculated_at,
            "settlement_resolved_at": settlement_resolved_at,
        }

    def _get_case_settlement_snapshot(
        self,
        expense_case: dict[str, Any],
        *,
        case_expenses: list[dict[str, Any]] | None = None,
        mark_settled: bool = False,
        resolved_at: str | None = None,
    ) -> dict[str, Any]:
        case_id = str(expense_case.get("case_id", "") or "").strip()
        expenses = case_expenses
        if expenses is None:
            expenses = [
                item
                for item in self.sheets_service.list_expenses()
                if str(item.get("case_id", "") or "").strip() == case_id
            ]
        fondos = parse_float(expense_case.get("fondos_entregados")) or 0.0
        balance = self._compute_rendicion_balance(fondos, expenses)
        return self._compute_case_settlement(
            fondos_entregados=fondos,
            monto_aprobado=balance["monto_rendido_aprobado"],
            mark_settled=mark_settled,
            resolved_at=resolved_at,
        )

    def _enrich_cases(self, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        employees_by_phone = {
            item.get("phone"): item for item in self.sheets_service.list_employees()
        }
        expenses = self.sheets_service.list_expenses()
        enriched: list[dict[str, Any]] = []
        for case in cases:
            item = dict(case)
            phone = item.get("employee_phone", item.get("phone", ""))
            item["employee"] = employees_by_phone.get(phone)
            case_expenses = [e for e in expenses if e.get("case_id") == item.get("case_id")]
            item["expense_count"] = len(case_expenses)
            fondos = parse_float(item.get("fondos_entregados")) or 0.0
            balance = self._compute_rendicion_balance(fondos, case_expenses)
            item.update(balance)
            settlement = self._compute_case_settlement(
                fondos_entregados=fondos,
                monto_aprobado=balance["monto_rendido_aprobado"],
                mark_settled=normalize_state(item.get("settlement_status")) == SettlementStatus.SETTLED,
                resolved_at=str(item.get("settlement_resolved_at", "") or "").strip() or None,
            )
            stored_status = normalize_state(item.get("settlement_status"))
            if stored_status and settlement["settlement_direction"] != SettlementDirection.BALANCED:
                settlement["settlement_status"] = stored_status
            stored_resolved_at = str(item.get("settlement_resolved_at", "") or "").strip()
            if stored_resolved_at:
                settlement["settlement_resolved_at"] = stored_resolved_at
            stored_calculated_at = str(item.get("settlement_calculated_at", "") or "").strip()
            if stored_calculated_at:
                settlement["settlement_calculated_at"] = stored_calculated_at
            item.update(settlement)
            enriched.append(item)
        return enriched

    def _enrich_expenses(self, expenses: list[dict[str, Any]]) -> list[dict[str, Any]]:
        employees_by_phone = {
            item.get("phone"): item for item in self.sheets_service.list_employees()
        }
        cases_by_id = {
            item.get("case_id"): item for item in self.sheets_service.list_expense_cases()
        }
        enriched: list[dict[str, Any]] = []
        for expense in expenses:
            item = dict(expense)
            item["review_status"] = normalize_review_status(
                item.get("review_status"),
                expense_status=item.get("status"),
            )
            item["employee"] = employees_by_phone.get(item.get("phone"))
            item["case"] = cases_by_id.get(item.get("case_id"))
            if item.get("employee") is None and item.get("case"):
                case_phone = item["case"].get("employee_phone", item["case"].get("phone", ""))
                item["employee"] = employees_by_phone.get(case_phone)
            enriched.append(item)
        return enriched

    def _enrich_conversations(self, conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        employees_by_phone = {
            item.get("phone"): item for item in self.sheets_service.list_employees()
        }
        cases_by_id = {
            item.get("case_id"): item for item in self.sheets_service.list_expense_cases()
        }
        enriched: list[dict[str, Any]] = []
        for conversation in conversations:
            item = dict(conversation)
            if not item.get("case_id"):
                draft = item.get("context_json", {}).get("draft_expense", {})
                item["case_id"] = str(draft.get("case_id", "") or "").strip()
            item["employee"] = employees_by_phone.get(item.get("phone"))
            item["case"] = cases_by_id.get(item.get("case_id"))
            enriched.append(item)
        return enriched

    def _max_timestamp(self, values: list[Any]) -> str:
        cleaned = [str(value or "").strip() for value in values if str(value or "").strip()]
        if not cleaned:
            return ""
        return max(cleaned)

    def _get_expenses_for_employee(self, phone: str) -> list[dict[str, Any]]:
        return self._filter_expenses_by_employee_phone(
            self.sheets_service.list_expenses(),
            phone,
        )

    def _filter_expenses_by_employee_phone(
        self,
        expenses: list[dict[str, Any]],
        employee_phone: str,
    ) -> list[dict[str, Any]]:
        target_phone = self.sheets_service.get_employee_any_by_phone(employee_phone)
        normalized_phone = (
            str(target_phone.get("phone", "") or "").strip()
            if target_phone
            else str(employee_phone or "").strip()
        )
        cases_by_id = {
            item.get("case_id"): item for item in self.sheets_service.list_expense_cases()
        }
        filtered: list[dict[str, Any]] = []
        for expense in expenses:
            expense_phone = str(expense.get("phone", "") or "").strip()
            expense_case = cases_by_id.get(expense.get("case_id"))
            case_phone = ""
            if expense_case:
                case_phone = str(
                    expense_case.get("employee_phone", expense_case.get("phone", "")) or ""
                ).strip()
            if expense_phone == normalized_phone or case_phone == normalized_phone:
                filtered.append(expense)
        return filtered
