import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ["GOOGLE_SHEETS_SPREADSHEET_ID"] = ""

from fastapi import HTTPException
from pydantic import ValidationError

import app.main as main_app
from app.api.backoffice import (
    LOGIN_RATE_LIMIT_MAX_ATTEMPTS,
    _check_login_rate_limit,
    _clear_login_rate_limit,
    _login_rate_limit_attempts,
    _record_failed_login,
    _build_new_case_conversation_state,
    case_action,
    create_case,
    delete_case as delete_case_endpoint,
    generate_case_consolidated_document,
    list_audit_log,
    refresh_auth_token,
    require_global_admin,
    require_super_admin,
    send_conversation_message,
    send_conversation_template_message,
)
from app.main import create_app
from app.schemas.backoffice import (
    CasePayload,
    EmployeePayload,
    SendMessagePayload,
    SendTemplatePayload,
    SetupPasswordPayload,
    StatusActionPayload,
)

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

    def ensure_case_ready_for_document_confirmation(self, case_id):
        self.calls.append(("ensure_case_ready_for_document_confirmation", case_id))
        return {"all_documents_resolved": True}

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


class FakeBackofficeExpenses:
    def __init__(self):
        self.expense = {
            "expense_id": "EXP-1",
            "case_id": "CASE-1",
            "phone": "+56911111111",
            "source_message_id": "wamid.original",
            "merchant": "Cafe Central",
            "currency": "CLP",
            "total": 4500,
            "status": "pending_review",
            "review_status": "pending_review",
        }

    def get_expense_detail(self, expense_id, user=None):
        if expense_id != self.expense["expense_id"]:
            return None
        return {"expense": dict(self.expense)}

    def update_expense(self, expense_id, payload):
        if expense_id != self.expense["expense_id"]:
            return None
        self.expense = {**self.expense, **payload}
        return dict(self.expense)

    def get_case_detail(self, case_id, user=None):
        return {"case": {"case_id": case_id, "saldo_restante": 0}}


class FakeAuditSheets:
    def __init__(self):
        self.audit_rows = []

    def append_audit_log(self, **payload):
        self.audit_rows.append(payload)
        return payload

    def list_audit_log(self):
        return list(self.audit_rows)


class FakeBackofficeAuth:
    def create_access_token(self, user):
        return f"token-for-{user['email']}"


