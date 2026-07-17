import unittest
from datetime import datetime, timezone

from app.config import Settings
from services.scheduler_service import SchedulerService


class FakeStorageService:
    enabled = True

    def generate_signed_url(self, *, object_key, ttl_seconds=None):
        return f"https://example.com/storage/{object_key}"


class FakeConsolidatedDocumentService:
    def __init__(self):
        self.storage_service = FakeStorageService()

    def generate_for_case(self, *, phone, case_id, include_signed_url=True):
        return {
            "document_id": "DOC-1",
            "object_key": "docs/rendicion.pdf",
            "signed_url": "https://example.com/rendicion.pdf",
        }


class FakeDocusignService:
    enabled = False

    def create_envelope_from_remote_pdf(
        self,
        *,
        signer_name,
        signer_email,
        document_name,
        document_url,
        client_user_id,
    ):
        return {"envelopeId": "ENV-1", "statusDateTime": "2026-04-17T12:00:00Z"}

    def create_recipient_view(
        self,
        *,
        envelope_id,
        signer_name,
        signer_email,
        client_user_id,
        return_url,
    ):
        return "https://example.com/sign/ENV-1"


class FakeWhatsAppService:
    def __init__(self):
        self.sent_documents = []
        self.sent_messages = []
        self.sent_buttons = []
        self.sent_lists = []

    def send_outbound_document(self, phone, signed_url, filename=None, caption=None):
        self.sent_documents.append(
            {
                "phone": phone,
                "signed_url": signed_url,
                "filename": filename,
                "caption": caption,
            }
        )
        return {"id": "doc-msg-1"}

    def send_outbound_text(self, phone, message, reply_to_message_id=None):
        self.sent_messages.append(
            {
                "phone": phone,
                "message": message,
                "reply_to_message_id": reply_to_message_id,
            }
        )
        return {"id": "msg-1"}

    def send_outbound_buttons(self, phone, *, body, buttons, reply_to_message_id=None):
        self.sent_buttons.append(
            {
                "phone": phone,
                "body": body,
                "buttons": buttons,
                "reply_to_message_id": reply_to_message_id,
            }
        )
        return {"id": "btn-msg-1"}

    def send_outbound_list(self, phone, *, body, button_text, items, reply_to_message_id=None):
        self.sent_lists.append(
            {
                "phone": phone,
                "body": body,
                "button_text": button_text,
                "items": items,
                "reply_to_message_id": reply_to_message_id,
            }
        )
        return {"id": "list-msg-1"}


class FakeSheetsService:
    def __init__(self):
        self.case_row = {
            "case_id": "CASE-1",
            "phone": "+56911111111",
            "employee_phone": "+56911111111",
            "company_id": "acme",
            "status": "active",
            "closure_method": "simple",
            "rendicion_status": "pending_user_confirmation",
            "opened_at": "2026-04-16",
            "due_date": "2026-04-18",
            "fondos_entregados": 100000,
            "updated_at": "2026-04-16T10:00:00+00:00",
        }
        self.document_row = {
            "document_id": "DOC-1",
            "phone": "+56911111111",
            "case_id": "CASE-1",
            "signature_status": "pending",
        }
        self.expenses = [
            {
                "expense_id": "EXP-1",
                "phone": "+56911111111",
                "case_id": "CASE-1",
                "status": "approved",
                "total_clp": 110300,
            }
        ]
        self.conversation = {
            "phone": "+56911111111",
            "state": "WAIT_RECEIPT",
            "current_step": "",
            "context_json": {},
            "updated_at": "2026-04-16T10:00:00+00:00",
        }
        self.employee_row = {
            "phone": "+56911111111",
            "first_name": "Javier",
            "name": "Javier Calderon",
            "email": "javier@example.com",
            "company_id": "acme",
            "bank_name": "Banco Chile",
            "account_type": "Cuenta Vista",
            "account_number": "99887766",
            "account_holder": "Javier Calderon",
            "account_holder_rut": "12.345.678-9",
        }
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
        if self.case_row["case_id"] == case_id:
            return dict(self.case_row)
        return None

    def update_expense_case(self, case_id, payload):
        if self.case_row["case_id"] != case_id:
            return None
        self.case_row = {**self.case_row, **payload}
        return dict(self.case_row)

    def update_expense_case_document(self, document_id, payload):
        if self.document_row["document_id"] != document_id:
            return None
        self.document_row = {**self.document_row, **payload}
        return dict(self.document_row)

    def get_latest_expense_case_document_by_phone_case(self, phone, case_id):
        if self.document_row["phone"] == phone and self.document_row["case_id"] == case_id:
            return dict(self.document_row)
        return None

    def list_expense_cases(self):
        return [dict(self.case_row)]

    def list_active_expense_cases(self):
        if self.case_row.get("status") == "active":
            return [dict(self.case_row)]
        return []

    def list_expenses(self):
        return [dict(item) for item in self.expenses]

    def create_expense(self, expense_data):
        self.expenses.append(dict(expense_data))
        return dict(expense_data)

    def get_conversation(self, phone):
        if phone == self.case_row["phone"]:
            return dict(self.conversation)
        return None

    def list_conversations(self):
        return [dict(self.conversation)]

    def update_conversation(self, phone, payload):
        self.conversation = {
            "phone": phone,
            "state": payload.get("state", self.conversation.get("state", "WAIT_RECEIPT")),
            "current_step": payload.get("current_step", self.conversation.get("current_step", "")),
            "context_json": payload.get("context_json", self.conversation.get("context_json", {})),
            "updated_at": payload.get("updated_at", self.conversation.get("updated_at", "")),
        }
        return dict(self.conversation)

    def get_active_expense_case_by_phone(self, phone):
        if phone == self.case_row["phone"] and self.case_row.get("status") == "active":
            return dict(self.case_row)
        return None

    def get_employee_by_phone(self, phone):
        if phone == self.employee_row["phone"]:
            return dict(self.employee_row)
        return None

    def get_employee_any_by_phone(self, phone):
        return self.get_employee_by_phone(phone)

    def list_companies(self):
        return [dict(item) for item in self.companies]


