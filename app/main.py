from __future__ import annotations

import asyncio
import hmac
import html
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.api import backoffice_router
from app.config import settings
from app.logging_config import configure_logging, request_id_context
from services.consolidated_document_service import ConsolidatedDocumentService
from services.conversation_service import (
    CATEGORY_OPTIONS,
    COUNTRY_OPTIONS,
    CURRENCY_OPTIONS,
    DOCUMENT_TYPE_OPTIONS,
    ConversationService,
    get_correction_field_label,
    get_correction_field_options,
)
from services.backoffice_auth_service import BackofficeAuthService
from services.backoffice_service import BackofficeService
from services.docusign_service import DocusignError, DocusignService
from services.expense_service import ExpenseService
from services.llm_service import LLMService
from services.monthly_accounting_export_service import MonthlyAccountingExportService
from services.porta_excel_export_service import PortaExcelExportService
from services.porta_export_service import PortaExportService
from services.ocr_service import OCRService
from services.scheduler_service import SchedulerService
from services.sheets_service import SheetsService, normalize_cost_centers
from services.storage_service import GCSStorageService
from services.expense_case_service import ExpenseCaseService
from services.statuses import ExpenseStatus, RendicionStatus, SettlementDirection, SettlementStatus, normalize_state
from services.whatsapp_service import (
    MetaAccessTokenExpiredError,
    TwilioDailyLimitExceededError,
    WhatsAppService,
)
from utils.helpers import make_id, normalize_whatsapp_phone, parse_float, utc_now_iso

logger = logging.getLogger(__name__)

configure_logging(level=settings.log_level, log_format=settings.log_format)


HUMAN_ASSISTANCE_PHRASES = frozenset([
    "quiero hablar con un humano",
    "quiero hablar con una persona",
    "quiero hablar con alguien",
    "quiero hablar con un operador",
    "quiero hablar con una operadora",
    "quiero hablar con un agente",
    "hablar con un humano",
    "hablar con una persona",
    "hablar con el operador",
    "hablar con un operador",
    "hablar con una operadora",
    "hablar con un agente",
    "necesito asistencia humana",
    "necesito hablar con alguien",
    "necesito un humano",
    "necesito ayuda humana",
    "asistencia humana",
    "ayuda humana",
    "atencion humana",
    "atención humana",
    "soporte humano",
    "hablar con persona real",
    "quiero ayuda de una persona",
    "prefiero hablar con alguien",
    "quiero que me atienda una persona",
])


def _is_human_assistance_request(text: str) -> bool:
    normalized = (text or "").strip().lower()
    return any(phrase in normalized for phrase in HUMAN_ASSISTANCE_PHRASES)


def _set_human_assistance_flag(
    container: ServiceContainer,
    phone: str,
    *,
    value: bool,
    message: str = "",
) -> None:
    try:
        expense_case = container.sheets.get_active_expense_case_by_phone(phone)
        if not expense_case:
            return
        case_id = str(expense_case.get("case_id", "") or "").strip()
        if not case_id:
            return
        payload: dict[str, Any] = {"human_assistance_requested": value}
        if value and message:
            payload["human_assistance_message"] = message.strip()
        elif not value:
            payload["human_assistance_message"] = ""
        container.sheets.update_expense_case(case_id, payload)
    except Exception:
        logger.exception(
            "Failed to set human_assistance_requested=%s for phone=%s",
            value,
            phone,
        )


def _require_scheduler_token(x_scheduler_token: str | None) -> None:
    configured_token = (settings.scheduler_endpoint_token or "").strip()
    provided_token = str(x_scheduler_token or "").strip()
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler token is not configured",
        )
    if not hmac.compare_digest(provided_token, configured_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized scheduler token",
        )


STICKY_CONTEXT_KEYS = (
    "message_log",
    "scheduler",
    "pending_receipts",
    "submission_closure",
    "trip_closure",
    "active_receipt_message_id",
    "receipt_batch_notice",
    "processed_message_ids",
)
ACTIVE_RECEIPT_STATES = {"PROCESSING", "NEEDS_INFO", "CONFIRM_SUMMARY"}
MAX_PROCESSED_MESSAGE_IDS = 50
RECEIPT_BATCH_NOTICE_DELAY_SECONDS = 2
NO_DOCUMENT_IDENTIFIED_REPLY = (
    "No se identificaron boletas/documentos en esa imagen. "
    "Envíame una boleta, factura, ticket o comprobante para procesarlo."
)


