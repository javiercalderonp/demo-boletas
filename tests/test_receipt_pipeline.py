import asyncio
import hashlib
import hmac
import os
import unittest
from unittest.mock import patch

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ""
os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = ""
os.environ["GCS_BUCKET_NAME"] = ""

from app.main import (
    _build_initial_wait_receipt_reply,
    _debounced_send_receipt_batch_notice,
    _extract_media_entries,
    _is_duplicate_inbound_message,
    _log_inbound_media_message,
    _maybe_handle_settlement_payment_proof,
    _mark_inbound_message_processed,
    _handle_media_message,
    _handle_case_selection_response,
    _list_active_cases_for_phone,
    _process_media_message_async,
    _prompt_for_expense_case_selection,
    _reset_receipt_processing_state,
    _safe_send_outbound_response,
    _send_single_outbound_response,
    _stamp_media_entries,
    _sync_manual_cost_center_to_case,
)
from app.config import Settings
from services.conversation_service import ConversationService
from services.expense_service import ExpenseService
from services.llm_service import LLMService
from services.ocr_service import OCRService
from services.whatsapp_service import MetaAccessTokenExpiredError, WhatsAppService


class FakeSheets:
    def __init__(self, conversation):
        self.conversation = conversation
        self.updates = []
        self.expenses = []
        self.expense_case = {
            "case_id": "CASE-1",
            "employee_phone": "+56911111111",
            "status": "active",
            "cost_centers": ["Operaciones", "Ventas"],
        }
        self.expense_cases = [self.expense_case]
        self.employee = {"phone": "+56911111111", "first_name": "Javier", "name": "Javier Calderon"}
        self.case_documents = []

    def get_conversation(self, phone):
        return {
            "phone": phone,
            "state": self.conversation.get("state", "WAIT_RECEIPT"),
            "current_step": self.conversation.get("current_step", ""),
            "context_json": dict(self.conversation.get("context_json", {})),
        }

    def update_conversation(self, phone, payload):
        self.conversation = {
            "phone": phone,
            "state": payload.get("state", self.conversation.get("state", "WAIT_RECEIPT")),
            "current_step": payload.get("current_step", self.conversation.get("current_step", "")),
            "context_json": dict(payload.get("context_json", self.conversation.get("context_json", {}))),
        }
        self.updates.append(self.conversation)
        return self.conversation

    def create_expense(self, payload):
        self.expenses.append(dict(payload))
        return dict(payload)

    def get_expense_case_by_id(self, case_id):
        for expense_case in self.expense_cases:
            if case_id == expense_case.get("case_id"):
                return dict(expense_case)
        return None

    def update_expense_case(self, case_id, payload):
        for index, expense_case in enumerate(self.expense_cases):
            if case_id != expense_case.get("case_id"):
                continue
            expense_case.update(dict(payload))
            self.expense_cases[index] = expense_case
            if self.expense_case.get("case_id") == case_id:
                self.expense_case = expense_case
            return dict(expense_case)
        return None

    def list_expense_cases(self):
        return [dict(item) for item in self.expense_cases]

    def list_active_expense_cases_by_phone(self, phone):
        return [
            dict(item)
            for item in self.expense_cases
            if item.get("employee_phone", item.get("phone")) == phone
            and str(item.get("status", "")).strip().lower() == "active"
        ]

    def create_expense_case_document(self, payload):
        self.case_documents.append(dict(payload))
        return dict(payload)

    def get_employee_by_phone(self, phone):
        if phone == self.employee.get("phone"):
            return dict(self.employee)
        return None


class FakeConversationService:
    def default_context(self):
        return {
            "draft_expense": {},
            "missing_fields": [],
            "last_question": None,
            "scheduler": {"sent_reminders": {}},
            "trip_closure": {},
        }

    def ensure_conversation(self, conversation):
        if not conversation:
            return {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": self.default_context(),
            }
        context = dict(conversation.get("context_json", {}))
        merged = self.default_context()
        merged.update(context)
        conversation["context_json"] = merged
        conversation.setdefault("state", "WAIT_RECEIPT")
        conversation.setdefault("current_step", "")
        return conversation


class FakeContainer:
    def __init__(self, conversation):
        self.sheets = FakeSheets(conversation)
        self.conversation = FakeConversationService()
        self.whatsapp = type("WhatsApp", (), {"send_outbound_text": lambda *args, **kwargs: None})()


class FakeWhatsAppRecorder:
    def __init__(self):
        self.sent_texts = []
        self.sent_buttons = []
        self.sent_lists = []

    def send_outbound_text(self, phone, message, reply_to_message_id=None):
        self.sent_texts.append((phone, message, reply_to_message_id))
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
        return {"id": "btn-1"}

    def send_outbound_list(self, phone, *, body, button_text, items, reply_to_message_id=None):
        self.sent_lists.append((phone, body, button_text, items, reply_to_message_id))
        return {"id": "list-1"}


class FakeOCR:
    def extract_receipt_data(self, media_url, media_content_type=None):
        return {
            "document_type": "boleta",
            "is_document": True,
            "merchant": "Starbucks",
            "date": "2026-03-31",
            "total": 4500.0,
            "currency": "CLP",
            "country": "Chile",
            "category": "Meals",
            "ocr_text": "STARBUCKS COFFEE SANTIAGO RUT 76.123.456-7 TOTAL $4.500",
        }


class FakeTravel:
    def get_active_trip_for_phone(self, phone):
        return {"trip_id": "TRIP-123", "country": "Chile"}


class FakeNoActiveTravel:
    def get_active_trip_for_phone(self, phone):
        return None