class SchedulerSimpleConfirmationTests(unittest.TestCase):
    def build_service(self):
        return SchedulerService(
            settings=Settings(),
            sheets_service=FakeSheetsService(),
            whatsapp_service=FakeWhatsAppService(),
            consolidated_document_service=FakeConsolidatedDocumentService(),
            docusign_service=FakeDocusignService(),
        )

    def test_simple_closure_package_requires_whatsapp_confirmation(self):
        service = self.build_service()

        message = service._deliver_submission_closure_package(
            phone="+56911111111",
            case_id="CASE-1",
        )

        self.assertEqual(message, "")
        self.assertEqual(len(service.whatsapp_service.sent_documents), 1)
        self.assertEqual(len(service.whatsapp_service.sent_buttons), 1)
        self.assertEqual(len(service.whatsapp_service.sent_lists), 0)
        self.assertIn("elige una opción", service.whatsapp_service.sent_buttons[0]["body"])
        self.assertEqual(
            service.whatsapp_service.sent_buttons[0]["buttons"][0]["id"],
            "simple_confirmation_yes_confirm_consolidated",
        )
        self.assertEqual(service.whatsapp_service.sent_buttons[0]["reply_to_message_id"], "doc-msg-1")
        self.assertEqual(
            service.sheets_service.case_row["rendicion_status"],
            "pending_user_confirmation",
        )
        self.assertEqual(
            service.sheets_service.case_row["user_confirmation_status"],
            "pending_simple_confirmation",
        )
        self.assertEqual(
            service.sheets_service.document_row["signature_status"],
            "pending",
        )

    def test_simple_confirmation_yes_company_owes_employee_reports_deposit(self):
        # fondos_entregados=100000, total_clp=110300 → net=-10300 → empresa le debe al empleado
        service = self.build_service()

        reply = service.handle_simple_document_confirmation_user_response(
            phone="+56911111111",
            message="si",
        )

        self.assertIsInstance(reply, list)
        self.assertEqual(len(reply), 2)
        self.assertIn("Te vamos a depositar", reply[0])
        self.assertIn("Banco Chile", reply[1])
        self.assertIn("Javier Calderon", reply[1])
        self.assertNotIn("comprobante", reply[1])
        self.assertEqual(len(service.whatsapp_service.sent_messages), 0)
        self.assertEqual(
            service.sheets_service.case_row["rendicion_status"],
            "approved",
        )
        self.assertEqual(
            service.sheets_service.case_row["user_confirmation_status"],
            "confirmed_simple",
        )
        self.assertEqual(
            service.sheets_service.document_row["signature_status"],
            "completed",
        )
        self.assertEqual(
            service.sheets_service.case_row["settlement_direction"],
            "company_owes_employee",
        )
        self.assertEqual(
            service.sheets_service.case_row["settlement_status"],
            "pending_company_payment",
        )
        self.assertEqual(
            service.sheets_service.case_row["settlement_amount_clp"],
            10300.0,
        )

    def test_simple_confirmation_yes_employee_owes_company_reports_company_bank_details(self):
        # fondos_entregados > total_clp → empleado debe devolver el exceso
        service = self.build_service()
        service.sheets_service.case_row["fondos_entregados"] = 120000
        service.sheets_service.expenses[0]["total_clp"] = 110300

        reply = service.handle_simple_document_confirmation_user_response(
            phone="+56911111111",
            message="si",
        )

        self.assertIsInstance(reply, list)
        self.assertEqual(len(reply), 2)
        self.assertIn("Debes depositar", reply[0])
        self.assertIn("Datos bancarios de ACME", reply[1])
        self.assertIn("comprobante", reply[1])
        self.assertEqual(
            service.sheets_service.case_row["settlement_direction"],
            "employee_owes_company",
        )
        self.assertEqual(
            service.sheets_service.case_row["settlement_status"],
            "pending_employee_payment_proof",
        )
        self.assertEqual(
            service.sheets_service.case_row["settlement_amount_clp"],
            9700.0,
        )

    def test_docusign_closure_package_sends_pdf_link_and_closure_message(self):
        service = self.build_service()
        service.docusign_service.enabled = True
        service.sheets_service.case_row["closure_method"] = "docusign"

        message = service._deliver_submission_closure_package(
            phone="+56911111111",
            case_id="CASE-1",
        )

        self.assertEqual(message, "")
        self.assertEqual(len(service.whatsapp_service.sent_documents), 1)
        self.assertEqual(len(service.whatsapp_service.sent_messages), 2)
        self.assertTrue(service.whatsapp_service.sent_messages[0]["message"].endswith("/r/sign/DOC-1"))
        self.assertIn("Rendición cerrada", service.whatsapp_service.sent_messages[1]["message"])
        self.assertIn("Abre el enlace para firmar", service.whatsapp_service.sent_messages[1]["message"])

    def test_simple_confirmation_no_keeps_pending_user_confirmation(self):
        service = self.build_service()

        reply = service.handle_simple_document_confirmation_user_response(
            phone="+56911111111",
            message="simple_confirmation_no_review_company",
        )

        self.assertIn("sin confirmación final", reply)
        self.assertEqual(
            service.sheets_service.case_row["rendicion_status"],
            "pending_user_confirmation",
        )
        self.assertEqual(
            service.sheets_service.case_row["user_confirmation_status"],
            "rejected_simple",
        )
        self.assertEqual(
            service.sheets_service.document_row["signature_status"],
            "declined",
        )

    def test_simple_confirmation_accepts_quick_yes_variant(self):
        service = self.build_service()

        reply = service.handle_simple_document_confirmation_user_response(
            phone="+56911111111",
            message="perfecto",
        )

        self.assertIsInstance(reply, list)
        self.assertEqual(service.sheets_service.case_row["user_confirmation_status"], "confirmed_simple")
        self.assertEqual(service.sheets_service.document_row["signature_status"], "completed")

    def test_submission_reminder_skips_closed_rendicion_cases(self):
        service = self.build_service()
        service.sheets_service.case_row["rendicion_status"] = "closed"

        report = service.run_submission_reminders(
            dry_run=True,
            now_utc=datetime(2026, 4, 17, 12, 5, tzinfo=timezone.utc),
        )

        reminder_items = [item for item in report["items"] if item.get("item_type") == "reminder"]
        self.assertEqual(len(reminder_items), 1)
        self.assertEqual(reminder_items[0]["outcome"], "skipped_non_open_case")

    def test_submission_reminder_skips_cases_with_daily_reminders_disabled(self):
        service = self.build_service()
        service.sheets_service.case_row["rendicion_status"] = "open"
        service.sheets_service.case_row["daily_reminders_enabled"] = False

        report = service.run_submission_reminders(
            dry_run=True,
            now_utc=datetime(2026, 4, 17, 12, 5, tzinfo=timezone.utc),
        )

        reminder_items = [item for item in report["items"] if item.get("item_type") == "reminder"]
        self.assertEqual(len(reminder_items), 1)
        self.assertEqual(reminder_items[0]["outcome"], "skipped_daily_reminders_disabled")
        self.assertEqual(service.whatsapp_service.sent_messages, [])

    def test_evening_submission_reminder_sends_daily_summary(self):
        service = self.build_service()
        service.sheets_service.case_row["rendicion_status"] = "open"
        service.sheets_service.case_row["context_label"] = "Viña del Mar"
        service.sheets_service.case_row["fondos_entregados"] = 100000
        service.sheets_service.expenses = [
            {
                "expense_id": "EXP-1",
                "phone": "+56911111111",
                "case_id": "CASE-1",
                "date": "2026-04-17",
                "status": "approved",
                "total_clp": 30000,
            },
            {
                "expense_id": "EXP-2",
                "phone": "+56911111111",
                "case_id": "CASE-1",
                "date": "2026-04-17",
                "status": "pending_review",
                "total_clp": 12000,
            },
            {
                "expense_id": "EXP-3",
                "phone": "+56911111111",
                "case_id": "CASE-1",
                "date": "2026-04-16",
                "status": "approved",
                "total_clp": 5000,
            },
        ]

        report = service.run_submission_reminders(
            dry_run=False,
            now_utc=datetime(2026, 4, 18, 0, 5, tzinfo=timezone.utc),
        )

        reminder_items = [item for item in report["items"] if item.get("item_type") == "reminder"]
        self.assertEqual(reminder_items[0]["outcome"], "sent")
        self.assertEqual(reminder_items[0]["slot"], "evening_2000")
        message = service.whatsapp_service.sent_messages[-1]["message"]
        self.assertIn("Cierre del día (Viña del Mar)", message)
        self.assertIn("Documentos registrados hoy: 2", message)
        self.assertIn("Fondos entregados: $100.000 CLP", message)
        self.assertIn("Rendido aprobado: $35.000 CLP", message)
        self.assertIn("Pendiente de revisión: $12.000 CLP", message)
        self.assertIn("Saldo restante: $65.000 CLP", message)

    def test_needs_info_reminder_is_sent_before_timeout(self):
        service = self.build_service()
        service.sheets_service.conversation = {
            "phone": "+56911111111",
            "state": "NEEDS_INFO",
            "current_step": "currency",
            "context_json": {
                "draft_expense": {
                    "case_id": "CASE-1",
                    "merchant": "Hotel",
                    "total": 12000,
                },
                "missing_fields": ["currency"],
                "last_question": "currency",
            },
            "updated_at": "2026-04-17T08:00:00+00:00",
        }

        report = service.run_submission_reminders(
            dry_run=False,
            now_utc=datetime(2026, 4, 17, 12, 30, tzinfo=timezone.utc),
        )

        needs_info_items = [
            item for item in report["items"] if item.get("item_type") == "needs_info_timeout"
        ]
        self.assertEqual(needs_info_items[-1]["outcome"], "sent_needs_info_reminder")
        self.assertEqual(report["needs_info_reminder_sent_count"], 1)
        self.assertIn(
            "Tienes un gasto pendiente de completar",
            service.whatsapp_service.sent_messages[-1]["message"],
        )
        self.assertEqual(service.sheets_service.conversation["state"], "NEEDS_INFO")
        self.assertIn(
            "reminder_sent_at_utc",
            service.sheets_service.conversation["context_json"]["needs_info_timeout"],
        )

    def test_needs_info_timeout_saves_draft_for_review_and_resets_conversation(self):
        service = self.build_service()
        service.sheets_service.expenses = []
        service.sheets_service.conversation = {
            "phone": "+56911111111",
            "state": "NEEDS_INFO",
            "current_step": "currency",
            "context_json": {
                "draft_expense": {
                    "case_id": "CASE-1",
                    "merchant": "Hotel",
                    "date": "2026-04-17",
                    "total": 12000,
                    "source_message_id": "wamid.1",
                },
                "missing_fields": ["currency"],
                "last_question": "currency",
                "message_log": [{"id": "msg-1", "speaker": "person", "text": "foto"}],
            },
            "updated_at": "2026-04-17T08:00:00+00:00",
        }

        report = service.run_submission_reminders(
            dry_run=False,
            now_utc=datetime(2026, 4, 17, 14, 5, tzinfo=timezone.utc),
        )

        needs_info_items = [
            item for item in report["items"] if item.get("item_type") == "needs_info_timeout"
        ]
        self.assertEqual(needs_info_items[-1]["outcome"], "needs_info_timeout")
        self.assertEqual(report["needs_info_timeout_count"], 1)
        self.assertEqual(service.sheets_service.conversation["state"], "WAIT_RECEIPT")
        self.assertEqual(service.sheets_service.conversation["current_step"], "")
        self.assertEqual(len(service.sheets_service.expenses), 1)
        saved = service.sheets_service.expenses[0]
        self.assertEqual(saved["status"], "pending_review")
        self.assertEqual(saved["review_status"], "needs_info_timeout")
        self.assertEqual(saved["review_reason"], "needs_info_timeout:currency")
        self.assertEqual(saved["case_id"], "CASE-1")
        self.assertIn(
            "pendiente de revisión",
            service.whatsapp_service.sent_messages[-1]["message"],
        )

    def test_submission_start_intro_uses_employee_name_in_greeting(self):
        service = self.build_service()

        messages = service._build_submission_start_intro_messages(
            expense_case=service.sheets_service.case_row
        )

        self.assertEqual(len(messages), 2)
        self.assertIn("Hola, Javier.", messages[0])
        self.assertEqual(
            messages[1],
            "Puedes enviarme una o varias boletas, facturas o comprobantes por este chat.",
        )


if __name__ == "__main__":
    unittest.main()