@dataclass
class ServiceContainer:
    sheets: SheetsService
    backoffice_auth: BackofficeAuthService
    backoffice: BackofficeService
    expense_case: ExpenseCaseService
    storage: GCSStorageService
    consolidated_document: ConsolidatedDocumentService
    docusign: DocusignService
    ocr: OCRService
    expense: ExpenseService
    conversation: ConversationService
    whatsapp: WhatsAppService
    scheduler: SchedulerService
    monthly_accounting_export: MonthlyAccountingExportService
    porta_export: PortaExportService


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
    )
    backoffice_origins = [
        origin.strip()
        for origin in (
            settings.backoffice_frontend_origins
            or settings.backoffice_frontend_origin
            or ""
        ).split(",")
        if origin.strip()
    ]
    default_backoffice_origins = [
        "https://viaticos-backoffice.vercel.app",
        "https://expenseops-backoffice.vercel.app",
        "https://expensops.com",
    ]
    if settings.debug:
        default_backoffice_origins.append("http://localhost:3000")
    for origin in default_backoffice_origins:
        if origin not in backoffice_origins:
            backoffice_origins.append(origin)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=backoffice_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = str(request.headers.get("x-request-id") or uuid.uuid4().hex)
        logger.error(
            "Unhandled API error method=%s path=%s request_id=%s",
            request.method,
            request.url.path,
            request_id,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        headers = {"X-Request-ID": request_id}
        origin = request.headers.get("origin", "")
        if origin in backoffice_origins:
            headers["Access-Control-Allow-Origin"] = origin
            headers["Vary"] = "Origin"
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "La API encontró un error interno. Intenta nuevamente.",
                "request_id": request_id,
            },
            headers=headers,
        )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = str(request.headers.get("x-request-id") or uuid.uuid4().hex)
        token = request_id_context.set(request_id)
        start_time = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info(
                "HTTP request completed method=%s path=%s duration_ms=%s",
                request.method,
                request.url.path,
                duration_ms,
            )
            request_id_context.reset(token)
        response.headers["X-Request-ID"] = request_id
        return response

    sheets_service = SheetsService(settings=settings)
    backoffice_auth_service = BackofficeAuthService(
        settings=settings,
        sheets_service=sheets_service,
    )
    backoffice_auth_service.ensure_default_admin()
    llm_service = LLMService(settings=settings)
    from services.review_score_service import ReviewScoreService
    review_score_service = ReviewScoreService()
    expense_service = ExpenseService(
        sheets_service=sheets_service,
        llm_service=llm_service,
        review_score_service=review_score_service,
    )
    whatsapp_service = WhatsAppService(settings=settings)
    storage_service = GCSStorageService(settings=settings)
    docusign_service = DocusignService(settings=settings)
    consolidated_document_service = ConsolidatedDocumentService(
        sheets_service=sheets_service,
        storage_service=storage_service,
    )
    container = ServiceContainer(
        sheets=sheets_service,
        backoffice_auth=backoffice_auth_service,
        backoffice=BackofficeService(sheets_service=sheets_service),
        expense_case=ExpenseCaseService(sheets_service=sheets_service),
        storage=storage_service,
        consolidated_document=consolidated_document_service,
        docusign=docusign_service,
        ocr=OCRService(settings=settings),
        expense=expense_service,
        conversation=ConversationService(expense_service=expense_service),
        whatsapp=whatsapp_service,
        scheduler=SchedulerService(
            settings=settings,
            sheets_service=sheets_service,
            whatsapp_service=whatsapp_service,
            consolidated_document_service=consolidated_document_service,
            docusign_service=docusign_service,
        ),
        monthly_accounting_export=MonthlyAccountingExportService(
            sheets_service=sheets_service,
            storage_service=storage_service,
        ),
        porta_export=PortaExportService(
            sheets_service=sheets_service,
            storage_service=storage_service,
            excel_service=PortaExcelExportService(settings.porta_export_template_path),
            default_date_source=settings.porta_export_date_source,
            expense_service=expense_service,
        ),
    )
    app.state.services = container
    app.include_router(backoffice_router)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
        }

    @app.get("/webhook")
    async def webhook_verification(
        hub_mode: Optional[str] = Query(default=None, alias="hub.mode"),
        hub_verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
        hub_challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
    ) -> Response:
        if container.whatsapp.provider != "meta":
            raise HTTPException(status_code=404, detail="Webhook verification not enabled")
        if container.whatsapp.is_meta_webhook_verification_valid(hub_mode, hub_verify_token):
            return Response(content=hub_challenge or "", media_type="text/plain", status_code=200)
        return Response(content="Invalid verify token", media_type="text/plain", status_code=403)

    @app.get("/docusign/callback")
    async def docusign_callback(
        code: str = Query("", description="Authorization code devuelto por DocuSign"),
        state: str = Query("", description="State opcional de OAuth"),
        error: str = Query("", description="Error OAuth opcional"),
        error_description: str = Query("", description="Descripcion del error OAuth"),
        source: str = Query("", description="Origen opcional del callback"),
        document_id: str = Query("", description="Documento asociado a la firma"),
    ) -> HTMLResponse:
        if source == "signing_complete" and not error:
            clean_document_id = str(document_id or "").strip()
            if clean_document_id:
                document = container.sheets.get_expense_case_document_by_id(clean_document_id) or {}
                current_status = str(document.get("signature_status", "") or "").strip().lower()
                if document and current_status != "completed":
                    completed_at = utc_now_iso()
                    container.sheets.update_expense_case_document(
                        clean_document_id,
                        {
                            "updated_at": completed_at,
                            "signature_status": "completed",
                            "signature_completed_at": completed_at,
                            "signature_error": "",
                        },
                    )
                    # Update rendición confirmation status on the case
                    case_id = str(document.get("case_id", document.get("trip_id", "")) or "").strip()
                    if case_id:
                        container.sheets.update_expense_case(
                            case_id,
                            {
                                "user_confirmed_at": completed_at,
                                "user_confirmation_status": "confirmed",
                                "rendicion_status": RendicionStatus.APPROVED,
                            },
                        )
                        expense_case = container.backoffice.sync_case_settlement(case_id)
                    else:
                        expense_case = None
                    phone = str(document.get("phone", "") or "").strip()
                    if phone:
                        try:
                            container.whatsapp.send_outbound_text(
                                phone,
                                container.backoffice.build_case_settlement_whatsapp_message(
                                    expense_case or {}
                                ),
                            )
                        except Exception:
                            logger.exception(
                                "Failed to send signed confirmation WhatsApp phone=%s document_id=%s",
                                phone,
                                clean_document_id,
                            )
            return HTMLResponse(
                content=_render_docusign_callback_page(
                    title="Documento Firmado",
                    message="Tu documento fue firmado con éxito.",
                    detail="Ya puedes cerrar esta ventana y volver a WhatsApp.",
                    success=True,
                )
            )
        if error:
            return HTMLResponse(
                content=_render_docusign_callback_page(
                    title="No Se Pudo Completar",
                    message="DocuSign devolvió un error al volver al sistema.",
                    detail=error_description or error,
                    success=False,
                ),
                status_code=400,
            )
        if code:
            next_step = (
                "Llama POST /jobs/docusign/oauth/exchange?code=... para obtener access_token"
            )
            return HTMLResponse(
                content=_render_docusign_callback_page(
                    title="Autorizacion Recibida",
                    message="DocuSign devolvió correctamente el código OAuth.",
                    detail=f"Código recibido. Siguiente paso: {next_step}",
                    success=True,
                )
            )
        return HTMLResponse(
            content=_render_docusign_callback_page(
                title="Callback DocuSign",
                message="El flujo de DocuSign terminó.",
                detail="Puedes volver a la aplicación.",
                success=True,
            )
        )

    @app.post("/jobs/docusign/oauth/exchange")
    async def exchange_docusign_oauth_code(
        code: str = Query(..., description="Authorization code devuelto por DocuSign"),
        redirect_uri: str = Query(
            default=settings.docusign_return_url,
            description="Redirect URI usado en la autorizacion",
        ),
        x_scheduler_token: Optional[str] = Header(default=None, alias="X-Scheduler-Token"),
    ) -> dict[str, Any]:
        _require_scheduler_token(x_scheduler_token)
        try:
            token_response = container.docusign.exchange_authorization_code(
                code=code,
                redirect_uri=redirect_uri,
            )
        except DocusignError as exc:
            logger.warning("DocuSign OAuth exchange failed: %s", exc)
            raise HTTPException(
                status_code=502,
                detail="No se pudo intercambiar el código OAuth de DocuSign.",
            ) from exc

        access_token = str(token_response.get("access_token", "") or "").strip()
        refresh_token = str(token_response.get("refresh_token", "") or "").strip()
        return {
            "ok": bool(access_token),
            "access_token_present": bool(access_token),
            "refresh_token_present": bool(refresh_token),
            "token_type": token_response.get("token_type"),
            "expires_in": token_response.get("expires_in"),
            "scope": token_response.get("scope"),
        }

    @app.post("/jobs/reminders/run")
    async def run_submission_reminders(
        dry_run: bool = False,
        x_scheduler_token: Optional[str] = Header(default=None, alias="X-Scheduler-Token"),
    ) -> dict[str, Any]:
        _require_scheduler_token(x_scheduler_token)
        return container.scheduler.run_submission_reminders(dry_run=dry_run)

    @app.post("/jobs/documents/consolidated/generate")
    async def generate_consolidated_document(
        phone: str = Query(..., description="Telefono del empleado en formato E.164"),
        case_id: str = Query(..., description="Identificador del caso o rendición"),
        include_signed_url: bool = Query(
            True, description="Incluye URL temporal firmada para descarga"
        ),
        x_scheduler_token: Optional[str] = Header(default=None, alias="X-Scheduler-Token"),
    ) -> dict[str, Any]:
        _require_scheduler_token(x_scheduler_token)
        try:
            return container.consolidated_document.generate_for_case(
                phone=phone,
                case_id=case_id,
                include_signed_url=include_signed_url,
            )
        except ValueError as exc:
            logger.info("Invalid consolidated document request phone=%s case_id=%s: %s", phone, case_id, exc)
            raise HTTPException(
                status_code=400,
                detail="No se pudo generar el documento con los datos enviados.",
            ) from exc
        except RuntimeError as exc:
            logger.warning("Consolidated document service unavailable phone=%s case_id=%s: %s", phone, case_id, exc)
            raise HTTPException(
                status_code=503,
                detail="El servicio de documentos no está disponible temporalmente.",
            ) from exc
        except Exception as exc:  # pragma: no cover - runtime dependency/errors
            logger.exception(
                "Consolidated document generation failed due to upstream dependency phone=%s case_id=%s",
                phone,
                case_id,
            )
            raise HTTPException(
                status_code=503,
                detail="No se pudo acceder a Google Sheets para generar el documento. Intenta nuevamente.",
            ) from exc

    @app.post("/jobs/documents/signature/start")
    async def start_docusign_signature(
        phone: str = Query(..., description="Telefono del empleado en formato E.164"),
        case_id: str = Query(..., description="Identificador del caso o rendición"),
        signer_email: str = Query(..., description="Email del firmante"),
        signer_name: str = Query("", description="Nombre del firmante (opcional)"),
        embedded_signing: bool = Query(
            True, description="Genera URL embebida de firma si es true"
        ),
        x_scheduler_token: Optional[str] = Header(default=None, alias="X-Scheduler-Token"),
    ) -> dict[str, Any]:
        _require_scheduler_token(x_scheduler_token)
        if not container.storage.enabled:
            raise HTTPException(status_code=503, detail="Storage privado no habilitado")
        if not container.docusign.enabled:
            raise HTTPException(status_code=503, detail="DocuSign no esta configurado")

        latest_document = container.sheets.get_latest_expense_case_document_by_phone_case(phone, case_id)
        if not latest_document:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No existe documento consolidado para ese phone/case_id. "
                    "Primero genera el consolidado."
                ),
            )

        document_id = str(latest_document.get("document_id", "") or "").strip()
        object_key = str(latest_document.get("object_key", "") or "").strip()
        if not object_key:
            raise HTTPException(status_code=400, detail="Documento sin object_key en storage")

        signer_name_final = str(signer_name or "").strip()
        if not signer_name_final:
            employee = container.sheets.get_employee_by_phone(phone) or {}
            signer_name_final = str(employee.get("name", "") or "").strip()
        if not signer_name_final:
            raise HTTPException(status_code=400, detail="Debes indicar signer_name")

        try:
            document_url = container.storage.generate_signed_url(
                object_key=object_key,
                ttl_seconds=max(settings.docusign_document_url_ttl_seconds, 600),
            )
            envelope = container.docusign.create_envelope_from_remote_pdf(
                signer_name=signer_name_final,
                signer_email=signer_email,
                document_name=f"Rendicion de gastos {case_id}",
                document_url=document_url,
                client_user_id=phone if embedded_signing else None,
            )
            envelope_id = str(envelope.get("envelopeId", "") or "").strip()
            if not envelope_id:
                raise DocusignError("DocuSign no devolvio envelopeId")

            signing_url = ""
            if embedded_signing:
                signing_url = container.docusign.create_recipient_view(
                    envelope_id=envelope_id,
                    signer_name=signer_name_final,
                    signer_email=signer_email,
                    client_user_id=phone,
                    return_url=_build_signing_return_url(settings),
                )

            status_time = str(envelope.get("statusDateTime", "") or "").strip() or utc_now_iso()
            container.sheets.update_expense_case_document(
                document_id,
                {
                    "updated_at": status_time,
                    "signature_provider": "docusign",
                    "signature_status": "pending",
                    "docusign_envelope_id": envelope_id,
                    "signature_url": signing_url,
                    "signature_sent_at": status_time,
                    "signature_error": "",
                },
            )

            return {
                "document_id": document_id,
                "case_id": str(latest_document.get("case_id", latest_document.get("trip_id", "")) or ""),
                "signature_provider": "docusign",
                "signature_status": "pending",
                "docusign_envelope_id": envelope_id,
                "signing_url": signing_url or None,
            }
        except DocusignError as exc:
            if document_id:
                container.sheets.update_expense_case_document(
                    document_id,
                    {
                        "signature_provider": "docusign",
                        "signature_status": "error",
                        "signature_error": str(exc),
                    },
                )
            logger.warning("DocuSign signature start failed document_id=%s: %s", document_id, exc)
            raise HTTPException(
                status_code=502,
                detail="No se pudo iniciar la firma con DocuSign.",
            ) from exc

    @app.get("/r/sign/{document_id}")
    async def redirect_short_signing_url(document_id: str) -> RedirectResponse:
        document = container.sheets.get_expense_case_document_by_id(document_id)
        if not document:
            raise HTTPException(status_code=404, detail="Documento no encontrado")
        signing_url = str(document.get("signature_url", "") or "").strip()
        if not signing_url:
            raise HTTPException(status_code=404, detail="Documento sin URL de firma")
        return RedirectResponse(url=signing_url, status_code=307)

    @app.post("/webhook")
    async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks) -> Response:
        try:
            if container.whatsapp.provider == "meta":
                return await _handle_meta_webhook(
                    request=request,
                    background_tasks=background_tasks,
                    container=container,
                )

            form = await request.form()
            payload = {key: form.get(key) for key in form.keys()}
            num_media = int(payload.get("NumMedia") or 0)
            body = (payload.get("Body") or "").strip()
            from_raw = payload.get("From") or ""
            phone = normalize_whatsapp_phone(from_raw)
            signature = request.headers.get("X-Twilio-Signature")
            request_url = str(request.url)

            if not container.whatsapp.validate_incoming_request(
                request_url, payload, signature
            ):
                xml = container.whatsapp.build_twiml_message("Firma Twilio inválida.")
                return Response(content=xml, media_type="application/xml", status_code=403)

            if not phone:
                xml = container.whatsapp.build_twiml_message(
                    "No pude identificar tu número. Intenta nuevamente."
                )
                return Response(content=xml, media_type="application/xml")

            employee = container.sheets.get_employee_by_phone(phone)
            if not employee:
                xml = container.whatsapp.build_twiml_message(
                    "Tu número no está registrado como empleado activo."
                )
                return Response(content=xml, media_type="application/xml")

            if num_media > 0:
                media_entries = _extract_media_entries(payload)
                if not media_entries:
                    xml = container.whatsapp.build_twiml_message(
                        "No pude leer las imágenes adjuntas. Reenvía el comprobante, por favor."
                    )
                    return Response(
                        content=xml,
                        media_type="application/xml",
                        status_code=status.HTTP_200_OK,
                        background=background_tasks,
                    )

                conversation = container.conversation.ensure_conversation(
                    container.sheets.get_conversation(phone)
                )
                _log_inbound_media_message(
                    container,
                    phone,
                    media_entries,
                    caption=body,
                    message_id=str(payload.get("MessageSid") or payload.get("SmsSid") or "").strip()
                    or None,
                )
                context = conversation.get("context_json", {})
                pending_receipts = _get_pending_receipts(context)
                state = str(conversation.get("state", "WAIT_RECEIPT") or "WAIT_RECEIPT")

                if state in ACTIVE_RECEIPT_STATES:
                    queued_count = _enqueue_media_entries(container, phone, media_entries)
                    xml = container.whatsapp.build_twiml_message(
                        "Recibí tu documento y lo dejé en cola. "
                        f"Tienes {queued_count} documento(s) pendientes; "
                        "las revisaré una por una."
                    )
                    return Response(
                        content=xml,
                        media_type="application/xml",
                        status_code=status.HTTP_200_OK,
                        background=background_tasks,
                    )

                if pending_receipts:
                    _enqueue_media_entries(container, phone, media_entries)
                    started = _maybe_schedule_next_pending_media(
                        container=container,
                        phone=phone,
                    )
                    xml = (
                        container.whatsapp.build_empty_twiml()
                        if started
                        else container.whatsapp.build_twiml_message(
                            "Recibí tu documento y lo dejé en cola para procesarlo."
                        )
                    )
                    return Response(
                        content=xml,
                        media_type="application/xml",
                        status_code=status.HTTP_200_OK,
                        background=background_tasks,
                    )

                first_entry = media_entries[0]
                extra_entries = media_entries[1:]
                if extra_entries:
                    _enqueue_media_entries(container, phone, extra_entries)
                _set_processing_lock(container, phone)
                _spawn_media_processing_task(
                    container,
                    phone,
                    {
                        "MediaId0": first_entry.get("media_id", ""),
                        "MediaUrl0": first_entry.get("media_url", ""),
                        "MediaContentType0": first_entry.get("media_content_type"),
                        "InboundMessageId": first_entry.get("message_id", ""),
                    },
                )
                reply = "Boleta recibida. Ya la estoy procesando."
                xml = container.whatsapp.build_twiml_message(reply)
                return Response(
                    content=xml,
                    media_type="application/xml",
                    status_code=status.HTTP_200_OK,
                    background=background_tasks,
                )
            else:
                _log_inbound_text_message(
                    container,
                    phone,
                    body,
                    message_id=str(payload.get("MessageSid") or payload.get("SmsSid") or "").strip()
                    or None,
                )
                response_text = _handle_text_message(container, phone, body)
                _maybe_schedule_next_pending_media(
                    container=container,
                    phone=phone,
                )

            _log_outbound_message(container, phone, _coerce_response_to_text(response_text))
            xml = container.whatsapp.build_twiml_message(_coerce_response_to_text(response_text))
            return Response(content=xml, media_type="application/xml", status_code=status.HTTP_200_OK)
        except Exception as exc:  # pragma: no cover - runtime dependency/errors
            logger.exception("Webhook processing failed")
            message = (
                "Estoy con alta carga temporal y no pude procesar tu mensaje. "
                "Intenta nuevamente en 1 minuto."
            )
            if settings.debug:
                message += f"\nDetalle técnico: {exc}"
            xml = container.whatsapp.build_twiml_message(message)
            return Response(content=xml, media_type="application/xml", status_code=status.HTTP_200_OK)

    # ── Test simulation endpoint (debug only) ──────────────────────
    @app.post("/test/simulate")
    async def test_simulate(
        request: Request,
        x_scheduler_token: Optional[str] = Header(default=None, alias="X-Scheduler-Token"),
    ) -> dict[str, Any]:
        """Synchronous test endpoint for conversation simulation. Only in debug mode."""
        if not settings.debug:
            raise HTTPException(status_code=404, detail="Not found")
        _require_scheduler_token(x_scheduler_token)

        payload = await request.json()
        phone = normalize_whatsapp_phone(payload.get("phone", ""))
        msg_type = payload.get("type", "text")  # "media" or "text"
        body = payload.get("body", "")
        media_url = payload.get("media_url", "")
        media_content_type = payload.get("media_content_type", "image/png")

        if not phone:
            raise HTTPException(status_code=400, detail="phone is required")

        employee = container.sheets.get_employee_by_phone(phone)
        if not employee:
            return {"reply": "Número no registrado como empleado.", "state": "error"}

        if msg_type == "media":
            if not media_url:
                raise HTTPException(status_code=400, detail="media_url is required for type=media")
            fake_payload = {
                "MediaUrl0": media_url,
                "MediaContentType0": media_content_type,
                "MessageSid": f"SIM{make_id('MSG')}",
            }
            reply = _handle_media_message(container, phone, fake_payload)
        else:
            reply = _handle_text_message(container, phone, body)

        conversation = container.sheets.get_conversation(phone)
        reply_text = reply if isinstance(reply, str) else "\n".join(reply) if isinstance(reply, list) else str(reply)

        return {
            "reply": reply_text,
            "state": conversation.get("state", "") if conversation else "",
            "current_step": conversation.get("current_step", "") if conversation else "",
        }

    @app.post("/test/reset")
    async def test_reset(
        request: Request,
        x_scheduler_token: Optional[str] = Header(default=None, alias="X-Scheduler-Token"),
    ) -> dict[str, Any]:
        """Reset conversation state for testing. Only in debug mode."""
        if not settings.debug:
            raise HTTPException(status_code=404, detail="Not found")
        _require_scheduler_token(x_scheduler_token)

        payload = await request.json()
        phone = normalize_whatsapp_phone(payload.get("phone", ""))
        if not phone:
            raise HTTPException(status_code=400, detail="phone is required")

        container.sheets.update_conversation(
            phone,
            {
                "phone": phone,
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": container.conversation.default_context(),
            },
        )
        return {"status": "reset", "phone": phone}

    return app


