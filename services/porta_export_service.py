from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from services.backoffice_permissions import can_access_company
from services.porta_excel_export_service import FORMAT_VERSION, PortaExcelExportService
from services.statuses import is_expense_eligible_for_accounting_export
from utils.helpers import json_dumps, json_loads, make_id, utc_now_iso


PORTA_COST_CENTERS = {
    "gastos de produccion": "Gastos de Producción",
    "alimentacion": "Alimentación",
    "combustible": "Combustible",
    "estacionamientos peajes y taxis": "Estacionamientos-Peajes-Taxis",
    "boletas de honorarios": "Boletas de Honorarios",
    "facturas": "Facturas",
}
VALID_SCOPES = {"case", "month", "range", "company"}
VALID_DATE_SOURCES = {"document_date", "case_closed_at"}


def _normalized_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _integer(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@dataclass
class PortaExportService:
    sheets_service: Any
    storage_service: Any
    excel_service: PortaExcelExportService
    default_date_source: str = "document_date"
    expense_service: Any = None

    def preview(self, *, user: dict[str, Any], **filters: Any) -> dict[str, Any]:
        return self._dataset(user=user, **filters)["preview"]

    def generate(self, *, user: dict[str, Any], **filters: Any) -> dict[str, Any]:
        dataset = self._dataset(user=user, **filters)
        preview = dataset["preview"]
        if not preview["included_count"]:
            raise ValueError("No hay gastos elegibles y completos para exportar")
        export_id = make_id("porta")
        now = utc_now_iso()
        normalized = dataset["filters"]
        row = {
            "export_id": export_id,
            "company_id": normalized["company_id"],
            "scope": normalized["scope"],
            "case_id": normalized.get("case_id", ""),
            "period_year": normalized.get("year", ""),
            "period_month": normalized.get("month", ""),
            "date_from": normalized.get("date_from", ""),
            "date_to": normalized.get("date_to", ""),
            "date_source": normalized["date_source"],
            "filters_json": json_dumps(normalized),
            "status": "processing",
            "requested_by": str(user.get("email", "") or ""),
            "requested_at": now,
            "completed_at": "",
            "expense_count": preview["included_count"],
            "case_count": preview["case_count"],
            "total_clp": preview["total_clp"],
            "warnings_json": json_dumps(preview["excluded"]),
            "format_version": FORMAT_VERSION,
        }
        self.sheets_service.create_porta_export(row)
        try:
            content = self.excel_service.render(dataset["included"])
            scope_label = self._scope_label(normalized)
            object_key = (
                f"porta-exports/{normalized['company_id']}/{scope_label}/"
                f"{export_id}/Rendicion_Porta_{scope_label}.xlsx"
            )
            self.storage_service.upload_private_bytes(
                object_key=object_key,
                content=content,
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            status = "completed_with_warnings" if preview["excluded"] else "completed"
            updated = self.sheets_service.update_porta_export(
                export_id,
                {
                    "status": status,
                    "completed_at": utc_now_iso(),
                    "xlsx_object_key": object_key,
                },
            )
            return self._public_row(updated or row)
        except Exception as exc:
            self.sheets_service.update_porta_export(
                export_id, {"status": "failed", "error_message": str(exc)}
            )
            raise

    def list_for_user(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._public_row(row)
            for row in self.sheets_service.list_porta_exports()
            if can_access_company(user, row.get("company_id", ""))
        ][:50]

    def get_for_user(self, user: dict[str, Any], export_id: str) -> dict[str, Any] | None:
        row = self.sheets_service.get_porta_export(export_id)
        if not row or not can_access_company(user, row.get("company_id", "")):
            return None
        return self._public_row(row)

    def signed_download_url(self, user: dict[str, Any], export_id: str) -> str | None:
        row = self.sheets_service.get_porta_export(export_id)
        if not row or not can_access_company(user, row.get("company_id", "")):
            return None
        object_key = str(row.get("xlsx_object_key", "") or "")
        if not object_key:
            return None
        return self.storage_service.generate_signed_url(object_key=object_key, ttl_seconds=300)

    def _dataset(
        self,
        *,
        user: dict[str, Any],
        company_id: str,
        scope: str,
        case_id: str = "",
        year: int | str = "",
        month: int | str = "",
        date_from: str = "",
        date_to: str = "",
        date_source: str = "",
    ) -> dict[str, Any]:
        scope = str(scope or "").strip().lower()
        if scope not in VALID_SCOPES:
            raise ValueError("Modalidad de exportación inválida")
        date_source = str(date_source or self.default_date_source).strip().lower()
        if date_source not in VALID_DATE_SOURCES:
            raise ValueError("Regla temporal inválida")
        if not company_id or not can_access_company(user, company_id):
            raise PermissionError("No tienes acceso a la empresa seleccionada")
        if not any(
            str(company.get("company_id", "")) == company_id
            for company in self.sheets_service.list_companies()
        ):
            raise ValueError("Empresa inexistente")
        if scope == "case" and not case_id:
            raise ValueError("Debes indicar un caso")
        if scope == "month":
            year, month = int(year), int(month)
            if not (2000 <= year <= 2100 and 1 <= month <= 12):
                raise ValueError("Mes inválido")
        if scope == "range":
            try:
                start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
            except ValueError as exc:
                raise ValueError("Rango de fechas inválido") from exc
            if start > end:
                raise ValueError("La fecha desde no puede ser posterior a la fecha hasta")

        employee_companies = {
            str(employee.get("phone", "") or ""): str(employee.get("company_id", "") or "")
            for employee in self.sheets_service.list_employees()
        }
        company_cases = {}
        for item in self.sheets_service.list_expense_cases():
            phone = str(item.get("employee_phone", item.get("phone", "")) or "")
            resolved_company = str(item.get("company_id", "") or employee_companies.get(phone, ""))
            if resolved_company == company_id:
                company_cases[str(item.get("case_id", ""))] = item
        if scope == "case" and case_id not in company_cases:
            raise ValueError("Caso inexistente o de otra empresa")

        included, excluded = [], []
        selected_case_ids: set[str] = set()
        for expense in self.sheets_service.list_expenses():
            expense_case_id = str(expense.get("case_id", "") or "")
            case = company_cases.get(expense_case_id)
            if not case or (scope == "case" and expense_case_id != case_id):
                continue
            temporal_value = expense.get("date") if date_source == "document_date" else case.get("closed_at")
            temporal = str(temporal_value or "")[:10]
            if scope == "month" and not temporal.startswith(f"{year:04d}-{month:02d}"):
                continue
            if scope == "range" and not (len(temporal) == 10 and date_from <= temporal <= date_to):
                continue
            if not is_expense_eligible_for_accounting_export(expense):
                continue
            selected_case_ids.add(expense_case_id)
            prepared, reasons = self._prepare_expense(expense)
            if reasons:
                excluded.append(
                    {
                        "expense_id": str(expense.get("expense_id", "")),
                        "case_id": expense_case_id,
                        "reasons": reasons,
                    }
                )
            else:
                included.append(prepared)

        total = sum(int(item["gross_amount"]) for item in included)
        by_sheet = {
            sheet: sum(1 for item in included if item["porta_sheet"] == sheet)
            for sheet in PORTA_COST_CENTERS.values()
        }
        filters = {
            "company_id": company_id, "scope": scope, "case_id": case_id,
            "year": year, "month": month, "date_from": date_from,
            "date_to": date_to, "date_source": date_source,
        }
        return {
            "filters": filters,
            "included": included,
            "preview": {
                "company_id": company_id,
                "scope": scope,
                "date_source": date_source,
                "included_count": len(included),
                "excluded_count": len(excluded),
                "case_count": len(selected_case_ids),
                "total_clp": total,
                "by_sheet": by_sheet,
                "excluded": excluded,
            },
        }

    def _prepare_expense(self, expense: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        if self.expense_service is not None:
            expense = self.expense_service.prepare_accounting_export_fields(expense)
        reasons: list[str] = []
        sheet = PORTA_COST_CENTERS.get(_normalized_text(expense.get("cost_center")))
        if not sheet:
            reasons.append("Centro de costo no corresponde a una hoja Porta")
        expense_date = str(expense.get("date", "") or "")[:10]
        try:
            date.fromisoformat(expense_date)
        except ValueError:
            reasons.append("Fecha del documento incompleta")
        document_number = str(
            expense.get("invoice_number")
            or expense.get("document_number")
            or expense.get("receipt_number")
            or ""
        ).strip()
        if sheet in {"Facturas", "Boletas de Honorarios"} and not document_number:
            reasons.append("Número de documento incompleto")
        detail = str(expense.get("service_description") or expense.get("merchant") or "").strip()
        if not detail:
            reasons.append("Detalle del gasto incompleto")
        gross = _decimal(expense.get("gross_amount"))
        total = _decimal(expense.get("total_clp")) or _decimal(expense.get("total"))
        gross = gross or total
        net = _decimal(expense.get("net_amount"))
        tax = _decimal(expense.get("tax_amount"))
        withholding = _decimal(expense.get("withholding_amount"))
        if sheet == "Facturas":
            if gross is None and net is not None and tax is not None:
                gross = net + tax
            if net is None and gross is not None and tax is not None:
                net = gross - tax
            if tax is None and gross is not None and net is not None:
                tax = gross - net
            if net is None and gross is not None:
                net = gross / Decimal("1.19")
                tax = gross - net
            if any(value is None for value in (net, tax, gross)):
                reasons.append("Montos neto, IVA o total incompletos")
        elif sheet == "Boletas de Honorarios":
            if gross is None and net is not None and withholding is not None:
                gross = net + withholding
            if net is None and gross is not None and withholding is not None:
                net = gross - withholding
            if withholding is None and gross is not None and net is not None:
                withholding = gross - net
            if any(value is None for value in (net, withholding, gross)):
                reasons.append("Montos líquido, retención o bruto incompletos")
        elif gross is None:
            reasons.append("Monto total incompleto")
        prepared = {
            "expense_id": str(expense.get("expense_id", "")),
            "porta_sheet": sheet or "",
            "date": expense_date,
            "document_number": document_number,
            "detail": detail,
            "net_amount": _integer(net or Decimal("0")),
            "tax_amount": _integer(tax or Decimal("0")),
            "withholding_amount": _integer(withholding or Decimal("0")),
            "gross_amount": _integer(gross or Decimal("0")),
        }
        return prepared, reasons

    @staticmethod
    def _scope_label(filters: dict[str, Any]) -> str:
        if filters["scope"] == "case":
            return f"caso-{filters['case_id']}"
        if filters["scope"] == "month":
            return f"{int(filters['year']):04d}-{int(filters['month']):02d}"
        if filters["scope"] == "range":
            return f"{filters['date_from']}-{filters['date_to']}"
        return "empresa-completa"

    @staticmethod
    def _public_row(row: dict[str, Any]) -> dict[str, Any]:
        public = dict(row)
        public["filters"] = json_loads(public.pop("filters_json", ""), default={})
        public["warnings"] = json_loads(public.pop("warnings_json", ""), default=[])
        public.pop("xlsx_object_key", None)
        return public
