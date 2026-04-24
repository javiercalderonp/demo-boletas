import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.backoffice import _build_new_case_conversation_state, case_action, create_case
from app.schemas.backoffice import CasePayload, StatusActionPayload


class FakeConversationService:
    def default_context(self):
        return {
            "draft_expense": {},
            "missing_fields": [],
            "last_question": None,
            "message_log": [],
            "scheduler": {"sent_reminders": {}},
            "submission_closure": {},
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
        if "submission_closure" not in merged and "trip_closure" in context:
            merged["submission_closure"] = dict(context.get("trip_closure", {}))
        if "trip_closure" not in merged and "submission_closure" in context:
            merged["trip_closure"] = dict(context.get("submission_closure", {}))
        conversation["context_json"] = merged
        conversation.setdefault("state", "WAIT_RECEIPT")
        conversation.setdefault("current_step", "")
        return conversation


class FakeSheets:
    def __init__(self, conversation):
        self.conversation = conversation

    def get_conversation(self, phone):
        if not self.conversation:
            return None
        return {
            "phone": phone,
            "state": self.conversation.get("state", "WAIT_RECEIPT"),
            "current_step": self.conversation.get("current_step", ""),
            "context_json": dict(self.conversation.get("context_json", {})),
        }

    def update_conversation(self, phone, payload):
        self.conversation = {
            "phone": phone,
            "state": payload.get("state", "WAIT_RECEIPT"),
            "current_step": payload.get("current_step", ""),
            "context_json": dict(payload.get("context_json", {})),
        }
        return dict(self.conversation)


class FakeBackoffice:
    def create_case(self, payload):
        return {
            "case_id": payload.get("case_id") or "CASE-NEW",
            "employee_phone": payload.get("employee_phone"),
            "company_id": payload.get("company_id", ""),
        }


class FakeBackofficeActions:
    def __init__(self):
        self.case_row = {
            "case_id": "CASE-1",
            "rendicion_status": "approved",
            "settlement_status": "settled",
            "status": "active",
        }
        self.calls = []

    def ensure_case_ready_for_settlement_resolution(self, case_id):
        self.calls.append(("ensure_case_ready_for_settlement_resolution", case_id))
        return None

    def sync_case_settlement(self, case_id, *, mark_settled=False, resolved_at=None):
        self.calls.append(("sync_case_settlement", case_id, mark_settled, bool(resolved_at)))
        self.case_row = {
            **self.case_row,
            "case_id": case_id,
            "settlement_status": "settled",
        }
        return dict(self.case_row)

    def update_case(self, case_id, payload):
        self.calls.append(("update_case", case_id, dict(payload)))
        self.case_row = {**self.case_row, **payload}
        return dict(self.case_row)


class FakeScheduler:
    def _resolve_case_timezone(self, expense_case):
        return "America/Santiago"

    def _build_submission_start_intro_messages(self, expense_case):
        return ["Hola, ya puedes enviar tu boleta."]

    def _submission_start_intro_key(self, case_id, local_date):
        return f"{case_id}:{local_date}"

    def _mark_reminder_sent(self, **kwargs):
        return None


class FakeWhatsApp:
    def __init__(self):
        self.sent = []

    def send_outbound_text(self, phone, message, reply_to_message_id=None):
        self.sent.append((phone, message, reply_to_message_id))
        return {"sid": "SM123"}


class BackofficeApiTests(unittest.TestCase):
    def test_resolve_settlement_closes_case_automatically(self):
        container = SimpleNamespace(
            backoffice=FakeBackofficeActions(),
            whatsapp=FakeWhatsApp(),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        result = case_action(
            "CASE-1",
            StatusActionPayload(action="resolve_settlement"),
            request,
            {},
        )

        self.assertEqual(result["settlement_status"], "settled")
        self.assertEqual(result["rendicion_status"], "closed")
        self.assertEqual(result["status"], "closed")
        self.assertIn(
            ("update_case", "CASE-1", {"rendicion_status": "closed", "status": "closed"}),
            container.backoffice.calls,
        )

    def test_create_case_returns_409_when_employee_already_has_active_case(self):
        class ConflictBackoffice:
            def create_case(self, payload):
                raise ValueError(
                    "La persona ya tiene un caso activo. Debes cerrarlo o resolver el conflicto antes de crear uno nuevo."
                )

        container = SimpleNamespace(
            backoffice=ConflictBackoffice(),
            scheduler=FakeScheduler(),
            whatsapp=FakeWhatsApp(),
            sheets=FakeSheets(None),
            conversation=FakeConversationService(),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        with self.assertRaises(HTTPException) as ctx:
            create_case(
                CasePayload(employee_phone="+56911111111", company_id="COMP-1", case_id="CASE-NEW"),
                request,
                {},
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("ya tiene un caso activo", str(ctx.exception.detail))

    def test_build_new_case_conversation_state_clears_receipt_runtime_context(self):
        container = SimpleNamespace(conversation=FakeConversationService())
        conversation = {
            "state": "CONFIRM_SUMMARY",
            "current_step": "confirm",
            "context_json": {
                "draft_expense": {"merchant": "Cafe"},
                "missing_fields": ["category"],
                "last_question": "confirm",
                "message_log": [{"id": "m1", "speaker": "bot"}],
                "scheduler": {"sent_reminders": {"CASE-OLD": True}},
                "submission_closure": {"status": "pending"},
                "trip_closure": {"status": "pending"},
                "pending_receipts": [{"media_url": "https://example.com/old.jpg", "queued_at": "2026-04-17T00:00:00Z"}],
                "active_receipt_message_id": "wamid.old",
                "receipt_batch_notice": {"token": "tok"},
                "processed_message_ids": ["wamid.old"],
            },
        }

        result = _build_new_case_conversation_state(container, conversation)
        context = result["context_json"]

        self.assertEqual(result["state"], "WAIT_RECEIPT")
        self.assertEqual(result["current_step"], "")
        self.assertEqual(context["message_log"], [{"id": "m1", "speaker": "bot"}])
        self.assertEqual(context["scheduler"], {"sent_reminders": {"CASE-OLD": True}})
        self.assertEqual(context["submission_closure"], {"status": "pending"})
        self.assertEqual(context["trip_closure"], {"status": "pending"})
        self.assertEqual(context["processed_message_ids"], ["wamid.old"])
        self.assertNotIn("pending_receipts", context)
        self.assertNotIn("active_receipt_message_id", context)
        self.assertNotIn("receipt_batch_notice", context)
        self.assertEqual(context["draft_expense"], {})
        self.assertEqual(context["missing_fields"], [])
        self.assertIsNone(context["last_question"])

    def test_create_case_resets_existing_conversation_before_intro_messages(self):
        conversation = {
            "state": "PROCESSING",
            "current_step": "confirm",
            "context_json": {
                "message_log": [{"id": "old-msg", "speaker": "person", "type": "media"}],
                "scheduler": {"sent_reminders": {"CASE-OLD": True}},
                "submission_closure": {"status": "pending"},
                "trip_closure": {"status": "pending"},
                "pending_receipts": [{"media_url": "https://example.com/old.jpg", "queued_at": "2026-04-17T00:00:00Z"}],
                "active_receipt_message_id": "wamid.old",
                "receipt_batch_notice": {"token": "tok"},
                "processed_message_ids": ["wamid.old"],
            },
        }
        container = SimpleNamespace(
            backoffice=FakeBackoffice(),
            scheduler=FakeScheduler(),
            whatsapp=FakeWhatsApp(),
            sheets=FakeSheets(conversation),
            conversation=FakeConversationService(),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        result = create_case(
            CasePayload(employee_phone="+56911111111", company_id="COMP-1", case_id="CASE-NEW"),
            request,
            {},
        )

        self.assertEqual(result["case_id"], "CASE-NEW")
        updated = container.sheets.conversation
        context = updated["context_json"]
        self.assertEqual(updated["state"], "WAIT_RECEIPT")
        self.assertEqual(updated["current_step"], "")
        self.assertNotIn("pending_receipts", context)
        self.assertNotIn("active_receipt_message_id", context)
        self.assertNotIn("receipt_batch_notice", context)
        self.assertEqual(context["processed_message_ids"], ["wamid.old"])
        self.assertEqual(context["scheduler"], {"sent_reminders": {"CASE-OLD": True}})
        self.assertEqual(context["submission_closure"], {"status": "pending"})
        self.assertEqual(context["trip_closure"], {"status": "pending"})
        self.assertEqual(len(context["message_log"]), 2)
        self.assertEqual(context["message_log"][0]["id"], "old-msg")
        self.assertEqual(context["message_log"][1]["text"], "Hola, ya puedes enviar tu boleta.")


if __name__ == "__main__":
    unittest.main()