def _handle_media_message(container: ServiceContainer, phone: str, payload: dict[str, Any]) -> str:
    started_at = time.perf_counter()
    media_url = str(payload.get("MediaUrl0") or "").strip()
    media_id = str(payload.get("MediaId0") or "").strip()
    media_content_type = payload.get("MediaContentType0")
    inbound_message_id = str(
        payload.get("InboundMessageId") or payload.get("MessageSid") or payload.get("SmsSid") or ""
    ).strip()
    logger.warning(
        "Receipt processing started phone=%s provider=%s media_id=%s has_media_url=%s mime=%s inbound_message_id=%s",
        phone,
        container.whatsapp.provider,
        media_id or None,
        bool(media_url),
        media_content_type or None,
        inbound_message_id or None,
    )
    if container.whatsapp.provider == "meta" and media_id:
        media_url, resolved_mime_type = container.whatsapp.get_meta_media_url(media_id)
        if resolved_mime_type and not media_content_type:
            media_content_type = resolved_mime_type
        logger.warning(
            "Receipt media resolved from Meta phone=%s media_id=%s resolved_mime=%s has_media_url=%s",
            phone,
            media_id,
            media_content_type or None,
            bool(media_url),
        )
    ocr_warning = ""
    storage_result: dict[str, str] = {}
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    base_context = conversation.get("context_json", {})
    processing_context = _merge_context_preserving_sticky(
        base_context,
        container.conversation.default_context(),
    )
    if inbound_message_id:
        processing_context["active_receipt_message_id"] = inbound_message_id

    container.sheets.update_conversation(
        phone,
        {
            "phone": phone,
            "state": "PROCESSING",
            "current_step": "",
            "context_json": processing_context,
        },
    )
    logger.info("Receipt conversation set to PROCESSING phone=%s", phone)

    try:
        ocr_started_at = time.perf_counter()
        ocr_data = container.ocr.extract_receipt_data(media_url, media_content_type)
        logger.warning(
            "Receipt OCR completed phone=%s elapsed_ms=%d summary=%s",
            phone,
            int((time.perf_counter() - ocr_started_at) * 1000),
            _summarize_receipt_payload(ocr_data),
        )
    except Exception as exc:  # pragma: no cover - depende de red/API externa
        logger.exception("OCR processing failed for phone=%s", phone)
        ocr_data = {}
        ocr_warning = (
            "No pude extraer datos automáticamente del comprobante. "
            "Te pediré los datos manualmente."
        )
        if settings.debug:
            ocr_warning += f"\nDetalle técnico: {exc}"

    if container.storage.enabled and media_url:
        try:
            storage_started_at = time.perf_counter()
            storage_result = container.storage.upload_receipt_from_url(
                phone=phone,
                media_url=media_url,
                media_content_type=media_content_type,
            )
            logger.info(
                "Receipt storage upload completed phone=%s elapsed_ms=%d provider=%s object_key=%s",
                phone,
                int((time.perf_counter() - storage_started_at) * 1000),
                storage_result.get("receipt_storage_provider") or None,
                storage_result.get("receipt_object_key") or None,
            )
        except Exception as exc:  # pragma: no cover - depende de red/API externa
            logger.exception("GCS upload failed for phone=%s", phone)
            if settings.debug:
                logger.warning("Receipt upload to GCS failed phone=%s error=%s", phone, exc)
            container.sheets.update_conversation(
                phone,
                {
                    "state": "WAIT_RECEIPT",
                    "current_step": "",
                    "context_json": _clear_active_receipt_message_id(
                        _merge_context_preserving_sticky(
                            _get_latest_context(container, phone),
                            container.conversation.default_context(),
                        )
                    ),
                },
            )
            return (
                "No pude almacenar el comprobante en el storage privado. "
                "Inténtalo nuevamente en unos segundos."
            )

    ocr_data["receipt_storage_provider"] = storage_result.get("receipt_storage_provider", "")
    ocr_data["receipt_object_key"] = storage_result.get("receipt_object_key", "")

    settlement_proof_reply = _maybe_handle_settlement_payment_proof(
        container=container,
        phone=phone,
        payload=payload,
        media_url=media_url,
        media_content_type=media_content_type,
        ocr_data=ocr_data,
        storage_result=storage_result,
        inbound_message_id=inbound_message_id,
    )
    if settlement_proof_reply:
        return settlement_proof_reply

    if not bool(ocr_data.get("is_document")):
        container.sheets.update_conversation(
            phone,
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": _clear_active_receipt_message_id(
                    _merge_context_preserving_sticky(
                        _get_latest_context(container, phone),
                        container.conversation.default_context(),
                    )
                ),
            },
        )
        logger.info("Image rejected as non-document phone=%s media_id=%s", phone, media_id or None)
        reply = NO_DOCUMENT_IDENTIFIED_REPLY
        if ocr_warning:
            reply = f"{ocr_warning}\n\n{reply}"
        return reply

    active_cases = _list_active_cases_for_phone(container, phone)
    if len(active_cases) > 1:
        return _prompt_for_expense_case_selection(
            container=container,
            phone=phone,
            ocr_data=ocr_data,
            active_cases=active_cases,
        )

    case_lookup_started_at = time.perf_counter()
    expense_case_service = getattr(container, "expense_case", None) or getattr(container, "travel", None)
    expense_case = (
        expense_case_service.get_active_case_for_phone(phone)
        if hasattr(expense_case_service, "get_active_case_for_phone")
        else expense_case_service.get_active_trip_for_phone(phone)
    )
    logger.info(
        "Active expense case lookup completed phone=%s elapsed_ms=%d found=%s case_id=%s",
        phone,
        int((time.perf_counter() - case_lookup_started_at) * 1000),
        bool(expense_case),
        str((expense_case or {}).get("case_id") or "").strip() or None,
    )

    if not expense_case:
        container.sheets.update_conversation(
            phone,
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": _clear_active_receipt_message_id(
                    _merge_context_preserving_sticky(
                        _get_latest_context(container, phone),
                        container.conversation.default_context(),
                    )
                ),
            },
        )
        logger.info(
            "Receipt rejected because there is no active expense case phone=%s",
            phone,
        )
        return "No tienes una rendición creada."

    transition_started_at = time.perf_counter()
    transition = container.conversation.process_ocr_result(phone, ocr_data, expense_case)
    logger.info(
        "Conversation transition completed phone=%s elapsed_ms=%d target_state=%s current_step=%s draft=%s",
        phone,
        int((time.perf_counter() - transition_started_at) * 1000),
        transition.get("state"),
        transition.get("current_step") or None,
        _summarize_receipt_payload(transition.get("context_json", {}).get("draft_expense", {})),
    )

    container.sheets.update_conversation(
        phone,
        {
            "state": transition["state"],
            "current_step": transition.get("current_step", ""),
            "context_json": _merge_context_preserving_sticky(
                _get_latest_context(container, phone),
                transition.get("context_json", {}),
            ),
        },
    )
    reply = transition.get(
        "reply",
        "Recibí tu comprobante. Estoy procesándolo.",
    )
    if ocr_warning:
        reply = f"{ocr_warning}\n\n{reply}"
    logger.info(
        "Receipt processing completed phone=%s total_elapsed_ms=%d final_state=%s",
        phone,
        int((time.perf_counter() - started_at) * 1000),
        transition.get("state"),
    )
    return reply


