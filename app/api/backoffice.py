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
    CasePayload,
    ConversationPayload,
    EmployeePayload,
    ExpensePayload,
    LoginRequest,
    LoginResponse,
    SendMessagePayload,
    StatusActionPayload,
)
from services.statuses import (
    CaseStatus,
    ExpenseReviewStatus,
    ExpenseStatus,
    RendicionStatus,
)
from utils.helpers import make_id, utc_now_iso


router = APIRouter(prefix="/api", tags=["backoffice"])
logger = logging.getLogger(__name__)


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
        next_context["message_log"] = [item for item in message_log if isinstance(item, dict)][-100:]

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

    if action == "approve":
        msg = f"Tu documento fue aprobado: {merchant}"
        if amount_str:
            msg += f" por {amount_str}"
        return msg + "."
    if action == "reject":
        msg = f"Tu documento fue rechazado: {merchant}"
        if amount_str:
            msg += f" por {amount_str}"
        return msg + ". Si tienes dudas, contacta a soporte."
    if action == "observe":
        msg = f"Tu documento quedó observado: {merchant}"
        if amount_str:
            msg += f" por {amount_str}"
        return msg + ". Podrían pedirte información adicional."
    msg = f"Tu documento quedó en revisión manual: {merchant}"
    if amount_str:
        msg += f" por {amount_str}"
    return msg + ". Te avisaremos cuando haya una resolución."


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
    safe_user = {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
        "active": user.get("active"),
    }
    return LoginResponse(access_token=token, user=safe_user)


@router.get("/auth/me")
def me(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "role": user.get("role"),
        "active": user.get("active"),
    }


