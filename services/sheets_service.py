from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import Settings
from utils.helpers import (
    json_dumps,
    json_loads,
    make_id,
    normalize_whatsapp_phone,
    parse_iso_date,
    truthy,
    utc_now_iso,
)


logger = logging.getLogger(__name__)


SHEET_NAMES = {
    "companies": "empresas",
    "employees": "Employees",
    "expense_cases": "ExpenseCases",
    "expenses": "Expenses",
    "conversations": "Conversations",
    "expense_case_documents": "ExpenseCaseDocuments",
    "backoffice_users": "BackofficeUsers",
}

LEGACY_SHEET_NAMES = {
    "expense_cases": "Trips",
    "expense_case_documents": "TripDocuments",
}

_EMPLOYEE_REQUIRED_HEADERS = [
    "phone",
    "first_name",
    "last_name",
    "name",
    "rut",
    "email",
    "company_id",
    "bank_name",
    "account_type",
    "account_number",
    "account_holder",
    "account_holder_rut",
    "active",
    "last_activity_at",
    "created_at",
    "updated_at",
]
_EXPENSE_REQUIRED_HEADERS = {
    "receipt_storage_provider",
    "receipt_object_key",
    "source_message_id",
    "image_url",
    "document_url",
    "updated_at",
    "processing_status",
    "case_lookup_status",
    "review_reason",
    "document_type",
    "invoice_number",
    "tax_amount",
    "issuer_tax_id",
    "receiver_tax_id",
    "gross_amount",
    "withholding_rate",
    "withholding_amount",
    "net_amount",
    "receiver_name",
    "service_description",
}
_TRIP_REQUIRED_HEADERS = [
    "company_id",
    "employee_phone",
    "context_label",
    "closure_method",
    "closure_status",
    "closure_prompted_at",
    "closure_deadline_at",
    "closure_response",
    "closure_responded_at",
    "closed_at",
    "closure_reason",
    "max_total_amount",
    "max_receipt_amount",
    "created_at",
    "updated_at",
    "notes",
    "fondos_entregados",
    "rendicion_status",
    "user_confirmed_at",
    "user_confirmation_status",
    "settlement_direction",
    "settlement_status",
    "settlement_amount_clp",
    "settlement_net_clp",
    "settlement_calculated_at",
    "settlement_resolved_at",
]
_CONVERSATION_REQUIRED_HEADERS = [
    "phone",
    "case_id",
    "state",
    "current_step",
    "context_json",
    "updated_at",
]
_TRIP_DOCUMENT_HEADERS = [
    "document_id",
    "phone",
    "case_id",
    "storage_provider",
    "object_key",
    "expense_count",
    "total_clp",
    "status",
    "created_at",
    "updated_at",
    "signature_provider",
    "signature_status",
    "docusign_envelope_id",
    "signature_url",
    "signature_sent_at",
    "signature_completed_at",
    "signature_declined_at",
    "signature_expired_at",
    "signed_storage_provider",
    "signed_object_key",
    "signature_error",
]
_BACKOFFICE_USER_HEADERS = [
    "id",
    "name",
    "email",
    "password_hash",
    "role",
    "active",
    "created_at",
    "updated_at",
]
_COMPANY_HEADERS = [
    "company_id",
    "name",
    "rut",
    "bank_name",
    "account_type",
    "account_number",
    "account_holder",
    "account_holder_rut",
    "finance_email",
    "active",
]