def _list_active_cases_for_phone(container: ServiceContainer, phone: str) -> list[dict[str, Any]]:
    normalized_phone = normalize_whatsapp_phone(phone)
    if not normalized_phone:
        return []

    list_by_phone = getattr(container.sheets, "list_active_expense_cases_by_phone", None)
    if callable(list_by_phone):
        return list_by_phone(normalized_phone)

    try:
        cases = container.sheets.list_expense_cases()
    except Exception:
        return []

    active_cases: list[dict[str, Any]] = []
    for expense_case in cases:
        case_phone = normalize_whatsapp_phone(
            expense_case.get("employee_phone", expense_case.get("phone", ""))
        )
        if case_phone != normalized_phone:
            continue
        if normalize_state(expense_case.get("status")) != "active":
            continue
        active_cases.append(expense_case)
    return active_cases


def _prompt_for_expense_case_selection(
    *,
    container: ServiceContainer,
    phone: str,
    ocr_data: dict[str, Any],
    active_cases: list[dict[str, Any]],
) -> str:
    options = [_case_selection_option(item, index) for index, item in enumerate(active_cases, start=1)]
    context = _merge_context_preserving_sticky(
        _get_latest_context(container, phone),
        {
            "draft_expense": {},
            "missing_fields": [],
            "last_question": "case_selection",
            "pending_case_selection": {
                "draft_expense": dict(ocr_data),
                "options": options,
            },
        },
    )
    container.sheets.update_conversation(
        phone,
        {
            "state": "NEEDS_INFO",
            "current_step": "case_selection",
            "context_json": context,
        },
    )
    lines = [
        "Tienes más de una rendición activa. ¿A cuál asocio este documento?",
        *[
            f"{option['index']}. {option['label']}"
            for option in options
        ],
        "Responde con el número o el ID de la rendición.",
    ]
    return "\n".join(lines)


def _case_selection_option(expense_case: dict[str, Any], index: int) -> dict[str, str]:
    case_id = str(expense_case.get("case_id", expense_case.get("trip_id", "")) or "").strip()
    label = str(expense_case.get("context_label", expense_case.get("destination", "")) or "").strip()
    if label and case_id:
        display = f"{label} ({case_id})"
    else:
        display = label or case_id or f"Rendición {index}"
    return {
        "index": str(index),
        "case_id": case_id,
        "label": display,
    }


def _maybe_handle_settlement_payment_proof(
    *,
    container: ServiceContainer,
    phone: str,
    payload: dict[str, Any],
    media_url: str,
    media_content_type: Any,
    ocr_data: dict[str, Any],
    storage_result: dict[str, str],
    inbound_message_id: str,
) -> str | None:
    expense_case = _find_case_waiting_for_employee_payment_proof(container, phone)
    if not expense_case:
        return None

    case_id = str(expense_case.get("case_id", expense_case.get("trip_id", "")) or "").strip()
    document_id = make_id("PAYPROOF")
    filename = str(payload.get("MediaFilename0") or payload.get("filename") or "").strip()
    expected_amount = expense_case.get("settlement_amount_clp", "")
    backoffice = getattr(container, "backoffice", None)
    resolve_company = getattr(backoffice, "_resolve_company_for_case", None)
    company = resolve_company(expense_case) if callable(resolve_company) else {}
    company = company or {}
    extracted_amount = ocr_data.get("total", ocr_data.get("net_amount", ""))
    extracted_date = ocr_data.get("date", "")
    extracted_recipient = (
        ocr_data.get("receiver_name")
        or ocr_data.get("merchant")
        or ocr_data.get("supplier_name")
        or ""
    )
    extracted_tax_id = (
        ocr_data.get("receiver_tax_id")
        or ocr_data.get("issuer_tax_id")
        or ""
    )
    expected_amount_value = parse_float(expected_amount)
    extracted_amount_value = parse_float(extracted_amount)
    amount_matches = (
        expected_amount_value is not None
        and extracted_amount_value is not None
        and abs(expected_amount_value - extracted_amount_value) < 1
    )
    company_name = str(company.get("name", "") or "").strip()
    company_tax_id = str(company.get("rut", company.get("account_holder_rut", "")) or "").strip()

    pending_document = {
        "document_id": document_id,
        "phone": phone,
        "case_id": case_id,
        "document_type": "settlement_payment_proof",
        "storage_provider": storage_result.get("receipt_storage_provider", ""),
        "object_key": storage_result.get("receipt_object_key", ""),
        "media_url": media_url,
        "media_content_type": str(media_content_type or ""),
        "filename": filename,
        "status": "pending_user_confirmation",
        "review_status": "pending_user_confirmation",
        "review_reason": "",
        "expected_amount_clp": expected_amount,
        "ocr_json": json.dumps(
            {
                **ocr_data,
                "settlement_validation": {
                    "amount_matches": amount_matches,
                    "expected_amount_clp": expected_amount,
                    "company_name": company_name,
                    "company_tax_id": company_tax_id,
                },
            },
            ensure_ascii=False,
        ),
        "created_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
    }
    if inbound_message_id:
        pending_document["source_message_id"] = inbound_message_id

    latest_context = _get_latest_context(container, phone)
    latest_context["pending_settlement_payment_proof"] = pending_document
    container.sheets.update_conversation(
        phone,
        {
            "state": "CONFIRM_SETTLEMENT_PAYMENT_PROOF",
            "current_step": "confirm_settlement_payment_proof",
            "context_json": latest_context,
        },
    )
    logger.info(
        "Settlement payment proof OCR ready for confirmation phone=%s case_id=%s document_id=%s",
        phone,
        case_id,
        document_id,
    )
    amount_text = (
        f"${extracted_amount_value:,.0f}".replace(",", ".")
        if extracted_amount_value is not None
        else "No identificado"
    )
    expected_text = (
        f"${expected_amount_value:,.0f}".replace(",", ".")
        if expected_amount_value is not None
        else "No informado"
    )
    validation_line = (
        "✅ El monto coincide con la devolución esperada."
        if amount_matches
        else f"⚠️ El monto esperado es {expected_text}; revisa antes de confirmar."
    )
    return (
        "Leí este comprobante de transferencia:\n"
        f"- Monto: {amount_text}\n"
        f"- Fecha: {extracted_date or 'No identificada'}\n"
        f"- Destinatario: {extracted_recipient or 'No identificado'}\n"
        f"- RUT destinatario: {extracted_tax_id or 'No identificado'}\n"
        f"{validation_line}\n\n"
        "¿Confirmas que estos datos corresponden a la transferencia que realizaste?\n"
        "Responde *sí* para enviarla a revisión o *no* para descartarla y reenviar el comprobante."
    )


def _find_case_waiting_for_employee_payment_proof(
    container: ServiceContainer,
    phone: str,
) -> dict[str, Any] | None:
    normalized_phone = normalize_whatsapp_phone(phone)
    if not normalized_phone:
        return None

    try:
        cases = container.sheets.list_expense_cases()
    except Exception:
        cases = []

    candidates: list[dict[str, Any]] = []
    for expense_case in cases:
        case_phone = normalize_whatsapp_phone(
            expense_case.get("employee_phone", expense_case.get("phone", ""))
        )
        if case_phone != normalized_phone:
            continue
        if normalize_state(expense_case.get("status")) != "active":
            continue
        if normalize_state(expense_case.get("rendicion_status")) != RendicionStatus.APPROVED:
            continue
        if normalize_state(expense_case.get("settlement_direction")) != SettlementDirection.EMPLOYEE_OWES_COMPANY:
            continue
        settlement_status = normalize_state(expense_case.get("settlement_status"))
        if settlement_status not in {
            "",
            SettlementStatus.PENDING,
            SettlementStatus.PENDING_EMPLOYEE_PAYMENT_PROOF,
            SettlementStatus.PAYMENT_PROOF_REJECTED,
        }:
            continue
        candidates.append(expense_case)

    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: str(item.get("settlement_calculated_at", item.get("updated_at", "")) or ""),
        reverse=True,
    )[0]


def _handle_text_message(container: ServiceContainer, phone: str, body: str) -> str | list[str]:
    conversation = container.sheets.get_conversation(phone)
    is_new_conversation = not conversation
    if not conversation:
        conversation = container.sheets.update_conversation(
            phone,
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": container.conversation.default_context(),
            },
        )

    settlement_proof_confirmation_reply = _handle_settlement_payment_proof_confirmation(
        container,
        phone,
        body,
        conversation,
    )
    if settlement_proof_confirmation_reply:
        return settlement_proof_confirmation_reply

    case_selection_reply = _handle_case_selection_response(container, phone, body, conversation)
    if case_selection_reply:
        return case_selection_reply

    closure_reply = container.scheduler.handle_submission_closure_user_response(
        phone=phone,
        message=body,
    )
    if closure_reply:
        return closure_reply

    simple_confirmation_reply = container.scheduler.handle_simple_document_confirmation_user_response(
        phone=phone,
        message=body,
    )
    if simple_confirmation_reply:
        return simple_confirmation_reply

    direct_close_reply = container.scheduler.handle_direct_submission_close_command(
        phone=phone,
        message=body,
    )
    if direct_close_reply:
        return direct_close_reply

    if _is_human_assistance_request(body):
        _set_human_assistance_flag(container, phone, value=True, message=body)
        return (
            "Entendido, ya notifiqué a un operador que necesitas asistencia humana. "
            "Pronto alguien te contactará por este mismo chat.\n\n"
            "Mientras tanto, puedo seguir ayudándote con tu rendición de gastos: "
            "envíame fotos de tus comprobantes y los proceso como siempre. 🤝"
        )

    result = container.conversation.handle_text_message(conversation, body, phone=phone)

    if result.get("action") == "save_expense":
        draft = result.get("context_json", {}).get("draft_expense", {})
        try:
            latest_context = _get_latest_context(container, phone)
            source_message_id = _get_active_receipt_message_id(latest_context)
            if isinstance(draft, dict) and source_message_id:
                draft = {**draft, "source_message_id": source_message_id}
            if isinstance(draft, dict):
                _sync_manual_cost_center_to_case(container, draft)
            saved = container.expense.save_confirmed_expense(phone, draft)
            has_pending_receipts = bool(_get_pending_receipts(latest_context))
            policy_message = None
            saved_status = str(saved.get("status", "") or "").strip().lower()
            if saved_status == ExpenseStatus.PENDING_REVIEW:
                reply_messages = [
                    "No encontré un caso activo asociado a tu usuario. Un operador deberá revisarlo.",
                ]
                if has_pending_receipts:
                    reply_messages.append("Ahora voy con el siguiente documento.")
                else:
                    reply_messages.append("Si tienes más comprobantes, envíamelos cuando quieras.")
            else:
                closing_line = "Si tienes más comprobantes, envíamelos cuando quieras."
                if has_pending_receipts:
                    closing_line = "Recibido. Ahora voy con el siguiente documento."
                case_id = str(saved.get("case_id", saved.get("trip_id", "")) or "")
                reply_messages = ["Gasto guardado con éxito."]
                if not has_pending_receipts:
                    policy_alert_message = container.expense.build_policy_alert_message(
                        phone=phone,
                        case_id=case_id,
                    )
                    if policy_alert_message:
                        reply_messages.append(policy_alert_message)
                reply_messages.append(closing_line)
            container.sheets.update_conversation(
                phone,
                {
                    "state": "WAIT_RECEIPT",
                    "current_step": "",
                    "context_json": _clear_active_receipt_message_id(
                        _merge_context_preserving_sticky(
                            _get_latest_context(container, phone),
                            container.conversation.default_context(),
                        )
                    ),
                },
            )
            return reply_messages
        except Exception as exc:  # pragma: no cover - runtime dependency/errors
            result = {
                "state": "CONFIRM_SUMMARY",
                "current_step": "confirm_summary",
                "context_json": result.get("context_json", {}),
                "reply": f"No pude guardar el gasto: {exc}",
            }

    merged_result_context = _merge_context_preserving_sticky(
        _get_latest_context(container, phone),
        result.get("context_json", conversation.get("context_json", {})),
    )
    target_state = result.get("state", conversation.get("state", "WAIT_RECEIPT"))
    if target_state == "WAIT_RECEIPT":
        merged_result_context = _clear_active_receipt_message_id(merged_result_context)

    container.sheets.update_conversation(
        phone,
        {
            "state": target_state,
            "current_step": result.get("current_step", conversation.get("current_step", "")),
            "context_json": merged_result_context,
        },
    )
    reply = result.get("reply", "No pude procesar tu mensaje.")
    if (
        is_new_conversation
        and target_state == "WAIT_RECEIPT"
        and result.get("action") == "noop"
        and reply == "Envíame una foto de la boleta, factura o comprobante para procesar el gasto."
    ):
        reply = _build_initial_wait_receipt_reply(container, phone)
    return reply


