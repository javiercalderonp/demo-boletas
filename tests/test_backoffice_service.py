import unittest

from services.backoffice_service import BackofficeService


class FakeSheetsService:
    def __init__(self, *, case_row, expenses):
        self.case_row = case_row
        self.expenses = expenses
        self.created_case_payloads = []
        self.companies = [
            {
                "company_id": "acme",
                "name": "ACME",
                "bank_name": "Banco Estado",
                "account_type": "Cuenta Corriente",
                "account_number": "12345678",
                "account_holder": "ACME SpA",
                "account_holder_rut": "76.123.456-7",
            }
        ]

    def get_expense_case_by_id(self, case_id):
        if self.case_row and self.case_row.get("case_id") == case_id:
            return dict(self.case_row)
        return None

    def list_expenses(self):
        return [dict(item) for item in self.expenses]

    def get_expense_by_id(self, expense_id):
        for item in self.expenses:
            if item.get("expense_id") == expense_id:
                return dict(item)
        return None

    def update_expense(self, expense_id, payload):
        for index, item in enumerate(self.expenses):
            if item.get("expense_id") == expense_id:
                updated = {**item, **payload}
                self.expenses[index] = updated
                return dict(updated)
        return None

    def list_employees(self):
        return []

    def list_companies(self):
        return [dict(item) for item in self.companies]

    def list_expense_cases(self):
        return [dict(self.case_row)] if self.case_row else []

    def update_expense_case(self, case_id, payload):
        if not self.case_row or self.case_row.get("case_id") != case_id:
            return None
        self.case_row = {**self.case_row, **payload}
        return dict(self.case_row)

    def list_active_expense_cases_by_phone(self, phone):
        if not self.case_row:
            return []
        row_phone = self.case_row.get("employee_phone", self.case_row.get("phone", ""))
        row_status = self.case_row.get("status", "")
        if row_phone == phone and str(row_status).strip().lower() == "active":
            return [dict(self.case_row)]
        return []

    def create_expense_case(self, payload):
        self.created_case_payloads.append(dict(payload))
        return dict(payload)


