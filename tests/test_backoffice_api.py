import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from app.api.backoffice import (
    _build_new_case_conversation_state,
    case_action,
    create_case,
    delete_case as delete_case_endpoint,
    require_super_admin,
    send_conversation_template_message,
)
from app.schemas.backoffice import CasePayload, SendTemplatePayload, StatusActionPayload

SUPER_ADMIN_USER = {"role": "super_admin", "scope_type": "global", "active": True}


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
            "context_label": payload.get("context_label", ""),
            "cost_centers": payload.get("cost_centers", []),
            "fondos_entregados": payload.get("fondos_entregados", ""),
        }

    def get_conversation_detail(self, phone, user=None):
        return {"conversation": {"phone": phone}}


class FakeBackofficeActions:
    def __init__(self):
        self.case_row = {
            "case_id": "CASE-1",
            "employee_phone": "+56911111111",
            "rendicion_status": "approved",
            "settlement_direction": "employee_owes_company",
            "settlement_amount_clp": 4500,
            "settlement_status": "settled",
            "status": "active",
        }
        self.calls = []

    def ensure_case_ready_for_settlement_resolution(self, case_id):
        self.calls.append(("ensure_case_ready_for_settlement_resolution", case_id))
        return None

    def get_case_detail(self, case_id, user=None):
        if self.case_row.get("case_id") != case_id:
            return None
        return {"case": dict(self.case_row)}

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

    def build_case_settlement_resolved_whatsapp_message(self, expense_case):
        self.calls.append(("build_case_settlement_resolved_whatsapp_message", dict(expense_case)))
        return "Tu liquidación quedó resuelta.\nConfirmamos que llegó tu depósito por $4.500."


class FakeBackofficeDelete:
    def __init__(self):
        self.case_row = {
            "case_id": "CASE-DEL",
            "employee_phone": "+56911111111",
            "context_label": "Viaje Santiago",
        }

    def get_case_detail(self, case_id, user=None):
        if self.case_row.get("case_id") != case_id:
            return None
        return {"case": dict(self.case_row)}

    def delete_case_with_related_data(self, case_id):
        if self.case_row.get("case_id") != case_id:
            return None
        deleted = dict(self.case_row)
        self.case_row = {}
        return {"case": deleted, "deleted_expenses": 2}


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
        self.sent_templates = []

    def send_outbound_text(self, phone, message, reply_to_message_id=None):
        self.sent.append((phone, message, reply_to_message_id))
        return {"sid": "SM123"}

    def send_outbound_template(
        self,
        phone,
        *,
        template_name,
        language_code="en_US",
        body_parameters=None,
    ):
        self.sent_templates.append(
            {
                "phone": phone,
                "template_name": template_name,
                "language_code": language_code,
                "body_parameters": list(body_parameters or []),
            }
        )
        return {"id": "wamid.template", "provider": "meta"}


class FailingWhatsApp:
    provider = "meta"

    def send_outbound_text(self, phone, message, reply_to_message_id=None):
        raise RuntimeError("Meta API error HTTP 400: outside customer care window")

    def send_outbound_template(
        self,
        phone,
        *,
        template_name,
        language_code="en_US",
        body_parameters=None,
    ):
        raise RuntimeError("Meta API error HTTP 400: template send failed")