class FakeExpense:
    def __init__(self, general_answer=None):
        self.general_answer = general_answer
        self.llm_service = None

    def build_summary_message(self, draft_expense, include_text_actions=True):
        summary = (
            "Detecte este gasto:\n"
            f"Tipo de documento: {draft_expense.get('document_type')}\n"
            f"Merchant: {draft_expense.get('merchant')}\n"
            f"Fecha: {draft_expense.get('date')}\n"
            f"Total: {draft_expense.get('total')} {draft_expense.get('currency')}\n"
            f"Categoria: {draft_expense.get('category')}\n"
            f"Pais: {draft_expense.get('country')}"
        )
        if not include_text_actions:
            return summary
        return f"{summary}\n\n1. Confirmar\n2. Corregir\n3. Cancelar"

    def enrich_draft_expense(self, draft_expense):
        return dict(draft_expense)

    def find_missing_required_fields(self, draft_expense):
        required_fields = [
            "merchant",
            "date",
            "total",
            "currency",
            "country",
            "trip_id",
        ]
        missing = []
        for field in required_fields:
            value = draft_expense.get(field)
            if value is None or str(value).strip() == "":
                missing.append(field)
        return missing

    def compute_draft_review(self, phone, draft_expense):
        return {"review_score": 80, "review_flags": ["requires_confirmation"]}

    def save_confirmed_expense(self, phone, draft_expense):
        saved = {
            "expense_id": "EXP-SAVED-1",
            "phone": phone,
            "case_id": draft_expense.get("case_id", draft_expense.get("trip_id", "")),
            "status": "pending_approval",
            "review_score": 80,
            "review_flags": ["requires_confirmation"],
            **dict(draft_expense),
        }
        return self.sheets_service.create_expense(saved) if hasattr(self, "sheets_service") else saved

    def create_expense_for_review(self, *, phone, draft_expense, review_reason):
        return {
            "expense_id": "EXP-REVIEW-1",
            "phone": phone,
            "status": "pending_review",
            "review_reason": review_reason,
            **dict(draft_expense),
        }

    def answer_general_question(self, question, *, phone="", case_context_hint=False):
        return self.general_answer

    def answer_rendicion_question(self, *, phone="", question=""):
        return None

    def chat_whatsapp_conversational(self, message, *, phone="", message_log=None):
        return None

    def classify_message_intent(self, message):
        return "unknown"


class FakePerfectExpense(FakeExpense):
    def compute_draft_review(self, phone, draft_expense):
        return {"review_score": 95, "review_flags": []}

    def save_confirmed_expense(self, phone, draft_expense):
        saved = {
            "expense_id": "EXP-AUTO-1",
            "phone": phone,
            "case_id": draft_expense.get("case_id", draft_expense.get("trip_id", "")),
            "status": "pending_approval",
            "review_score": 95,
            "review_flags": [],
            **dict(draft_expense),
        }
        return self.sheets_service.create_expense(saved) if hasattr(self, "sheets_service") else saved


class FakeGeoLLM:
    def __init__(self, geo_result=None, category_result=None, merchant_result=None):
        self.geo_result = dict(geo_result or {})
        self.category_result = category_result
        self.merchant_result = merchant_result
        self.geo_calls = 0

    def infer_expense_merchant(self, draft_expense):
        return self.merchant_result

    def infer_expense_country_currency(self, draft_expense):
        self.geo_calls += 1
        return dict(self.geo_result)

    def classify_expense_category(self, draft_expense):
        return self.category_result


