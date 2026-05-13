from __future__ import annotations

import csv
import io
import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.schemas.backoffice import (
    BackofficeUserPayload,
    CasePayload,
    CaseChatPayload,
    ConversationPayload,
    EmployeePayload,
    ExpensePayload,
    LoginRequest,
    LoginResponse,
    SendMessagePayload,
    SetupPasswordPayload,
    SetupPasswordRequest,
    StatusActionPayload,
)
from services.backoffice_permissions import (
    COMPANY_ADMIN_ROLE,
    COMPANY_SCOPE,
    GLOBAL_SCOPE,
    LEGACY_ADMIN_ROLE,
    SUPER_ADMIN_ROLE,
    can_access_company,
    resolve_access,
)
from services.statuses import (
    CaseStatus,
    ExpenseStatus,
    RendicionStatus,
)
from utils.helpers import make_id, utc_now_iso


router = APIRouter(prefix="/api", tags=["backoffice"])
logger = logging.getLogger(__name__)
MAX_MESSAGE_LOG_ITEMS = 500
ADMIN_ROLES = {SUPER_ADMIN_ROLE, LEGACY_ADMIN_ROLE, COMPANY_ADMIN_ROLE}


def _get_container(request: Request):
    return request.app.state.services


def _extract_bearer_token(authorization: Optional[str]) -> str:
    value = str(authorization or "").strip()
    if not value.lower().startswith("bearer "):
        return ""
    return value.split(" ", 1)[1].strip()


def _is_transient_dependency_error(exc: Exception) -> bool:
    status_code = getattr(exc, "code", None)
    response = getattr(exc, "response", None)
    response_code = getattr(response, "status_code", None) if response is not None else None
    try:
        if int(status_code) in {429, 500, 502, 503, 504}:
            return True
    except Exception:
        pass
    try:
        if int(response_code) in {429, 500, 502, 503, 504}:
            return True
    except Exception:
        pass
    message = str(exc)
    fragments = (
        "[429]",
        "[500]",
        "[502]",
        "[503]",
        "[504]",
        "service is currently unavailable",
        "Service Unavailable",
        "Timeout",
        "timed out",
        "Temporary failure",
    )
    return any(fragment in message for fragment in fragments)


def require_user(
    request: Request,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    container = _get_container(request)
    token = _extract_bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    try:
        user = container.backoffice_auth.verify_access_token(token)
    except Exception as exc:
        if _is_transient_dependency_error(exc):
            logger.warning("Backoffice auth temporarily unavailable: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Servicio de autenticación temporalmente no disponible. Intenta nuevamente.",
            ) from exc
        raise
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return user


def _safe_user(user: dict[str, Any]) -> dict[str, Any]:
    access = resolve_access(user)
    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
        "active": user.get("active"),
        "scope_type": access.scope_type,
        "company_ids": sorted(access.company_ids),
        "company_id": user.get("company_id", ""),
        "created_at": user.get("created_at", ""),
        "updated_at": user.get("updated_at", ""),
        "has_password": bool(str(user.get("password_hash", "") or "").strip()),
    }


def require_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    role = str(user.get("role", "") or "").strip().lower()
    if role not in ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    return user


