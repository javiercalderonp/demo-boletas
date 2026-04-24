import os
import unittest
from unittest.mock import patch

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ""
os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = ""
os.environ["GCS_BUCKET_NAME"] = ""

from app.main import (
    _build_initial_wait_receipt_reply,
    _debounced_send_receipt_batch_notice,
    _is_duplicate_inbound_message,
    _mark_inbound_message_processed,
    _handle_media_message,
    _process_media_message_async,
    _reset_receipt_processing_state,
    _safe_send_outbound_response,
)
from app.config import Settings
from services.conversation_service import ConversationService
from services.expense_service import ExpenseService
from services.llm_service import LLMService
from services.whatsapp_service import MetaAccessTokenExpiredError, WhatsAppService


class FakeSheets:
    def __init__(self, conversation):
        self.conversation = conversation
        self.updates = []
        self.expenses = []
        self.employee = {"phone": "+56911111111", "first_name": "Javier", "name": "Javier Calderon"}

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
            "category",
            "country",
            "trip_id",
        ]
        missing = []
        for field in required_fields:
            value = draft_expense.get(field)
            if value is None or str(value).strip() == "":
                missing.append(field)
        return missing

    def create_expense_for_review(self, *, phone, draft_expense, review_reason):
        return {
            "expense_id": "EXP-REVIEW-1",
            "phone": phone,
            "status": "pending_review",
            "review_reason": review_reason,
            **dict(draft_expense),
        }

    def answer_general_question(self, question):
        return self.general_answer


class ConversationDocumentTypeTests(unittest.TestCase):
    def test_accepts_professional_fee_receipt_as_document_type_answer(self):
        service = ConversationService(ExpenseService(sheets_service=FakeSheets({})))

        self.assertEqual(
            service._parse_document_type_value("boleta de honorarios"),
            "professional_fee_receipt",
        )
        self.assertEqual(service._parse_document_type_value("3"), "professional_fee_receipt")


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

    def test_handle_media_message_routes_to_review_when_no_active_case(self):
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

        self.assertIn("Un operador deberá revisarlo", reply)
        self.assertNotIn("identificador del caso", reply.lower())
        self.assertEqual(container.sheets.conversation["state"], "WAIT_RECEIPT")
        self.assertEqual(container.sheets.conversation["current_step"], "")

    def test_meta_interactive_list_reply_uses_list_title(self):
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
        self.assertEqual(events[0]["body"], "Moneda")

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
