import unittest

from services.expense_service import ExpenseService


class FakeSheetsService:
    def __init__(self):
        self.saved_expense = None
        self.case = {"case_id": "CASE-1", "fondos_entregados": 10000}
        self.case_expenses = []

    def get_active_expense_case_by_phone(self, phone):
        return {**self.case, "phone": phone}

    def list_expenses_by_phone_case(self, phone, case_id):
        return list(self.case_expenses)

    def create_expense(self, payload):
        self.saved_expense = dict(payload)
        return dict(payload)

    def get_expense_case_by_id(self, case_id):
        if case_id == self.case["case_id"]:
            return {**self.case, "phone": "+56911111111"}
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

    def test_save_confirmed_expense_uses_selected_case_id_from_draft(self):
        sheets = FakeSheetsService()
        sheets.case = {"case_id": "CASE-2", "fondos_entregados": 10000}
        service = ExpenseService(sheets_service=sheets)

        saved = service.save_confirmed_expense(
            "+56911111111",
            {
                "case_id": "CASE-2",
                "merchant": "Hotel",
                "date": "2026-04-16",
                "currency": "CLP",
                "total": 20000,
                "category": "Lodging",
                "country": "Chile",
            },
        )

        self.assertEqual(saved["case_id"], "CASE-2")
        self.assertEqual(saved["trip_id"], "CASE-2")
        self.assertEqual(sheets.saved_expense["case_lookup_status"], "active_case_linked")

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

    def test_rendicion_summary_is_answered_on_request(self):
        sheets = FakeSheetsService()
        sheets.case_expenses = [{"total_clp": 110300}]
        sheets.case["fondos_entregados"] = 1000000
        service = ExpenseService(sheets_service=sheets)

        answer = service.answer_rendicion_question(
            phone="+56911111111",
            question="dame el resumen",
        )

        self.assertIn("Estado de tu rendición:", answer)
        self.assertIn("- Fondos entregados: $1.000.000 CLP", answer)
        self.assertIn("- Rendido: $110.300 CLP (11.0%)", answer)
        self.assertIn("- Saldo restante: $889.700 CLP", answer)

    def test_case_context_includes_budget_by_cost_center(self):
        sheets = FakeSheetsService()
        sheets.case.update(
            {
                "context_label": "Rendición mayo",
                "cost_centers": ["Operaciones", "Ventas"],
                "fondos_entregados": 150000,
                "fondos_por_centro": {"Operaciones": 100000, "Ventas": 50000},
            }
        )
        sheets.case_expenses = [
            {"cost_center": "Operaciones", "total_clp": 30000},
            {"cost_center": "Ventas", "total_clp": 12000},
            {"cost_center": "Marketing", "total_clp": 8000},
        ]
        service = ExpenseService(sheets_service=sheets)

        context = service.build_case_context_text("+56911111111")

        self.assertIn("Nombre de la rendición: Rendición mayo", context)
        self.assertIn("Fondos entregados: $150.000 CLP", context)
        self.assertIn("Total rendido: $50.000 CLP (3 gasto(s))", context)
        self.assertIn("Saldo restante: $100.000 CLP", context)
        self.assertIn(
            "Operaciones: presupuesto $100.000 CLP; rendido $30.000 CLP; saldo $70.000 CLP",
            context,
        )
        self.assertIn(
            "Ventas: presupuesto $50.000 CLP; rendido $12.000 CLP; saldo $38.000 CLP",
            context,
        )
        self.assertIn(
            "Marketing: presupuesto no asignado; rendido $8.000 CLP",
            context,
        )

    def test_rendicion_cost_centers_question_is_answered_from_case(self):
        sheets = FakeSheetsService()
        sheets.case.update(
            {
                "cost_centers": ["Operaciones", "Ventas"],
                "fondos_por_centro": {"Operaciones": 100000, "Ventas": 50000},
            }
        )
        service = ExpenseService(sheets_service=sheets)

        answer = service.answer_rendicion_question(
            phone="+56911111111",
            question="Cuales son mis centros de costo?",
        )

        self.assertIn("Tus centros de costo son:", answer)
        self.assertIn("- Operaciones: $100.000 CLP", answer)
        self.assertIn("- Ventas: $50.000 CLP", answer)

    def test_rendicion_budget_question_is_answered_from_case(self):
        sheets = FakeSheetsService()
        sheets.case.update(
            {
                "cost_centers": ["Operaciones", "Ventas"],
                "fondos_entregados": 150000,
                "fondos_por_centro": {"Operaciones": 100000, "Ventas": 50000},
            }
        )
        sheets.case_expenses = [
            {"cost_center": "Operaciones", "total_clp": 30000},
            {"cost_center": "Ventas", "total_clp": 12000},
        ]
        service = ExpenseService(sheets_service=sheets)

        answer = service.answer_rendicion_question(
            phone="+56911111111",
            question="Cual es mi presupuesto?",
        )

        self.assertIn("Fondos entregados: $150.000 CLP", answer)
        self.assertIn(
            "- Operaciones: $100.000 CLP; rendido $30.000 CLP; saldo $70.000 CLP",
            answer,
        )
        self.assertIn(
            "- Ventas: $50.000 CLP; rendido $12.000 CLP; saldo $38.000 CLP",
            answer,
        )

    def test_rendicion_balance_and_last_expense_are_answered_on_request(self):
        sheets = FakeSheetsService()
        sheets.case["fondos_entregados"] = 50000
        sheets.case_expenses = [
            {
                "merchant": "Cafe",
                "date": "2026-04-15",
                "total": 4500,
                "total_clp": 4500,
                "created_at": "2026-04-15T12:00:00Z",
            },
            {
                "merchant": "Taxi",
                "date": "2026-04-16",
                "total": 8000,
                "total_clp": 8000,
                "created_at": "2026-04-16T12:00:00Z",
            },
        ]
        service = ExpenseService(sheets_service=sheets)

        balance = service.answer_rendicion_question(
            phone="+56911111111",
            question="cuanto presupuesto me queda",
        )
        last_expense = service.answer_rendicion_question(
            phone="+56911111111",
            question="cual fue el ultimo gasto",
        )

        self.assertEqual(balance, "- Saldo restante: $37.500 CLP")
        self.assertEqual(
            last_expense,
            "Último gasto registrado: Taxi, monto $8.000 CLP, fecha 2026-04-16.",
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

    def test_professional_fee_receipt_summary_uses_gross_total_and_retention(self):
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
                "receiver_tax_id": "RUT: 77.123.456-1",
                "gross_amount": 100000,
                "withholding_amount": 15250,
            }
        )
        summary = service.build_summary_message(draft, include_text_actions=False)

        self.assertEqual(draft["document_type"], "professional_fee_receipt")
        self.assertEqual(draft["total"], 100000)
        self.assertEqual(draft["net_amount"], 84750)
        self.assertEqual(draft["withholding_rate"], 15.25)
        self.assertIn("boleta de honorarios", summary)
        self.assertIn("💰 Monto bruto: 100000", summary)
        self.assertNotIn("Retención", summary)
        self.assertIn("💵 Monto líquido: 84750", summary)
        self.assertIn("🪪 RUT emisor: 12.345.678-9", summary)
        self.assertIn("🪪 RUT receptor: 77.123.456-1", summary)
        self.assertNotIn("RUT emisor: RUT", summary)
        self.assertNotIn("RUT receptor: RUT", summary)
        self.assertNotIn("Categoría:", summary)
        self.assertNotIn("País:", summary)

    def test_professional_fee_receipt_summary_order_and_integer_amounts(self):
        service = ExpenseService(sheets_service=FakeSheetsService())

        summary = service.build_summary_message(
            {
                "document_type": "professional_fee_receipt",
                "merchant": "SONIDO AL SUR SPA",
                "date": "2024-05-12",
                "invoice_number": "1255",
                "issuer_tax_id": "RUT: 77.987.654-3",
                "receiver_tax_id": "RUT: 77.123.456-1",
                "gross_amount": 280000.0,
                "net_amount": 241500.0,
                "total": 280000.0,
                "currency": "CLP",
            },
            include_text_actions=False,
        )

        self.assertEqual(
            summary.splitlines(),
            [
                "Detecté este gasto a partir de una *boleta de honorarios*:",
                "🏢 Emisor: SONIDO AL SUR SPA",
                "📅 Fecha: 2024-05-12",
                "🔢 Folio: 1255",
                "🪪 RUT emisor: 77.987.654-3",
                "🪪 RUT receptor: 77.123.456-1",
                "💵 Monto líquido: 241500 CLP",
                "💰 Monto bruto: 280000 CLP",
            ],
        )

    def test_professional_fee_receipt_reconciles_equal_gross_and_net_with_retention(self):
        service = ExpenseService(sheets_service=FakeSheetsService())

        draft = service.enrich_draft_expense(
            {
                "document_type": "professional_fee_receipt",
                "merchant": "SONIDO AL SUR SPA",
                "date": "2024-05-12",
                "currency": "CLP",
                "total": 280000,
                "gross_amount": 280000,
                "net_amount": 280000,
                "withholding_amount": 38500,
            }
        )

        self.assertEqual(draft["gross_amount"], 318500)
        self.assertEqual(draft["net_amount"], 280000)
        self.assertEqual(draft["total"], 318500)

    def test_professional_fee_receipt_prefers_explicit_labeled_amounts(self):
        service = ExpenseService(sheets_service=FakeSheetsService())

        draft = service.enrich_draft_expense(
            {
                "document_type": "professional_fee_receipt",
                "merchant": "SONIDO AL SUR SPA",
                "date": "2024-05-12",
                "currency": "CLP",
                "total": 280000,
                "gross_amount": 280000,
                "net_amount": 280000,
                "ocr_text": (
                    "BOLETA DE HONORARIOS ELECTRONICA\n"
                    "Monto bruto: $280.000\n"
                    "Retención: $38.500\n"
                    "Monto líquido: $241.500"
                ),
            }
        )

        self.assertEqual(draft["gross_amount"], 280000)
        self.assertEqual(draft["withholding_amount"], 38500)
        self.assertEqual(draft["net_amount"], 241500)
        self.assertEqual(draft["total"], 280000)

    def test_professional_fee_receipt_derives_gross_from_net_and_expected_rate(self):
        service = ExpenseService(sheets_service=FakeSheetsService())

        draft = service.enrich_draft_expense(
            {
                "document_type": "professional_fee_receipt",
                "merchant": "ACTOR DE TEATRO, CINE Y TELEVISIÓN",
                "date": "2024-05-12",
                "currency": "CLP",
                "total": 362250,
                "net_amount": 362250,
                "invoice_number": "1252",
                "issuer_tax_id": "RUT: 18.765.432-1",
                "receiver_tax_id": "RUT: 77.123.456-1",
                "ocr_text": "BOLETA DE HONORARIOS ELECTRONICA TOTAL LIQUIDO 362250",
            }
        )
        summary = service.build_summary_message(draft, include_text_actions=False)

        self.assertEqual(draft["gross_amount"], 420000)
        self.assertEqual(draft["withholding_amount"], 57750)
        self.assertEqual(draft["net_amount"], 362250)
        self.assertEqual(draft["total"], 420000)
        self.assertIn("💰 Monto bruto: 420000 CLP", summary)
        self.assertIn("💵 Monto líquido: 362250 CLP", summary)

    def test_professional_fee_receipt_derives_gross_from_total_when_net_field_is_missing(self):
        service = ExpenseService(sheets_service=FakeSheetsService())

        draft = service.enrich_draft_expense(
            {
                "document_type": "boleta_honorarios",
                "merchant": "ACTOR DE TEATRO, CINE Y TELEVISIÓN",
                "date": "2024-05-12",
                "currency": "CLP",
                "total": 362250,
                "invoice_number": "1252",
                "issuer_tax_id": "RUT: 18.765.432-1",
                "receiver_tax_id": "RUT: 77.123.456-1",
                "ocr_text": "BOLETA DE HONORARIOS ELECTRONICA TOTAL LIQUIDO 362250",
            }
        )
        summary = service.build_summary_message(draft, include_text_actions=False)

        self.assertEqual(draft["document_type"], "professional_fee_receipt")
        self.assertEqual(draft["gross_amount"], 420000)
        self.assertEqual(draft["net_amount"], 362250)
        self.assertEqual(draft["total"], 420000)
        self.assertIn("💰 Monto bruto: 420000 CLP", summary)
        self.assertIn("💵 Monto líquido: 362250 CLP", summary)

    def test_professional_fee_receipt_does_not_require_category_or_country(self):
        service = ExpenseService(sheets_service=FakeSheetsService())

        draft = service.enrich_draft_expense(
            {
                "document_type": "professional_fee_receipt",
                "merchant": "Juan Perez",
                "date": "2026-04-16",
                "currency": "CLP",
                "total": 84750,
                "category": "",
                "country": "",
                "invoice_number": "123",
                "issuer_tax_id": "RUT 12.345.678-9",
            }
        )

        self.assertEqual(service.find_missing_required_fields(draft), [])
        extraction = service.build_document_extraction_result(draft)
        self.assertEqual(extraction["missing_required_fields"], [])


if __name__ == "__main__":
    unittest.main()