def require_super_admin(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    role = str(user.get("role", "") or "").strip().lower()
    if role != SUPER_ADMIN_ROLE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No autorizado")
    return user


def _safe_user_payload(user: dict[str, Any]) -> dict[str, Any]:
    return _safe_user(user)


def _ensure_user_can_access_company(user: dict[str, Any], company_id: Any) -> None:
    if can_access_company(user, company_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No tienes acceso a esa empresa",
    )


def _attach_expense_receipt_urls(request: Request, expense: dict[str, Any]) -> dict[str, Any]:
    item = dict(expense)
    if item.get("image_url") or item.get("document_url"):
        return item

    container = _get_container(request)
    storage = getattr(container, "storage", None)
    if not storage or not getattr(storage, "enabled", False):
        return item

    provider = str(item.get("receipt_storage_provider", "") or "").strip().lower()
    object_key = str(item.get("receipt_object_key", "") or "").strip()
    if provider != "gcs" or not object_key:
        return item

    signed_url = storage.generate_signed_url(object_key=object_key)
    if object_key.lower().endswith(".pdf"):
        item["document_url"] = signed_url
    else:
        item["image_url"] = signed_url
    return item


def _get_expense_reply_target(request: Request, expense: dict[str, Any]) -> str | None:
    direct = str(expense.get("source_message_id", "") or "").strip()
    if direct:
        return direct

    phone = str(expense.get("phone", "") or "").strip()
    if not phone:
        return None

    conversation = _get_container(request).sheets.get_conversation(phone) or {}
    context = conversation.get("context_json", {})
    if not isinstance(context, dict):
        return None
    message_log = context.get("message_log", [])
    if not isinstance(message_log, list):
        return None

    for item in reversed(message_log):
        if not isinstance(item, dict):
            continue
        if str(item.get("speaker", "") or "").strip() != "person":
            continue
        if str(item.get("type", "") or "").strip() != "media":
            continue
        message_id = str(item.get("message_id", "") or "").strip()
        if message_id:
            return message_id
    return None


def _enrich_conversation_media_messages(request: Request, detail: dict[str, Any]) -> dict[str, Any]:
    conversation = detail.get("conversation")
    if not isinstance(conversation, dict):
        return detail
    context = conversation.get("context_json")
    if not isinstance(context, dict):
        return detail
    message_log = context.get("message_log")
    if not isinstance(message_log, list):
        return detail

    phone = str(conversation.get("phone") or "").strip()
    expenses = [
        _attach_expense_receipt_urls(request, expense)
        for expense in _get_container(request).sheets.list_expenses()
        if str(expense.get("phone") or "").strip() == phone
    ]
    expenses_by_message_id = {
        str(expense.get("source_message_id") or "").strip(): expense
        for expense in expenses
        if str(expense.get("source_message_id") or "").strip()
    }

    enriched_messages: list[Any] = []
    for item in message_log:
        if not isinstance(item, dict):
            enriched_messages.append(item)
            continue
        message = dict(item)
        if str(message.get("type") or "").strip() != "media":
            enriched_messages.append(message)
            continue
        expense = expenses_by_message_id.get(str(message.get("message_id") or "").strip())
        if expense:
            image_url = str(expense.get("image_url") or "").strip()
            document_url = str(expense.get("document_url") or "").strip()
            if image_url and not str(message.get("image_url") or "").strip():
                message["image_url"] = image_url
            if document_url and not str(message.get("document_url") or "").strip():
                message["document_url"] = document_url
        enriched_messages.append(message)

    enriched_context = dict(context)
    enriched_context["message_log"] = enriched_messages
    enriched_conversation = dict(conversation)
    enriched_conversation["context_json"] = enriched_context
    return {**detail, "conversation": enriched_conversation}


def _safe_send_whatsapp_notification(
    request: Request,
    *,
    phone: str,
    message: str,
    reply_to_message_id: str | None = None,
) -> None:
    if not phone or not message:
        return
    try:
        _get_container(request).whatsapp.send_outbound_text(
            phone,
            message,
            reply_to_message_id=reply_to_message_id,
        )
    except Exception:
        pass


def _build_new_case_conversation_state(
    container: Any,
    conversation: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = container.conversation.ensure_conversation(conversation)
    current_context = normalized.get("context_json", {})
    if not isinstance(current_context, dict):
        current_context = {}

    next_context = container.conversation.default_context()

    message_log = current_context.get("message_log")
    if isinstance(message_log, list):
        next_context["message_log"] = [
            item for item in message_log if isinstance(item, dict)
        ][-MAX_MESSAGE_LOG_ITEMS:]

    scheduler_context = current_context.get("scheduler")
    if isinstance(scheduler_context, dict):
        next_context["scheduler"] = dict(scheduler_context)

    submission_closure = current_context.get("submission_closure", current_context.get("trip_closure"))
    if isinstance(submission_closure, dict):
        next_context["submission_closure"] = dict(submission_closure)
        next_context["trip_closure"] = dict(submission_closure)

    processed_message_ids = current_context.get("processed_message_ids")
    if isinstance(processed_message_ids, list):
        next_context["processed_message_ids"] = [str(item) for item in processed_message_ids if item][-50:]

    return {
        "state": "WAIT_RECEIPT",
        "current_step": "",
        "context_json": next_context,
    }


def _build_expense_status_notification(expense: dict[str, Any], action: str) -> str:
    merchant = str(expense.get("merchant", "") or "").strip() or "sin comercio"
    total = expense.get("total", "")
    currency = str(expense.get("currency", "") or "").strip()
    amount_str = f"{currency} {total}".strip() if total else ""
    reason = str(expense.get("review_reason", "") or "").strip()

    if action == "approve":
        return "Tu documento fue aprobado"
    if action == "reject":
        msg = f"Tu documento fue rechazado: {merchant}"
        if amount_str:
            msg += f" por {amount_str}"
        if reason:
            msg += f". Motivo: {reason}"
        return msg + ". Si tienes dudas, contacta a soporte."
    msg = f"Tu documento quedó en revisión manual: {merchant}"
    if amount_str:
        msg += f" por {amount_str}"
    return msg + ". Te avisaremos cuando haya una resolución."


def _build_case_deleted_notification(expense_case: dict[str, Any]) -> str:
    case_label = str(expense_case.get("context_label", "") or "").strip()
    case_id = str(expense_case.get("case_id", "") or "").strip()
    if case_label and case_id:
        case_reference = f"{case_label} ({case_id})"
    elif case_label:
        case_reference = case_label
    elif case_id:
        case_reference = case_id
    else:
        case_reference = "tu rendición"
    return f"Tu caso {case_reference} ha sido eliminado por administración."


def _log_outbound_bot_message(
    container: Any,
    *,
    phone: str,
    message: str,
    created_at: str | None = None,
) -> None:
    conversation = container.sheets.get_conversation(phone)
    if not conversation:
        conversation = container.sheets.update_conversation(
            phone,
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": container.conversation.default_context(),
            },
        )
    conversation = container.conversation.ensure_conversation(conversation)
    context = conversation.get("context_json", {})
    if not isinstance(context, dict):
        context = container.conversation.default_context()
    message_log = context.get("message_log", [])
    if not isinstance(message_log, list):
        message_log = []
    message_log.append(
        {
            "id": make_id("msg"),
            "speaker": "bot",
            "type": "text",
            "text": message,
            "created_at": created_at or utc_now_iso(),
        }
    )
    context["message_log"] = message_log[-MAX_MESSAGE_LOG_ITEMS:]
    container.sheets.update_conversation(
        phone,
        {
            "state": conversation.get("state", "WAIT_RECEIPT"),
            "current_step": conversation.get("current_step", ""),
            "context_json": context,
        },
    )


def _build_case_settlement_message(expense_case: dict[str, Any]) -> str:
    case_id = str(expense_case.get("case_id", "") or "").strip() or "sin id"
    fondos = expense_case.get("fondos_entregados", "")
    aprobado = expense_case.get("monto_rendido_aprobado", "")
    direction = str(expense_case.get("settlement_direction", "") or "").strip()
    amount = expense_case.get("settlement_amount_clp", "")

    lines = [
        f"Resumen de tu rendición {case_id}:",
        f"- Fondos entregados: CLP {fondos}",
        f"- Monto aprobado: CLP {aprobado}",
    ]
    if direction == "balanced":
        lines.append("- Resultado: la rendición quedó cuadrada.")
    elif direction == "company_owes_employee":
        lines.append(f"- Resultado: la empresa debe reembolsarte CLP {amount}.")
    elif direction == "employee_owes_company":
        lines.append(f"- Resultado: debes devolver CLP {amount} a la empresa.")
    return "\n".join(lines)


@router.post("/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request) -> LoginResponse:
    container = _get_container(request)
    try:
        user = container.backoffice_auth.authenticate(payload.email, payload.password)
    except Exception as exc:
        if _is_transient_dependency_error(exc):
            logger.warning("Backoffice login temporarily unavailable: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Servicio de autenticación temporalmente no disponible. Intenta nuevamente.",
            ) from exc
        raise
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    token = container.backoffice_auth.create_access_token(user)
    return LoginResponse(access_token=token, user=_safe_user_payload(user))


@router.post("/auth/setup-password/request")
def request_password_setup(payload: SetupPasswordRequest, request: Request) -> dict[str, Any]:
    container = _get_container(request)
    email = str(payload.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ingresa un email válido")
    try:
        user = container.sheets.get_user_by_email(email)
    except Exception as exc:
        if _is_transient_dependency_error(exc):
            logger.warning("Backoffice password setup lookup temporarily unavailable: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Servicio de autenticación temporalmente no disponible. Intenta nuevamente.",
            ) from exc
        raise
    if not user or not user.get("active"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No hay una cuenta activa registrada con ese email.",
        )
    if container.backoffice_auth.user_has_password(user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta cuenta ya tiene clave. Ingresa con tu password.",
        )
    return {"email": email, "name": user.get("name", ""), "can_setup_password": True}


@router.post("/auth/setup-password", response_model=LoginResponse)
def setup_password(payload: SetupPasswordPayload, request: Request) -> LoginResponse:
    container = _get_container(request)
    try:
        user = container.backoffice_auth.setup_password(
            payload.email,
            payload.password,
            name=payload.name,
        )
    except Exception as exc:
        if _is_transient_dependency_error(exc):
            logger.warning("Backoffice password setup temporarily unavailable: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Servicio de autenticación temporalmente no disponible. Intenta nuevamente.",
            ) from exc
        raise
    if not user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede crear clave para esta cuenta.",
        )
    token = container.backoffice_auth.create_access_token(user)
    return LoginResponse(access_token=token, user=_safe_user_payload(user))


@router.get("/auth/me")
def me(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return _safe_user_payload(user)


@router.get("/users")
def list_backoffice_users(
    request: Request,
    _: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return {"items": [_safe_user_payload(user) for user in _get_container(request).sheets.list_users()]}


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_backoffice_user(
    payload: BackofficeUserPayload,
    request: Request,
    user: dict[str, Any] = Depends(require_super_admin),
) -> dict[str, Any]:
    container = _get_container(request)
    email = str(payload.email or "").strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ingresa un email válido")
    if container.sheets.get_user_by_email(email):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe un usuario con ese email")

    requester_access = resolve_access(user)
    requested_role = str(payload.role or COMPANY_ADMIN_ROLE).strip().lower()
    if requested_role not in {SUPER_ADMIN_ROLE, LEGACY_ADMIN_ROLE, COMPANY_ADMIN_ROLE, "operator"}:
        requested_role = COMPANY_ADMIN_ROLE

    requested_scope = str(payload.scope_type or COMPANY_SCOPE).strip().lower()
    company_ids = [str(item or "").strip() for item in payload.company_ids if str(item or "").strip()]
    if payload.company_id and str(payload.company_id).strip() not in company_ids:
        company_ids.append(str(payload.company_id).strip())

    if not requester_access.is_global:
        requested_scope = COMPANY_SCOPE
        if requested_role == SUPER_ADMIN_ROLE:
            requested_role = COMPANY_ADMIN_ROLE
        company_ids = [company_id for company_id in company_ids if can_access_company(user, company_id)]
        if not company_ids and requester_access.company_ids:
            company_ids = sorted(requester_access.company_ids)
        if not company_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes empresas asignadas para crear usuarios.",
            )
    elif requested_role == SUPER_ADMIN_ROLE or requested_scope == GLOBAL_SCOPE:
        requested_scope = GLOBAL_SCOPE
        company_ids = []
    else:
        requested_scope = COMPANY_SCOPE

    now = utc_now_iso()
    created = container.sheets.upsert_user(
        make_id("usr"),
        {
            "name": str(payload.name or "").strip() or email.split("@", 1)[0],
            "email": email,
            "password_hash": "",
            "role": requested_role,
            "scope_type": requested_scope,
            "company_ids": company_ids,
            "company_id": company_ids[0] if len(company_ids) == 1 else "",
            "active": payload.active,
            "created_at": now,
            "updated_at": now,
        },
    )
    return _safe_user_payload(created)


@router.get("/dashboard")
def dashboard(
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return _get_container(request).backoffice.get_dashboard(user)


@router.get("/employees")
def list_employees(
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"items": _get_container(request).backoffice.list_employees(user)}


@router.get("/companies")
def list_companies(
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"items": _get_container(request).backoffice.list_companies(user)}


@router.post("/employees", status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeePayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    _ensure_user_can_access_company(user, payload.company_id)
    return _get_container(request).backoffice.create_employee(payload.model_dump())


@router.get("/employees/{phone}")
def get_employee(
    phone: str,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    detail = _get_container(request).backoffice.get_employee_detail(phone, user)
    if not detail:
        raise HTTPException(status_code=404, detail="Employee not found")
    return detail


@router.put("/employees/{phone}")
def update_employee(
    phone: str,
    payload: EmployeePayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    existing = _get_container(request).backoffice.get_employee_detail(phone, user)
    if not existing:
        raise HTTPException(status_code=404, detail="Employee not found")
    _ensure_user_can_access_company(user, payload.company_id)
    employee = _get_container(request).backoffice.update_employee(phone, payload.model_dump())
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


@router.post("/employees/{phone}/actions")
def employee_action(
    phone: str,
    payload: StatusActionPayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    if payload.action not in {"deactivate", "activate"}:
        raise HTTPException(status_code=400, detail="Unsupported action")
    existing = _get_container(request).backoffice.get_employee_detail(phone, user)
    if not existing:
        raise HTTPException(status_code=404, detail="Employee not found")
    employee = _get_container(request).backoffice.update_employee(
        phone,
        {"active": payload.action == "activate"},
    )
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


@router.delete("/employees/{phone}")
def delete_employee(
    phone: str,
    request: Request,
    delete_cases: bool = Query(default=False),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    existing = _get_container(request).backoffice.get_employee_detail(phone, user)
    if not existing:
        raise HTTPException(status_code=404, detail="Employee not found")
    result = _get_container(request).backoffice.delete_employee_with_related_data(
        phone,
        delete_cases=delete_cases,
    )
    if not result:
        raise HTTPException(status_code=404, detail="Employee not found")
    return result


@router.get("/cases")
def list_cases(
    request: Request,
    cost_center: str = Query(default=""),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {
        "items": _get_container(request).backoffice.list_cases(
            {"cost_center": cost_center},
            user,
        )
    }


@router.post("/cases", status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CasePayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    container = _get_container(request)
    _ensure_user_can_access_company(user, payload.company_id)
    try:
        expense_case = container.backoffice.create_case(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    phone = str(expense_case.get("employee_phone", expense_case.get("phone", "")) or "").strip()
    if phone:
        timezone_name = "America/Santiago"
        messages: list[str] = []
        try:
            timezone_name = container.scheduler._resolve_case_timezone(expense_case)
            messages = container.scheduler._build_submission_start_intro_messages(
                expense_case=expense_case
            )
            conversation = container.sheets.update_conversation(
                phone,
                _build_new_case_conversation_state(
                    container,
                    container.sheets.get_conversation(phone),
                ),
            )
        except Exception as exc:
            expense_case["intro_notification"] = {
                "status": "conversation_reset_failed",
                "error": str(exc),
            }
            logger.exception(
                "Failed to reset conversation for new case intro case_id=%s phone=%s",
                str(expense_case.get("case_id", "") or "").strip() or None,
                phone,
            )
            return expense_case

        try:
            sent_at_utc = utc_now_iso()
            send_results = [
                container.whatsapp.send_outbound_text(phone, message)
                for message in messages
            ]
            conversation = container.sheets.get_conversation(phone)
            conversation = container.conversation.ensure_conversation(conversation)
            context = conversation.get("context_json", {})
            message_log = context.get("message_log", [])
            if not isinstance(message_log, list):
                message_log = []
            for message in messages:
                message_log.append(
                    {
                        "id": make_id("msg"),
                        "speaker": "bot",
                        "type": "text",
                        "text": message,
                        "created_at": sent_at_utc,
                    }
                )
            context["message_log"] = message_log[-MAX_MESSAGE_LOG_ITEMS:]
            container.sheets.update_conversation(
                phone,
                {
                    "state": conversation.get("state", "WAIT_RECEIPT"),
                    "current_step": conversation.get("current_step", ""),
                    "context_json": context,
                },
            )
            reminder_key = container.scheduler._submission_start_intro_key(
                case_id=str(expense_case.get("case_id", "") or "").strip(),
                local_date=datetime.now(ZoneInfo(timezone_name)).date().isoformat(),
            )
            container.scheduler._mark_reminder_sent(
                phone=phone,
                reminder_key=reminder_key,
                payload={
                    "sent_at_utc": sent_at_utc,
                    "slot": "submission_start_intro_manual",
                    "case_id": str(expense_case.get("case_id", "") or "").strip(),
                    "timezone": timezone_name,
                    "twilio_message_sid": send_results[-1].get("sid") if send_results else None,
                },
            )
            expense_case["intro_notification"] = {
                "status": "sent",
                "message_count": len(messages),
            }
        except Exception as exc:
            expense_case["intro_notification"] = {
                "status": "send_failed",
                "error": str(exc),
            }
            logger.exception(
                "Failed to send new case intro WhatsApp case_id=%s phone=%s provider=%s",
                str(expense_case.get("case_id", "") or "").strip() or None,
                phone,
                str(getattr(container.whatsapp, "provider", "") or "") or None,
            )

    return expense_case


@router.get("/cases/{case_id}")
def get_case(
    case_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    detail = _get_container(request).backoffice.get_case_detail(case_id, user)
    if not detail:
        raise HTTPException(status_code=404, detail="Case not found")
    return detail


def _build_case_context_for_ai(detail: dict[str, Any]) -> str:
    case = detail.get("case") or {}
    employee = detail.get("employee") or {}
    expenses = detail.get("expenses") or []

    lines: list[str] = []

    case_id = str(case.get("case_id", "") or "").strip()
    label = str(case.get("context_label", "") or "").strip()
    if case_id:
        lines.append(f"Rendición ID: {case_id}" + (f" — {label}" if label else ""))

    emp_name = str(employee.get("name", "") or "").strip()
    emp_phone = str(employee.get("phone", "") or "").strip()
    if emp_name or emp_phone:
        lines.append(f"Empleado: {emp_name or 'Sin nombre'} ({emp_phone})")

    rendicion_status_labels = {
        "open": "Abierta",
        "pending_user_confirmation": "Pendiente confirmación usuario",
        "approved": "Aprobada",
        "closed": "Cerrada",
    }
    rendicion_status = str(case.get("rendicion_status", "") or "open").strip()
    lines.append(f"Estado rendición: {rendicion_status_labels.get(rendicion_status, rendicion_status)}")

    cost_centers = case.get("cost_centers") or []
    if cost_centers:
        lines.append(f"Centros de costo: {', '.join(str(c) for c in cost_centers)}")

    def _parse_num(v: Any) -> float:
        try:
            return float(str(v).replace(",", ".")) if v not in (None, "", "None") else 0.0
        except (ValueError, TypeError):
            return 0.0

    fondos = _parse_num(case.get("fondos_entregados"))
    if fondos:
        lines.append(f"Fondos entregados: ${fondos:,.0f} CLP")

    approved = _parse_num(case.get("monto_rendido_aprobado"))
    pending = _parse_num(case.get("monto_pendiente_revision"))
    saldo = _parse_num(case.get("saldo_restante"))
    if approved or pending:
        lines.append(f"Monto aprobado: ${approved:,.0f} CLP | Pendiente revisión: ${pending:,.0f} CLP")
    if fondos:
        lines.append(f"Saldo restante: ${saldo:,.0f} CLP")

    if expenses:
        lines.append(f"\nGastos registrados ({len(expenses)}):")
        status_labels = {
            "approved": "aprobado",
            "rejected": "rechazado",
            "pending_approval": "pendiente",
            "needs_manual_review": "revisión manual",
            "observed": "observado",
        }
        for exp in expenses:
            merchant = str(exp.get("merchant", "") or "Sin nombre").strip()
            date = str(exp.get("date", "") or "").strip()
            total = _parse_num(exp.get("total_clp") or exp.get("total"))
            currency = str(exp.get("currency", "CLP") or "CLP").strip()
            category = str(exp.get("category", "") or "").strip()
            cost_center = str(exp.get("cost_center", "") or "").strip()
            exp_status = str(exp.get("review_status", exp.get("status", "")) or "").strip()
            doc_type = str(exp.get("document_type", "") or "").strip()
            doc_labels = {"receipt": "boleta", "invoice": "factura", "professional_fee_receipt": "honorarios"}
            parts = [f"- {merchant}"]
            if date:
                parts.append(f"({date})")
            if total:
                parts.append(f"${total:,.0f} {currency}")
            if category:
                parts.append(f"[{category}]")
            if cost_center:
                parts.append(f"CC: {cost_center}")
            if doc_type:
                parts.append(f"Tipo: {doc_labels.get(doc_type, doc_type)}")
            if exp_status:
                parts.append(f"Estado: {status_labels.get(exp_status, exp_status)}")
            lines.append(" ".join(parts))
    else:
        lines.append("Sin gastos registrados.")

    return "\n".join(lines)


@router.post("/cases/{case_id}/chat")
def case_chat(
    case_id: str,
    payload: CaseChatPayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    container = _get_container(request)
    detail = container.backoffice.get_case_detail(case_id, user)
    if not detail:
        raise HTTPException(status_code=404, detail="Case not found")

    llm = getattr(getattr(container, "expense", None), "llm_service", None)
    if not llm or not getattr(llm, "chat_assistant_enabled", False):
        raise HTTPException(status_code=503, detail="Asistente IA no disponible")

    context_text = _build_case_context_for_ai(detail)
    history = [{"role": m.role, "content": m.content} for m in payload.history]
    answer = llm.chat_case_backoffice(
        message=payload.message,
        case_context_text=context_text,
        history=history,
    )
    if not answer:
        raise HTTPException(status_code=503, detail="No se pudo obtener respuesta del asistente")

    return {"answer": answer}


@router.put("/cases/{case_id}")
def update_case(
    case_id: str,
    payload: CasePayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    existing = _get_container(request).backoffice.get_case_detail(case_id, user)
    if not existing:
        raise HTTPException(status_code=404, detail="Case not found")
    _ensure_user_can_access_company(user, payload.company_id)
    expense_case = _get_container(request).backoffice.update_case(
        case_id,
        payload.model_dump(exclude_none=True),
    )
    if not expense_case:
        raise HTTPException(status_code=404, detail="Case not found")
    return expense_case


@router.delete("/cases/{case_id}")
def delete_case(
    case_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    container = _get_container(request)
    existing = container.backoffice.get_case_detail(case_id, user)
    if not existing:
        raise HTTPException(status_code=404, detail="Case not found")
    result = container.backoffice.delete_case_with_related_data(case_id)
    if not result:
        raise HTTPException(status_code=404, detail="Case not found")
    deleted_case = result.get("case") or existing.get("case") or {}
    phone = str(
        deleted_case.get("employee_phone", deleted_case.get("phone", "")) or ""
    ).strip()
    if phone:
        message = _build_case_deleted_notification(deleted_case)
        try:
            container.whatsapp.send_outbound_text(phone, message)
            _log_outbound_bot_message(container, phone=phone, message=message)
            result["delete_notification"] = {"status": "sent"}
        except Exception as exc:
            result["delete_notification"] = {
                "status": "send_failed",
                "error": str(exc),
            }
            logger.exception(
                "Failed to send case deletion WhatsApp case_id=%s phone=%s provider=%s",
                case_id,
                phone,
                str(getattr(container.whatsapp, "provider", "") or "") or None,
            )
    return result


@router.post("/cases/{case_id}/actions")
def case_action(
    case_id: str,
    payload: StatusActionPayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    container = _get_container(request)
    if not container.backoffice.get_case_detail(case_id, user):
        raise HTTPException(status_code=404, detail="Case not found")

    # Legacy status actions
    status_map = {"close": CaseStatus.CLOSED, "reopen": CaseStatus.ACTIVE}
    if payload.action in status_map:
        expense_case = container.backoffice.update_case(
            case_id, {"status": status_map[payload.action]}
        )
        if not expense_case:
            raise HTTPException(status_code=404, detail="Case not found")
        return expense_case

    # Rendición lifecycle actions
    if payload.action == "request_user_confirmation":
        try:
            container.backoffice.ensure_case_ready_for_document_confirmation(case_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        expense_case = container.backoffice.update_case(
            case_id,
            {
                "rendicion_status": RendicionStatus.PENDING_USER_CONFIRMATION,
                "user_confirmation_status": "pending",
            },
        )
        if not expense_case:
            raise HTTPException(status_code=404, detail="Case not found")
        phone = expense_case.get("employee_phone", expense_case.get("phone", ""))
        if phone:
            try:
                msg = container.scheduler._deliver_submission_closure_package(
                    phone=phone, case_id=case_id,
                )
                if msg:
                    container.whatsapp.send_outbound_text(phone, msg)
            except Exception:
                pass
        return expense_case

    if payload.action == "resolve_settlement":
        try:
            container.backoffice.ensure_case_ready_for_settlement_resolution(case_id)
            expense_case = container.backoffice.sync_case_settlement(
                case_id,
                mark_settled=True,
                resolved_at=utc_now_iso(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not expense_case:
            raise HTTPException(status_code=404, detail="Case not found")
        expense_case = container.backoffice.update_case(
            case_id,
            {"rendicion_status": RendicionStatus.CLOSED, "status": CaseStatus.CLOSED},
        )
        if not expense_case:
            raise HTTPException(status_code=404, detail="Case not found")
        phone = str(expense_case.get("employee_phone", expense_case.get("phone", "")) or "").strip()
        if phone:
            _safe_send_whatsapp_notification(
                request,
                phone=phone,
                message=container.backoffice.build_case_settlement_resolved_whatsapp_message(
                    expense_case
                ),
            )
        return expense_case

    if payload.action == "close_rendicion":
        try:
            container.backoffice.ensure_case_ready_for_close(case_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        expense_case = container.backoffice.update_case(
            case_id,
            {"rendicion_status": RendicionStatus.CLOSED, "status": CaseStatus.CLOSED},
        )
        if not expense_case:
            raise HTTPException(status_code=404, detail="Case not found")
        phone = str(expense_case.get("employee_phone", expense_case.get("phone", "")) or "").strip()
        if phone:
            _safe_send_whatsapp_notification(
                request,
                phone=phone,
                message=(
                    "Tu rendición quedó completamente cerrada.\n"
                    + _build_case_settlement_message(expense_case)
                ),
            )
        return expense_case

    raise HTTPException(status_code=400, detail="Unsupported action")


@router.get("/expenses")
def list_expenses(
    request: Request,
    status_value: str = Query(default="", alias="status"),
    review_status: str = Query(default=""),
    employee_phone: str = Query(default=""),
    category: str = Query(default=""),
    cost_center: str = Query(default=""),
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    sort_by: str = Query(default=""),
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {
        "items": _get_container(request).backoffice.list_expenses(
            {
                "status": status_value,
                "review_status": review_status,
                "employee_phone": employee_phone,
                "category": category,
                "cost_center": cost_center,
                "date_from": date_from,
                "date_to": date_to,
                "sort_by": sort_by,
            },
            user,
        )
    }


@router.get("/expenses/{expense_id}")
def get_expense(
    expense_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    detail = _get_container(request).backoffice.get_expense_detail(expense_id, user)
    if not detail:
        raise HTTPException(status_code=404, detail="Expense not found")
    detail["expense"] = _attach_expense_receipt_urls(request, detail["expense"])
    return detail


@router.put("/expenses/{expense_id}")
def update_expense(
    expense_id: str,
    payload: ExpensePayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    if not _get_container(request).backoffice.get_expense_detail(expense_id, user):
        raise HTTPException(status_code=404, detail="Expense not found")
    expense = _get_container(request).backoffice.update_expense(expense_id, payload.model_dump())
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return _attach_expense_receipt_urls(request, expense)


@router.post("/expenses/{expense_id}/actions")
def expense_action(
    expense_id: str,
    payload: StatusActionPayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    container = _get_container(request)
    if not container.backoffice.get_expense_detail(expense_id, user):
        raise HTTPException(status_code=404, detail="Expense not found")
    status_map = {
        "approve": ExpenseStatus.APPROVED,
        "reject": ExpenseStatus.REJECTED,
    }
    if payload.action not in status_map:
        raise HTTPException(status_code=400, detail="Unsupported action")
    update_payload: dict[str, Any] = {"status": status_map[payload.action]}
    if payload.action in ("approve", "reject"):
        update_payload["review_status"] = status_map[payload.action]
    if payload.action == "reject":
        reason = str(payload.reason or "").strip()
        if not reason:
            raise HTTPException(status_code=400, detail="Debes indicar el motivo del rechazo.")
        update_payload["review_reason"] = reason
    elif payload.action == "approve":
        update_payload["review_reason"] = ""
    expense = container.backoffice.update_expense(expense_id, update_payload)
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")

    balance_warning: str | None = None
    phone = str(expense.get("phone", "") or "").strip()
    if phone:
        reply_target = _get_expense_reply_target(request, expense)
        msg = _build_expense_status_notification(expense, payload.action)
        _safe_send_whatsapp_notification(
            request,
            phone=phone,
            message=msg,
            reply_to_message_id=reply_target,
        )

    if payload.action == "approve":
        # Check for negative balance after approval
        case_id = str(expense.get("case_id", "") or "").strip()
        if case_id:
            case_detail = container.backoffice.get_case_detail(case_id)
            if case_detail:
                saldo = case_detail["case"].get("saldo_restante", 0)
                if isinstance(saldo, (int, float)) and saldo < 0:
                    balance_warning = (
                        f"La rendición {case_id} tiene saldo negativo: "
                        f"${abs(saldo):,.0f} CLP sobre los fondos entregados."
                    )

    result: dict[str, Any] = dict(expense)
    if balance_warning:
        result["_balance_warning"] = balance_warning
    return result


@router.get("/cases/export/csv")
def export_cases_csv(
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> StreamingResponse:
    cases = _get_container(request).backoffice.list_cases(user=user)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "case_id",
        "nombre_rendicion",
        "empleado",
        "telefono",
        "empresa",
        "centros_costo",
        "fondos_entregados",
        "rendido_aprobado",
        "pendiente_revision",
        "saldo_restante",
        "estado_rendicion",
        "estado",
        "documentos",
        "creado",
        "actualizado",
    ])
    for c in cases:
        emp = c.get("employee") or {}
        writer.writerow([
            c.get("case_id", ""),
            c.get("context_label", ""),
            emp.get("name", ""),
            c.get("employee_phone", c.get("phone", "")),
            c.get("company_id", ""),
            ", ".join(str(center) for center in c.get("cost_centers", [])),
            c.get("fondos_entregados", ""),
            c.get("monto_rendido_aprobado", ""),
            c.get("monto_pendiente_revision", ""),
            c.get("saldo_restante", ""),
            c.get("rendicion_status", ""),
            c.get("status", ""),
            c.get("expense_count", 0),
            c.get("created_at", ""),
            c.get("updated_at", ""),
        ])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=rendiciones.csv"},
    )


@router.get("/expenses/export/csv")
def export_expenses_csv(
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> StreamingResponse:
    expenses = _get_container(request).backoffice.list_expenses(user=user)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "expense_id",
        "case_id",
        "empleado",
        "telefono",
        "merchant",
        "fecha",
        "moneda",
        "total",
        "total_clp",
        "categoria",
        "centro_costo",
        "pais",
        "estado",
        "review_status",
        "review_score",
        "tipo_documento",
        "creado",
    ])
    for e in expenses:
        emp = e.get("employee") or {}
        writer.writerow([
            e.get("expense_id", ""),
            e.get("case_id", ""),
            emp.get("name", ""),
            e.get("phone", ""),
            e.get("merchant", ""),
            e.get("date", ""),
            e.get("currency", ""),
            e.get("total", ""),
            e.get("total_clp", ""),
            e.get("category", ""),
            e.get("cost_center", ""),
            e.get("country", ""),
            e.get("status", ""),
            e.get("review_status", ""),
            e.get("review_score", ""),
            e.get("document_type", ""),
            e.get("created_at", ""),
        ])
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=gastos.csv"},
    )


@router.get("/conversations")
def list_conversations(
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"items": _get_container(request).backoffice.list_conversations(user)}


@router.get("/conversations/{phone}")
def get_conversation(
    phone: str,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    detail = _get_container(request).backoffice.get_conversation_detail(phone, user)
    if not detail:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _enrich_conversation_media_messages(request, detail)


@router.put("/conversations/{phone}")
def update_conversation(
    phone: str,
    payload: ConversationPayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    if not _get_container(request).backoffice.get_conversation_detail(phone, user):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _get_container(request).backoffice.update_conversation(phone, payload.model_dump())


@router.post("/conversations/{phone}/messages")
def send_conversation_message(
    phone: str,
    payload: SendMessagePayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    """Send a message from the backoffice operator to the user via WhatsApp."""
    container = _get_container(request)
    if not container.backoffice.get_conversation_detail(phone, user):
        raise HTTPException(status_code=404, detail="Conversation not found")
    message_text = payload.message.strip()

    # Send via WhatsApp
    try:
        container.whatsapp.send_outbound_text(phone, message_text)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo enviar el mensaje por WhatsApp: {exc}",
        ) from exc

    # Log message in conversation message_log
    conversation = container.sheets.get_conversation(phone)
    if not conversation:
        conversation = container.sheets.update_conversation(
            phone,
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": container.conversation.default_context(),
            },
        )
    conversation = container.conversation.ensure_conversation(conversation)
    context = conversation.get("context_json", {})
    message_log = context.get("message_log", [])
    if not isinstance(message_log, list):
        message_log = []

    operator_name = str(user.get("name", "") or user.get("email", "") or "Operador").strip()
    new_entry = {
        "id": make_id("msg"),
        "speaker": "operator",
        "type": "text",
        "text": message_text,
        "created_at": utc_now_iso(),
        "operator_name": operator_name,
    }
    message_log.append(new_entry)
    message_log = message_log[-MAX_MESSAGE_LOG_ITEMS:]
    context["message_log"] = message_log

    container.sheets.update_conversation(
        phone,
        {
            "state": conversation.get("state", "WAIT_RECEIPT"),
            "current_step": conversation.get("current_step", ""),
            "context_json": context,
        },
    )

    # Clear human assistance flag when an operator replies
    try:
        active_case = container.sheets.get_active_expense_case_by_phone(phone)
        if active_case:
            case_id = str(active_case.get("case_id", "") or "").strip()
            if case_id and active_case.get("human_assistance_requested"):
                container.sheets.update_expense_case(
                    case_id,
                    {"human_assistance_requested": False, "human_assistance_message": ""},
                )
    except Exception:
        logger.exception(
            "Failed to clear human_assistance_requested for phone=%s",
            phone,
        )

    return {
        "ok": True,
        "message": new_entry,
        "conversation": container.backoffice.get_conversation_detail(phone, user),
    }


@router.post("/conversations/{phone}/actions")
def conversation_action(
    phone: str,
    payload: StatusActionPayload,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    if payload.action != "resolve":
        raise HTTPException(status_code=400, detail="Unsupported action")
    if not _get_container(request).backoffice.get_conversation_detail(phone, user):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return _get_container(request).backoffice.update_conversation(phone, {"state": "DONE"})