class ConversationDocumentTypeTests(unittest.TestCase):
    def test_accepts_professional_fee_receipt_as_document_type_answer(self):
        service = ConversationService(ExpenseService(sheets_service=FakeSheets({})))

        self.assertEqual(
            service._parse_document_type_value("boleta de honorarios"),
            "professional_fee_receipt",
        )
        self.assertEqual(service._parse_document_type_value("3"), "professional_fee_receipt")

    def test_professional_fee_receipt_with_no_category_goes_to_confirmation(self):
        service = ConversationService(ExpenseService(sheets_service=FakeSheets({})))

        result = service.process_ocr_result(
            phone="+56911111111",
            ocr_data={
                "document_type": "boleta_honorarios",
                "is_document": True,
                "merchant": "Rodrigo Salinas Producciones SPA",
                "date": "2024-05-12",
                "invoice_number": "1252",
                "currency": "CLP",
                "total": 362250,
                "gross_amount": 420000,
                "withholding_amount": 57750,
                "issuer_tax_id": "RUT: 18.765.432-1",
                "receiver_tax_id": "RUT: 77.123.456-1",
                "category": "",
                "country": "",
                "ocr_text": "BOLETA DE HONORARIOS ELECTRONICA RUT: 18.765.432-1 TOTAL LIQUIDO 362250",
            },
            expense_case={"case_id": "CASE-1", "country": "Chile"},
        )

        self.assertEqual(result["state"], "CONFIRM_SUMMARY")
        self.assertEqual(result["current_step"], "confirm_summary")
        self.assertEqual(result["context_json"]["missing_fields"], [])
        self.assertIsNone(result["context_json"]["last_question"])
        self.assertNotIn("¿Cuál es la categoría?", result["reply"])
        self.assertNotIn("Categoría:", result["reply"])
        self.assertNotIn("País:", result["reply"])

    def test_receipt_with_no_category_goes_to_confirmation(self):
        service = ConversationService(ExpenseService(sheets_service=FakeSheets({})))

        result = service.process_ocr_result(
            phone="+56911111111",
            ocr_data={
                "document_type": "boleta",
                "is_document": True,
                "merchant": "Comercio sin categoria",
                "date": "2024-05-12",
                "currency": "CLP",
                "total": 12500,
                "category": "",
                "country": "Chile",
            },
            expense_case={"case_id": "CASE-1", "country": "Chile"},
        )

        self.assertEqual(result["state"], "CONFIRM_SUMMARY")
        self.assertEqual(result["current_step"], "confirm_summary")
        self.assertEqual(result["context_json"]["missing_fields"], [])
        self.assertNotIn("¿Cuál es la categoría?", result["reply"])

    def test_cost_center_other_requests_manual_text(self):
        service = ConversationService(ExpenseService(sheets_service=FakeSheets({})))
        conversation = {
            "state": "CONFIRM_SUMMARY",
            "current_step": "cost_center",
            "context_json": {
                "draft_expense": {"cost_centers": ["Operaciones", "Ventas"]},
                "missing_fields": [],
                "last_question": "cost_center",
            },
        }

        other_result = service.handle_text_message(conversation, "Otra")

        self.assertEqual(other_result["state"], "CONFIRM_SUMMARY")
        self.assertEqual(other_result["current_step"], "cost_center")
        self.assertTrue(other_result["context_json"]["awaiting_manual_cost_center"])
        self.assertIn("manualmente", other_result["reply"])

        manual_result = service.handle_text_message(
            {
                "state": "CONFIRM_SUMMARY",
                "current_step": "cost_center",
                "context_json": other_result["context_json"],
            },
            "Marketing",
        )

        self.assertEqual(manual_result["state"], "DONE")
        self.assertEqual(manual_result["context_json"]["draft_expense"]["cost_center"], "Marketing")
        self.assertEqual(
            manual_result["context_json"]["draft_expense"]["cost_centers"],
            ["Operaciones", "Ventas", "Marketing"],
        )

    def test_cost_center_manual_text_adds_new_center_without_other_button(self):
        service = ConversationService(ExpenseService(sheets_service=FakeSheets({})))
        conversation = {
            "state": "CONFIRM_SUMMARY",
            "current_step": "cost_center",
            "context_json": {
                "draft_expense": {"cost_centers": ["Operaciones", "Ventas"]},
                "missing_fields": [],
                "last_question": "cost_center",
            },
        }

        result = service.handle_text_message(conversation, "Marketing")

        self.assertEqual(result["state"], "DONE")
        self.assertEqual(result["context_json"]["draft_expense"]["cost_center"], "Marketing")
        self.assertEqual(
            result["context_json"]["draft_expense"]["cost_centers"],
            ["Operaciones", "Ventas", "Marketing"],
        )

    def test_confirm_summary_saves_without_cost_center_prompt_when_case_has_no_centers(self):
        service = ConversationService(ExpenseService(sheets_service=FakeSheets({})))
        conversation = {
            "state": "CONFIRM_SUMMARY",
            "current_step": "confirm_summary",
            "context_json": {
                "draft_expense": {"case_id": "CASE-1", "cost_centers": []},
                "missing_fields": [],
                "last_question": None,
            },
        }

        result = service.handle_text_message(conversation, "1")

        self.assertEqual(result["state"], "DONE")
        self.assertEqual(result["current_step"], "")
        self.assertEqual(result["action"], "save_expense")
        self.assertNotIn("centro de costo", result["reply"].lower())

    def test_confirm_summary_accepts_quick_confirmation_variants(self):
        service = ConversationService(ExpenseService(sheets_service=FakeSheets({})))
        for message in ("dale", "listo", "va", "perfecto", "👍"):
            conversation = {
                "state": "CONFIRM_SUMMARY",
                "current_step": "confirm_summary",
                "context_json": {
                    "draft_expense": {"case_id": "CASE-1", "cost_centers": []},
                    "missing_fields": [],
                    "last_question": None,
                },
            }

            result = service.handle_text_message(conversation, message)

            self.assertEqual(result["state"], "DONE")
            self.assertEqual(result["action"], "save_expense")

    def test_cost_center_prompt_uses_all_centers_as_reply_buttons_up_to_three(self):
        container = FakeContainer(
            {
                "state": "CONFIRM_SUMMARY",
                "current_step": "cost_center",
                "context_json": {
                    "draft_expense": {
                        "cost_centers": ["Operaciones", "Ventas", "Finanzas"],
                    },
                    "missing_fields": [],
                    "last_question": "cost_center",
                },
            }
        )
        container.whatsapp = FakeWhatsAppRecorder()

        _send_single_outbound_response(container, "+56911111111", "placeholder")

        self.assertEqual(len(container.whatsapp.sent_lists), 0)
        self.assertEqual(len(container.whatsapp.sent_buttons), 1)
        self.assertIn("escríbelo para agregarlo al caso", container.whatsapp.sent_buttons[0]["body"])
        self.assertEqual(
            [button["title"] for button in container.whatsapp.sent_buttons[0]["buttons"]],
            ["Operaciones", "Ventas", "Finanzas"],
        )

    def test_cost_center_prompt_uses_list_when_more_than_three_centers(self):
        container = FakeContainer(
            {
                "state": "CONFIRM_SUMMARY",
                "current_step": "cost_center",
                "context_json": {
                    "draft_expense": {
                        "cost_centers": [
                            "Operaciones",
                            "Ventas",
                            "Finanzas",
                            "Marketing",
                            "TI",
                            "Legal",
                        ],
                    },
                    "missing_fields": [],
                    "last_question": "cost_center",
                },
            }
        )
        container.whatsapp = FakeWhatsAppRecorder()

        _send_single_outbound_response(container, "+56911111111", "placeholder")

        self.assertEqual(len(container.whatsapp.sent_buttons), 0)
        self.assertEqual(len(container.whatsapp.sent_lists), 1)
        _phone, body, button_text, items, _reply_to = container.whatsapp.sent_lists[0]
        self.assertIn("¿A qué centro de costo está dirigido este gasto?", body)
        self.assertIn("escríbelo para agregarlo al caso", body)
        self.assertEqual(button_text, "Ver opciones")
        self.assertEqual(
            [item["title"] for item in items],
            ["Operaciones", "Ventas", "Finanzas", "Marketing", "TI", "Legal"],
        )

    def test_cost_center_prompt_splits_large_center_lists_without_dropping_options(self):
        centers = [f"Centro {index}" for index in range(1, 12)]
        container = FakeContainer(
            {
                "state": "CONFIRM_SUMMARY",
                "current_step": "cost_center",
                "context_json": {
                    "draft_expense": {"cost_centers": centers},
                    "missing_fields": [],
                    "last_question": "cost_center",
                },
            }
        )
        container.whatsapp = FakeWhatsAppRecorder()

        _send_single_outbound_response(container, "+56911111111", "placeholder")

        sent_titles = [
            item["title"]
            for _phone, _body, _button_text, items, _reply_to in container.whatsapp.sent_lists
            for item in items
        ]
        self.assertEqual(len(container.whatsapp.sent_lists), 2)
        self.assertEqual(sent_titles, centers)

    def test_manual_cost_center_is_added_to_case_before_saving(self):
        container = FakeContainer({})
        _sync_manual_cost_center_to_case(
            container,
            {
                "case_id": "CASE-1",
                "cost_center": "Marketing",
            },
        )

        self.assertEqual(
            container.sheets.expense_case["cost_centers"],
            ["Operaciones", "Ventas", "Marketing"],
        )

    def test_settlement_payment_proof_is_saved_as_case_document(self):
        container = FakeContainer({"state": "WAIT_RECEIPT", "current_step": "", "context_json": {}})
        container.sheets.expense_case.update(
            {
                "rendicion_status": "approved",
                "settlement_direction": "employee_owes_company",
                "settlement_status": "pending_employee_payment_proof",
                "settlement_amount_clp": 9700,
            }
        )

        reply = _maybe_handle_settlement_payment_proof(
            container=container,
            phone="+56911111111",
            payload={"MediaFilename0": "deposito.pdf"},
            media_url="https://example.com/deposito.pdf",
            media_content_type="application/pdf",
            ocr_data={"is_document": True, "total": 9700, "date": "2026-04-20"},
            storage_result={"receipt_storage_provider": "gcs", "receipt_object_key": "receipts/proof.pdf"},
            inbound_message_id="wamid.payment",
        )

        self.assertIn("revisión financiera", reply)
        self.assertEqual(container.sheets.expenses, [])
        self.assertEqual(len(container.sheets.case_documents), 1)
        document = container.sheets.case_documents[0]
        self.assertEqual(document["document_type"], "settlement_payment_proof")
        self.assertEqual(document["status"], "payment_proof_under_review")
        self.assertEqual(document["object_key"], "receipts/proof.pdf")
        self.assertEqual(document["source_message_id"], "wamid.payment")
        self.assertEqual(
            container.sheets.expense_case["settlement_status"],
            "payment_proof_under_review",
        )
        self.assertEqual(
            container.sheets.expense_case["settlement_payment_proof_document_id"],
            document["document_id"],
        )

    def test_multiple_active_cases_prompt_for_case_selection(self):
        container = FakeContainer({"state": "WAIT_RECEIPT", "current_step": "", "context_json": {}})
        container.sheets.expense_cases = [
            {
                "case_id": "CASE-1",
                "employee_phone": "+56911111111",
                "status": "active",
                "context_label": "Viaje norte",
            },
            {
                "case_id": "CASE-2",
                "employee_phone": "+56911111111",
                "status": "active",
                "context_label": "Proyecto sur",
            },
        ]

        active_cases = _list_active_cases_for_phone(container, "+56911111111")
        reply = _prompt_for_expense_case_selection(
            container=container,
            phone="+56911111111",
            ocr_data={"is_document": True, "merchant": "Hotel", "total": 20000, "currency": "CLP"},
            active_cases=active_cases,
        )

        self.assertIn("más de una rendición activa", reply)
        self.assertIn("1. Viaje norte (CASE-1)", reply)
        self.assertIn("2. Proyecto sur (CASE-2)", reply)
        self.assertEqual(container.sheets.conversation["state"], "NEEDS_INFO")
        self.assertEqual(container.sheets.conversation["current_step"], "case_selection")
        pending = container.sheets.conversation["context_json"]["pending_case_selection"]
        self.assertEqual(pending["draft_expense"]["merchant"], "Hotel")
        self.assertEqual(pending["options"][1]["case_id"], "CASE-2")

    def test_case_selection_response_resumes_receipt_summary_with_selected_case(self):
        container = FakeContainer({"state": "WAIT_RECEIPT", "current_step": "", "context_json": {}})
        container.conversation = FakeConversationProcessor()
        container.sheets.expense_cases = [
            {
                "case_id": "CASE-1",
                "employee_phone": "+56911111111",
                "phone": "+56911111111",
                "status": "active",
                "context_label": "Viaje norte",
                "country": "Chile",
            },
            {
                "case_id": "CASE-2",
                "employee_phone": "+56911111111",
                "phone": "+56911111111",
                "status": "active",
                "context_label": "Proyecto sur",
                "country": "Chile",
            },
        ]
        _prompt_for_expense_case_selection(
            container=container,
            phone="+56911111111",
            ocr_data={
                "is_document": True,
                "merchant": "Hotel",
                "date": "2026-04-17",
                "total": 20000,
                "currency": "CLP",
                "country": "Chile",
                "category": "lodging",
            },
            active_cases=container.sheets.list_active_expense_cases_by_phone("+56911111111"),
        )

        reply = _handle_case_selection_response(
            container,
            "+56911111111",
            "2",
            container.sheets.get_conversation("+56911111111"),
        )

        self.assertIn("Proyecto sur (CASE-2)", reply)
        self.assertEqual(container.sheets.conversation["state"], "CONFIRM_SUMMARY")
        draft = container.sheets.conversation["context_json"]["draft_expense"]
        self.assertEqual(draft["case_id"], "CASE-2")
        self.assertEqual(draft["trip_id"], "CASE-2")

    def test_conversation_detects_english_and_replies_in_english(self):
        service = ConversationService(FakeExpense())
        conversation = service.ensure_conversation(None)

        result = service.handle_text_message(conversation, "hello, I need help", phone="+56911111111")

        self.assertEqual(result["context_json"]["language"], "en")
        self.assertIn("expense reporting assistant", result["reply"])
        self.assertIn("receipt", result["reply"])

    def test_conversation_detects_portuguese_and_replies_in_portuguese(self):
        service = ConversationService(FakeExpense())
        conversation = service.ensure_conversation(None)

        result = service.handle_text_message(conversation, "olá, preciso de ajuda", phone="+56911111111")

        self.assertEqual(result["context_json"]["language"], "pt")
        self.assertIn("prestação de contas", result["reply"])
        self.assertIn("comprovante", result["reply"])