@router.get("/dashboard")
def dashboard(
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return _get_container(request).backoffice.get_dashboard()


@router.get("/employees")
def list_employees(
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"items": _get_container(request).backoffice.list_employees()}


@router.get("/companies")
def list_companies(
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"items": _get_container(request).backoffice.list_companies()}


@router.post("/employees", status_code=status.HTTP_201_CREATED)
def create_employee(
    payload: EmployeePayload,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return _get_container(request).backoffice.create_employee(payload.model_dump())


@router.get("/employees/{phone}")
def get_employee(
    phone: str,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    detail = _get_container(request).backoffice.get_employee_detail(phone)
    if not detail:
        raise HTTPException(status_code=404, detail="Employee not found")
    return detail


@router.put("/employees/{phone}")
def update_employee(
    phone: str,
    payload: EmployeePayload,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    employee = _get_container(request).backoffice.update_employee(phone, payload.model_dump())
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return employee


@router.post("/employees/{phone}/actions")
def employee_action(
    phone: str,
    payload: StatusActionPayload,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    if payload.action not in {"deactivate", "activate"}:
        raise HTTPException(status_code=400, detail="Unsupported action")
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
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
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
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"items": _get_container(request).backoffice.list_cases()}


@router.post("/cases", status_code=status.HTTP_201_CREATED)
def create_case(
    payload: CasePayload,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    container = _get_container(request)
    try:
        expense_case = container.backoffice.create_case(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    phone = str(expense_case.get("employee_phone", expense_case.get("phone", "")) or "").strip()
    if phone:
        try:
            timezone_name = container.scheduler._resolve_case_timezone(expense_case)
            sent_at_utc = utc_now_iso()
            messages = container.scheduler._build_submission_start_intro_messages(
                expense_case=expense_case
            )
            send_results = [
                container.whatsapp.send_outbound_text(phone, message)
                for message in messages
            ]
            conversation = container.sheets.update_conversation(
                phone,
                _build_new_case_conversation_state(
                    container,
                    container.sheets.get_conversation(phone),
                ),
            )
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
            context["message_log"] = message_log[-100:]
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
        except Exception:
            pass

    return expense_case


@router.get("/cases/{case_id}")
def get_case(
    case_id: str,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    detail = _get_container(request).backoffice.get_case_detail(case_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Case not found")
    return detail


@router.put("/cases/{case_id}")
def update_case(
    case_id: str,
    payload: CasePayload,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    expense_case = _get_container(request).backoffice.update_case(case_id, payload.model_dump())
    if not expense_case:
        raise HTTPException(status_code=404, detail="Case not found")
    return expense_case


@router.post("/cases/{case_id}/actions")
def case_action(
    case_id: str,
    payload: StatusActionPayload,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    container = _get_container(request)

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
    date_from: str = Query(default=""),
    date_to: str = Query(default=""),
    sort_by: str = Query(default=""),
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {
        "items": _get_container(request).backoffice.list_expenses(
            {
                "status": status_value,
                "review_status": review_status,
                "employee_phone": employee_phone,
                "category": category,
                "date_from": date_from,
                "date_to": date_to,
                "sort_by": sort_by,
            }
        )
    }


@router.get("/expenses/{expense_id}")
def get_expense(
    expense_id: str,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    detail = _get_container(request).backoffice.get_expense_detail(expense_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Expense not found")
    detail["expense"] = _attach_expense_receipt_urls(request, detail["expense"])
    return detail


@router.put("/expenses/{expense_id}")
def update_expense(
    expense_id: str,
    payload: ExpensePayload,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    expense = _get_container(request).backoffice.update_expense(expense_id, payload.model_dump())
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    return _attach_expense_receipt_urls(request, expense)


@router.post("/expenses/{expense_id}/actions")
def expense_action(
    expense_id: str,
    payload: StatusActionPayload,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    container = _get_container(request)
    status_map = {
        "approve": ExpenseStatus.APPROVED,
        "reject": ExpenseStatus.REJECTED,
        "observe": ExpenseStatus.OBSERVED,
        "request_review": ExpenseStatus.NEEDS_MANUAL_REVIEW,
    }
    if payload.action not in status_map:
        raise HTTPException(status_code=400, detail="Unsupported action")
    update_payload: dict[str, Any] = {"status": status_map[payload.action]}
    if payload.action in ("approve", "reject"):
        update_payload["review_status"] = status_map[payload.action]
    elif payload.action == "observe":
        update_payload["review_status"] = ExpenseReviewStatus.OBSERVED
    elif payload.action == "request_review":
        update_payload["review_status"] = ExpenseReviewStatus.NEEDS_MANUAL_REVIEW
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
    _: dict[str, Any] = Depends(require_user),
) -> StreamingResponse:
    cases = _get_container(request).backoffice.list_cases()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "case_id",
        "nombre_rendicion",
        "empleado",
        "telefono",
        "empresa",
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
    _: dict[str, Any] = Depends(require_user),
) -> StreamingResponse:
    expenses = _get_container(request).backoffice.list_expenses()
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
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    return {"items": _get_container(request).backoffice.list_conversations()}


@router.get("/conversations/{phone}")
def get_conversation(
    phone: str,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    detail = _get_container(request).backoffice.get_conversation_detail(phone)
    if not detail:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.put("/conversations/{phone}")
def update_conversation(
    phone: str,
    payload: ConversationPayload,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
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
    message_log = message_log[-100:]
    context["message_log"] = message_log

    container.sheets.update_conversation(
        phone,
        {
            "state": conversation.get("state", "WAIT_RECEIPT"),
            "current_step": conversation.get("current_step", ""),
            "context_json": context,
        },
    )

    return {
        "ok": True,
        "message": new_entry,
        "conversation": container.backoffice.get_conversation_detail(phone),
    }


@router.post("/conversations/{phone}/actions")
def conversation_action(
    phone: str,
    payload: StatusActionPayload,
    request: Request,
    _: dict[str, Any] = Depends(require_user),
) -> dict[str, Any]:
    if payload.action != "resolve":
        raise HTTPException(status_code=400, detail="Unsupported action")
    return _get_container(request).backoffice.update_conversation(phone, {"state": "DONE"})