class FakeScheduler:
    def _resolve_case_timezone(self, expense_case):
        return "America/Santiago"

    def _build_submission_start_intro_messages(self, expense_case):
        return ["Hola, ya puedes enviar tu boleta."]

    def _deliver_submission_closure_package(self, *, phone, case_id):
        return "Revisa y confirma tu rendición."

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
    def _create_app_with_fake_services(self):
        class FakeService:
            enabled = False
            document_ai_enabled = False
            category_classification_enabled = False
            chat_assistant_enabled = False
            provider = "meta"

            def __init__(self, *args, **kwargs):
                pass

            def ensure_default_admin(self):
                pass

        with (
            patch("app.main.SheetsService", FakeService),
            patch("app.main.BackofficeAuthService", FakeService),
            patch("app.main.BackofficeService", FakeService),
            patch("app.main.ExpenseCaseService", FakeService),
            patch("app.main.GCSStorageService", FakeService),
            patch("app.main.ConsolidatedDocumentService", FakeService),
            patch("app.main.DocusignService", FakeService),
            patch("app.main.OCRService", FakeService),
            patch("app.main.ExpenseService", FakeService),
            patch("app.main.LLMService", FakeService),
            patch("app.main.ConversationService", FakeService),
            patch("app.main.WhatsAppService", FakeService),
            patch("app.main.SchedulerService", FakeService),
            patch("services.review_score_service.ReviewScoreService", FakeService),
        ):
            return create_app()

    def _fake_request(self, host="203.0.113.9"):
        return SimpleNamespace(headers={}, client=SimpleNamespace(host=host))

    def test_health_exposes_minimal_public_payload(self):
        app = self._create_app_with_fake_services()
        route = next(route for route in app.routes if getattr(route, "path", None) == "/health")

        response = asyncio.run(route.endpoint())

        self.assertEqual(response, {"status": "ok"})

    def test_backoffice_payloads_validate_phone_e164(self):
        self.assertEqual(EmployeePayload(phone="+56911111111").phone, "+56911111111")
        self.assertEqual(
            CasePayload(employee_phone="+56911111111", company_id="COMP-1").employee_phone,
            "+56911111111",
        )

        with self.assertRaises(ValidationError):
            EmployeePayload(phone="56911111111")
        with self.assertRaises(ValidationError):
            CasePayload(employee_phone="56911111111", company_id="COMP-1")

    def test_setup_password_payload_requires_strong_password(self):
        self.assertEqual(
            SetupPasswordPayload(email="user@example.com", password="Strongpass1!").password,
            "Strongpass1!",
        )
        with self.assertRaises(ValidationError):
            SetupPasswordPayload(email="user@example.com", password="weakpass")

    def test_refresh_auth_token_returns_new_login_response(self):
        container = SimpleNamespace(backoffice_auth=FakeBackofficeAuth())
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))
        user = {
            "id": "usr_1",
            "email": "operator@example.com",
            "role": "company_admin",
            "active": True,
        }

        response = refresh_auth_token(request, user)

        self.assertEqual(response.access_token, "token-for-operator@example.com")
        self.assertEqual(response.user["email"], "operator@example.com")

    def test_production_app_disables_docs_and_localhost_cors(self):
        original_debug = main_app.settings.debug
        main_app.settings.debug = False
        try:
            app = self._create_app_with_fake_services()
        finally:
            main_app.settings.debug = original_debug

        paths = {getattr(route, "path", None) for route in app.routes}
        self.assertNotIn("/docs", paths)
        self.assertNotIn("/redoc", paths)
        self.assertNotIn("/openapi.json", paths)

        cors_middleware = next(
            middleware for middleware in app.user_middleware if middleware.cls.__name__ == "CORSMiddleware"
        )
        self.assertNotIn("http://localhost:3000", cors_middleware.kwargs["allow_origins"])

    def test_debug_app_allows_localhost_cors(self):
        original_debug = main_app.settings.debug
        main_app.settings.debug = True
        try:
            app = self._create_app_with_fake_services()
        finally:
            main_app.settings.debug = original_debug

        cors_middleware = next(
            middleware for middleware in app.user_middleware if middleware.cls.__name__ == "CORSMiddleware"
        )
        self.assertIn("http://localhost:3000", cors_middleware.kwargs["allow_origins"])

    def test_login_rate_limit_blocks_after_repeated_failures_and_clears_on_success(self):
        request = self._fake_request()
        email = "admin@example.com"
        _login_rate_limit_attempts.clear()

        try:
            for _ in range(LOGIN_RATE_LIMIT_MAX_ATTEMPTS):
                _record_failed_login(request, email)

            with self.assertRaises(HTTPException) as ctx:
                _check_login_rate_limit(request, email)

            self.assertEqual(ctx.exception.status_code, 429)

            _clear_login_rate_limit(request, email)
            _check_login_rate_limit(request, email)
        finally:
            _login_rate_limit_attempts.clear()

    def test_internal_scheduler_token_fails_closed_when_not_configured(self):
        original_token = main_app.settings.scheduler_endpoint_token
        main_app.settings.scheduler_endpoint_token = ""
        try:
            with self.assertRaises(HTTPException) as ctx:
                main_app._require_scheduler_token("anything")
        finally:
            main_app.settings.scheduler_endpoint_token = original_token

        self.assertEqual(ctx.exception.status_code, 503)

    def test_internal_scheduler_token_rejects_missing_or_invalid_token(self):
        original_token = main_app.settings.scheduler_endpoint_token
        main_app.settings.scheduler_endpoint_token = "expected-token"
        try:
            with self.assertRaises(HTTPException) as missing_ctx:
                main_app._require_scheduler_token(None)
            with self.assertRaises(HTTPException) as invalid_ctx:
                main_app._require_scheduler_token("wrong-token")
        finally:
            main_app.settings.scheduler_endpoint_token = original_token

        self.assertEqual(missing_ctx.exception.status_code, 401)
        self.assertEqual(invalid_ctx.exception.status_code, 401)

    def test_internal_scheduler_token_accepts_configured_token(self):
        original_token = main_app.settings.scheduler_endpoint_token
        main_app.settings.scheduler_endpoint_token = "expected-token"
        try:
            main_app._require_scheduler_token("expected-token")
        finally:
            main_app.settings.scheduler_endpoint_token = original_token

    def test_require_super_admin_rejects_non_super_admin(self):
        with self.assertRaises(HTTPException) as ctx:
            require_super_admin({"role": "company_admin", "scope_type": "company", "active": True})

        self.assertEqual(ctx.exception.status_code, 403)

    def test_require_global_admin_accepts_legacy_general_admin(self):
        user = {"role": "admin", "scope_type": "global", "active": True}

        self.assertIs(require_global_admin(user), user)

    def test_require_global_admin_rejects_company_admin(self):
        with self.assertRaises(HTTPException) as ctx:
            require_global_admin(
                {
                    "role": "company_admin",
                    "scope_type": "company",
                    "company_ids": ["acme"],
                    "active": True,
                }
            )

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

    def test_send_conversation_message_preserves_full_message_log(self):
        class ConversationSheets:
            def __init__(self):
                self.conversation = {
                    "phone": "+56911111111",
                    "state": "WAIT_RECEIPT",
                    "current_step": "",
                    "context_json": {
                        "message_log": [
                            {
                                "id": f"msg-{index}",
                                "speaker": "person",
                                "type": "text",
                                "text": str(index),
                            }
                            for index in range(550)
                        ]
                    },
                }
                self.audit_rows = []

            def get_conversation(self, phone):
                return {
                    **self.conversation,
                    "context_json": dict(self.conversation["context_json"]),
                }

            def update_conversation(self, phone, payload):
                self.conversation = {
                    "phone": phone,
                    "state": payload.get("state", ""),
                    "current_step": payload.get("current_step", ""),
                    "context_json": payload.get("context_json", {}),
                }
                return dict(self.conversation)

            def get_active_expense_case_by_phone(self, phone):
                return None

            def append_audit_log(self, **payload):
                self.audit_rows.append(payload)
                return payload

        class ConversationBackoffice:
            def __init__(self, sheets):
                self.sheets = sheets

            def get_conversation_detail(self, phone, user=None):
                return {"conversation": self.sheets.get_conversation(phone)}

        sheets = ConversationSheets()
        container = SimpleNamespace(
            backoffice=ConversationBackoffice(sheets),
            whatsapp=FakeWhatsApp(),
            sheets=sheets,
            conversation=FakeConversationService(),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        result = send_conversation_message(
            "+56911111111",
            SendMessagePayload(message="Respuesta operador"),
            request,
            {"email": "operator@example.com", "name": "Operador", "role": "company_admin"},
        )

        message_log = sheets.conversation["context_json"]["message_log"]
        self.assertTrue(result["ok"])
        self.assertEqual(len(message_log), 551)
        self.assertEqual(message_log[0]["id"], "msg-0")
        self.assertEqual(message_log[-1]["text"], "Respuesta operador")

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

    def test_request_user_confirmation_delivers_closure_package_and_logs_audit(self):
        sheets = FakeAuditSheets()
        whatsapp = FakeWhatsApp()
        backoffice = FakeBackofficeActions()
        container = SimpleNamespace(
            backoffice=backoffice,
            scheduler=FakeScheduler(),
            whatsapp=whatsapp,
            sheets=sheets,
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        result = case_action(
            "CASE-1",
            StatusActionPayload(action="request_user_confirmation"),
            request,
            SUPER_ADMIN_USER,
        )

        self.assertEqual(result["rendicion_status"], "pending_user_confirmation")
        self.assertEqual(result["user_confirmation_status"], "pending")
        self.assertIn(("ensure_case_ready_for_document_confirmation", "CASE-1"), backoffice.calls)
        self.assertEqual(
            whatsapp.sent,
            [("+56911111111", "Revisa y confirma tu rendición.", None)],
        )
        self.assertEqual(sheets.audit_rows[0]["action"], "case.request_user_confirmation")

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

    def test_expense_action_writes_audit_log(self):
        from app.api.backoffice import expense_action

        sheets = FakeAuditSheets()
        container = SimpleNamespace(
            backoffice=FakeBackofficeExpenses(),
            whatsapp=FakeWhatsApp(),
            sheets=sheets,
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))
        user = {"email": "operator@example.com", "role": "company_admin"}

        result = expense_action(
            "EXP-1",
            StatusActionPayload(action="approve"),
            request,
            user,
        )

        self.assertEqual(result["status"], "approved")
        self.assertEqual(len(sheets.audit_rows), 1)
        self.assertEqual(sheets.audit_rows[0]["action"], "expense.approve")
        self.assertEqual(sheets.audit_rows[0]["resource_type"], "expense")
        self.assertEqual(sheets.audit_rows[0]["resource_id"], "EXP-1")

    def test_audit_log_endpoint_filters_by_company_scope(self):
        sheets = FakeAuditSheets()
        sheets.audit_rows = [
            {
                "audit_id": "audit-1",
                "timestamp": "2026-01-02T12:00:00Z",
                "user_email": "global@example.com",
                "user_role": "super_admin",
                "action": "case.create",
                "resource_type": "case",
                "resource_id": "CASE-1",
                "company_id": "COMP-1",
                "details": '{"source":"test"}',
            },
            {
                "audit_id": "audit-2",
                "timestamp": "2026-01-02T12:01:00Z",
                "user_email": "global@example.com",
                "user_role": "super_admin",
                "action": "case.create",
                "resource_type": "case",
                "resource_id": "CASE-2",
                "company_id": "COMP-2",
                "details": "{}",
            },
        ]
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(sheets=sheets))))
        user = {
            "email": "admin@example.com",
            "role": "company_admin",
            "scope_type": "company",
            "company_ids": ["COMP-1"],
        }

        response = list_audit_log(request, None, None, None, 200, user)

        self.assertEqual([item["audit_id"] for item in response["items"]], ["audit-1"])
        self.assertEqual(response["items"][0]["details"], {"source": "test"})

    def test_generate_case_consolidated_document_from_backoffice(self):
        class ConsolidatedBackoffice:
            def get_case_detail(self, case_id, user=None):
                return {
                    "case": {
                        "case_id": case_id,
                        "employee_phone": "+56911111111",
                        "company_id": "COMP-1",
                    },
                    "employee": {"phone": "+56911111111"},
                    "expenses": [],
                }

        class ConsolidatedDocument:
            def __init__(self):
                self.calls = []

            def generate_for_case(self, *, phone, case_id, include_signed_url=True):
                self.calls.append((phone, case_id, include_signed_url))
                return {
                    "document_id": "DOC-1",
                    "case_id": case_id,
                    "phone": phone,
                    "signed_url": "https://example.com/rendicion.pdf",
                }

        sheets = FakeAuditSheets()
        consolidated_document = ConsolidatedDocument()
        container = SimpleNamespace(
            backoffice=ConsolidatedBackoffice(),
            consolidated_document=consolidated_document,
            sheets=sheets,
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        result = generate_case_consolidated_document(
            "CASE-1",
            request,
            {"email": "admin@example.com", "role": "company_admin"},
        )

        self.assertEqual(result["signed_url"], "https://example.com/rendicion.pdf")
        self.assertEqual(consolidated_document.calls, [("+56911111111", "CASE-1", True)])
        self.assertEqual(sheets.audit_rows[0]["action"], "case.generate_consolidated_document")
        self.assertEqual(sheets.audit_rows[0]["resource_id"], "CASE-1")

    def test_expense_observe_notifies_with_requested_evidence(self):
        from app.api.backoffice import expense_action

        sheets = FakeAuditSheets()
        whatsapp = FakeWhatsApp()
        container = SimpleNamespace(
            backoffice=FakeBackofficeExpenses(),
            whatsapp=whatsapp,
            sheets=sheets,
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        result = expense_action(
            "EXP-1",
            StatusActionPayload(action="observe", reason="foto más nítida"),
            request,
            {"email": "operator@example.com", "role": "company_admin"},
        )

        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["review_status"], "observed")
        self.assertEqual(result["review_reason"], "foto más nítida")
        self.assertEqual(whatsapp.sent[0][0], "+56911111111")
        self.assertIn("quedó observado", whatsapp.sent[0][1])
        self.assertIn("foto más nítida", whatsapp.sent[0][1])
        self.assertEqual(whatsapp.sent[0][2], "wamid.original")
        self.assertEqual(sheets.audit_rows[0]["action"], "expense.observe")

    def test_expense_manual_review_notifies_user(self):
        from app.api.backoffice import expense_action

        whatsapp = FakeWhatsApp()
        container = SimpleNamespace(
            backoffice=FakeBackofficeExpenses(),
            whatsapp=whatsapp,
            sheets=FakeAuditSheets(),
        )
        request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=container)))

        result = expense_action(
            "EXP-1",
            StatusActionPayload(action="manual_review"),
            request,
            {"email": "operator@example.com", "role": "company_admin"},
        )

        self.assertEqual(result["status"], "needs_manual_review")
        self.assertEqual(result["review_status"], "needs_manual_review")
        self.assertIn("revisión manual", whatsapp.sent[0][1])

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
            "Plantilla WhatsApp enviada: inicio_rendicion_detalle (es_CL)",
        )
        self.assertEqual(context["message_log"][1]["template_name"], "inicio_rendicion_detalle")
        self.assertEqual(
            context["message_log"][1]["template_parameters"],
            ["Usuario", "CASE-NEW", "Sin presupuesto definido", "Sin centros de costo definidos"],
        )
        self.assertEqual(
            container.whatsapp.sent_templates,
            [
                {
                    "phone": "+56911111111",
                    "template_name": "inicio_rendicion_detalle",
                    "language_code": "es_CL",
                    "body_parameters": [
                        "Usuario",
                        "CASE-NEW",
                        "Sin presupuesto definido",
                        "Sin centros de costo definidos",
                    ],
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