class BackofficeApiTests(unittest.TestCase):
    def test_require_super_admin_rejects_non_super_admin(self):
        with self.assertRaises(HTTPException) as ctx:
            require_super_admin({"role": "company_admin", "scope_type": "company", "active": True})

        self.assertEqual(ctx.exception.status_code, 403)

    def test_delete_case_notifies_user_and_logs_message(self):
        container = SimpleNamespace(
            backoffice=FakeBackofficeDelete(),
            whatsapp=FakeWhatsApp(),
            sheets=FakeSheets({"context_json": {"message_log": []}}),
            conversation=FakeConversationService(),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        result = delete_case_endpoint("CASE-DEL", request, SUPER_ADMIN_USER)

        expected_message = "Tu caso Viaje Santiago (CASE-DEL) ha sido eliminado por administración."
        self.assertEqual(result["deleted_expenses"], 2)
        self.assertEqual(result["delete_notification"], {"status": "sent"})
        self.assertEqual(
            container.whatsapp.sent,
            [("+56911111111", expected_message, None)],
        )
        message_log = container.sheets.conversation["context_json"]["message_log"]
        self.assertEqual(message_log[-1]["speaker"], "bot")
        self.assertEqual(message_log[-1]["text"], expected_message)

    def test_send_template_message_opens_conversation_and_logs_operator_message(self):
        container = SimpleNamespace(
            backoffice=FakeBackoffice(),
            whatsapp=FakeWhatsApp(),
            sheets=FakeSheets({}),
            conversation=FakeConversationService(),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        result = send_conversation_template_message(
            "56979956605",
            SendTemplatePayload(template_name="hello_world", language_code="en_US"),
            request,
            {"name": "Operador Uno"},
        )

        self.assertTrue(result["ok"])
        self.assertEqual(
            container.whatsapp.sent_templates,
            [
                {
                    "phone": "56979956605",
                    "template_name": "hello_world",
                    "language_code": "en_US",
                    "body_parameters": [],
                }
            ],
        )
        message_log = container.sheets.conversation["context_json"]["message_log"]
        self.assertEqual(message_log[-1]["speaker"], "operator")
        self.assertEqual(message_log[-1]["text"], "Plantilla WhatsApp enviada: hello_world (en_US)")
        self.assertEqual(message_log[-1]["provider_message_id"], "wamid.template")

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
            SUPER_ADMIN_USER,
        )

        self.assertEqual(result["settlement_status"], "settled")
        self.assertEqual(result["rendicion_status"], "closed")
        self.assertEqual(result["status"], "closed")
        self.assertIn(
            ("update_case", "CASE-1", {"rendicion_status": "closed", "status": "closed"}),
            container.backoffice.calls,
        )
        self.assertEqual(
            container.whatsapp.sent,
            [
                (
                    "+56911111111",
                    "Tu liquidación quedó resuelta.\nConfirmamos que llegó tu depósito por $4.500.",
                    None,
                )
            ],
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
                SUPER_ADMIN_USER,
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
            SUPER_ADMIN_USER,
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
        self.assertEqual(
            context["message_log"][1]["text"],
            "Plantilla WhatsApp enviada: inicio_rendicion (es_CL)",
        )
        self.assertEqual(context["message_log"][1]["template_name"], "inicio_rendicion")
        self.assertEqual(context["message_log"][1]["template_parameters"], ["Usuario", "CASE-NEW"])
        self.assertEqual(
            container.whatsapp.sent_templates,
            [
                {
                    "phone": "+56911111111",
                    "template_name": "inicio_rendicion",
                    "language_code": "es_CL",
                    "body_parameters": ["Usuario", "CASE-NEW"],
                }
            ],
        )

    def test_create_case_uses_detail_template_when_cost_centers_are_enabled(self):
        container = SimpleNamespace(
            backoffice=FakeBackoffice(),
            scheduler=FakeScheduler(),
            whatsapp=FakeWhatsApp(),
            sheets=FakeSheets({"context_json": {"message_log": []}}),
            conversation=FakeConversationService(),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        result = create_case(
            CasePayload(
                employee_phone="+56911111111",
                company_id="COMP-1",
                case_id="CASE-NEW",
                context_label="Viaje Santiago",
                cost_centers=["Operaciones", "Ventas"],
                fondos_entregados=250000,
            ),
            request,
            SUPER_ADMIN_USER,
        )

        self.assertEqual(result["intro_notification"]["status"], "sent")
        self.assertEqual(result["intro_notification"]["template_name"], "inicio_rendicion_detalle")
        self.assertEqual(
            container.whatsapp.sent_templates,
            [
                {
                    "phone": "+56911111111",
                    "template_name": "inicio_rendicion_detalle",
                    "language_code": "es_CL",
                    "body_parameters": [
                        "Usuario",
                        "Viaje Santiago",
                        "CLP 250.000",
                        "Operaciones, Ventas",
                    ],
                }
            ],
        )

    def test_create_case_keeps_conversation_ready_when_intro_message_fails(self):
        conversation = {
            "state": "PROCESSING",
            "current_step": "confirm",
            "context_json": {
                "message_log": [{"id": "old-msg", "speaker": "person", "type": "media"}],
                "pending_receipts": [{"media_url": "https://example.com/old.jpg"}],
                "active_receipt_message_id": "wamid.old",
            },
        }
        container = SimpleNamespace(
            backoffice=FakeBackoffice(),
            scheduler=FakeScheduler(),
            whatsapp=FailingWhatsApp(),
            sheets=FakeSheets(conversation),
            conversation=FakeConversationService(),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        result = create_case(
            CasePayload(employee_phone="+56911111111", company_id="COMP-1", case_id="CASE-NEW"),
            request,
            SUPER_ADMIN_USER,
        )

        self.assertEqual(result["case_id"], "CASE-NEW")
        self.assertEqual(result["intro_notification"]["status"], "send_failed")
        updated = container.sheets.conversation
        context = updated["context_json"]
        self.assertEqual(updated["state"], "WAIT_RECEIPT")
        self.assertEqual(updated["current_step"], "")
        self.assertNotIn("pending_receipts", context)
        self.assertNotIn("active_receipt_message_id", context)
        self.assertEqual(context["message_log"], [{"id": "old-msg", "speaker": "person", "type": "media"}])


if __name__ == "__main__":
    unittest.main()