def _to_sheet_cell(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json_dumps(value)
    return value


def _column_label(column_number: int) -> str:
    if column_number < 1:
        raise ValueError("column_number must be >= 1")
    label = ""
    current = column_number
    while current > 0:
        current, remainder = divmod(current - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


@dataclass
class SheetsService:
    settings: Settings
    record_cache_ttl_seconds: float = 15.0

    def __post_init__(self) -> None:
        configured_record_cache_ttl = getattr(
            self.settings,
            "google_sheets_record_cache_ttl_seconds",
            self.record_cache_ttl_seconds,
        )
        self.record_cache_ttl_seconds = max(0.0, float(configured_record_cache_ttl))
        self.read_cooldown_seconds = max(
            0.0,
            float(getattr(self.settings, "google_sheets_read_cooldown_seconds", 60) or 60),
        )
        self._client = None
        self._spreadsheet = None
        self._worksheet_cache: dict[str, Any] = {}
        self._records_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._headers_cache: dict[str, tuple[float, list[str]]] = {}
        self._read_cooldowns: dict[str, float] = {}
        self._memory_store: dict[str, list[dict[str, Any]]] = {
            "empresas": [],
            "Employees": [],
            "ExpenseCases": [],
            "Expenses": [],
            "Conversations": [],
            "ExpenseCaseDocuments": [],
            "BackofficeUsers": [],
        }
        if self.settings.google_sheets_enabled:
            self._connect()
            self._ensure_required_headers()

    @property
    def enabled(self) -> bool:
        return self._spreadsheet is not None

    def _connect(self) -> None:
        try:
            import gspread
            import google.auth
            from google.oauth2.service_account import Credentials
        except ImportError as exc:  # pragma: no cover - dependency setup
            raise RuntimeError(
                "Faltan dependencias para Google Sheets. Instala gspread y google-auth."
            ) from exc

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
        ]
        credentials_path = (self.settings.google_application_credentials or "").strip()
        if credentials_path:
            creds = Credentials.from_service_account_file(
                credentials_path,
                scopes=scopes,
            )
            auth_source = f"file:{credentials_path}"
        else:
            creds, _ = google.auth.default(scopes=scopes)
            auth_source = "adc"
        self._client = gspread.authorize(creds)
        self._client.http_client.timeout = max(
            1.0,
            float(getattr(self.settings, "google_sheets_timeout_seconds", 15) or 15),
        )
        self._spreadsheet = self._client.open_by_key(
            self.settings.google_sheets_spreadsheet_id
        )
        logger.info(
            "Google Sheets connected spreadsheet_id=%s auth=%s timeout_seconds=%.1f",
            self.settings.google_sheets_spreadsheet_id,
            auth_source,
            self._client.http_client.timeout,
        )

    def _worksheet(self, name: str):
        if not self._spreadsheet:
            return None
        cached = self._worksheet_cache.get(name)
        if cached is not None:
            return cached
        try:
            ws = self._with_retry(lambda: self._spreadsheet.worksheet(name))
        except Exception as exc:  # pragma: no cover - runtime dependency/errors
            if not self._is_worksheet_not_found(exc):
                raise
            logger.info("Worksheet not found, attempting recovery worksheet=%s", name)
            legacy_name = next(
                (
                    legacy
                    for key, canonical in SHEET_NAMES.items()
                    if canonical == name and (legacy := LEGACY_SHEET_NAMES.get(key))
                ),
                None,
            )
            if legacy_name:
                try:
                    ws = self._with_retry(lambda: self._spreadsheet.worksheet(legacy_name))
                except Exception as legacy_exc:  # pragma: no cover - runtime dependency/errors
                    if not self._is_worksheet_not_found(legacy_exc):
                        raise
                    logger.info(
                        "Creating missing worksheet worksheet=%s legacy_worksheet=%s",
                        name,
                        legacy_name,
                    )
                    ws = self._with_retry(
                        lambda: self._spreadsheet.add_worksheet(title=name, rows=200, cols=30)
                    )
            else:
                logger.info("Creating missing worksheet worksheet=%s", name)
                ws = self._with_retry(
                    lambda: self._spreadsheet.add_worksheet(title=name, rows=200, cols=30)
                )
        self._worksheet_cache[name] = ws
        return ws

    def _get_records(self, name: str) -> list[dict[str, Any]]:
        ws = self._worksheet(name)
        if ws is None:
            return list(self._memory_store.get(name, []))
        cached = self._records_cache.get(name)
        now = time.monotonic()
        if (
            cached
            and self.record_cache_ttl_seconds > 0
            and now - cached[0] <= self.record_cache_ttl_seconds
        ):
            return [row.copy() for row in cached[1]]
        cooldown_fallback = self._cached_records_during_read_cooldown(name=name, cached=cached)
        if cooldown_fallback is not None:
            return cooldown_fallback
        try:
            records = self._with_retry(lambda: self._get_worksheet_records(ws, name=name))
        except Exception as exc:
            self._mark_read_cooldown_if_needed(name=name, exc=exc)
            fallback = self._stale_records_fallback(name=name, cached=cached, exc=exc)
            if fallback is not None:
                return fallback
            raise
        self._clear_read_cooldown(name)
        self._records_cache[name] = (now, [dict(row) for row in records])
        return [dict(row) for row in records]

    def _get_worksheet_records(self, ws, *, name: str) -> list[dict[str, Any]]:
        try:
            return ws.get_all_records()
        except Exception as exc:
            if not self._is_duplicate_header_error(exc):
                raise
            logger.warning(
                "Worksheet has duplicate headers; using raw row fallback worksheet=%s error=%s",
                name,
                exc,
            )
            return self._get_records_with_duplicate_headers(ws)

    def _get_records_with_duplicate_headers(self, ws) -> list[dict[str, Any]]:
        rows = ws.get_all_values()
        if not rows:
            return []
        raw_headers = [str(value or "").strip() for value in rows[0]]
        records: list[dict[str, Any]] = []
        for raw_row in rows[1:]:
            if not any(str(value or "").strip() for value in raw_row):
                continue
            record: dict[str, Any] = {}
            for index, header in enumerate(raw_headers):
                if not header:
                    continue
                value = raw_row[index] if index < len(raw_row) else ""
                existing = record.get(header)
                if header not in record or (
                    not str(existing or "").strip() and str(value or "").strip()
                ):
                    record[header] = value
            records.append(record)
        return records

    def _get_headers(self, name: str) -> list[str]:
        ws = self._worksheet(name)
        if ws is None:
            rows = self._memory_store.get(name, [])
            if not rows:
                return []
            return list(rows[0].keys())
        cached = self._headers_cache.get(name)
        now = time.monotonic()
        if cached and now - cached[0] <= self.record_cache_ttl_seconds:
            return list(cached[1])
        cooldown_fallback = self._cached_headers_during_read_cooldown(name=name, cached=cached)
        if cooldown_fallback is not None:
            return cooldown_fallback
        try:
            headers = self._with_retry(lambda: ws.row_values(1))
        except Exception as exc:
            self._mark_read_cooldown_if_needed(name=name, exc=exc)
            fallback = self._stale_headers_fallback(name=name, cached=cached, exc=exc)
            if fallback is not None:
                return fallback
            raise
        self._clear_read_cooldown(name)
        self._headers_cache[name] = (now, list(headers))
        return list(headers)

    def _set_records_cache(self, name: str, records: list[dict[str, Any]]) -> None:
        self._records_cache[name] = (
            time.monotonic(),
            [dict(row) for row in records],
        )

    def _set_headers_cache(self, name: str, headers: list[str]) -> None:
        self._headers_cache[name] = (time.monotonic(), list(headers))

    def _stale_records_fallback(
        self,
        *,
        name: str,
        cached: tuple[float, list[dict[str, Any]]] | None,
        exc: Exception,
    ) -> list[dict[str, Any]] | None:
        if not cached or not self._can_use_stale_cache(cached_at=cached[0], exc=exc):
            return None
        age_seconds = max(0.0, time.monotonic() - cached[0])
        logger.warning(
            "Google Sheets stale records fallback worksheet=%s age_seconds=%.1f error=%s",
            name,
            age_seconds,
            exc,
        )
        return [row.copy() for row in cached[1]]

    def _stale_headers_fallback(
        self,
        *,
        name: str,
        cached: tuple[float, list[str]] | None,
        exc: Exception,
    ) -> list[str] | None:
        if not cached or not self._can_use_stale_cache(cached_at=cached[0], exc=exc):
            return None
        age_seconds = max(0.0, time.monotonic() - cached[0])
        logger.warning(
            "Google Sheets stale headers fallback worksheet=%s age_seconds=%.1f error=%s",
            name,
            age_seconds,
            exc,
        )
        return list(cached[1])

    def _can_use_stale_cache(self, *, cached_at: float, exc: Exception) -> bool:
        stale_ttl_seconds = self._stale_cache_ttl_seconds()
        age_seconds = max(0.0, time.monotonic() - cached_at)
        return age_seconds <= stale_ttl_seconds and self._is_retryable_sheets_error(exc)

    def _stale_cache_ttl_seconds(self) -> float:
        return max(
            self.record_cache_ttl_seconds,
            float(getattr(self.settings, "google_sheets_stale_cache_ttl_seconds", 300) or 300),
        )

    def _cached_records_during_read_cooldown(
        self,
        *,
        name: str,
        cached: tuple[float, list[dict[str, Any]]] | None,
    ) -> list[dict[str, Any]] | None:
        if not cached or not self._is_read_cooldown_active(name):
            return None
        if not self._can_use_cached_read_fallback(cached_at=cached[0]):
            return None
        return [row.copy() for row in cached[1]]

    def _cached_headers_during_read_cooldown(
        self,
        *,
        name: str,
        cached: tuple[float, list[str]] | None,
    ) -> list[str] | None:
        if not cached or not self._is_read_cooldown_active(name):
            return None
        if not self._can_use_cached_read_fallback(cached_at=cached[0]):
            return None
        return list(cached[1])

    def _can_use_cached_read_fallback(self, *, cached_at: float) -> bool:
        age_seconds = max(0.0, time.monotonic() - cached_at)
        return age_seconds <= self._stale_cache_ttl_seconds()

    def _is_read_cooldown_active(self, name: str) -> bool:
        until = self._read_cooldowns.get(name, 0.0)
        return until > time.monotonic()

    def _mark_read_cooldown_if_needed(self, *, name: str, exc: Exception) -> None:
        if not self._is_rate_limit_error(exc) or self.read_cooldown_seconds <= 0:
            return
        self._read_cooldowns[name] = time.monotonic() + self.read_cooldown_seconds

    def _clear_read_cooldown(self, name: str) -> None:
        self._read_cooldowns.pop(name, None)

    def _append_row(self, name: str, row_dict: dict[str, Any]) -> None:
        ws = self._worksheet(name)
        if ws is None:
            self._memory_store.setdefault(name, []).append(row_dict.copy())
            return
        headers = self._get_headers(name)
        row = [_to_sheet_cell(row_dict.get(header, "")) for header in headers]
        self._with_retry(lambda: ws.append_row(row, value_input_option="USER_ENTERED"))
        cached_records = self._get_records(name)
        cached_records.append(row_dict.copy())
        self._set_records_cache(name, cached_records)

    def _ensure_required_headers(self) -> None:
        self._ensure_sheet_headers(SHEET_NAMES["companies"], list(_COMPANY_HEADERS))
        self._ensure_sheet_headers(SHEET_NAMES["employees"], list(_EMPLOYEE_REQUIRED_HEADERS))
        self._ensure_sheet_headers(SHEET_NAMES["expense_cases"], list(_TRIP_REQUIRED_HEADERS))
        self._ensure_expenses_headers()
        self._ensure_sheet_headers(
            SHEET_NAMES["conversations"], list(_CONVERSATION_REQUIRED_HEADERS)
        )
        self._ensure_sheet_headers(
            SHEET_NAMES["expense_case_documents"], list(_TRIP_DOCUMENT_HEADERS)
        )
        self._ensure_sheet_headers(
            SHEET_NAMES["backoffice_users"], list(_BACKOFFICE_USER_HEADERS)
        )

    def _ensure_expenses_headers(self) -> None:
        ws = self._worksheet(SHEET_NAMES["expenses"])
        if ws is None:
            return
        headers = self._get_headers(SHEET_NAMES["expenses"])
        if not headers:
            return
        missing = [header for header in _EXPENSE_REQUIRED_HEADERS if header not in headers]
        if not missing:
            return
        updated_headers = headers + missing
        self._with_retry(lambda: ws.update("A1", [updated_headers]))
        self._set_headers_cache(SHEET_NAMES["expenses"], updated_headers)

    def _ensure_sheet_headers(self, worksheet_name: str, required_headers: list[str]) -> None:
        ws = self._worksheet(worksheet_name)
        if ws is None:
            return
        headers = self._get_headers(worksheet_name)
        if not headers:
            self._with_retry(lambda: ws.update("A1", [required_headers]))
            self._set_headers_cache(worksheet_name, required_headers)
            return
        missing = [header for header in required_headers if header not in headers]
        if not missing:
            return
        updated_headers = headers + missing
        self._with_retry(lambda: ws.update("A1", [updated_headers]))
        self._set_headers_cache(worksheet_name, updated_headers)

    def _is_worksheet_not_found(self, exc: Exception) -> bool:
        class_name = exc.__class__.__name__
        if class_name == "WorksheetNotFound":
            return True
        return "WorksheetNotFound" in str(exc)

    def _upsert_by_key(
        self, name: str, key_field: str, key_value: Any, payload: dict[str, Any]
    ) -> None:
        ws = self._worksheet(name)
        if ws is None:
            rows = self._memory_store.setdefault(name, [])
            for idx, row in enumerate(rows):
                if self._keys_match(key_field, row.get(key_field), key_value):
                    updated = row.copy()
                    updated.update(payload)
                    rows[idx] = updated
                    return
            rows.append(payload.copy())
            return

        headers = self._get_headers(name)
        records = self._get_records(name)
        matching_rows: list[int] = []
        for index, record in enumerate(records, start=2):
            if self._keys_match(key_field, record.get(key_field, ""), key_value):
                matching_rows.append(index)
        row_number = matching_rows[-1] if matching_rows else None

        row_values = [_to_sheet_cell(payload.get(header, "")) for header in headers]
        if row_number is None:
            self._with_retry(lambda: ws.append_row(row_values, value_input_option="USER_ENTERED"))
            records.append(payload.copy())
        else:
            start_col = "A"
            end_col = _column_label(len(headers))
            self._with_retry(
                lambda: ws.update(f"{start_col}{row_number}:{end_col}{row_number}", [row_values])
            )
            records[row_number - 2] = payload.copy()
        self._set_records_cache(name, records)

    def _delete_by_key(self, name: str, key_field: str, key_value: Any) -> bool:
        ws = self._worksheet(name)
        if ws is None:
            rows = self._memory_store.setdefault(name, [])
            for index, row in enumerate(rows):
                if self._keys_match(key_field, row.get(key_field), key_value):
                    rows.pop(index)
                    return True
            return False

        records = self._get_records(name)
        row_number = None
        for index, record in enumerate(records, start=2):
            if self._keys_match(key_field, record.get(key_field, ""), key_value):
                row_number = index
                break

        if row_number is None:
            return False

        self._with_retry(lambda: ws.delete_rows(row_number))
        del records[row_number - 2]
        self._set_records_cache(name, records)
        return True

    def _delete_many_by_predicate(self, name: str, predicate) -> int:
        ws = self._worksheet(name)
        if ws is None:
            rows = self._memory_store.setdefault(name, [])
            remaining_rows: list[dict[str, Any]] = []
            deleted_count = 0
            for row in rows:
                if predicate(row):
                    deleted_count += 1
                    continue
                remaining_rows.append(row)
            self._memory_store[name] = remaining_rows
            return deleted_count

        records = self._get_records(name)
        rows_to_delete = [
            index
            for index, record in enumerate(records, start=2)
            if predicate(record)
        ]
        if not rows_to_delete:
            return 0

        for row_number in reversed(rows_to_delete):
            self._with_retry(lambda row_number=row_number: ws.delete_rows(row_number))
            del records[row_number - 2]
        self._set_records_cache(name, records)
        return len(rows_to_delete)

    def _with_retry(self, operation, retries: int = 3, base_delay: float = 0.5):
        last_exc: Exception | None = None
        operation_name = getattr(operation, "__name__", None) or getattr(
            getattr(operation, "__class__", None),
            "__name__",
            "unknown",
        )
        for attempt in range(retries + 1):
            try:
                return operation()
            except Exception as exc:  # pragma: no cover - runtime dependency/errors
                last_exc = exc
                if self._is_worksheet_not_found(exc):
                    logger.info(
                        "Google Sheets worksheet lookup missed operation=%s attempt=%d retries=%d",
                        operation_name,
                        attempt + 1,
                        retries + 1,
                    )
                    raise
                if not self._is_retryable_sheets_error(exc):
                    logger.exception(
                        "Google Sheets operation failed operation=%s attempt=%d retries=%d",
                        operation_name,
                        attempt + 1,
                        retries + 1,
                    )
                    raise
                if attempt >= retries:
                    logger.warning(
                        "Google Sheets retries exhausted operation=%s attempt=%d retries=%d error=%s",
                        operation_name,
                        attempt + 1,
                        retries + 1,
                        exc,
                    )
                    raise
                logger.warning(
                    "Google Sheets retry operation=%s attempt=%d retries=%d error=%s",
                    operation_name,
                    attempt + 1,
                    retries + 1,
                    exc,
                )
                time.sleep(base_delay * (2**attempt))
        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected retry state")

    def _is_retryable_sheets_error(self, exc: Exception) -> bool:
        retryable_status_codes = {429, 500, 502, 503, 504}
        status_code = getattr(exc, "code", None)
        try:
            if int(status_code) in retryable_status_codes:
                return True
        except Exception:
            pass
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                if int(getattr(response, "status_code", 0)) in retryable_status_codes:
                    return True
            except Exception:
                pass
            text = str(getattr(response, "text", "") or "")
            if (
                "Quota exceeded" in text
                or "429" in text
                or "500" in text
                or "502" in text
                or "503" in text
                or "504" in text
            ):
                return True
        message = str(exc)
        retryable_fragments = (
            "Quota exceeded",
            "[429]",
            "[500]",
            "[502]",
            "[503]",
            "[504]",
            "Connection aborted",
            "Operation timed out",
            "Read timed out",
            "timed out",
            "TimeoutError",
            "Connection reset",
            "Temporary failure",
            "Remote end closed connection",
            "service is currently unavailable",
            "Service Unavailable",
            "backendError",
        )
        return any(fragment in message for fragment in retryable_fragments)

    def _is_rate_limit_error(self, exc: Exception) -> bool:
        status_code = getattr(exc, "code", None)
        try:
            if int(status_code) == 429:
                return True
        except Exception:
            pass
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                if int(getattr(response, "status_code", 0)) == 429:
                    return True
            except Exception:
                pass
            text = str(getattr(response, "text", "") or "")
            if "Quota exceeded" in text or "429" in text:
                return True
        message = str(exc)
        return "Quota exceeded" in message or "[429]" in message

    def _is_duplicate_header_error(self, exc: Exception) -> bool:
        return "header row in the worksheet contains duplicates" in str(exc).lower()

    def _keys_match(self, key_field: str, left_value: Any, right_value: Any) -> bool:
        if key_field == "phone":
            return normalize_whatsapp_phone(left_value) == normalize_whatsapp_phone(
                right_value
            )
        return str(left_value).strip() == str(right_value).strip()

    def get_employee_by_phone(self, phone: str) -> dict[str, Any] | None:
        target_phone = normalize_whatsapp_phone(phone)
        for row in self._get_records(SHEET_NAMES["employees"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            if row_phone != target_phone:
                continue
            if row.get("active", "") in ("", None):
                employee = self._normalize_employee_row(row)
                employee["phone"] = row_phone
                employee["active"] = True
                return employee
            if truthy(row.get("active")):
                employee = self._normalize_employee_row(row)
                employee["phone"] = row_phone
                employee["active"] = True
                return employee
        return None

    def get_employee_any_by_phone(self, phone: str) -> dict[str, Any] | None:
        target_phone = normalize_whatsapp_phone(phone)
        for row in self._get_records(SHEET_NAMES["employees"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            if row_phone != target_phone:
                continue
            employee = self._normalize_employee_row(row)
            employee["phone"] = row_phone
            employee["active"] = truthy(employee.get("active", True))
            return employee
        return None

    def get_active_expense_case_by_phone(self, phone: str) -> dict[str, Any] | None:
        today = parse_iso_date(utc_now_iso()[:10])
        target_phone = normalize_whatsapp_phone(phone)
        candidates: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["expense_cases"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            if row_phone != target_phone:
                continue
            if str(row.get("status", "")).strip().lower() != "active":
                continue
            start_date = parse_iso_date(str(row.get("start_date", row.get("opened_at", ""))))
            end_date = parse_iso_date(str(row.get("end_date", row.get("due_date", ""))))
            if today and start_date and end_date and start_date <= today <= end_date:
                return self._normalize_backoffice_case_row(row)
            candidates.append(self._normalize_backoffice_case_row(row))
        return candidates[0] if candidates else None

    def get_active_trip_by_phone(self, phone: str) -> dict[str, Any] | None:
        return self.get_active_expense_case_by_phone(phone)

    def create_expense(self, expense_data: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "Creating expense row phone=%s case_id=%s expense_id=%s merchant=%s total=%s currency=%s",
            normalize_whatsapp_phone(expense_data.get("phone", "")),
            str(expense_data.get("case_id", expense_data.get("trip_id", "")) or "").strip() or None,
            str(expense_data.get("expense_id", "") or "").strip() or None,
            str(expense_data.get("merchant", "") or "").strip() or None,
            expense_data.get("total"),
            str(expense_data.get("currency", "") or "").strip() or None,
        )
        self._append_row(SHEET_NAMES["expenses"], expense_data)
        return expense_data

    def create_expense_case_document(self, document_data: dict[str, Any]) -> dict[str, Any]:
        self._append_row(SHEET_NAMES["expense_case_documents"], document_data)
        return document_data

    def create_trip_document(self, document_data: dict[str, Any]) -> dict[str, Any]:
        return self.create_expense_case_document(document_data)

    def update_expense_case_document(
        self, document_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        existing = self.get_expense_case_document_by_id(document_id)
        if existing is None:
            return None
        merged = existing.copy()
        merged.update(payload)
        merged["document_id"] = str(document_id or "").strip()
        self._upsert_by_key(
            SHEET_NAMES["expense_case_documents"],
            "document_id",
            merged["document_id"],
            merged,
        )
        return merged

    def update_trip_document(self, document_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.update_expense_case_document(document_id, payload)

    def get_expense_case_document_by_id(self, document_id: str) -> dict[str, Any] | None:
        target_document_id = str(document_id or "").strip()
        if not target_document_id:
            return None
        latest_match: dict[str, Any] | None = None
        latest_ts: datetime | None = None
        for row in self._get_records(SHEET_NAMES["expense_case_documents"]):
            row_document_id = str(row.get("document_id", "")).strip()
            if row_document_id == target_document_id:
                candidate = self._normalize_expense_case_document_row(row)
                candidate_ts = self._parse_updated_at(candidate.get("updated_at")) or self._parse_updated_at(
                    candidate.get("created_at")
                )
                if latest_match is None:
                    latest_match = candidate
                    latest_ts = candidate_ts
                    continue
                if candidate_ts and (latest_ts is None or candidate_ts >= latest_ts):
                    latest_match = candidate
                    latest_ts = candidate_ts
        return latest_match

    def get_trip_document_by_id(self, document_id: str) -> dict[str, Any] | None:
        return self.get_expense_case_document_by_id(document_id)

    def list_expense_case_documents_by_phone_case(self, phone: str, case_id: str) -> list[dict[str, Any]]:
        target_phone = normalize_whatsapp_phone(phone)
        target_case_id = str(case_id or "").strip()
        if not target_phone or not target_case_id:
            return []
        matches: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["expense_case_documents"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            normalized_row = self._normalize_expense_case_document_row(row)
            row_case_id = str(normalized_row.get("case_id", "")).strip()
            if row_phone != target_phone or row_case_id != target_case_id:
                continue
            matches.append(normalized_row)
        return matches

    def list_trip_documents_by_phone_trip(self, phone: str, trip_id: str) -> list[dict[str, Any]]:
        return self.list_expense_case_documents_by_phone_case(phone, trip_id)

    def get_latest_expense_case_document_by_phone_case(
        self, phone: str, case_id: str
    ) -> dict[str, Any] | None:
        records = self.list_expense_case_documents_by_phone_case(phone, case_id)
        latest: dict[str, Any] | None = None
        latest_ts: datetime | None = None
        for row in records:
            row_ts = self._parse_updated_at(row.get("updated_at")) or self._parse_updated_at(
                row.get("created_at")
            )
            if latest is None:
                latest = row
                latest_ts = row_ts
                continue
            if row_ts and (latest_ts is None or row_ts >= latest_ts):
                latest = row
                latest_ts = row_ts
        return latest

    def get_latest_trip_document_by_phone_trip(self, phone: str, trip_id: str) -> dict[str, Any] | None:
        return self.get_latest_expense_case_document_by_phone_case(phone, trip_id)

    def get_expense_case_by_id(self, case_id: str) -> dict[str, Any] | None:
        target_case_id = str(case_id or "").strip()
        if not target_case_id:
            return None
        for row in self._get_records(SHEET_NAMES["expense_cases"]):
            normalized_row = self._normalize_backoffice_case_row(row)
            row_case_id = str(normalized_row.get("case_id", "")).strip()
            if row_case_id == target_case_id:
                return normalized_row
        return None

    def get_trip_by_id(self, trip_id: str) -> dict[str, Any] | None:
        return self.get_expense_case_by_id(trip_id)

    def list_expenses_by_phone_case(self, phone: str, case_id: str) -> list[dict[str, Any]]:
        target_phone = normalize_whatsapp_phone(phone)
        target_case_id = str(case_id or "").strip()
        if not target_phone or not target_case_id:
            return []
        expenses: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["expenses"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            row_case_id = str(row.get("case_id", row.get("trip_id", ""))).strip()
            if row_phone != target_phone or row_case_id != target_case_id:
                continue
            expenses.append(self._normalize_expense_row(row))
        return expenses

    def list_expenses_by_phone_trip(self, phone: str, trip_id: str) -> list[dict[str, Any]]:
        return self.list_expenses_by_phone_case(phone, trip_id)

    def list_active_expense_cases(self) -> list[dict[str, Any]]:
        active_rows: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["expense_cases"]):
            if str(row.get("status", "")).strip().lower() == "active":
                active_rows.append(self._normalize_backoffice_case_row(row))
        return active_rows

    def list_active_trips(self) -> list[dict[str, Any]]:
        return self.list_active_expense_cases()

    def list_active_expense_cases_by_phone(self, phone: str) -> list[dict[str, Any]]:
        target_phone = normalize_whatsapp_phone(phone)
        matches: list[dict[str, Any]] = []
        if not target_phone:
            return matches
        for row in self.list_active_expense_cases():
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            if row_phone == target_phone:
                matches.append(row)
        return matches

    def list_active_trips_by_phone(self, phone: str) -> list[dict[str, Any]]:
        return self.list_active_expense_cases_by_phone(phone)

    def update_expense_case(self, case_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_expense_case_by_id(case_id)
        if existing is None:
            return None
        merged = existing.copy()
        merged.update(payload)
        merged["case_id"] = str(case_id or "").strip()
        merged["updated_at"] = str(payload.get("updated_at", "") or "").strip() or utc_now_iso()
        self._upsert_by_key(
            SHEET_NAMES["expense_cases"],
            "case_id" if "case_id" in self._get_headers(SHEET_NAMES["expense_cases"]) else "trip_id",
            merged["case_id"],
            self._denormalize_backoffice_case_row(merged),
        )
        return merged

    def update_trip(self, trip_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return self.update_expense_case(trip_id, payload)

    def get_conversation(self, phone: str) -> dict[str, Any] | None:
        target_phone = normalize_whatsapp_phone(phone)
        latest_match: dict[str, Any] | None = None
        latest_match_ts: datetime | None = None
        for row in self._get_records(SHEET_NAMES["conversations"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            if row_phone == target_phone:
                candidate = row.copy()
                candidate_ts = self._parse_updated_at(candidate.get("updated_at"))
                if latest_match is None:
                    latest_match = candidate
                    latest_match_ts = candidate_ts
                    continue
                if candidate_ts and (latest_match_ts is None or candidate_ts >= latest_match_ts):
                    latest_match = candidate
                    latest_match_ts = candidate_ts
        if latest_match is None:
            return None
        latest_match["context_json"] = json_loads(
            latest_match.get("context_json"), default={}
        )
        return latest_match

    def _parse_updated_at(self, value: Any) -> datetime | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def update_conversation(self, phone: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_conversation(phone) or {}
        context = payload.get("context_json")
        if isinstance(context, str):
            context_obj = json_loads(context, default={})
        else:
            context_obj = context if context is not None else existing.get("context_json", {})

        conversation = {
            "phone": phone,
            "state": payload.get("state", existing.get("state", "WAIT_RECEIPT")),
            "current_step": payload.get(
                "current_step", existing.get("current_step", "")
            ),
            "context_json": context_obj,
            "updated_at": payload.get("updated_at", utc_now_iso()),
        }
        to_sheet = conversation.copy()
        to_sheet["context_json"] = json_dumps(conversation["context_json"])
        logger.info(
            "Updating conversation phone=%s state=%s current_step=%s context_keys=%s",
            normalize_whatsapp_phone(phone),
            conversation["state"],
            conversation["current_step"] or None,
            sorted(conversation["context_json"].keys())
            if isinstance(conversation["context_json"], dict)
            else None,
        )
        self._upsert_by_key(SHEET_NAMES["conversations"], "phone", phone, to_sheet)
        return conversation

    def list_employees(self) -> list[dict[str, Any]]:
        employees: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["employees"]):
            employee = self._normalize_employee_row(row)
            employee["phone"] = normalize_whatsapp_phone(employee.get("phone", ""))
            employee["active"] = truthy(employee.get("active", True))
            employees.append(employee)
        employees.sort(key=lambda item: str(item.get("name", "") or "").lower())
        return employees

    def list_companies(self) -> list[dict[str, Any]]:
        companies: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["companies"]):
            company = dict(row)
            company["company_id"] = str(company.get("company_id", "") or "").strip()
            company["name"] = str(company.get("name", "") or "").strip()
            company["active"] = truthy(company.get("active", True))
            companies.append(company)
        companies.sort(
            key=lambda item: (
                str(item.get("name", "") or "").lower(),
                str(item.get("company_id", "") or "").lower(),
            )
        )
        return companies

    def create_employee(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        normalized_phone = normalize_whatsapp_phone(payload.get("phone", ""))
        existing = self.get_employee_any_by_phone(normalized_phone)
        if existing is not None:
            merged = dict(existing)
            for key in (
                "first_name",
                "last_name",
                "name",
                "rut",
                "email",
                "company_id",
                "bank_name",
                "account_type",
                "account_number",
                "account_holder",
                "account_holder_rut",
                "active",
                "last_activity_at",
            ):
                if key in payload:
                    merged[key] = payload.get(key)
            return self.update_employee(normalized_phone, merged) or merged
        first_name = str(payload.get("first_name", "") or "").strip()
        last_name = str(payload.get("last_name", "") or "").strip()
        full_name = self._compose_employee_name(
            first_name=first_name,
            last_name=last_name,
            fallback=payload.get("name", ""),
        )
        employee = {
            "phone": normalized_phone,
            "first_name": first_name,
            "last_name": last_name,
            "name": full_name,
            "rut": str(payload.get("rut", "") or "").strip(),
            "email": str(payload.get("email", "") or "").strip(),
            "company_id": str(payload.get("company_id", "") or "").strip(),
            "bank_name": str(payload.get("bank_name", "") or "").strip(),
            "account_type": str(payload.get("account_type", "") or "").strip(),
            "account_number": str(payload.get("account_number", "") or "").strip(),
            "account_holder": str(payload.get("account_holder", "") or "").strip(),
            "account_holder_rut": str(payload.get("account_holder_rut", "") or "").strip(),
            "active": bool(payload.get("active", True)),
            "last_activity_at": str(payload.get("last_activity_at", "") or "").strip(),
            "created_at": str(payload.get("created_at", "") or "").strip() or now,
            "updated_at": str(payload.get("updated_at", "") or "").strip() or now,
        }
        to_sheet = dict(employee)
        to_sheet["active"] = "TRUE" if employee["active"] else "FALSE"
        self._append_row(SHEET_NAMES["employees"], to_sheet)
        return employee

    def update_employee(self, phone: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_employee_any_by_phone(phone)
        if existing is None:
            return None
        merged = dict(existing)
        merged.update(payload)
        merged["first_name"] = str(merged.get("first_name", "") or "").strip()
        merged["last_name"] = str(merged.get("last_name", "") or "").strip()
        merged["name"] = self._compose_employee_name(
            first_name=merged.get("first_name", ""),
            last_name=merged.get("last_name", ""),
            fallback=merged.get("name", ""),
        )
        merged["phone"] = normalize_whatsapp_phone(merged.get("phone", phone))
        merged["active"] = bool(merged.get("active", True))
        merged["updated_at"] = str(payload.get("updated_at", "") or "").strip() or utc_now_iso()
        to_sheet = dict(merged)
        to_sheet["active"] = "TRUE" if merged["active"] else "FALSE"
        self._upsert_by_key(SHEET_NAMES["employees"], "phone", normalize_whatsapp_phone(phone), to_sheet)
        return merged

    def delete_employee(self, phone: str) -> dict[str, Any] | None:
        existing = self.get_employee_any_by_phone(phone)
        if existing is None:
            return None
        deleted = self._delete_by_key(
            SHEET_NAMES["employees"],
            "phone",
            normalize_whatsapp_phone(phone),
        )
        if not deleted:
            return None
        return existing

    def delete_expense_case(self, case_id: str) -> dict[str, Any] | None:
        existing = self.get_expense_case_by_id(case_id)
        if existing is None:
            return None
        deleted = self._delete_by_key(SHEET_NAMES["expense_cases"], "case_id", str(case_id or "").strip())
        if not deleted:
            return None
        return existing

    def delete_expenses_for_employee_or_cases(self, phone: str, case_ids: set[str]) -> int:
        normalized_phone = normalize_whatsapp_phone(phone)

        def _matches(row: dict[str, Any]) -> bool:
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            row_case_id = str(row.get("case_id", row.get("trip_id", "")) or "").strip()
            return row_phone == normalized_phone or row_case_id in case_ids

        return self._delete_many_by_predicate(SHEET_NAMES["expenses"], _matches)

    def list_expense_cases(self) -> list[dict[str, Any]]:
        cases = [self._normalize_backoffice_case_row(row) for row in self._get_records(SHEET_NAMES["expense_cases"])]
        cases.sort(key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""), reverse=True)
        return cases

    def create_expense_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        case_id = str(payload.get("case_id", "") or "").strip() or make_id("case")
        case_row = self._normalize_backoffice_case_row(
            {
                "case_id": case_id,
                "context_label": str(payload.get("context_label", "") or "").strip(),
                "company_id": str(payload.get("company_id", "") or "").strip(),
                "employee_phone": normalize_whatsapp_phone(
                    payload.get("employee_phone", payload.get("phone", ""))
                ),
                "phone": normalize_whatsapp_phone(
                    payload.get("employee_phone", payload.get("phone", ""))
                ),
                "closure_method": str(payload.get("closure_method", "docusign") or "docusign").strip().lower(),
                "status": str(payload.get("status", "active") or "active").strip(),
                "created_at": str(payload.get("created_at", "") or "").strip() or now,
                "updated_at": str(payload.get("updated_at", "") or "").strip() or now,
                "notes": str(payload.get("notes", "") or "").strip(),
                "fondos_entregados": payload.get("fondos_entregados", ""),
                "rendicion_status": str(payload.get("rendicion_status", "open") or "open").strip(),
                "user_confirmed_at": "",
                "user_confirmation_status": "",
                "settlement_direction": str(payload.get("settlement_direction", "") or "").strip(),
                "settlement_status": str(payload.get("settlement_status", "") or "").strip(),
                "settlement_amount_clp": payload.get("settlement_amount_clp", ""),
                "settlement_net_clp": payload.get("settlement_net_clp", ""),
                "settlement_calculated_at": str(payload.get("settlement_calculated_at", "") or "").strip(),
                "settlement_resolved_at": str(payload.get("settlement_resolved_at", "") or "").strip(),
            }
        )
        self._append_row(
            SHEET_NAMES["expense_cases"],
            self._denormalize_backoffice_case_row(case_row),
        )
        return case_row

    def list_expenses(self) -> list[dict[str, Any]]:
        expenses = [self._normalize_expense_row(row) for row in self._get_records(SHEET_NAMES["expenses"])]
        expenses.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        return expenses

    def get_expense_by_id(self, expense_id: str) -> dict[str, Any] | None:
        target = str(expense_id or "").strip()
        if not target:
            return None
        for row in self._get_records(SHEET_NAMES["expenses"]):
            if str(row.get("expense_id", "")).strip() == target:
                return self._normalize_expense_row(row)
        return None

    def update_expense(self, expense_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_expense_by_id(expense_id)
        if existing is None:
            return None
        merged = dict(existing)
        merged.update(payload)
        merged["expense_id"] = str(expense_id or "").strip()
        merged["phone"] = normalize_whatsapp_phone(merged.get("phone", ""))
        merged["case_id"] = str(merged.get("case_id", merged.get("trip_id", "")) or "").strip()
        merged["updated_at"] = str(payload.get("updated_at", "") or "").strip() or utc_now_iso()
        self._upsert_by_key(SHEET_NAMES["expenses"], "expense_id", merged["expense_id"], merged)
        return merged

    def list_conversations(self) -> list[dict[str, Any]]:
        conversations: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["conversations"]):
            item = dict(row)
            item["phone"] = normalize_whatsapp_phone(item.get("phone", ""))
            item["case_id"] = str(item.get("case_id", "") or "").strip()
            item["context_json"] = json_loads(item.get("context_json"), default={})
            conversations.append(item)
        conversations.sort(key=lambda item: str(item.get("updated_at", "")), reverse=True)
        return conversations

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        target = str(email or "").strip().lower()
        if not target:
            return None
        for row in self._get_records(SHEET_NAMES["backoffice_users"]):
            row_email = str(row.get("email", "") or "").strip().lower()
            if row_email == target:
                user = dict(row)
                user["active"] = truthy(user.get("active", True))
                return user
        return None

    def list_users(self) -> list[dict[str, Any]]:
        users: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["backoffice_users"]):
            item = dict(row)
            item["active"] = truthy(item.get("active", True))
            users.append(item)
        users.sort(key=lambda item: str(item.get("name", "") or "").lower())
        return users

    def upsert_user(self, user_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        existing = next((row for row in self.list_users() if str(row.get("id", "")) == str(user_id or "").strip()), None)
        merged = dict(existing or {})
        merged.update(payload)
        merged["id"] = str(user_id or merged.get("id", "")).strip()
        merged["email"] = str(merged.get("email", "") or "").strip().lower()
        merged["active"] = bool(merged.get("active", True))
        merged["created_at"] = str(merged.get("created_at", "") or "").strip() or now
        merged["updated_at"] = str(payload.get("updated_at", "") or "").strip() or now
        to_sheet = dict(merged)
        to_sheet["active"] = "TRUE" if merged["active"] else "FALSE"
        self._upsert_by_key(SHEET_NAMES["backoffice_users"], "id", merged["id"], to_sheet)
        return merged

    def _normalize_expense_case_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        normalized["case_id"] = str(row.get("case_id", row.get("trip_id", "")) or "").strip()
        normalized["context_label"] = row.get("context_label", row.get("destination", ""))
        normalized["opened_at"] = row.get("opened_at", row.get("start_date", ""))
        normalized["due_date"] = row.get("due_date", row.get("end_date", ""))
        normalized["policy_limit"] = row.get("policy_limit", row.get("budget", ""))
        return normalized

    def _denormalize_expense_case_row(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = dict(row)
        payload.setdefault("destination", payload.get("context_label", ""))
        payload.setdefault("start_date", payload.get("opened_at", ""))
        payload.setdefault("end_date", payload.get("due_date", ""))
        payload.setdefault("budget", payload.get("policy_limit", ""))
        return payload

    def _normalize_expense_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        normalized["case_id"] = str(row.get("case_id", row.get("trip_id", "")) or "").strip()
        normalized["phone"] = normalize_whatsapp_phone(normalized.get("phone", ""))
        return normalized

    def _normalize_expense_case_document_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        normalized["case_id"] = str(row.get("case_id", row.get("trip_id", "")) or "").strip()
        return normalized

    def _normalize_backoffice_case_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_expense_case_row(row)
        normalized["employee_phone"] = normalize_whatsapp_phone(
            normalized.get("employee_phone", normalized.get("phone", ""))
        )
        normalized["phone"] = normalized["employee_phone"]
        normalized["company_id"] = str(normalized.get("company_id", "") or "").strip()
        normalized["closure_method"] = str(normalized.get("closure_method", "") or "").strip().lower() or "docusign"
        normalized["created_at"] = normalized.get("created_at", normalized.get("opened_at", ""))
        normalized["updated_at"] = normalized.get("updated_at", normalized.get("created_at", ""))
        normalized["notes"] = normalized.get("notes", "")
        normalized["fondos_entregados"] = normalized.get("fondos_entregados", "")
        normalized["rendicion_status"] = str(normalized.get("rendicion_status", "") or "").strip() or "open"
        normalized["user_confirmed_at"] = normalized.get("user_confirmed_at", "")
        normalized["user_confirmation_status"] = normalized.get("user_confirmation_status", "")
        normalized["settlement_direction"] = str(normalized.get("settlement_direction", "") or "").strip()
        normalized["settlement_status"] = str(normalized.get("settlement_status", "") or "").strip()
        normalized["settlement_amount_clp"] = normalized.get("settlement_amount_clp", "")
        normalized["settlement_net_clp"] = normalized.get("settlement_net_clp", "")
        normalized["settlement_calculated_at"] = normalized.get("settlement_calculated_at", "")
        normalized["settlement_resolved_at"] = normalized.get("settlement_resolved_at", "")
        return normalized

    def _denormalize_backoffice_case_row(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = self._denormalize_expense_case_row(row)
        payload["phone"] = normalize_whatsapp_phone(
            row.get("employee_phone", row.get("phone", ""))
        )
        payload["employee_phone"] = payload["phone"]
        payload["company_id"] = str(row.get("company_id", "") or "").strip()
        payload["closure_method"] = str(row.get("closure_method", "") or "").strip().lower() or "docusign"
        payload["created_at"] = row.get("created_at", "")
        payload["updated_at"] = row.get("updated_at", "")
        payload["notes"] = row.get("notes", "")
        payload["fondos_entregados"] = row.get("fondos_entregados", "")
        payload["rendicion_status"] = row.get("rendicion_status", "")
        payload["user_confirmed_at"] = row.get("user_confirmed_at", "")
        payload["user_confirmation_status"] = row.get("user_confirmation_status", "")
        payload["settlement_direction"] = row.get("settlement_direction", "")
        payload["settlement_status"] = row.get("settlement_status", "")
        payload["settlement_amount_clp"] = row.get("settlement_amount_clp", "")
        payload["settlement_net_clp"] = row.get("settlement_net_clp", "")
        payload["settlement_calculated_at"] = row.get("settlement_calculated_at", "")
        payload["settlement_resolved_at"] = row.get("settlement_resolved_at", "")
        if not payload.get("opened_at"):
            payload["opened_at"] = payload.get("created_at", "")
        return payload

    def _normalize_employee_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        first_name = str(normalized.get("first_name", "") or "").strip()
        last_name = str(normalized.get("last_name", "") or "").strip()
        legacy_name = str(normalized.get("name", "") or "").strip()
        if not first_name and legacy_name:
            split_name = legacy_name.split(None, 1)
            first_name = split_name[0]
            last_name = split_name[1] if len(split_name) > 1 else ""
        normalized["first_name"] = first_name
        normalized["last_name"] = last_name
        normalized["name"] = self._compose_employee_name(
            first_name=first_name,
            last_name=last_name,
            fallback=legacy_name,
        )
        return normalized

    def _compose_employee_name(self, *, first_name: Any, last_name: Any, fallback: Any = "") -> str:
        parts = [str(first_name or "").strip(), str(last_name or "").strip()]
        full_name = " ".join(part for part in parts if part)
        if full_name:
            return full_name
        return str(fallback or "").strip()