def _handle_settlement_payment_proof_confirmation(
    container: ServiceContainer,
    phone: str,
    body: str,
    conversation: dict[str, Any],
) -> str | None:
    if normalize_state(conversation.get("state")) != "confirm_settlement_payment_proof":
        return None
    context = conversation.get("context_json")
    if isinstance(context, str):
        try:
            context = json.loads(context)
        except (TypeError, ValueError):
            context = {}
    if not isinstance(context, dict):
        context = {}
    pending_document = context.get("pending_settlement_payment_proof")
    if not isinstance(pending_document, dict):
        return None

    answer = normalize_state(body).replace("í", "i")
    affirmative = answer in {"si", "s", "confirmo", "confirmar", "correcto", "ok"}
    negative = answer in {"no", "n", "rechazar", "descartar", "incorrecto"}
    if not affirmative and not negative:
        return (
            "Por favor responde *sí* para enviar esta transferencia a revisión "
            "o *no* para descartarla y reenviar el comprobante."
        )

    context.pop("pending_settlement_payment_proof", None)
    context = _clear_active_receipt_message_id(context)
    if negative:
        container.sheets.update_conversation(
            phone,
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": context,
            },
        )
        return "Descarté este comprobante. Envíame una nueva imagen cuando quieras."

    now = utc_now_iso()
    document = {
        **pending_document,
        "status": SettlementStatus.PAYMENT_PROOF_UNDER_REVIEW,
        "review_status": SettlementStatus.PAYMENT_PROOF_UNDER_REVIEW,
        "review_reason": "user_confirmed_pending_finance_review",
        "user_confirmed_at": now,
        "updated_at": now,
    }
    container.sheets.create_expense_case_document(document)
    case_id = str(document.get("case_id", "") or "").strip()
    container.sheets.update_expense_case(
        case_id,
        {
            "settlement_status": SettlementStatus.PAYMENT_PROOF_UNDER_REVIEW,
            "settlement_payment_proof_document_id": document.get("document_id", ""),
            "updated_at": now,
        },
    )
    container.sheets.update_conversation(
        phone,
        {
            "state": "WAIT_RECEIPT",
            "current_step": "",
            "context_json": context,
        },
    )
    return (
        "Gracias. Guardé el comprobante y lo envié a revisión financiera. "
        "Te avisaremos cuando sea aprobado."
    )


def _handle_case_selection_response(
    container: ServiceContainer,
    phone: str,
    body: str,
    conversation: dict[str, Any],
) -> str | None:
    if str(conversation.get("current_step", "") or "") != "case_selection":
        return None
    context = conversation.get("context_json", {})
    pending = context.get("pending_case_selection") if isinstance(context, dict) else None
    if not isinstance(pending, dict):
        return None
    options = pending.get("options")
    if not isinstance(options, list):
        return None

    selected = _match_case_selection_option(body, options)
    if not selected:
        return (
            "No pude identificar esa rendición. "
            "Responde con el número de la lista o con el ID de la rendición."
        )

    case_id = str(selected.get("case_id", "") or "").strip()
    expense_case = container.sheets.get_expense_case_by_id(case_id) if case_id else None
    if not expense_case:
        return "No encontré esa rendición activa. Un operador deberá revisarla."

    draft = dict(pending.get("draft_expense", {}) or {})
    draft["case_id"] = case_id
    draft["trip_id"] = case_id
    transition = container.conversation.process_ocr_result(phone, draft, expense_case)
    transition_context = transition.get("context_json", {})
    if isinstance(transition_context, dict):
        transition_draft = dict(transition_context.get("draft_expense", {}) or {})
        transition_draft["case_id"] = case_id
        transition_draft["trip_id"] = case_id
        transition_context = {**transition_context, "draft_expense": transition_draft}
    updated_context = _merge_context_preserving_sticky(
        context,
        {
            **transition_context,
            "pending_case_selection": {},
        },
    )
    updated_context.pop("pending_case_selection", None)
    container.sheets.update_conversation(
        phone,
        {
            "state": transition.get("state", "CONFIRM_SUMMARY"),
            "current_step": transition.get("current_step", "confirm_summary"),
            "context_json": updated_context,
        },
    )
    label = str(selected.get("label", "") or "").strip()
    prefix = f"Perfecto, asociaré este documento a {label}.\n\n" if label else ""
    return prefix + transition.get("reply", "Recibí tu comprobante. Estoy procesándolo.")


def _match_case_selection_option(body: str, options: list[Any]) -> dict[str, Any] | None:
    normalized = str(body or "").strip().lower()
    if not normalized:
        return None
    for option in options:
        if not isinstance(option, dict):
            continue
        index = str(option.get("index", "") or "").strip().lower()
        case_id = str(option.get("case_id", "") or "").strip().lower()
        if normalized in {index, case_id}:
            return option
    return None


def _build_initial_wait_receipt_reply(container: ServiceContainer, phone: str) -> str:
    greeting_name = _get_employee_greeting_name(container, phone)
    greeting = f"Hola, {greeting_name}." if greeting_name else "Hola."
    return (
        f"{greeting} Envíame una foto de la boleta, factura o comprobante "
        "para procesar el gasto."
    )


def _sync_manual_cost_center_to_case(container: ServiceContainer, draft: dict[str, Any]) -> None:
    case_id = str(draft.get("case_id", draft.get("trip_id", "")) or "").strip()
    cost_center = str(draft.get("cost_center", "") or "").strip()
    if not case_id or not cost_center:
        return
    if not hasattr(container.sheets, "get_expense_case_by_id") or not hasattr(
        container.sheets, "update_expense_case"
    ):
        return
    expense_case = container.sheets.get_expense_case_by_id(case_id)
    if not expense_case:
        return
    centers = normalize_cost_centers(expense_case.get("cost_centers", []))
    if cost_center.lower() in {center.lower() for center in centers}:
        return
    container.sheets.update_expense_case(case_id, {"cost_centers": centers + [cost_center]})


def _get_employee_greeting_name(container: ServiceContainer, phone: str) -> str:
    employee = container.sheets.get_employee_by_phone(phone) or {}
    first_name = str(employee.get("first_name", "") or "").strip()
    if first_name:
        return first_name
    full_name = str(employee.get("name", "") or "").strip()
    if full_name:
        return full_name.split()[0]
    return ""


def _process_media_message_async(
    container: ServiceContainer,
    phone: str,
    payload: dict[str, Any],
) -> None:
    started_at = time.perf_counter()
    inbound_message_id = str(
        payload.get("InboundMessageId") or payload.get("MessageSid") or payload.get("SmsSid") or ""
    ).strip() or None
    should_auto_advance = False
    processing_succeeded = False
    try:
        response_text = _handle_media_message(container, phone, payload)
        processing_succeeded = True
    except Exception as exc:  # pragma: no cover - runtime dependency/errors
        logger.exception(
            "Async media processing failed for phone=%s inbound_message_id=%s",
            phone,
            inbound_message_id,
        )
        _reset_receipt_processing_state(container, phone, reason="async_processing_failure")
        response_text = (
            "No pude procesar tu comprobante en este intento. "
            "Por favor reenvíala o escribe 'reiniciar'."
        )
        if settings.debug:
            response_text += f"\nDetalle técnico: {exc}"
    try:
        _send_outbound_response(container, phone, response_text)
        if processing_succeeded:
            conversation = container.conversation.ensure_conversation(
                container.sheets.get_conversation(phone)
            )
            should_auto_advance = (
                str(conversation.get("state", "WAIT_RECEIPT") or "WAIT_RECEIPT") == "WAIT_RECEIPT"
            )
        logger.info(
            "Receipt outbound response sent phone=%s elapsed_ms=%d",
            phone,
            int((time.perf_counter() - started_at) * 1000),
        )
    except TwilioDailyLimitExceededError:
        logger.warning(
            "No se pudo enviar respuesta por WhatsApp: límite diario de Twilio alcanzado phone=%s",
            phone,
        )
    except Exception:  # pragma: no cover - runtime dependency/errors
        logger.exception("Failed to send outbound WhatsApp reply phone=%s", phone)
        try:
            container.whatsapp.send_outbound_text(
                phone,
                _coerce_response_to_text(response_text),
                reply_to_message_id=inbound_message_id,
            )
            logger.warning("Fallback plain-text outbound response sent phone=%s", phone)
        except Exception:  # pragma: no cover - runtime dependency/errors
            logger.exception("Fallback plain-text outbound response also failed phone=%s", phone)
    finally:
        if should_auto_advance:
            _maybe_process_next_pending_media_inline(container, phone)


def _spawn_media_processing_task(
    container: ServiceContainer,
    phone: str,
    payload: dict[str, Any],
) -> None:
    async def runner() -> None:
        await asyncio.to_thread(_process_media_message_async, container, phone, payload)

    asyncio.create_task(runner())


def _spawn_receipt_batch_notice_task(
    container: ServiceContainer,
    phone: str,
    notice_token: str,
) -> None:
    asyncio.create_task(_debounced_send_receipt_batch_notice(container, phone, notice_token))


async def _run_media_processing_during_request(
    container: ServiceContainer,
    phone: str,
    payload: dict[str, Any],
) -> None:
    await asyncio.to_thread(_process_media_message_async, container, phone, payload)


