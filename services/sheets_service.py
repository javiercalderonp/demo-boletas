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
    normalize_whatsapp_phone,
    parse_iso_date,
    truthy,
    utc_now_iso,
)


logger = logging.getLogger(__name__)


SHEET_NAMES = {
    "employees": "Employees",
    "trips": "Trips",
    "expenses": "Expenses",
    "conversations": "Conversations",
    "trip_documents": "TripDocuments",
}

_EMPLOYEE_REQUIRED_HEADERS = ["email"]
_EXPENSE_REQUIRED_HEADERS = {"receipt_storage_provider", "receipt_object_key"}
_TRIP_REQUIRED_HEADERS = [
    "closure_status",
    "closure_prompted_at",
    "closure_deadline_at",
    "closure_response",
    "closure_responded_at",
    "closed_at",
    "closure_reason",
]
_TRIP_DOCUMENT_HEADERS = [
    "document_id",
    "phone",
    "trip_id",
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


@dataclass
class SheetsService:
    settings: Settings
    record_cache_ttl_seconds: float = 15.0

    def __post_init__(self) -> None:
        self._client = None
        self._spreadsheet = None
        self._worksheet_cache: dict[str, Any] = {}
        self._records_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._headers_cache: dict[str, tuple[float, list[str]]] = {}
        self._memory_store: dict[str, list[dict[str, Any]]] = {
            "Employees": [],
            "Trips": [],
            "Expenses": [],
            "Conversations": [],
            "TripDocuments": [],
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
            from google.oauth2.service_account import Credentials
        except ImportError as exc:  # pragma: no cover - dependency setup
            raise RuntimeError(
                "Faltan dependencias para Google Sheets. Instala gspread y google-auth."
            ) from exc

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
        ]
        creds = Credentials.from_service_account_file(
            self.settings.google_application_credentials,
            scopes=scopes,
        )
        self._client = gspread.authorize(creds)
        self._spreadsheet = self._client.open_by_key(
            self.settings.google_sheets_spreadsheet_id
        )
        logger.info(
            "Google Sheets connected spreadsheet_id=%s credentials_path=%s",
            self.settings.google_sheets_spreadsheet_id,
            self.settings.google_application_credentials,
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
            if name != SHEET_NAMES["trip_documents"]:
                raise
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
        if cached and now - cached[0] <= self.record_cache_ttl_seconds:
            return [row.copy() for row in cached[1]]
        records = self._with_retry(ws.get_all_records)
        self._records_cache[name] = (now, [dict(row) for row in records])
        return [dict(row) for row in records]

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
        headers = self._with_retry(lambda: ws.row_values(1))
        self._headers_cache[name] = (now, list(headers))
        return list(headers)

    def _set_records_cache(self, name: str, records: list[dict[str, Any]]) -> None:
        self._records_cache[name] = (
            time.monotonic(),
            [dict(row) for row in records],
        )

    def _set_headers_cache(self, name: str, headers: list[str]) -> None:
        self._headers_cache[name] = (time.monotonic(), list(headers))

    def _append_row(self, name: str, row_dict: dict[str, Any]) -> None:
        ws = self._worksheet(name)
        if ws is None:
            self._memory_store.setdefault(name, []).append(row_dict.copy())
            return
        headers = self._get_headers(name)
        row = [row_dict.get(header, "") for header in headers]
        self._with_retry(lambda: ws.append_row(row, value_input_option="USER_ENTERED"))
        cached_records = self._get_records(name)
        cached_records.append(row_dict.copy())
        self._set_records_cache(name, cached_records)

    def _ensure_required_headers(self) -> None:
        self._ensure_sheet_headers(SHEET_NAMES["employees"], list(_EMPLOYEE_REQUIRED_HEADERS))
        self._ensure_sheet_headers(SHEET_NAMES["trips"], list(_TRIP_REQUIRED_HEADERS))
        self._ensure_expenses_headers()
        self._ensure_sheet_headers(
            SHEET_NAMES["trip_documents"], list(_TRIP_DOCUMENT_HEADERS)
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

        row_values = [payload.get(header, "") for header in headers]
        if row_number is None:
            self._with_retry(lambda: ws.append_row(row_values, value_input_option="USER_ENTERED"))
            records.append(payload.copy())
        else:
            start_col = "A"
            end_col = chr(ord("A") + len(headers) - 1)
            self._with_retry(
                lambda: ws.update(f"{start_col}{row_number}:{end_col}{row_number}", [row_values])
            )
            records[row_number - 2] = payload.copy()
        self._set_records_cache(name, records)

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
                if not self._is_retryable_sheets_error(exc) or attempt >= retries:
                    logger.exception(
                        "Google Sheets operation failed operation=%s attempt=%d retries=%d",
                        operation_name,
                        attempt + 1,
                        retries + 1,
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
        status_code = getattr(exc, "code", None)
        if status_code == 429:
            return True
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
        retryable_fragments = (
            "Quota exceeded",
            "[429]",
            "Connection aborted",
            "Operation timed out",
            "Read timed out",
            "timed out",
            "TimeoutError",
            "Connection reset",
            "Temporary failure",
            "Remote end closed connection",
        )
        return any(fragment in message for fragment in retryable_fragments)

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
                return row
            if truthy(row.get("active")):
                return row
        return None

    def get_active_trip_by_phone(self, phone: str) -> dict[str, Any] | None:
        today = parse_iso_date(utc_now_iso()[:10])
        target_phone = normalize_whatsapp_phone(phone)
        candidates: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["trips"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            if row_phone != target_phone:
                continue
            if str(row.get("status", "")).strip().lower() != "active":
                continue
            start_date = parse_iso_date(str(row.get("start_date", "")))
            end_date = parse_iso_date(str(row.get("end_date", "")))
            if today and start_date and end_date and start_date <= today <= end_date:
                return row
            candidates.append(row)
        return candidates[0] if candidates else None

    def create_expense(self, expense_data: dict[str, Any]) -> dict[str, Any]:
        logger.info(
            "Creating expense row phone=%s trip_id=%s expense_id=%s merchant=%s total=%s currency=%s",
            normalize_whatsapp_phone(expense_data.get("phone", "")),
            str(expense_data.get("trip_id", "") or "").strip() or None,
            str(expense_data.get("expense_id", "") or "").strip() or None,
            str(expense_data.get("merchant", "") or "").strip() or None,
            expense_data.get("total"),
            str(expense_data.get("currency", "") or "").strip() or None,
        )
        self._append_row(SHEET_NAMES["expenses"], expense_data)
        return expense_data

    def create_trip_document(self, document_data: dict[str, Any]) -> dict[str, Any]:
        self._append_row(SHEET_NAMES["trip_documents"], document_data)
        return document_data

    def update_trip_document(
        self, document_id: str, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        existing = self.get_trip_document_by_id(document_id)
        if existing is None:
            return None
        merged = existing.copy()
        merged.update(payload)
        merged["document_id"] = str(document_id or "").strip()
        self._upsert_by_key(
            SHEET_NAMES["trip_documents"],
            "document_id",
            merged["document_id"],
            merged,
        )
        return merged

    def get_trip_document_by_id(self, document_id: str) -> dict[str, Any] | None:
        target_document_id = str(document_id or "").strip()
        if not target_document_id:
            return None
        latest_match: dict[str, Any] | None = None
        latest_ts: datetime | None = None
        for row in self._get_records(SHEET_NAMES["trip_documents"]):
            row_document_id = str(row.get("document_id", "")).strip()
            if row_document_id == target_document_id:
                candidate = row.copy()
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

    def list_trip_documents_by_phone_trip(self, phone: str, trip_id: str) -> list[dict[str, Any]]:
        target_phone = normalize_whatsapp_phone(phone)
        target_trip_id = str(trip_id or "").strip()
        if not target_phone or not target_trip_id:
            return []
        matches: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["trip_documents"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            row_trip_id = str(row.get("trip_id", "")).strip()
            if row_phone != target_phone or row_trip_id != target_trip_id:
                continue
            matches.append(row)
        return matches

    def get_latest_trip_document_by_phone_trip(
        self, phone: str, trip_id: str
    ) -> dict[str, Any] | None:
        records = self.list_trip_documents_by_phone_trip(phone, trip_id)
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

    def get_trip_by_id(self, trip_id: str) -> dict[str, Any] | None:
        target_trip_id = str(trip_id or "").strip()
        if not target_trip_id:
            return None
        for row in self._get_records(SHEET_NAMES["trips"]):
            row_trip_id = str(row.get("trip_id", "")).strip()
            if row_trip_id == target_trip_id:
                return row
        return None

    def list_expenses_by_phone_trip(self, phone: str, trip_id: str) -> list[dict[str, Any]]:
        target_phone = normalize_whatsapp_phone(phone)
        target_trip_id = str(trip_id or "").strip()
        if not target_phone or not target_trip_id:
            return []
        expenses: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["expenses"]):
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            row_trip_id = str(row.get("trip_id", "")).strip()
            if row_phone != target_phone or row_trip_id != target_trip_id:
                continue
            expenses.append(row)
        return expenses

    def list_active_trips(self) -> list[dict[str, Any]]:
        active_rows: list[dict[str, Any]] = []
        for row in self._get_records(SHEET_NAMES["trips"]):
            if str(row.get("status", "")).strip().lower() == "active":
                active_rows.append(row)
        return active_rows

    def list_active_trips_by_phone(self, phone: str) -> list[dict[str, Any]]:
        target_phone = normalize_whatsapp_phone(phone)
        matches: list[dict[str, Any]] = []
        if not target_phone:
            return matches
        for row in self.list_active_trips():
            row_phone = normalize_whatsapp_phone(row.get("phone", ""))
            if row_phone == target_phone:
                matches.append(row)
        return matches

    def update_trip(self, trip_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.get_trip_by_id(trip_id)
        if existing is None:
            return None
        merged = existing.copy()
        merged.update(payload)
        merged["trip_id"] = str(trip_id or "").strip()
        self._upsert_by_key(SHEET_NAMES["trips"], "trip_id", merged["trip_id"], merged)
        return merged

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
