import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import Mock, patch

from app.config import Settings
from services.sheets_service import SHEET_NAMES, SheetsService, _column_label


class SheetsServiceFallbackTests(unittest.TestCase):
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