async def _handle_meta_webhook(
    *,
    request: Request,
    background_tasks: BackgroundTasks,
    container: ServiceContainer,
) -> Response:
    body_bytes = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not container.whatsapp.validate_meta_signature(body_bytes, signature):
        return Response(
            content=json.dumps({"detail": "Invalid Meta signature"}),
            media_type="application/json",
            status_code=403,
        )

    payload = json.loads(body_bytes.decode("utf-8") or "{}")
    logger.warning(
        "Meta webhook received object=%s entry_count=%d",
        payload.get("object"),
        len(payload.get("entry", []) or []),
    )
    if payload.get("object") != "whatsapp_business_account":
        return Response(
            content=json.dumps({"ignored": True, "reason": "unsupported_object"}),
            media_type="application/json",
            status_code=200,
        )

    events = container.whatsapp.parse_meta_webhook_messages(payload)
    statuses = container.whatsapp.parse_meta_webhook_statuses(payload)
    logger.warning(
        "Meta webhook parsed events=%d statuses=%d",
        len(events),
        len(statuses),
    )
    for delivery in statuses:
        phone = normalize_whatsapp_phone(delivery.get("phone"))
        message_id = str(delivery.get("message_id") or "").strip()
        delivery_status = str(delivery.get("status") or "").strip()
        error_code = delivery.get("error_code")
        error_details = str(
            delivery.get("error_details")
            or delivery.get("error_message")
            or delivery.get("error_title")
            or ""
        ).strip()
        log_method = logger.error if delivery_status == "failed" else logger.info
        log_method(
            "Meta delivery status phone=%s message_id=%s status=%s error_code=%s error=%s",
            phone or None,
            message_id or None,
            delivery_status or None,
            error_code,
            error_details or None,
        )
        if phone:
            _record_meta_delivery_status(container, phone, delivery)
    for event in events:
        phone = normalize_whatsapp_phone(event.get("phone"))
        body = str(event.get("body") or "").strip()
        raw_media_entries = event.get("media_entries", [])
        message_type = str(event.get("message_type") or "").strip().lower()
        inbound_message_id = str(event.get("message_id") or "").strip()
        media_entries = _stamp_media_entries(raw_media_entries, message_id=inbound_message_id)
        logger.warning(
            "Meta webhook event phone=%s type=%s media_count=%d has_body=%s message_id=%s",
            phone,
            message_type,
            len(media_entries),
            bool(body),
            inbound_message_id,
        )
        if not phone:
            continue

        employee = container.sheets.get_employee_by_phone(phone)
        if not employee:
            logger.warning("Meta webhook phone not registered phone=%s", phone)
            _safe_send_outbound_text(
                container,
                phone,
                "Tu número no está registrado como empleado activo.",
            )
            continue

        if inbound_message_id and _is_duplicate_inbound_message(container, phone, inbound_message_id):
            logger.warning(
                "Meta webhook duplicate message ignored phone=%s message_id=%s",
                phone,
                inbound_message_id,
            )
            continue

        if inbound_message_id:
            _mark_inbound_message_processed(container, phone, inbound_message_id)

        if media_entries:
            _log_inbound_media_message(
                container,
                phone,
                media_entries,
                caption=body,
                message_id=inbound_message_id or None,
            )
            conversation = container.conversation.ensure_conversation(
                container.sheets.get_conversation(phone)
            )
            context = conversation.get("context_json", {})
            pending_receipts = _get_pending_receipts(context)
            state = str(conversation.get("state", "WAIT_RECEIPT") or "WAIT_RECEIPT")

            if state in ACTIVE_RECEIPT_STATES:
                _enqueue_media_entries(container, phone, media_entries)
                _schedule_receipt_batch_notice(
                    container=container,
                    phone=phone,
                    received_count=len(media_entries),
                    started_processing=False,
                    reply_to_message_id=inbound_message_id,
                )
                continue

            if pending_receipts:
                _enqueue_media_entries(container, phone, media_entries)
                next_payload = _dequeue_next_pending_media_payload(
                    container=container,
                    phone=phone,
                )
                started = next_payload is not None
                if next_payload is not None:
                    await _run_media_processing_during_request(
                        container,
                        phone,
                        next_payload,
                    )
                _schedule_receipt_batch_notice(
                    container=container,
                    phone=phone,
                    received_count=len(media_entries),
                    started_processing=started,
                    reply_to_message_id=inbound_message_id,
                )
                continue

            first_entry = media_entries[0]
            extra_entries = media_entries[1:]
            if extra_entries:
                _enqueue_media_entries(container, phone, extra_entries)
            _set_processing_lock(container, phone)
            first_payload = {
                "MediaId0": first_entry.get("media_id", ""),
                "MediaUrl0": first_entry.get("media_url", ""),
                "MediaContentType0": first_entry.get("media_content_type"),
                "InboundMessageId": first_entry.get("message_id", "") or inbound_message_id,
            }
            logger.warning(
                "Meta image queued for processing phone=%s media_id=%s mime=%s",
                phone,
                first_entry.get("media_id", ""),
                first_entry.get("media_content_type", ""),
            )
            _schedule_receipt_batch_notice(
                container=container,
                phone=phone,
                received_count=len(media_entries),
                started_processing=True,
                reply_to_message_id=inbound_message_id,
            )
            await _run_media_processing_during_request(container, phone, first_payload)
            continue

        if message_type in {"image", "document"} and not media_entries:
            logger.warning(
                "Meta webhook media event skipped: no valid media entry phone=%s type=%s message_id=%s",
                phone,
                message_type,
                inbound_message_id,
            )
            continue

        if not body and not media_entries:
            logger.warning(
                "Meta webhook empty event skipped phone=%s type=%s message_id=%s",
                phone,
                message_type,
                inbound_message_id,
            )
            continue

        _log_inbound_text_message(
            container,
            phone,
            body,
            message_id=inbound_message_id or None,
        )
        response_text = _handle_text_message(container, phone, body)
        next_payload = _dequeue_next_pending_media_payload(
            container=container,
            phone=phone,
        )
        _safe_send_outbound_response(container, phone, response_text)
        if next_payload is not None:
            await _run_media_processing_during_request(container, phone, next_payload)

    return Response(
        content=json.dumps({"processed": len(events), "statuses": len(statuses)}),
        media_type="application/json",
        status_code=200,
        background=background_tasks,
    )


def _record_meta_delivery_status(
    container: ServiceContainer,
    phone: str,
    delivery: dict[str, Any],
) -> None:
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    context = conversation.get("context_json", {})
    if not isinstance(context, dict):
        context = {}
    message_log = context.get("message_log", [])
    if not isinstance(message_log, list):
        return

    message_id = str(delivery.get("message_id") or "").strip()
    updated = False
    next_log: list[Any] = []
    for item in message_log:
        if not isinstance(item, dict) or str(item.get("provider_message_id") or "").strip() != message_id:
            next_log.append(item)
            continue
        next_item = dict(item)
        next_item["delivery_status"] = str(delivery.get("status") or "").strip()
        next_item["delivery_updated_at"] = utc_now_iso()
        if delivery.get("error_code") is not None:
            next_item["delivery_error_code"] = delivery.get("error_code")
        error_detail = str(
            delivery.get("error_details")
            or delivery.get("error_message")
            or delivery.get("error_title")
            or ""
        ).strip()
        if error_detail:
            next_item["delivery_error"] = error_detail
        next_log.append(next_item)
        updated = True

    if not updated:
        return
    container.sheets.update_conversation(
        phone,
        {
            "state": conversation.get("state", "WAIT_RECEIPT"),
            "current_step": conversation.get("current_step", ""),
            "context_json": {**context, "message_log": next_log},
        },
    )