class BackofficeCaseTransitionTests(unittest.TestCase):
    def test_create_case_blocks_when_employee_already_has_active_case(self):
        sheets = FakeSheetsService(
            case_row={
                "case_id": "CASE-1",
                "context_label": "Rendición abril",
                "employee_phone": "+56911111111",
                "status": "active",
            },
            expenses=[],
        )
        service = BackofficeService(sheets_service=sheets)

        with self.assertRaises(ValueError) as ctx:
            service.create_case(
                {
                    "employee_phone": "+56911111111",
                    "company_id": "acme",
                    "context_label": "abril",
                    "status": "active",
                }
            )

        self.assertIn("ya tiene un caso activo", str(ctx.exception))
        self.assertIn("Rendición abril (CASE-1)", str(ctx.exception))
        self.assertEqual(sheets.created_case_payloads, [])

    def test_create_case_allows_new_case_when_existing_case_is_closed(self):
        sheets = FakeSheetsService(
            case_row={"case_id": "CASE-1", "employee_phone": "+56911111111", "status": "closed"},
            expenses=[],
        )
        service = BackofficeService(sheets_service=sheets)

        created = service.create_case(
            {
                "case_id": "CASE-2",
                "employee_phone": "+56911111111",
                "company_id": "acme",
                "context_label": "abril",
                "status": "active",
            }
        )

        self.assertEqual(created["case_id"], "CASE-2")
        self.assertEqual(len(sheets.created_case_payloads), 1)

    def test_document_confirmation_requires_all_documents_resolved(self):
        service = BackofficeService(
            sheets_service=FakeSheetsService(
                case_row={"case_id": "CASE-1", "rendicion_status": "open"},
                expenses=[
                    {"expense_id": "EXP-1", "case_id": "CASE-1", "status": "approved"},
                    {"expense_id": "EXP-2", "case_id": "CASE-1", "status": "observed"},
                ],
            )
        )

        with self.assertRaises(ValueError) as ctx:
            service.ensure_case_ready_for_document_confirmation("CASE-1")

        self.assertIn("documentos no resueltos", str(ctx.exception))
        self.assertIn("awaiting_employee_input", str(ctx.exception))

    def test_document_confirmation_allows_approved_and_rejected_documents(self):
        service = BackofficeService(
            sheets_service=FakeSheetsService(
                case_row={"case_id": "CASE-1", "rendicion_status": "open"},
                expenses=[
                    {"expense_id": "EXP-1", "case_id": "CASE-1", "status": "approved"},
                    {"expense_id": "EXP-2", "case_id": "CASE-1", "status": "rejected"},
                ],
            )
        )

        gate = service.ensure_case_ready_for_document_confirmation("CASE-1")

        self.assertTrue(gate["all_documents_resolved"])
        self.assertEqual(gate["resolved_expense_count"], 2)

    def test_close_requires_case_approval(self):
        service = BackofficeService(
            sheets_service=FakeSheetsService(
                case_row={"case_id": "CASE-1", "rendicion_status": "pending_user_confirmation"},
                expenses=[
                    {"expense_id": "EXP-1", "case_id": "CASE-1", "status": "approved"},
                ],
            )
        )

        with self.assertRaises(ValueError) as ctx:
            service.ensure_case_ready_for_close("CASE-1")

        self.assertIn("después de estar aprobada", str(ctx.exception))

    def test_sync_case_settlement_marks_company_owes_employee_as_pending(self):
        sheets = FakeSheetsService(
            case_row={"case_id": "CASE-1", "rendicion_status": "approved", "fondos_entregados": 10000},
            expenses=[
                {"expense_id": "EXP-1", "case_id": "CASE-1", "status": "approved", "total_clp": 16000},
            ],
        )
        service = BackofficeService(sheets_service=sheets)

        updated = service.sync_case_settlement("CASE-1")

        self.assertEqual(updated["settlement_direction"], "company_owes_employee")
        self.assertEqual(updated["settlement_status"], "settlement_pending")
        self.assertEqual(updated["settlement_amount_clp"], 6000.0)
        self.assertEqual(updated["settlement_net_clp"], 6000.0)

    def test_sync_case_settlement_marks_balanced_as_settled(self):
        sheets = FakeSheetsService(
            case_row={"case_id": "CASE-1", "rendicion_status": "approved", "fondos_entregados": 10000},
            expenses=[
                {"expense_id": "EXP-1", "case_id": "CASE-1", "status": "approved", "total_clp": 10000},
            ],
        )
        service = BackofficeService(sheets_service=sheets)

        updated = service.sync_case_settlement("CASE-1")

        self.assertEqual(updated["settlement_direction"], "balanced")
        self.assertEqual(updated["settlement_status"], "settled")
        self.assertEqual(updated["settlement_amount_clp"], 0.0)
        self.assertEqual(updated["settlement_net_clp"], 0.0)

    def test_close_requires_settlement_resolution(self):
        service = BackofficeService(
            sheets_service=FakeSheetsService(
                case_row={
                    "case_id": "CASE-1",
                    "rendicion_status": "approved",
                    "settlement_direction": "employee_owes_company",
                    "settlement_status": "settlement_pending",
                },
                expenses=[
                    {"expense_id": "EXP-1", "case_id": "CASE-1", "status": "approved"},
                ],
            )
        )

        with self.assertRaises(ValueError) as ctx:
            service.ensure_case_ready_for_close("CASE-1")

        self.assertIn("liquidación financiera sigue pendiente", str(ctx.exception))

    def test_close_allows_balanced_snapshot_even_if_stored_settlement_is_stale(self):
        service = BackofficeService(
            sheets_service=FakeSheetsService(
                case_row={
                    "case_id": "CASE-1",
                    "rendicion_status": "approved",
                    "fondos_entregados": 10000,
                    "settlement_status": "settlement_pending",
                },
                expenses=[
                    {"expense_id": "EXP-1", "case_id": "CASE-1", "status": "approved", "total_clp": 10000},
                ],
            )
        )

        gate = service.ensure_case_ready_for_close("CASE-1")

        self.assertTrue(gate["all_documents_resolved"])

    def test_update_expense_syncs_review_status_from_resolved_status(self):
        sheets = FakeSheetsService(
            case_row={"case_id": "CASE-1", "rendicion_status": "open"},
            expenses=[
                {"expense_id": "EXP-1", "case_id": "CASE-1", "status": "pending_approval", "review_status": ""},
            ],
        )
        service = BackofficeService(sheets_service=sheets)

        updated = service.update_expense("EXP-1", {"status": "approved"})

        self.assertIsNotNone(updated)
        self.assertEqual(updated["status"], "approved")
        self.assertEqual(updated["review_status"], "approved")

    def test_update_expense_resyncs_settlement_for_approved_case(self):
        sheets = FakeSheetsService(
            case_row={
                "case_id": "CASE-1",
                "rendicion_status": "approved",
                "fondos_entregados": 10000,
                "settlement_status": "settlement_pending",
            },
            expenses=[
                {
                    "expense_id": "EXP-1",
                    "case_id": "CASE-1",
                    "status": "pending_approval",
                    "review_status": "",
                    "total_clp": 10000,
                },
            ],
        )
        service = BackofficeService(sheets_service=sheets)

        updated = service.update_expense("EXP-1", {"status": "approved"})

        self.assertIsNotNone(updated)
        self.assertEqual(sheets.case_row["settlement_direction"], "balanced")
        self.assertEqual(sheets.case_row["settlement_status"], "settled")
        self.assertEqual(sheets.case_row["settlement_amount_clp"], 0.0)

    def test_update_expense_clears_stale_review_status_when_returning_to_pending_approval(self):
        sheets = FakeSheetsService(
            case_row={"case_id": "CASE-1", "rendicion_status": "open"},
            expenses=[
                {"expense_id": "EXP-1", "case_id": "CASE-1", "status": "approved", "review_status": "approved"},
            ],
        )
        service = BackofficeService(sheets_service=sheets)

        updated = service.update_expense("EXP-1", {"status": "pending_approval"})

        self.assertIsNotNone(updated)
        self.assertEqual(updated["status"], "pending_approval")
        self.assertEqual(updated["review_status"], "pending_approval")

    def test_build_case_settlement_whatsapp_message_for_employee_deposit(self):
        service = BackofficeService(
            sheets_service=FakeSheetsService(case_row={"case_id": "CASE-1"}, expenses=[])
        )

        message = service.build_case_settlement_whatsapp_message(
            {"settlement_direction": "employee_owes_company", "settlement_amount_clp": 4500}
        )

        self.assertIn("Debes depositar", message)
        self.assertIn("$4.500", message)

    def test_build_case_settlement_bank_details_message_for_employee_deposit(self):
        service = BackofficeService(
            sheets_service=FakeSheetsService(case_row={"case_id": "CASE-1"}, expenses=[])
        )

        message = service.build_case_settlement_bank_details_message(
            {"company_id": "acme", "settlement_direction": "employee_owes_company"}
        )

        self.assertIsNotNone(message)
        self.assertIn("Datos bancarios de ACME", message)
        self.assertIn("Banco Estado", message)
        self.assertIn("envíame el comprobante", message)


if __name__ == "__main__":
    unittest.main()