class FakeConversationProcessor(FakeConversationService):
    def __init__(self):
        self.expense_service = FakeExpense()

    def process_ocr_result(self, phone, ocr_data, trip):
        draft = dict(ocr_data)
        if trip:
            draft.setdefault("trip_id", trip.get("trip_id"))
        return {
            "phone": phone,
            "state": "CONFIRM_SUMMARY",
            "current_step": "confirm_summary",
            "context_json": {
                "draft_expense": draft,
                "missing_fields": [],
                "last_question": None,
            },
            "reply": self.expense_service.build_summary_message(draft),
        }


class FakeContainerSuccess:
    def __init__(self):
        self.sheets = FakeSheets(
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": {
                    "scheduler": {"sent_reminders": {"trip-1": True}},
                    "trip_closure": {"status": "pending"},
                    "pending_receipts": [],
                },
            }
        )
        self.conversation = FakeConversationProcessor()
        self.ocr = FakeOCR()
        self.travel = FakeTravel()
        self.storage = type("Storage", (), {"enabled": False})()
        self.whatsapp = type("WhatsApp", (), {"provider": "meta"})()
        self.expense = FakeExpense()
        self.expense.sheets_service = self.sheets


class FakeContainerPerfectOCR(FakeContainerSuccess):
    def __init__(self):
        super().__init__()
        self.expense = FakePerfectExpense()
        self.expense.sheets_service = self.sheets


class FakeContainerNoActiveCase:
    def __init__(self):
        self.sheets = FakeSheets(
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": {
                    "pending_receipts": [],
                    "scheduler": {"sent_reminders": {}},
                    "trip_closure": {},
                },
            }
        )
        self.conversation = FakeConversationProcessor()
        self.ocr = FakeOCR()
        self.travel = FakeNoActiveTravel()
        self.storage = type("Storage", (), {"enabled": False})()
        self.whatsapp = type("WhatsApp", (), {"provider": "meta"})()
        self.expense = FakeExpense()


class FakeContainerWithWhatsApp:
    def __init__(self, whatsapp):
        self.whatsapp = whatsapp


class FakeOCRNoDocument:
    def extract_receipt_data(self, media_url, media_content_type=None):
        return {
            "document_type": None,
            "is_document": False,
            "merchant": None,
            "date": None,
            "total": None,
            "currency": None,
            "country": None,
            "category": None,
            "ocr_text": None,
        }


class FakeContainerNoDocument:
    def __init__(self):
        self.sheets = FakeSheets(
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": {
                    "pending_receipts": [],
                    "scheduler": {"sent_reminders": {}},
                    "trip_closure": {},
                },
            }
        )
        self.conversation = FakeConversationProcessor()
        self.ocr = FakeOCRNoDocument()
        self.travel = FakeTravel()
        self.storage = type("Storage", (), {"enabled": False})()
        self.whatsapp = type("WhatsApp", (), {"provider": "meta"})()
        self.expense = FakeExpense()