def _extract_media_entries(payload: dict[str, Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    num_media = int(payload.get("NumMedia") or 0)
    inbound_message_id = str(payload.get("MessageSid") or payload.get("SmsSid") or "").strip()
    queued_at = utc_now_iso()
    for index in range(max(1, num_media)):
        media_url = str(payload.get(f"MediaUrl{index}") or "").strip()
        if not media_url:
            continue
        media_content_type = str(payload.get(f"MediaContentType{index}") or "").strip()
        entries.append(
            {
                "media_id": "",
                "media_url": media_url,
                "media_content_type": media_content_type,
                "filename": str(payload.get(f"MediaFilename{index}") or "").strip(),
                "message_type": "document" if media_content_type.lower().startswith("application/pdf") else "image",
                "message_id": inbound_message_id,
                "queued_at": queued_at,
            }
        )
    return entries


def _safe_send_outbound_text(
    container: ServiceContainer,
    phone: str,
    message: str,
    *,
    reply_to_message_id: str | None = None,
) -> None:
    try:
        container.whatsapp.send_outbound_text(
            phone,
            message,
            reply_to_message_id=reply_to_message_id,
        )
        _log_outbound_message(container, phone, message)
    except MetaAccessTokenExpiredError:
        logger.exception(
            "Meta outbound text skipped because the access token expired phone=%s",
            phone,
        )
    except TwilioDailyLimitExceededError:
        logger.warning(
            "No se pudo enviar respuesta por WhatsApp: límite diario de Twilio alcanzado phone=%s",
            phone,
        )
    except Exception:
        logger.exception("Failed to send outbound WhatsApp text phone=%s", phone)


def _safe_send_outbound_response(
    container: ServiceContainer,
    phone: str,
    response_text: str | list[str],
) -> None:
    try:
        _send_outbound_response(container, phone, response_text)
    except MetaAccessTokenExpiredError:
        logger.exception(
            "Meta outbound response skipped because the access token expired phone=%s",
            phone,
        )
    except TwilioDailyLimitExceededError:
        logger.warning(
            "No se pudo enviar respuesta por WhatsApp: límite diario de Twilio alcanzado phone=%s",
            phone,
        )
    except Exception:
        logger.exception("Failed to send outbound WhatsApp response phone=%s", phone)


def _send_outbound_response(
    container: ServiceContainer,
    phone: str,
    response_text: str | list[str],
) -> None:
    logger.info(
        "Outbound response prepared phone=%s response_kind=%s message_count=%d",
        phone,
        "list" if isinstance(response_text, list) else "text",
        len(response_text) if isinstance(response_text, list) else 1,
    )
    if isinstance(response_text, list):
        cleaned_messages = [str(message).strip() for message in response_text if str(message).strip()]
        if not cleaned_messages:
            return
        _send_single_outbound_response(container, phone, cleaned_messages[0])
        for follow_up_message in cleaned_messages[1:]:
            container.whatsapp.send_outbound_text(phone, follow_up_message)
            _log_outbound_message(container, phone, follow_up_message)
        return

    _send_single_outbound_response(container, phone, response_text)


def _coerce_response_to_text(response_text: str | list[str]) -> str:
    if isinstance(response_text, list):
        return "\n\n".join(
            str(message).strip() for message in response_text if str(message).strip()
        ).strip()
    return str(response_text or "").strip()


def _send_single_outbound_response(
    container: ServiceContainer,
    phone: str,
    response_text: str,
) -> None:
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    state = str(conversation.get("state", "") or "")
    current_step = str(conversation.get("current_step", "") or "")
    context = conversation.get("context_json", {})
    reply_to_message_id = _get_active_receipt_message_id(context) or None

    if state == "CONFIRM_SUMMARY" and current_step == "confirm_summary":
        draft = context.get("draft_expense", {}) if isinstance(context, dict) else {}
        if isinstance(draft, dict) and draft:
            body = container.expense.build_summary_message(
                draft,
                include_text_actions=False,
            )
            container.whatsapp.send_outbound_buttons(
                phone,
                body=body,
                buttons=[
                    {"id": "1", "title": "Confirmar"},
                    {"id": "2", "title": "Corregir"},
                    {"id": "3", "title": "Cancelar"},
                ],
                reply_to_message_id=reply_to_message_id,
            )
            _log_outbound_message(container, phone, body)
            return

    interactive_prompt = _build_interactive_prompt(
        state=state,
        current_step=current_step,
        response_text=response_text,
        context=context,
    )
    if interactive_prompt:
        prompt_body = interactive_prompt["body"]
        choices = interactive_prompt["choices"]
        prompt_kind = interactive_prompt.get("kind", "buttons")
        if prompt_kind == "list":
            for batch_index, choice_batch in enumerate(_split_list_choices(choices), start=1):
                batch_body = prompt_body if batch_index == 1 else "Más centros de costo:"
                container.whatsapp.send_outbound_list(
                    phone,
                    body=batch_body,
                    button_text="Ver opciones",
                    items=choice_batch,
                    reply_to_message_id=reply_to_message_id,
                )
        else:
            for batch_index, choice_batch in enumerate(_split_button_choices(choices), start=1):
                batch_body = prompt_body if batch_index == 1 else "Más opciones:"
                container.whatsapp.send_outbound_buttons(
                    phone,
                    body=batch_body,
                    buttons=choice_batch,
                    reply_to_message_id=reply_to_message_id,
                )
        _log_outbound_message(container, phone, prompt_body)
        return

    container.whatsapp.send_outbound_text(
        phone,
        response_text,
        reply_to_message_id=reply_to_message_id,
    )
    _log_outbound_message(container, phone, response_text)


def _build_interactive_prompt(
    *,
    state: str,
    current_step: str,
    response_text: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if state == "NEEDS_INFO" and current_step == "document_type":
        return {
            "body": "No pude identificar con seguridad si este documento es una boleta o una factura. ¿Cuál de las dos es?",
            "choices": [
                {"id": "1", "title": "Boleta"},
                {"id": "2", "title": "Factura"},
            ],
        }

    if state == "CONFIRM_SUMMARY" and current_step == "select_correction_field":
        draft = context.get("draft_expense", {}) if isinstance(context, dict) else {}
        return {
            "body": "¿Qué campo quieres corregir?",
            "choices": [
                {
                    "id": option_id,
                    "title": get_correction_field_label(field_name, draft),
                }
                for option_id, field_name in get_correction_field_options(draft).items()
            ],
        }

    if state == "CONFIRM_SUMMARY" and current_step == "cost_center":
        draft = context.get("draft_expense", {}) if isinstance(context, dict) else {}
        centers = _normalize_cost_center_choices(
            draft.get("cost_centers", []) if isinstance(draft, dict) else []
        )
        if not centers:
            return None
        return {
            "body": (
                "¿A qué centro de costo está dirigido este gasto?\n"
                "Si no está en las opciones, escríbelo para agregarlo al caso."
            ),
            "kind": "list" if len(centers) > 3 else "buttons",
            "choices": _build_cost_center_choices(centers),
        }

    if state == "NEEDS_INFO" and current_step == "currency":
        return {
            "body": "¿Cuál es la moneda?",
            "choices": [
                {"id": option_id, "title": value}
                for option_id, value in CURRENCY_OPTIONS.items()
            ],
        }

    if state == "NEEDS_INFO" and current_step == "category":
        return {
            "body": "¿Cuál es la categoría?",
            "choices": [
                {"id": option_id, "title": value}
                for option_id, value in CATEGORY_OPTIONS.items()
            ],
        }

    if state == "NEEDS_INFO" and current_step == "country":
        return {
            "body": "¿En qué país fue el gasto?",
            "choices": [
                {"id": option_id, "title": value}
                for option_id, value in COUNTRY_OPTIONS.items()
            ]
            + [{"id": "otro", "title": "Otro"}],
        }

    return None


def _split_button_choices(choices: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    clean_choices = [
        choice
        for choice in choices
        if str(choice.get("id") or "").strip() and str(choice.get("title") or "").strip()
    ]
    return [clean_choices[index : index + 3] for index in range(0, len(clean_choices), 3)]


def _split_list_choices(choices: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    clean_choices = [
        choice
        for choice in choices
        if str(choice.get("id") or "").strip() and str(choice.get("title") or "").strip()
    ]
    return [clean_choices[index : index + 10] for index in range(0, len(clean_choices), 10)]


def _build_cost_center_choices(centers: list[str]) -> list[dict[str, str]]:
    return [
        {"id": str(index), "title": center}
        for index, center in enumerate(centers, start=1)
    ]


def _normalize_cost_center_choices(raw_value: Any) -> list[str]:
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            raw_items = parsed
        else:
            raw_items = raw_value.replace("\n", ",").replace(";", ",").split(",")
    elif isinstance(raw_value, (list, tuple, set)):
        raw_items = list(raw_value)
    else:
        raw_items = [raw_value]
    centers: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        center = str(item or "").strip()
        if not center:
            continue
        key = center.lower()
        if key in seen:
            continue
        seen.add(key)
        centers.append(center)
    return centers


def _merge_dicts_preserving_existing(base_value: dict[str, Any], new_value: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base_value)
    for key, value in new_value.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _merge_dicts_preserving_existing(merged[key], value)
        else:
            merged[key] = value
    return merged


def _summarize_receipt_payload(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    summary = {
        "document_type": str(data.get("document_type", "") or "").strip() or None,
        "is_document": bool(data.get("is_document")),
        "merchant": str(data.get("merchant", "") or "").strip() or None,
        "date": str(data.get("date", "") or "").strip() or None,
        "total": data.get("total"),
        "currency": str(data.get("currency", "") or "").strip() or None,
        "country": str(data.get("country", "") or "").strip() or None,
        "category": str(data.get("category", "") or "").strip() or None,
        "case_id": str(data.get("case_id", data.get("trip_id", "")) or "").strip() or None,
    }
    ocr_text = str(data.get("ocr_text", "") or "")
    if ocr_text:
        summary["ocr_text_len"] = len(ocr_text)
    return summary


def _reset_receipt_processing_state(
    container: ServiceContainer,
    phone: str,
    *,
    reason: str,
) -> None:
    try:
        latest_context = _get_latest_context(container, phone)
        reset_context = _clear_active_receipt_message_id(
            _merge_context_preserving_sticky(
                latest_context,
                container.conversation.default_context(),
            )
        )
        container.sheets.update_conversation(
            phone,
            {
                "state": "WAIT_RECEIPT",
                "current_step": "",
                "context_json": reset_context,
            },
        )
        logger.info("Receipt conversation reset phone=%s reason=%s", phone, reason)
    except Exception:  # pragma: no cover - runtime dependency/errors
        logger.exception(
            "Failed to reset receipt conversation after processing error phone=%s reason=%s",
            phone,
            reason,
        )


def _merge_context_preserving_sticky(
    base_context: dict[str, Any] | None,
    new_context: dict[str, Any] | None,
) -> dict[str, Any]:
    base = base_context if isinstance(base_context, dict) else {}
    merged = dict(new_context) if isinstance(new_context, dict) else {}
    for key in STICKY_CONTEXT_KEYS:
        if key not in base:
            continue
        if key not in merged:
            merged[key] = base[key]
            continue
        if isinstance(base[key], dict) and isinstance(merged[key], dict):
            merged[key] = _merge_dicts_preserving_existing(base[key], merged[key])
    if "pending_receipts" not in merged:
        merged["pending_receipts"] = []
    return merged


def _get_message_log(context: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(context, dict):
        return []
    raw = context.get("message_log")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _append_message_log(
    container: ServiceContainer,
    phone: str,
    entry: dict[str, Any],
) -> None:
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    context = conversation.get("context_json", {})
    message_log = _get_message_log(context)
    normalized_entry = {
        "id": str(entry.get("id") or make_id("msg")).strip(),
        "speaker": str(entry.get("speaker") or "").strip() or "system",
        "type": str(entry.get("type") or "").strip() or "text",
        "text": str(entry.get("text") or "").strip(),
        "created_at": str(entry.get("created_at") or utc_now_iso()).strip(),
    }
    if entry.get("message_id"):
        normalized_entry["message_id"] = str(entry.get("message_id")).strip()
    for key in ("media_url", "media_content_type", "image_url", "document_url", "filename"):
        value = str(entry.get(key) or "").strip()
        if value:
            normalized_entry[key] = value
    attachments = entry.get("attachments")
    if isinstance(attachments, list):
        normalized_attachments = []
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            normalized_attachment = {
                key: str(attachment.get(key) or "").strip()
                for key in ("media_url", "media_content_type", "image_url", "document_url", "filename")
                if str(attachment.get(key) or "").strip()
            }
            if normalized_attachment:
                normalized_attachments.append(normalized_attachment)
        if normalized_attachments:
            normalized_entry["attachments"] = normalized_attachments
    message_log.append(normalized_entry)
    updated_context = _merge_context_preserving_sticky(
        context,
        {**context, "message_log": message_log},
    )
    container.sheets.update_conversation(
        phone,
        {
            "state": conversation.get("state", "WAIT_RECEIPT"),
            "current_step": conversation.get("current_step", ""),
            "context_json": updated_context,
        },
    )


def _log_inbound_text_message(
    container: ServiceContainer,
    phone: str,
    text: str,
    *,
    message_id: str | None = None,
) -> None:
    cleaned_text = str(text or "").strip()
    if not cleaned_text:
        return
    _append_message_log(
        container,
        phone,
        {
            "speaker": "person",
            "type": "text",
            "text": cleaned_text,
            "message_id": message_id,
        },
    )


def _log_inbound_media_message(
    container: ServiceContainer,
    phone: str,
    media_entries: list[dict[str, Any]],
    *,
    caption: str = "",
    message_id: str | None = None,
) -> None:
    count = len(media_entries)
    if count <= 0 and not str(caption or "").strip():
        return
    has_pdf = any(
        str(item.get("media_content_type") or "").strip().lower() in {"application/pdf", "image/pdf"}
        or str(item.get("filename") or "").strip().lower().endswith(".pdf")
        for item in media_entries
        if isinstance(item, dict)
    )
    single_label = "Envio un PDF adjunto." if has_pdf and count == 1 else "Envio un comprobante adjunto."
    label = single_label if count == 1 else f"Envio {count} comprobantes adjuntos."
    cleaned_caption = str(caption or "").strip()
    text = label if not cleaned_caption else f"{label}\n{cleaned_caption}"
    first_media_url = str(media_entries[0].get("media_url") or "").strip() if media_entries else ""
    first_media_type = str(media_entries[0].get("media_content_type") or "").strip() if media_entries else ""
    first_filename = str(media_entries[0].get("filename") or "").strip() if media_entries else ""
    first_is_pdf = first_media_type.lower() in {"application/pdf", "image/pdf"} or first_filename.lower().endswith(".pdf")
    first_media_payload = {
        "media_url": "" if first_is_pdf else first_media_url,
        "document_url": first_media_url if first_is_pdf else "",
        "media_content_type": first_media_type,
        "filename": first_filename,
    }
    normalized_attachments = []
    for entry in media_entries:
        if not isinstance(entry, dict):
            continue
        media_url = str(entry.get("media_url") or "").strip()
        media_type = str(entry.get("media_content_type") or "").strip()
        filename = str(entry.get("filename") or "").strip()
        is_pdf = media_type.lower() in {"application/pdf", "image/pdf"} or filename.lower().endswith(".pdf")
        normalized_attachments.append(
            {
                **entry,
                "media_url": "" if is_pdf else media_url,
                "document_url": media_url if is_pdf else str(entry.get("document_url") or "").strip(),
                "media_content_type": media_type,
                "filename": filename,
            }
        )
    _append_message_log(
        container,
        phone,
        {
            "speaker": "person",
            "type": "media",
            "text": text,
            "message_id": message_id,
            **first_media_payload,
            "attachments": normalized_attachments,
        },
    )


def _log_outbound_message(
    container: ServiceContainer,
    phone: str,
    text: str,
) -> None:
    cleaned_text = str(text or "").strip()
    if not cleaned_text:
        return
    _append_message_log(
        container,
        phone,
        {
            "speaker": "bot",
            "type": "text",
            "text": cleaned_text,
        },
    )


def _get_latest_context(container: ServiceContainer, phone: str) -> dict[str, Any]:
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    context = conversation.get("context_json", {})
    return context if isinstance(context, dict) else {}


def _build_signing_return_url(current_settings) -> str:
    public_base_url = str(getattr(current_settings, "public_base_url", "") or "").strip().rstrip("/")
    if public_base_url:
        parsed = urlparse(public_base_url)
        hostname = (parsed.hostname or "").strip().lower()
        if hostname not in {"127.0.0.1", "localhost"}:
            return f"{public_base_url}/docusign/callback?source=signing_complete"
    return str(getattr(current_settings, "docusign_return_url", "") or "").strip()


def _render_docusign_callback_page(
    *,
    title: str,
    message: str,
    detail: str,
    success: bool,
) -> str:
    accent = "#166534" if success else "#991b1b"
    badge = "#dcfce7" if success else "#fee2e2"
    title_safe = html.escape(title)
    message_safe = html.escape(message)
    detail_safe = html.escape(detail)
    return f"""<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title_safe}</title>
  <style>
    :root {{
      --bg: #f5f1e8;
      --card: #fffdf8;
      --text: #1f2937;
      --muted: #6b7280;
      --accent: {accent};
      --badge: {badge};
      --border: rgba(31, 41, 55, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      background:
        radial-gradient(circle at top, rgba(22, 101, 52, 0.10), transparent 30%),
        linear-gradient(180deg, #f8f4ec 0%, var(--bg) 100%);
      color: var(--text);
      font-family: Georgia, "Times New Roman", serif;
      padding: 24px;
    }}
    .card {{
      width: min(100%, 540px);
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 24px;
      padding: 28px;
      box-shadow: 0 20px 50px rgba(31, 41, 55, 0.08);
    }}
    .badge {{
      display: inline-block;
      padding: 8px 12px;
      border-radius: 999px;
      background: var(--badge);
      color: var(--accent);
      font-size: 13px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 18px;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 34px;
      line-height: 1.05;
    }}
    p {{
      margin: 0 0 10px;
      font-size: 18px;
      line-height: 1.5;
    }}
    .detail {{
      color: var(--muted);
      font-size: 15px;
      border-top: 1px solid var(--border);
      margin-top: 18px;
      padding-top: 16px;
    }}
  </style>
</head>
<body>
  <main class="card">
    <div class="badge">Ripley Viaticos</div>
    <h1>{title_safe}</h1>
    <p>{message_safe}</p>
    <p class="detail">{detail_safe}</p>
  </main>
</body>
</html>"""


def _processed_message_ids(context: dict[str, Any] | None) -> list[str]:
    if not isinstance(context, dict):
        return []
    raw = context.get("processed_message_ids")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _is_duplicate_inbound_message(
    container: ServiceContainer,
    phone: str,
    inbound_message_id: str,
) -> bool:
    if not inbound_message_id:
        return False
    context = _get_latest_context(container, phone)
    return inbound_message_id in _processed_message_ids(context)


def _mark_inbound_message_processed(
    container: ServiceContainer,
    phone: str,
    inbound_message_id: str,
) -> None:
    if not inbound_message_id:
        return
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    context = conversation.get("context_json", {})
    processed_ids = _processed_message_ids(context)
    if inbound_message_id in processed_ids:
        return
    processed_ids.append(inbound_message_id)
    processed_ids = processed_ids[-MAX_PROCESSED_MESSAGE_IDS:]
    updated_context = _merge_context_preserving_sticky(
        context,
        {**context, "processed_message_ids": processed_ids},
    )
    container.sheets.update_conversation(
        phone,
        {
            "state": conversation.get("state", "WAIT_RECEIPT"),
            "current_step": conversation.get("current_step", ""),
            "context_json": updated_context,
        },
    )


def _get_pending_receipts(context: dict[str, Any] | None) -> list[dict[str, str]]:
    if not isinstance(context, dict):
        return []
    raw = context.get("pending_receipts")
    if not isinstance(raw, list):
        return []
    entries: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        media_id = str(item.get("media_id") or "").strip()
        media_url = str(item.get("media_url") or "").strip()
        if not media_url and not media_id:
            continue
        queued_at = str(item.get("queued_at") or "").strip()
        if not queued_at:
            continue
        media_content_type = str(item.get("media_content_type") or "").strip()
        entries.append(
            {
                "media_id": media_id,
                "media_url": media_url,
                "media_content_type": media_content_type,
                "filename": str(item.get("filename") or "").strip(),
                "message_type": str(item.get("message_type") or "").strip(),
                "message_id": str(item.get("message_id") or "").strip(),
                "queued_at": queued_at,
            }
        )
    return entries


def _stamp_media_entries(
    media_entries: list[dict[str, Any]] | Any,
    *,
    message_id: str = "",
) -> list[dict[str, str]]:
    if not isinstance(media_entries, list):
        return []
    queued_at = utc_now_iso()
    fallback_message_id = str(message_id or "").strip()
    stamped_entries: list[dict[str, str]] = []
    for item in media_entries:
        if not isinstance(item, dict):
            continue
        media_id = str(item.get("media_id") or "").strip()
        media_url = str(item.get("media_url") or "").strip()
        if not media_id and not media_url:
            continue
        stamped_entries.append(
            {
                "media_id": media_id,
                "media_url": media_url,
                "media_content_type": str(item.get("media_content_type") or "").strip(),
                "filename": str(item.get("filename") or "").strip(),
                "message_type": str(item.get("message_type") or "").strip(),
                "message_id": str(item.get("message_id") or "").strip() or fallback_message_id,
                "queued_at": str(item.get("queued_at") or "").strip() or queued_at,
            }
        )
    return stamped_entries


def _enqueue_media_entries(
    container: ServiceContainer,
    phone: str,
    media_entries: list[dict[str, str]],
) -> int:
    if not media_entries:
        return 0
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    context = conversation.get("context_json", {})
    pending = _get_pending_receipts(context)
    pending.extend(media_entries)
    merged_context = _merge_context_preserving_sticky(
        context,
        {**context, "pending_receipts": pending},
    )
    container.sheets.update_conversation(
        phone,
        {
            "state": conversation.get("state", "WAIT_RECEIPT"),
            "current_step": conversation.get("current_step", ""),
            "context_json": merged_context,
        },
    )
    return len(pending)


def _dequeue_next_pending_media_payload(
    *,
    container: ServiceContainer,
    phone: str,
) -> dict[str, str] | None:
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    state = str(conversation.get("state", "WAIT_RECEIPT") or "WAIT_RECEIPT")
    if state in ACTIVE_RECEIPT_STATES:
        return None
    context = conversation.get("context_json", {})
    pending = _get_pending_receipts(context)
    if not pending:
        return None
    next_media = pending.pop(0)
    updated_context = _merge_context_preserving_sticky(
        context,
        {**context, "pending_receipts": pending},
    )
    processing_context = _merge_context_preserving_sticky(
        updated_context,
        container.conversation.default_context(),
    )
    container.sheets.update_conversation(
        phone,
        {
            "state": "PROCESSING",
            "current_step": "",
            "context_json": processing_context,
        },
    )
    return {
        "MediaId0": next_media.get("media_id", ""),
        "MediaUrl0": next_media.get("media_url", ""),
        "MediaContentType0": next_media.get("media_content_type", ""),
        "InboundMessageId": next_media.get("message_id", ""),
    }


def _maybe_schedule_next_pending_media(
    *,
    container: ServiceContainer,
    phone: str,
) -> bool:
    next_payload = _dequeue_next_pending_media_payload(
        container=container,
        phone=phone,
    )
    if next_payload is None:
        return False
    _spawn_media_processing_task(container, phone, next_payload)
    return True


def _maybe_process_next_pending_media_inline(
    container: ServiceContainer,
    phone: str,
) -> bool:
    next_payload = _dequeue_next_pending_media_payload(
        container=container,
        phone=phone,
    )
    if next_payload is None:
        return False
    _process_media_message_async(container, phone, next_payload)
    return True


def _schedule_receipt_batch_notice(
    *,
    container: ServiceContainer,
    phone: str,
    received_count: int,
    started_processing: bool,
    reply_to_message_id: str,
) -> None:
    if received_count <= 0:
        return

    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    context = conversation.get("context_json", {})
    notice = _get_receipt_batch_notice(context)
    notice_token = make_id("RCPT")
    updated_notice = {
        "token": notice_token,
        "received_count": int(notice.get("received_count") or 0) + received_count,
        "started_processing": bool(notice.get("started_processing")) or started_processing,
        "reply_to_message_id": reply_to_message_id or str(notice.get("reply_to_message_id") or "").strip(),
        "updated_at": utc_now_iso(),
    }
    merged_context = _merge_context_preserving_sticky(
        context,
        {**context, "receipt_batch_notice": updated_notice},
    )
    container.sheets.update_conversation(
        phone,
        {
            "state": conversation.get("state", "WAIT_RECEIPT"),
            "current_step": conversation.get("current_step", ""),
            "context_json": merged_context,
        },
    )
    _spawn_receipt_batch_notice_task(container, phone, notice_token)


async def _debounced_send_receipt_batch_notice(
    container: ServiceContainer,
    phone: str,
    notice_token: str,
) -> None:
    await asyncio.sleep(RECEIPT_BATCH_NOTICE_DELAY_SECONDS)

    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    state = str(conversation.get("state", "WAIT_RECEIPT") or "WAIT_RECEIPT")
    context = conversation.get("context_json", {})
    notice = _get_receipt_batch_notice(context)
    if str(notice.get("token") or "").strip() != str(notice_token or "").strip():
        return

    received_count = int(notice.get("received_count") or 0)
    started_processing = bool(notice.get("started_processing"))
    if received_count <= 0:
        _clear_receipt_batch_notice(container, phone)
        return

    reply_to_message_id = str(notice.get("reply_to_message_id") or "").strip() or None
    if received_count == 1:
        if started_processing:
            _clear_receipt_batch_notice(container, phone)
            return
        message = "Recibí tu documento. Lo revisaré apenas termine el actual."
    else:
        message = f"Recibí {received_count} documento(s). Los revisaré uno por uno."

    try:
        container.whatsapp.send_outbound_text(
            phone,
            message,
            reply_to_message_id=reply_to_message_id,
        )
        _log_outbound_message(container, phone, message)
    except TwilioDailyLimitExceededError:
        logger.warning(
            "No se pudo enviar aviso agregado de documentos: límite diario de Twilio alcanzado phone=%s",
            phone,
        )
    except Exception:
        logger.exception("Failed to send debounced receipt batch notice phone=%s", phone)
    finally:
        _clear_receipt_batch_notice(container, phone)


def _set_processing_lock(
    container: ServiceContainer,
    phone: str,
    *,
    current_step: str = "",
) -> None:
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    context = conversation.get("context_json", {})
    processing_context = _merge_context_preserving_sticky(
        context,
        container.conversation.default_context(),
    )
    container.sheets.update_conversation(
        phone,
        {
            "state": "PROCESSING",
            "current_step": current_step,
            "context_json": processing_context,
        },
    )


def _clear_active_receipt_message_id(context: dict[str, Any] | None) -> dict[str, Any]:
    normalized = dict(context) if isinstance(context, dict) else {}
    normalized.pop("active_receipt_message_id", None)
    normalized.pop("prefilled_case_id", None)
    return normalized


def _get_receipt_batch_notice(context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    notice = context.get("receipt_batch_notice")
    return notice if isinstance(notice, dict) else {}


def _clear_receipt_batch_notice(container: ServiceContainer, phone: str) -> None:
    conversation = container.conversation.ensure_conversation(
        container.sheets.get_conversation(phone)
    )
    context = conversation.get("context_json", {})
    if not isinstance(context, dict) or "receipt_batch_notice" not in context:
        return
    updated_context = dict(context)
    updated_context.pop("receipt_batch_notice", None)
    container.sheets.update_conversation(
        phone,
        {
            "state": conversation.get("state", "WAIT_RECEIPT"),
            "current_step": conversation.get("current_step", ""),
            "context_json": updated_context,
        },
    )


def _get_active_receipt_message_id(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    return str(context.get("active_receipt_message_id") or "").strip()


app = create_app()
