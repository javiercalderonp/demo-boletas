import json
import unittest
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock, patch

from app.config import Settings
from app.main import _append_message_log
from services.backoffice_service import BackofficeService
from services.sheets_service import SHEET_NAMES, SheetsService, _column_label


class SheetsServiceFallbackTests(unittest.TestCase):
    def test_conversation_state_keeps_bounded_window_and_archives_full_history(self):
        service = SheetsService(
            Settings(google_application_credentials="", google_sheets_spreadsheet_id="")
        )
        phone = "+56911111111"
        messages = [
            {
                "id": f"msg-{index}",
                "speaker": "person",
                "type": "text",
                "text": f"Mensaje {index}",
                "created_at": f"2026-08-25T12:{index:02d}:00Z",
            }
            for index in range(60)
        ]

        service.update_conversation(phone, {"context_json": {"message_log": messages}})

        conversation = service.get_conversation(phone)
        self.assertEqual(len(conversation["context_json"]["message_log"]), 50)
        self.assertEqual(conversation["context_json"]["message_log"][0]["id"], "msg-10")
        self.assertEqual(len(service.list_conversation_messages(phone)), 60)

    def test_conversation_update_continues_when_history_archive_fails(self):
        service = SheetsService(
            Settings(google_application_credentials="", google_sheets_spreadsheet_id="")
        )
        phone = "+56911111111"
        messages = [{"id": f"msg-{index}", "text": "x" * 1200} for index in range(60)]

        with patch.object(service, "_archive_conversation_messages", side_effect=RuntimeError("down")):
            result = service.update_conversation(
                phone,
                {"state": "CONFIRM_SUMMARY", "context_json": {"message_log": messages}},
            )

        self.assertEqual(result["state"], "CONFIRM_SUMMARY")
        self.assertLessEqual(len(result["context_json"]["message_log"]), 50)
        self.assertLessEqual(len(str(result["context_json"])), 50_000)
        self.assertIs(result["context_json"]["history_archive_incomplete"], True)
        self.assertEqual(result["context_json"]["history_archive_message_count"], 60)
        self.assertTrue(result["context_json"]["history_archive_backlog"])

        recovered = service.update_conversation(
            phone,
            {"context_json": {"message_log": result["context_json"]["message_log"]}},
        )
        self.assertNotIn("history_archive_incomplete", recovered["context_json"])
        self.assertNotIn("history_archive_backlog", recovered["context_json"])

    def test_conversation_updates_merge_stale_message_histories(self):
        service = SheetsService(
            Settings(google_application_credentials="", google_sheets_spreadsheet_id="")
        )
        phone = "+56911111111"
        service.update_conversation(
            phone,
            {"context_json": {"message_log": [{"id": "person-1", "text": "Foto"}]}},
        )
        service.update_conversation(
            phone,
            {"context_json": {"message_log": [{"id": "operator-1", "text": "Hola"}]}},
        )

        result = service.update_conversation(
            phone,
            {"context_json": {"message_log": [{"id": "person-1", "text": "Foto"}, {"id": "bot-1", "text": "Procesando"}]}},
        )

        self.assertEqual(
            [message["id"] for message in result["context_json"]["message_log"]],
            ["person-1", "operator-1", "bot-1"],
        )

    def test_message_identity_prefers_provider_ids_and_preserves_legacy_duplicates(self):
        merged = SheetsService._merge_message_logs(
            [
                {"id": "local-1", "message_id": "wamid.1", "text": "original"},
                {"speaker": "person", "created_at": "2026-08-25T12:00:00Z", "text": "sí"},
            ],
            [
                {"id": "local-retry", "message_id": "wamid.1", "text": "enriched", "image_url": "https://example.test/a.jpg"},
                {"speaker": "person", "created_at": "2026-08-25T12:00:00Z", "text": "sí"},
            ],
        )

        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["text"], "enriched")
        self.assertEqual(merged[0]["image_url"], "https://example.test/a.jpg")

    def test_update_accepts_serialized_context_and_filters_invalid_messages(self):
        service = SheetsService(
            Settings(google_application_credentials="", google_sheets_spreadsheet_id="")
        )

        result = service.update_conversation(
            "+56911111111",
            {"context_json": '{"message_log":[null,"bad",{"id":"ok","text":"hola"}]}'},
        )

        self.assertEqual(result["context_json"]["message_log"], [{"id": "ok", "text": "hola"}])

    def test_append_rows_uses_single_remote_batch_and_updates_cache(self):
        service = SheetsService(
            Settings(google_application_credentials="", google_sheets_spreadsheet_id="")
        )
        worksheet = Mock()
        service._spreadsheet = object()
        service._worksheet_cache[SHEET_NAMES["conversation_messages"]] = worksheet
        service._headers_cache[SHEET_NAMES["conversation_messages"]] = (
            0.0,
            ["message_record_id", "phone", "text"],
        )
        service._records_cache[SHEET_NAMES["conversation_messages"]] = (0.0, [])

        with patch("services.sheets_service.time.monotonic", return_value=0.0):
            service._append_rows(
                SHEET_NAMES["conversation_messages"],
                [{"message_record_id": "m1", "phone": "+5691", "text": "uno"}, {"message_record_id": "m2", "phone": "+5691", "text": "dos"}],
            )

        worksheet.append_rows.assert_called_once()
        self.assertEqual(len(service._records_cache[SHEET_NAMES["conversation_messages"]][1]), 2)

    def test_append_rows_keeps_successful_batch_cached_when_later_batch_fails(self):
        service = SheetsService(
            Settings(google_application_credentials="", google_sheets_spreadsheet_id="")
        )
        worksheet = Mock()
        worksheet.append_rows.side_effect = [None, RuntimeError("second batch failed")]
        name = SHEET_NAMES["conversation_messages"]
        service._spreadsheet = object()
        service._worksheet_cache[name] = worksheet
        service._headers_cache[name] = (0.0, ["message_record_id"])
        service._records_cache[name] = (0.0, [])

        with patch("services.sheets_service.time.monotonic", return_value=0.0):
            with self.assertRaises(RuntimeError):
                service._append_rows(
                    name,
                    [{"message_record_id": f"m{index}"} for index in range(101)],
                )

        self.assertEqual(len(service._records_cache[name][1]), 100)

    def test_large_message_payload_is_valid_json_below_sheet_cell_limit(self):
        payload = SheetsService._safe_conversation_message_payload(
            {
                "id": "large",
                "speaker": "person",
                "text": "x" * 70_000,
                "attachments": [{"document_url": "https://example.test/" + "y" * 60_000}],
            }
        )

        parsed = json.loads(payload)
        self.assertLessEqual(len(payload), 40_000)
        self.assertIs(parsed["payload_truncated"], True)
        self.assertEqual(parsed["original_text_length"], 70_000)

        service = SheetsService(
            Settings(google_application_credentials="", google_sheets_spreadsheet_id="")
        )
        service._archive_conversation_messages("+56911111111", [{"id": "large", "text": "x" * 70_000}])
        archived = service._memory_store[SHEET_NAMES["conversation_messages"]][0]
        self.assertLessEqual(len(archived["text"]), 40_000)
        self.assertLessEqual(len(archived["payload_json"]), 40_000)

    def test_backoffice_detail_rehydrates_archived_history(self):
        sheets = Mock()
        sheets.get_conversation.return_value = {
            "phone": "+56911111111",
            "case_id": "",
            "context_json": {"message_log": [{"id": "recent"}]},
        }
        sheets.list_conversation_messages.return_value = [{"id": "old"}, {"id": "recent"}]
        sheets.list_employees.return_value = []
        sheets.list_expense_cases.return_value = []
        sheets.get_employee_any_by_phone.return_value = None
        sheets.get_expense_case_by_id.return_value = None
        service = BackofficeService(sheets)

        detail = service.get_conversation_detail("+56911111111")

        self.assertEqual(
            detail["conversation"]["context_json"]["message_log"],
            [{"id": "old"}, {"id": "recent"}],
        )

    def test_message_log_failure_does_not_escape_into_business_flow(self):
        sheets = Mock()
        sheets.get_conversation.return_value = {
            "state": "CONFIRM_SUMMARY",
            "current_step": "confirm_summary",
            "context_json": {"message_log": []},
        }
        sheets.update_conversation.side_effect = RuntimeError("Sheets unavailable")
        conversation = Mock()
        conversation.ensure_conversation.side_effect = lambda value: value
        container = SimpleNamespace(sheets=sheets, conversation=conversation)

        _append_message_log(container, "+56911111111", {"speaker": "person", "text": "Confirmar"})

        sheets.update_conversation.assert_called_once()

    def test_column_label_supports_columns_beyond_z(self):
        self.assertEqual(_column_label(1), "A")
        self.assertEqual(_column_label(26), "Z")
        self.assertEqual(_column_label(27), "AA")
        self.assertEqual(_column_label(31), "AE")

    def test_backoffice_case_daily_reminders_normalizes_sheet_booleans(self):
        service = SheetsService(
            Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
            )
        )

        disabled = service._normalize_backoffice_case_row(
            {
                "case_id": "CASE-1",
                "employee_phone": "+56911111111",
                "daily_reminders_enabled": "FALSE",
            }
        )
        missing = service._normalize_backoffice_case_row(
            {"case_id": "CASE-2", "employee_phone": "+56922222222"}
        )
        denormalized = service._denormalize_backoffice_case_row(disabled)

        self.assertIs(disabled["daily_reminders_enabled"], False)
        self.assertIs(missing["daily_reminders_enabled"], True)
        self.assertEqual(denormalized["daily_reminders_enabled"], "FALSE")

    def test_append_audit_log_uses_local_store_when_sheets_disabled(self):
        service = SheetsService(
            Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
            )
        )

        row = service.append_audit_log(
            user_email="Operator@Example.com",
            user_role="company_admin",
            action="expense.approve",
            resource_type="expense",
            resource_id="EXP-1",
            company_id="COMP-1",
            details={"case_id": "CASE-1"},
        )

        self.assertTrue(row["audit_id"].startswith("audit-"))
        self.assertEqual(row["user_email"], "operator@example.com")
        self.assertEqual(row["action"], "expense.approve")
        rows = service.list_audit_log()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["resource_id"], "EXP-1")

    def test_get_records_uses_stale_cache_on_retryable_timeout(self):
        service = SheetsService(
            Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
                google_sheets_stale_cache_ttl_seconds=300,
            )
        )
        worksheet = Mock()
        worksheet.get_all_records.side_effect = Exception(
            "('Connection aborted.', TimeoutError(60, 'Operation timed out'))"
        )
        service._spreadsheet = object()
        service._worksheet_cache[SHEET_NAMES["expense_cases"]] = worksheet
        service._records_cache[SHEET_NAMES["expense_cases"]] = (
            1000.0,
            [{"status": "active", "case_id": "CASE-1"}],
        )
        with patch("services.sheets_service.time.monotonic", return_value=1060.0):
            records = service._get_records(SHEET_NAMES["expense_cases"])

        self.assertEqual(records, [{"status": "active", "case_id": "CASE-1"}])
        self.assertEqual(worksheet.get_all_records.call_count, 4)

    def test_get_records_raises_when_stale_cache_is_too_old(self):
        service = SheetsService(
            Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
                google_sheets_stale_cache_ttl_seconds=30,
            )
        )
        worksheet = Mock()
        worksheet.get_all_records.side_effect = Exception(
            "('Connection aborted.', TimeoutError(60, 'Operation timed out'))"
        )
        service._spreadsheet = object()
        service._worksheet_cache[SHEET_NAMES["expense_cases"]] = worksheet
        service._records_cache[SHEET_NAMES["expense_cases"]] = (
            1000.0,
            [{"status": "active", "case_id": "CASE-1"}],
        )
        with patch("services.sheets_service.time.monotonic", return_value=1060.0):
            with self.assertRaises(Exception):
                service._get_records(SHEET_NAMES["expense_cases"])

    def test_get_records_falls_back_when_sheet_headers_are_duplicated(self):
        service = SheetsService(
            Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
                google_sheets_record_cache_ttl_seconds=15,
            )
        )
        worksheet = Mock()
        worksheet.get_all_records.side_effect = Exception(
            "the header row in the worksheet contains duplicates: ['settlement_calculated_at', 'settlement_resolved_at']"
        )
        worksheet.get_all_values.return_value = [
            [
                "case_id",
                "status",
                "settlement_calculated_at",
                "settlement_calculated_at",
                "settlement_resolved_at",
                "settlement_resolved_at",
            ],
            [
                "CASE-1",
                "active",
                "",
                "2026-04-16T12:00:00Z",
                "2026-04-17T08:00:00Z",
                "",
            ],
        ]
        service._spreadsheet = object()
        service._worksheet_cache[SHEET_NAMES["expense_cases"]] = worksheet

        with patch("services.sheets_service.time.monotonic", return_value=1000.0):
            records = service._get_records(SHEET_NAMES["expense_cases"])

        self.assertEqual(
            records,
            [
                {
                    "case_id": "CASE-1",
                    "status": "active",
                    "settlement_calculated_at": "2026-04-16T12:00:00Z",
                    "settlement_resolved_at": "2026-04-17T08:00:00Z",
                }
            ],
        )

    def test_get_records_bypasses_hot_cache_when_record_ttl_is_zero(self):
        service = SheetsService(
            Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
                google_sheets_record_cache_ttl_seconds=0,
            )
        )
        worksheet = Mock()
        worksheet.get_all_records.return_value = [{"case_id": "CASE-NEW", "status": "active"}]
        service._spreadsheet = object()
        service._worksheet_cache[SHEET_NAMES["expense_cases"]] = worksheet
        service._records_cache[SHEET_NAMES["expense_cases"]] = (
            1000.0,
            [{"case_id": "CASE-OLD", "status": "active"}],
        )

        with patch("services.sheets_service.time.monotonic", return_value=1000.0):
            records = service._get_records(SHEET_NAMES["expense_cases"])

        self.assertEqual(records, [{"case_id": "CASE-NEW", "status": "active"}])
        worksheet.get_all_records.assert_called_once()

    def test_get_records_uses_stale_cache_on_retryable_503(self):
        service = SheetsService(
            Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
                google_sheets_stale_cache_ttl_seconds=300,
            )
        )
        worksheet = Mock()
        worksheet.get_all_records.side_effect = Exception(
            "APIError: [503]: The service is currently unavailable."
        )
        service._spreadsheet = object()
        service._worksheet_cache[SHEET_NAMES["expense_cases"]] = worksheet
        service._records_cache[SHEET_NAMES["expense_cases"]] = (
            1000.0,
            [{"status": "active", "case_id": "CASE-503"}],
        )
        with patch("services.sheets_service.time.monotonic", return_value=1060.0):
            records = service._get_records(SHEET_NAMES["expense_cases"])

        self.assertEqual(records, [{"status": "active", "case_id": "CASE-503"}])
        self.assertEqual(worksheet.get_all_records.call_count, 4)

    def test_get_records_uses_cached_rows_during_read_cooldown(self):
        service = SheetsService(
            Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
                google_sheets_record_cache_ttl_seconds=0,
                google_sheets_stale_cache_ttl_seconds=300,
                google_sheets_read_cooldown_seconds=60,
            )
        )
        worksheet = Mock()
        worksheet.get_all_records.return_value = [{"case_id": "CASE-NEW", "status": "active"}]
        service._spreadsheet = object()
        service._worksheet_cache[SHEET_NAMES["expense_cases"]] = worksheet
        service._records_cache[SHEET_NAMES["expense_cases"]] = (
            1000.0,
            [{"case_id": "CASE-CACHED", "status": "active"}],
        )
        service._read_cooldowns[SHEET_NAMES["expense_cases"]] = 1060.0

        with patch("services.sheets_service.time.monotonic", return_value=1030.0):
            records = service._get_records(SHEET_NAMES["expense_cases"])

        self.assertEqual(records, [{"case_id": "CASE-CACHED", "status": "active"}])
        worksheet.get_all_records.assert_not_called()

    def test_get_headers_uses_cached_headers_during_read_cooldown(self):
        service = SheetsService(
            Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
                google_sheets_record_cache_ttl_seconds=0,
                google_sheets_stale_cache_ttl_seconds=300,
                google_sheets_read_cooldown_seconds=60,
            )
        )
        worksheet = Mock()
        worksheet.row_values.return_value = ["new", "headers"]
        service._spreadsheet = object()
        service._worksheet_cache[SHEET_NAMES["expense_cases"]] = worksheet
        service._headers_cache[SHEET_NAMES["expense_cases"]] = (
            1000.0,
            ["cached", "headers"],
        )
        service._read_cooldowns[SHEET_NAMES["expense_cases"]] = 1060.0

        with patch("services.sheets_service.time.monotonic", return_value=1030.0):
            headers = service._get_headers(SHEET_NAMES["expense_cases"])

        self.assertEqual(headers, ["cached", "headers"])
        worksheet.row_values.assert_not_called()

    def test_upsert_updates_existing_row_with_columns_beyond_z(self):
        service = SheetsService(
            Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
                google_sheets_record_cache_ttl_seconds=15,
            )
        )
        worksheet = Mock()
        headers = [f"col_{index}" for index in range(1, 32)]
        existing = {header: f"old-{header}" for header in headers}
        payload = {header: f"new-{header}" for header in headers}
        payload["col_1"] = "row-key"
        existing["col_1"] = "row-key"

        service._spreadsheet = object()
        service._worksheet_cache[SHEET_NAMES["expense_cases"]] = worksheet
        service._headers_cache[SHEET_NAMES["expense_cases"]] = (1000.0, headers)
        service._records_cache[SHEET_NAMES["expense_cases"]] = (1000.0, [existing])

        with patch("services.sheets_service.time.monotonic", return_value=1000.0):
            service._upsert_by_key(SHEET_NAMES["expense_cases"], "col_1", "row-key", payload)

        worksheet.update.assert_called_once_with(
            "A2:AE2",
            [[payload.get(header, "") for header in headers]],
        )

    def test_append_row_serializes_complex_values_for_google_sheets(self):
        service = SheetsService(
            Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
                google_sheets_record_cache_ttl_seconds=15,
            )
        )
        worksheet = Mock()
        headers = ["expense_id", "review_breakdown", "review_flags"]

        service._spreadsheet = object()
        service._worksheet_cache[SHEET_NAMES["expenses"]] = worksheet
        service._headers_cache[SHEET_NAMES["expenses"]] = (1000.0, headers)
        service._records_cache[SHEET_NAMES["expenses"]] = (1000.0, [])

        with patch("services.sheets_service.time.monotonic", return_value=1000.0):
            service._append_row(
                SHEET_NAMES["expenses"],
                {
                    "expense_id": "EXP-1",
                    "review_breakdown": {"document_quality": 100, "policy_risk": 95},
                    "review_flags": ["high_amount", "duplicate_match"],
                },
            )

        worksheet.append_row.assert_called_once_with(
            [
                "EXP-1",
                '{"document_quality": 100, "policy_risk": 95}',
                '["high_amount", "duplicate_match"]',
            ],
            value_input_option="USER_ENTERED",
        )

    def test_sqlite_persistence_survives_new_service_instance(self):
        with TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "expenses.sqlite3")
            settings = Settings(
                google_application_credentials="",
                google_sheets_spreadsheet_id="",
                persistence_backend="sqlite",
                sqlite_database_path=db_path,
            )
            service = SheetsService(settings)
            service.create_employee(
                {
                    "phone": "+56911111111",
                    "first_name": "Javier",
                    "active": True,
                }
            )
            service.create_expense_case(
                {
                    "case_id": "CASE-1",
                    "employee_phone": "+56911111111",
                    "status": "active",
                    "context_label": "Demo",
                }
            )
            service.create_expense(
                {
                    "expense_id": "EXP-1",
                    "phone": "+56911111111",
                    "case_id": "CASE-1",
                    "total_clp": 12000,
                }
            )

            reloaded = SheetsService(settings)

            self.assertTrue(reloaded.sqlite_enabled)
            self.assertEqual(reloaded.get_employee_by_phone("+56911111111")["first_name"], "Javier")
            self.assertEqual(reloaded.get_expense_case_by_id("CASE-1")["context_label"], "Demo")
            self.assertEqual(len(reloaded.list_expenses_by_phone_case("+56911111111", "CASE-1")), 1)

    def test_sqlite_upsert_and_delete_match_sheet_api(self):
        with TemporaryDirectory() as tmpdir:
            service = SheetsService(
                Settings(
                    google_application_credentials="",
                    google_sheets_spreadsheet_id="",
                    persistence_backend="sqlite",
                    sqlite_database_path=str(Path(tmpdir) / "expenses.sqlite3"),
                )
            )
            service.create_expense_case(
                {
                    "case_id": "CASE-1",
                    "employee_phone": "+56911111111",
                    "status": "active",
                    "context_label": "Original",
                }
            )

            updated = service.update_expense_case("CASE-1", {"context_label": "Actualizada"})
            deleted = service.delete_expense_case("CASE-1")

            self.assertEqual(updated["context_label"], "Actualizada")
            self.assertEqual(deleted["context_label"], "Actualizada")
            self.assertIsNone(service.get_expense_case_by_id("CASE-1"))


if __name__ == "__main__":
    unittest.main()