class ReceiptPipelineTests(unittest.TestCase):
    def test_stamp_media_entries_uses_event_message_id_when_attachment_has_none(self):
        entries = _stamp_media_entries(
            [
                {
                    "media_id": "media-1",
                    "media_url": "https://example.com/receipt.jpg",
                    "media_content_type": "image/jpeg",
                }
            ],
            message_id="wamid.meta-message",
        )

        self.assertEqual(entries[0]["message_id"], "wamid.meta-message")

    def test_extract_twilio_pdf_media_preserves_filename_and_document_type(self):
        entries = _extract_media_entries(
            {
                "NumMedia": "1",
                "MessageSid": "SM123",
                "MediaUrl0": "https://api.twilio.com/media/documento.pdf",
                "MediaContentType0": "application/pdf",
                "MediaFilename0": "factura.pdf",
            }
        )

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["media_content_type"], "application/pdf")
        self.assertEqual(entries[0]["filename"], "factura.pdf")
        self.assertEqual(entries[0]["message_type"], "document")

    def test_ocr_resolves_pdf_mime_from_content_type_or_url(self):
        service = OCRService(settings=Settings())

        self.assertEqual(
            service._resolve_mime_type(
                "https://example.com/media",
                "application/pdf",
                None,
            ),
            "application/pdf",
        )
        self.assertEqual(
            service._resolve_mime_type(
                "https://example.com/factura.pdf",
                "",
                None,
            ),
            "application/pdf",
        )

    def test_log_inbound_pdf_media_uses_document_url(self):
        container = FakeContainer({"state": "WAIT_RECEIPT", "current_step": "", "context_json": {}})

        _log_inbound_media_message(
            container,
            "+56911111111",
            [
                {
                    "media_url": "https://example.com/factura.pdf",
                    "media_content_type": "application/pdf",
                    "filename": "factura.pdf",
                    "message_id": "wamid.pdf",
                }
            ],
            caption="Factura proveedor",
            message_id="wamid.pdf",
        )

        message_log = container.sheets.conversation["context_json"]["message_log"]
        self.assertEqual(message_log[-1]["document_url"], "https://example.com/factura.pdf")
        self.assertEqual(message_log[-1]["filename"], "factura.pdf")
        self.assertNotIn("media_url", message_log[-1])
        self.assertEqual(message_log[-1]["attachments"][0]["document_url"], "https://example.com/factura.pdf")

    def test_initial_wait_receipt_reply_uses_employee_first_name(self):
        container = FakeContainer({"state": "WAIT_RECEIPT", "current_step": "", "context_json": {}})

        reply = _build_initial_wait_receipt_reply(container, "+56911111111")

        self.assertEqual(
            reply,
            "Hola, Javier. Envíame una foto de la boleta, factura o comprobante para procesar el gasto.",
        )

    def test_initial_wait_receipt_reply_falls_back_when_name_missing(self):
        container = FakeContainer({"state": "WAIT_RECEIPT", "current_step": "", "context_json": {}})
        container.sheets.employee = {"phone": "+56911111111", "first_name": "", "name": ""}

        reply = _build_initial_wait_receipt_reply(container, "+56911111111")

        self.assertEqual(
            reply,
            "Hola. Envíame una foto de la boleta, factura o comprobante para procesar el gasto.",
        )

    def test_wait_receipt_general_question_uses_less_repetitive_closing(self):
        service = ConversationService(
            expense_service=FakeExpense(
                general_answer=(
                    "Sí, puedes enviar varias boletas o comprobantes. "
                    "Si mandas más de uno, los iré procesando uno por uno por este chat."
                )
            )
        )
        conversation = {
            "state": "WAIT_RECEIPT",
            "current_step": "",
            "context_json": {
                "draft_expense": {},
                "missing_fields": [],
                "last_question": None,
            },
        }

        result = service.handle_text_message(conversation, "Puedo mandar mas de una boleta a la vez?")

        self.assertEqual(result["state"], "WAIT_RECEIPT")
        self.assertIn("Sí, puedes enviar varias boletas o comprobantes.", result["reply"])
        self.assertIn("Cuando quieras, envíame los comprobantes y los reviso.", result["reply"])
        self.assertNotIn("Si quieres registrar un gasto", result["reply"])

    def test_llm_service_recognizes_multiple_receipts_question(self):
        settings = Settings(
            openai_api_key="test-key",
            chat_assistant_enabled=True,
        )
        service = LLMService(settings=settings)

        answer = service.answer_general_question("Puedo mandar más de una boleta a la vez?")

        self.assertEqual(
            answer,
            "Sí, puedes enviar varias boletas o comprobantes. "
            "Si mandas más de uno, los iré procesando uno por uno por este chat.",
        )

    def test_cancel_confirmation_mentions_one_or_several_receipts(self):
        service = ConversationService(expense_service=FakeExpense())
        conversation = {
            "state": "CONFIRM_SUMMARY",
            "current_step": "confirm_summary",
            "context_json": {
                "draft_expense": {
                    "merchant": "Starbucks",
                    "date": "2026-03-31",
                    "total": 4500.0,
                    "currency": "CLP",
                    "category": "Meals",
                    "country": "Chile",
                },
                "missing_fields": [],
                "last_question": None,
            },
        }

        result = service.handle_text_message(conversation, "3")

        self.assertEqual(result["state"], "WAIT_RECEIPT")
        self.assertEqual(
            result["reply"],
            "Operación cancelada. Cuando quieras, envíame otro comprobante o varios.",
        )

    def test_currency_correction_accepts_eur_option(self):
        service = ConversationService(expense_service=FakeExpense())
        conversation = {
            "state": "NEEDS_INFO",
            "current_step": "currency",
            "context_json": {
                "draft_expense": {
                    "merchant": "Hotel",
                    "date": "2026-04-01",
                    "total": 1060.0,
                    "category": "Lodging",
                    "country": "Spain",
                    "trip_id": "TRIP-1",
                },
                "missing_fields": ["currency"],
                "last_question": "currency",
            },
        }

        result = service.handle_text_message(conversation, "5")

        self.assertEqual(result["state"], "CONFIRM_SUMMARY")
        self.assertEqual(result["context_json"]["draft_expense"]["currency"], "EUR")

    def test_expense_service_normalizes_invalid_euro_currency(self):
        service = ExpenseService(sheets_service=None, llm_service=None)

        draft = service.enrich_draft_expense(
            {
                "merchant": "Villa Contentezza",
                "date": "2024-07-26",
                "total": 1060.0,
                "currency": "Y?",
                "country": "Spain",
                "category": "Lodging",
                "trip_id": "TRIP-1",
                "ocr_text": "RECIBO TOTAL €1060,00 VILLA CONTENTEZZA",
            }
        )

        self.assertEqual(draft["currency"], "EUR")

    def test_expense_service_uses_receipt_text_geo_rules_before_llm(self):
        llm = FakeGeoLLM(geo_result={"country": "Peru", "currency": "PEN"})
        service = ExpenseService(sheets_service=None, llm_service=llm)

        draft = service.enrich_draft_expense(
            {
                "merchant": "Mistura del Peru",
                "date": "2026-04-27",
                "total": 12500.0,
                "currency": "",
                "country": "",
                "category": "Meals",
                "trip_id": "TRIP-1",
                "ocr_text": (
                    "MISTURA DEL PERU SPA\n"
                    "RUT 76.123.456-7\n"
                    "Av. Kennedy 9001, Las Condes, Santiago\n"
                    "TOTAL $12.500"
                ),
            }
        )

        self.assertEqual(draft["country"], "Chile")
        self.assertEqual(draft["currency"], "CLP")
        self.assertEqual(llm.geo_calls, 0)

    def test_expense_service_calls_geo_llm_when_text_rules_are_incomplete(self):
        llm = FakeGeoLLM(geo_result={"country": "Spain", "currency": "EUR"})
        service = ExpenseService(sheets_service=None, llm_service=llm)

        draft = service.enrich_draft_expense(
            {
                "merchant": "Hotel Central",
                "date": "2026-04-27",
                "total": 180.0,
                "currency": "",
                "country": "",
                "category": "Lodging",
                "trip_id": "TRIP-1",
                "ocr_text": "HOTEL CENTRAL TOTAL 180",
            }
        )

        self.assertEqual(draft["country"], "Spain")
        self.assertEqual(draft["currency"], "EUR")
        self.assertEqual(llm.geo_calls, 1)

    def test_processing_state_does_not_request_case_id(self):
        service = ConversationService(expense_service=FakeExpense())
        conversation = {
            "state": "PROCESSING",
            "current_step": "",
            "context_json": {
                "draft_expense": {},
                "missing_fields": [],
                "last_question": None,
            },
        }

        result = service.handle_text_message(
            conversation,
            "hola",
            phone="+56911111111",
        )

        self.assertEqual(result["state"], "PROCESSING")
        self.assertEqual(result["current_step"], "")
        self.assertNotIn("prefilled_case_id", result["context_json"])
        self.assertNotIn("identificador del caso", result["reply"].lower())

    def test_handle_media_message_rejects_receipt_when_no_active_case(self):
        container = FakeContainerNoActiveCase()

        with patch("app.main.logger.exception"), patch("app.main.logger.info"):
            reply = _handle_media_message(
                container,
                "+56933333333",
                {
                    "MediaUrl0": "https://example.com/receipt.jpg",
                    "MediaContentType0": "image/jpeg",
                    "InboundMessageId": "wamid.no-case",
                },
            )

        self.assertEqual(reply, "No tienes una rendición creada.")
        self.assertEqual(container.sheets.conversation["state"], "WAIT_RECEIPT")
        self.assertEqual(container.sheets.conversation["current_step"], "")
        self.assertEqual(container.sheets.expenses, [])

    def test_meta_interactive_list_reply_uses_list_id(self):
        service = WhatsAppService(settings=Settings())
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "from": "56911111111",
                                        "id": "wamid.list",
                                        "type": "interactive",
                                        "interactive": {
                                            "button_reply": {},
                                            "list_reply": {
                                                "id": "4",
                                                "title": "Moneda",
                                            },
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        events = service.parse_meta_webhook_messages(payload)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["body"], "4")

    def test_meta_document_pdf_message_is_media_entry(self):
        service = WhatsAppService(settings=Settings())
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "contacts": [{"profile": {"name": "Javier"}}],
                                "messages": [
                                    {
                                        "from": "56911111111",
                                        "id": "wamid.pdf",
                                        "type": "document",
                                        "document": {
                                            "id": "media-pdf-1",
                                            "mime_type": "application/pdf",
                                            "filename": "factura.pdf",
                                            "caption": "Factura proveedor",
                                        },
                                    }
                                ],
                            }
                        }
                    ]
                }
            ]
        }

        events = service.parse_meta_webhook_messages(payload)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["message_type"], "document")
        self.assertEqual(events[0]["body"], "Factura proveedor")
        self.assertEqual(events[0]["media_entries"][0]["media_id"], "media-pdf-1")
        self.assertEqual(events[0]["media_entries"][0]["media_content_type"], "application/pdf")
        self.assertEqual(events[0]["media_entries"][0]["filename"], "factura.pdf")
        self.assertEqual(events[0]["media_entries"][0]["message_type"], "document")

    def test_meta_delivery_failure_status_is_parsed_with_error_details(self):
        service = WhatsAppService(settings=Settings())
        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": "wamid.template",
                                        "recipient_id": "56911111111",
                                        "status": "failed",
                                        "timestamp": "1753398883",
                                        "errors": [
                                            {
                                                "code": 131049,
                                                "title": "Message not delivered",
                                                "message": "Message not delivered",
                                                "error_data": {
                                                    "details": "Meta chose not to deliver this marketing message."
                                                },
                                            }
                                        ],
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        statuses = service.parse_meta_webhook_statuses(payload)

        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0]["message_id"], "wamid.template")
        self.assertEqual(statuses[0]["phone"], "56911111111")
        self.assertEqual(statuses[0]["status"], "failed")
        self.assertEqual(statuses[0]["error_code"], 131049)
        self.assertIn("marketing", statuses[0]["error_details"])

    def test_meta_signature_validation_accepts_valid_sha256_signature(self):
        body = b'{"object":"whatsapp_business_account"}'
        app_secret = "test-app-secret"
        digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        service = WhatsAppService(
            settings=Settings(
                whatsapp_provider="meta",
                meta_validate_signature=True,
                meta_app_secret=app_secret,
            )
        )

        self.assertTrue(service.validate_meta_signature(body, f"sha256={digest}"))

    def test_meta_signature_validation_rejects_missing_or_invalid_signature(self):
        service = WhatsAppService(
            settings=Settings(
                whatsapp_provider="meta",
                meta_validate_signature=True,
                meta_app_secret="test-app-secret",
            )
        )

        self.assertFalse(service.validate_meta_signature(b"{}", None))
        self.assertFalse(service.validate_meta_signature(b"{}", "sha1=abc"))
        self.assertFalse(service.validate_meta_signature(b"{}", "sha256=invalid"))

    def test_meta_signature_validation_requires_app_secret_when_enabled(self):
        service = WhatsAppService(
            settings=Settings(
                whatsapp_provider="meta",
                meta_validate_signature=True,
                meta_app_secret="",
            )
        )

        self.assertFalse(service.validate_meta_signature(b"{}", "sha256=abc"))

    def test_meta_text_send_does_not_retry_when_access_token_expired(self):
        service = WhatsAppService(settings=Settings())

        with patch.object(
            service,
            "_send_outbound_text_meta",
            side_effect=MetaAccessTokenExpiredError("expired"),
        ) as mocked_send:
            with self.assertRaises(MetaAccessTokenExpiredError):
                service.send_outbound_text(
                    "+56911111111",
                    "Hola",
                    reply_to_message_id="wamid.reply",
                )

        self.assertEqual(mocked_send.call_count, 1)

    def test_meta_recipient_normalizes_phone_without_plus(self):
        service = WhatsAppService(settings=Settings())

        self.assertEqual(service._normalize_meta_recipient("56979956605"), "56979956605")
        self.assertEqual(service._normalize_meta_recipient("whatsapp:+56979956605"), "56979956605")

    def test_twilio_recipient_adds_plus_for_phone_without_plus(self):
        service = WhatsAppService(settings=Settings())

        self.assertEqual(
            service._normalize_twilio_whatsapp_address("56979956605"),
            "whatsapp:+56979956605",
        )
        self.assertEqual(
            service._normalize_twilio_whatsapp_address("whatsapp:+56979956605"),
            "whatsapp:+56979956605",
        )

    def test_meta_template_send_builds_hello_world_payload(self):
        settings = Settings(
            meta_access_token="token",
            meta_phone_number_id="phone-number-id",
        )
        service = WhatsAppService(settings=settings)

        with patch.object(
            service,
            "_meta_request_json",
            return_value={"messages": [{"id": "wamid.template"}]},
        ) as mocked_request:
            result = service.send_outbound_template(
                "56979956605",
                template_name="hello_world",
                language_code="en_US",
            )

        self.assertEqual(result["id"], "wamid.template")
        self.assertEqual(result["message_type"], "template")
        mocked_request.assert_called_once_with(
            method="POST",
            path="/phone-number-id/messages",
            payload={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": "56979956605",
                "type": "template",
                "template": {
                    "name": "hello_world",
                    "language": {"code": "en_US"},
                },
            },
        )

    def test_inbound_message_deduplication_marks_and_detects_duplicates(self):
        container = FakeContainer(
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": {},
            }
        )

        self.assertFalse(_is_duplicate_inbound_message(container, "+56911111111", "wamid.dup"))
        _mark_inbound_message_processed(container, "+56911111111", "wamid.dup")
        self.assertTrue(_is_duplicate_inbound_message(container, "+56911111111", "wamid.dup"))
        self.assertIn("wamid.dup", container.sheets.conversation["context_json"]["processed_message_ids"])

    def test_async_processing_failure_resets_conversation_and_notifies_user(self):
        container = FakeContainer(
            {
                "state": "PROCESSING",
                "current_step": "",
                "context_json": {
                    "active_receipt_message_id": "wamid.123",
                    "pending_receipts": [
                        {
                            "media_url": "https://example.com/next.jpg",
                            "queued_at": "2026-03-31T12:00:00Z",
                            "message_id": "wamid.next",
                        }
                    ],
                    "scheduler": {"sent_reminders": {"trip-1": True}},
                    "trip_closure": {"status": "pending"},
                },
            }
        )
        outbound_messages = []

        with patch("app.main._handle_media_message", side_effect=RuntimeError("boom")):
            with patch("app.main.logger.exception"):
                with patch(
                    "app.main._send_outbound_response",
                    side_effect=lambda _container, _phone, message: outbound_messages.append(message),
                ):
                    _process_media_message_async(
                        container,
                        "+56911111111",
                        {"InboundMessageId": "wamid.inbound"},
                    )

        self.assertEqual(container.sheets.conversation["state"], "WAIT_RECEIPT")
        self.assertEqual(container.sheets.conversation["current_step"], "")
        self.assertNotIn(
            "active_receipt_message_id",
            container.sheets.conversation["context_json"],
        )
        self.assertEqual(
            container.sheets.conversation["context_json"]["pending_receipts"],
            [
                {
                    "media_url": "https://example.com/next.jpg",
                    "queued_at": "2026-03-31T12:00:00Z",
                    "message_id": "wamid.next",
                }
            ],
        )
        self.assertEqual(
            container.sheets.conversation["context_json"]["scheduler"],
            {"sent_reminders": {"trip-1": True}},
        )
        self.assertEqual(
            container.sheets.conversation["context_json"]["trip_closure"],
            {"status": "pending"},
        )
        self.assertTrue(outbound_messages)
        self.assertIn("No pude procesar tu comprobante", outbound_messages[0])

    def test_async_processing_advances_to_next_pending_receipt_after_review_route(self):
        container = FakeContainer(
            {
                "state": "PROCESSING",
                "current_step": "",
                "context_json": {
                    "pending_receipts": [
                        {
                            "media_url": "https://example.com/next.jpg",
                            "queued_at": "2026-03-31T12:00:00Z",
                            "message_id": "wamid.next",
                        }
                    ],
                    "scheduler": {"sent_reminders": {}},
                    "trip_closure": {},
                },
            }
        )
        calls = []
        outbound_messages = []

        def fake_handle_media(_container, _phone, payload):
            calls.append(payload.get("InboundMessageId"))
            if len(calls) == 1:
                container.sheets.update_conversation(
                    _phone,
                    {
                        "state": "WAIT_RECEIPT",
                        "current_step": "",
                        "context_json": container.sheets.conversation["context_json"],
                    },
                )
                return "No encontré un caso activo asociado a tu usuario. Un operador deberá revisarlo."
            container.sheets.update_conversation(
                _phone,
                {
                    "state": "CONFIRM_SUMMARY",
                    "current_step": "confirm_summary",
                    "context_json": container.sheets.conversation["context_json"],
                },
            )
            return "Detecte este gasto"

        with patch("app.main._handle_media_message", side_effect=fake_handle_media):
            with patch(
                "app.main._send_outbound_response",
                side_effect=lambda _container, _phone, message: outbound_messages.append(message),
            ):
                _process_media_message_async(
                    container,
                    "+56911111111",
                    {"InboundMessageId": "wamid.first"},
                )

        self.assertEqual(calls, ["wamid.first", "wamid.next"])
        self.assertGreaterEqual(len(outbound_messages), 2)
        self.assertIn("Un operador deberá revisarlo", outbound_messages[0])
        self.assertIn("Detecte este gasto", outbound_messages[1])
        self.assertEqual(container.sheets.conversation["state"], "CONFIRM_SUMMARY")

    def test_handle_media_message_reaches_confirm_summary_on_success(self):
        container = FakeContainerSuccess()

        with patch("app.main.logger.exception"):
            with patch(
                "app.main.logger.info"
            ):
                reply = _handle_media_message(
                    container,
                    "+56933333333",
                    {
                        "MediaUrl0": "https://example.com/receipt.jpg",
                        "MediaContentType0": "image/jpeg",
                        "InboundMessageId": "wamid.success",
                    },
                )

        self.assertIn("Detecte este gasto", reply)
        self.assertIn("Tipo de documento: boleta", reply)
        self.assertEqual(container.sheets.conversation["state"], "CONFIRM_SUMMARY")
        self.assertEqual(container.sheets.conversation["current_step"], "confirm_summary")
        draft = container.sheets.conversation["context_json"]["draft_expense"]
        self.assertEqual(draft["document_type"], "boleta")
        self.assertEqual(draft["merchant"], "Starbucks")
        self.assertEqual(draft["trip_id"], "TRIP-123")
        self.assertEqual(draft["category"], "Meals")
        self.assertEqual(
            container.sheets.conversation["context_json"]["scheduler"],
            {"sent_reminders": {"trip-1": True}},
        )
        self.assertEqual(
            container.sheets.conversation["context_json"]["trip_closure"],
            {"status": "pending"},
        )

    def test_handle_media_message_auto_saves_when_review_is_perfect(self):
        container = FakeContainerPerfectOCR()

        with patch("app.main.logger.exception"), patch("app.main.logger.info"):
            reply = _handle_media_message(
                container,
                "+56933333333",
                {
                    "MediaUrl0": "https://example.com/receipt.jpg",
                    "MediaContentType0": "image/jpeg",
                    "InboundMessageId": "wamid.auto",
                },
            )

        self.assertIn("Guardé tu gasto: Starbucks", reply)
        self.assertIn("Si algo está mal, escribe 'corregir'", reply)
        self.assertEqual(container.sheets.conversation["state"], "WAIT_RECEIPT")
        self.assertEqual(container.sheets.conversation["current_step"], "")
        self.assertEqual(len(container.sheets.expenses), 1)
        self.assertEqual(container.sheets.expenses[0]["expense_id"], "EXP-AUTO-1")
        self.assertEqual(container.sheets.expenses[0]["source_message_id"], "wamid.auto")
        self.assertNotIn("active_receipt_message_id", container.sheets.conversation["context_json"])

    def test_handle_media_message_rejects_non_document_images(self):
        container = FakeContainerNoDocument()

        with patch("app.main.logger.exception"), patch("app.main.logger.info"):
            reply = _handle_media_message(
                container,
                "+56933333333",
                {
                    "MediaUrl0": "https://example.com/perro.jpg",
                    "MediaContentType0": "image/jpeg",
                    "InboundMessageId": "wamid.no-document",
                },
            )

        self.assertIn("No se identificaron boletas/documentos en esa imagen", reply)
        self.assertEqual(container.sheets.conversation["state"], "WAIT_RECEIPT")
        self.assertEqual(container.sheets.conversation["current_step"], "")

    def test_reset_receipt_processing_state_preserves_sticky_context(self):
        container = FakeContainer(
            {
                "state": "PROCESSING",
                "current_step": "confirm_summary",
                "context_json": {
                    "active_receipt_message_id": "wamid.999",
                    "pending_receipts": [{"media_url": "https://example.com/a.jpg", "queued_at": "2026-03-31T13:00:00Z"}],
                    "receipt_batch_notice": {"token": "RCPT-1"},
                    "scheduler": {"sent_reminders": {"trip-2": True}},
                    "trip_closure": {"status": "waiting"},
                    "draft_expense": {"merchant": "Store"},
                    "missing_fields": ["category"],
                    "last_question": "category",
                },
            }
        )

        _reset_receipt_processing_state(
            container,
            "+56922222222",
            reason="test_case",
        )

        context = container.sheets.conversation["context_json"]
        self.assertEqual(container.sheets.conversation["state"], "WAIT_RECEIPT")
        self.assertEqual(context["draft_expense"], {})
        self.assertEqual(context["missing_fields"], [])
        self.assertIsNone(context["last_question"])
        self.assertEqual(
            context["pending_receipts"],
            [{"media_url": "https://example.com/a.jpg", "queued_at": "2026-03-31T13:00:00Z"}],
        )
        self.assertEqual(context["receipt_batch_notice"], {"token": "RCPT-1"})
        self.assertEqual(context["scheduler"], {"sent_reminders": {"trip-2": True}})
        self.assertEqual(context["trip_closure"], {"status": "waiting"})
        self.assertNotIn("active_receipt_message_id", context)

    def test_debounced_batch_notice_notifies_for_single_queued_receipt(self):
        sent_messages = []
        container = FakeContainer(
            {
                "state": "CONFIRM_SUMMARY",
                "current_step": "confirm_summary",
                "context_json": {
                    "pending_receipts": [
                        {
                            "media_url": "https://example.com/a.jpg",
                            "queued_at": "2026-03-31T13:00:00Z",
                            "message_id": "wamid.queued",
                        }
                    ],
                    "receipt_batch_notice": {
                        "token": "RCPT-1",
                        "received_count": 1,
                        "started_processing": False,
                        "reply_to_message_id": "wamid.queued",
                    },
                    "scheduler": {"sent_reminders": {}},
                    "trip_closure": {},
                },
            }
        )
        container.whatsapp = type(
            "WhatsApp",
            (),
            {
                "send_outbound_text": lambda _self, _phone, message, reply_to_message_id=None: sent_messages.append(
                    (message, reply_to_message_id)
                )
            },
        )()

        async def immediate_sleep(_seconds):
            return None

        with patch("app.main.asyncio.sleep", side_effect=immediate_sleep):
            asyncio.run(
                _debounced_send_receipt_batch_notice(
                    container,
                    "+56911111111",
                    "RCPT-1",
                )
            )

        self.assertEqual(
            sent_messages,
            [("Recibí tu documento. Lo revisaré apenas termine el actual.", "wamid.queued")],
        )
        self.assertNotIn("receipt_batch_notice", container.sheets.conversation["context_json"])

    def test_safe_send_outbound_response_swallows_meta_expired_token_error(self):
        whatsapp = type(
            "WhatsApp",
            (),
            {
                "send_outbound_text": lambda *args, **kwargs: (_ for _ in ()).throw(
                    MetaAccessTokenExpiredError("expired")
                )
            },
        )()
        container = FakeContainerWithWhatsApp(whatsapp)

        with patch("app.main.logger.exception") as mocked_logger:
            _safe_send_outbound_response(container, "+56911111111", "Hola")

        self.assertTrue(mocked_logger.called)


if __name__ == "__main__":
    unittest.main()
