import unittest

from services.expense_service import ExpenseService


class FakeSheetsService:
    def __init__(self):
        self.saved_expense = None
        self.case = {"case_id": "CASE-1", "fondos_entregados": 10000}
        self.case_expenses = []

    def get_active_expense_case_by_phone(self, phone):
        return {"case_id": "CASE-1", "phone": phone}

    def list_expenses_by_phone_case(self, phone, case_id):
        return list(self.case_expenses)

    def create_expense(self, payload):
        self.saved_expense = dict(payload)
        return dict(payload)

    def get_expense_case_by_id(self, case_id):
        if case_id == self.case["case_id"]:
            return dict(self.case)
        return None


class ExpenseServiceNotificationTests(unittest.TestCase):
    def test_save_confirmed_expense_persists_source_message_id(self):
        sheets = FakeSheetsService()
        service = ExpenseService(sheets_service=sheets)

        saved = service.save_confirmed_expense(
            "+56911111111",
            {
                "merchant": "Cafe",
                "date": "2026-04-16",
                "currency": "CLP",
                "total": 4500,
                "category": "Meals",
                "country": "Chile",
                "source_message_id": "wamid.123",
            },
        )

        self.assertEqual(saved["source_message_id"], "wamid.123")
        self.assertEqual(sheets.saved_expense["source_message_id"], "wamid.123")

    def test_build_summary_message_does_not_warn_about_missing_invoice_number(self):
        service = ExpenseService(sheets_service=FakeSheetsService())

        summary = service.build_summary_message(
            {
                "document_type": "invoice",
                "merchant": "Proveedor Demo",
                "date": "2026-04-16",
                "currency": "CLP",
                "total": 4500,
                "category": "Meals",
                "country": "Chile",
                "invoice_number": "",
            },
            include_text_actions=False,
        )

        self.assertNotIn("No se detectó número de folio/factura.", summary)

    def test_policy_status_and_alert_messages_are_separated(self):
        sheets = FakeSheetsService()
        sheets.case_expenses = [{"total_clp": 12000}]
        service = ExpenseService(sheets_service=sheets)

        status_message = service.build_policy_status_message("+56911111111", "CASE-1")
        alert_message = service.build_policy_alert_message("+56911111111", "CASE-1")

        self.assertIn("Estado de tu rendición:", status_message)
        self.assertNotIn("Alertas:", status_message)
        self.assertEqual(
            alert_message,
            "Excediste los fondos entregados en $2.000 CLP.",
        )

    def test_build_summary_message_hides_tax_amount_from_chat(self):
        service = ExpenseService(sheets_service=FakeSheetsService())

        receipt_summary = service.build_summary_message(
            {
                "document_type": "receipt",
                "merchant": "Cafe Demo",
                "date": "2026-04-16",
                "currency": "CLP",
                "total": 4500,
                "category": "Meals",
                "country": "Chile",
                "tax_amount": 719,
            },
            include_text_actions=False,
        )
        invoice_summary = service.build_summary_message(
            {
                "document_type": "invoice",
                "merchant": "Proveedor Demo",
                "date": "2026-04-16",
                "currency": "CLP",
                "total": 4500,
                "category": "Meals",
                "country": "Chile",
                "tax_amount": 719,
                "invoice_number": "F123",
            },
            include_text_actions=False,
        )

        self.assertNotIn("Impuesto:", receipt_summary)
        self.assertNotIn("Impuesto/IVA:", invoice_summary)

    def test_classifies_boleta_de_honorarios_as_own_document_type(self):
        service = ExpenseService(sheets_service=FakeSheetsService())

        result = service.classify_document({"document_type": "boleta_honorarios"})

        self.assertEqual(result["document_type"], "professional_fee_receipt")
        self.assertFalse(result["requires_user_confirmation"])

    def test_professional_fee_receipt_summary_uses_net_total_and_retention(self):
        service = ExpenseService(sheets_service=FakeSheetsService())

        draft = service.enrich_draft_expense(
            {
                "document_type": "professional_fee_receipt",
                "merchant": "Juan Perez",
                "date": "2026-04-16",
                "currency": "",
                "total": None,
                "category": "Other",
                "country": "",
                "invoice_number": "123",
                "issuer_tax_id": "RUT 12.345.678-9",
                "gross_amount": 100000,
                "withholding_amount": 15250,
            }
        )
        summary = service.build_summary_message(draft, include_text_actions=False)

        self.assertEqual(draft["document_type"], "professional_fee_receipt")
        self.assertEqual(draft["total"], 84750)
        self.assertEqual(draft["withholding_rate"], 15.25)
        self.assertIn("boleta de honorarios", summary)
        self.assertIn("Monto bruto: 100000", summary)
        self.assertIn("Retención (15.25%): 15250", summary)
        self.assertIn("Monto líquido: 84750", summary)


if __name__ == "__main__":
    unittest.main()
