from __future__ import annotations

import json
import logging
import base64
from dataclasses import dataclass
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import Settings

logger = logging.getLogger(__name__)


class DocusignError(RuntimeError):
    pass


class DocusignHttpError(DocusignError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class DocusignService:
    settings: Settings

    def __post_init__(self) -> None:
        self._token_refresh_lock = Lock()

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.docusign_enabled
            and self.settings.docusign_base_url
            and self.settings.docusign_account_id
            and self.settings.docusign_access_token
        )

    def create_envelope_from_remote_pdf(
        self,
        *,
        signer_name: str,
        signer_email: str,
        document_name: str,
        document_url: str,
        client_user_id: str | None = None,
        email_subject: str | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise DocusignError("DocuSign no esta configurado")

        clean_signer_name = str(signer_name or "").strip()
        clean_signer_email = str(signer_email or "").strip()
        clean_document_name = str(document_name or "").strip() or "Rendicion de gastos"
        clean_document_url = str(document_url or "").strip()

        if not clean_signer_name:
            raise DocusignError("signer_name vacio")
        if not clean_signer_email:
            raise DocusignError("signer_email vacio")
        if not clean_document_url:
            raise DocusignError("document_url vacio")

        signer_payload: dict[str, Any] = {
            "email": clean_signer_email,
            "name": clean_signer_name,
            "recipientId": "1",
            "routingOrder": "1",
            "tabs": {
                "signHereTabs": [
                    {
                        "documentId": "1",
                        "anchorString": "[[DS_SIGN_HERE]]",
                        "anchorUnits": "pixels",
                        "anchorXOffset": "0",
                        "anchorYOffset": "0",
                    }
                ]
            },
        }
        if client_user_id:
            signer_payload["clientUserId"] = str(client_user_id)

        payload = {
            "emailSubject": email_subject or "Firma requerida - rendicion de gastos",
            "documents": [
                {
                    "documentId": "1",
                    "name": clean_document_name,
                    "fileExtension": "pdf",
                    "remoteUrl": clean_document_url,
                }
            ],
            "recipients": {
                "signers": [signer_payload],
            },
            "status": "sent",
        }

        return self._request_json(
            "POST",
            f"/v2.1/accounts/{self.settings.docusign_account_id}/envelopes",
            payload=payload,
        )

    def create_recipient_view(
        self,
        *,
        envelope_id: str,
        signer_name: str,
        signer_email: str,
        client_user_id: str,
        return_url: str | None = None,
    ) -> str:
        if not self.enabled:
            raise DocusignError("DocuSign no esta configurado")

        clean_envelope_id = str(envelope_id or "").strip()
        clean_signer_name = str(signer_name or "").strip()
        clean_signer_email = str(signer_email or "").strip()
        clean_client_user_id = str(client_user_id or "").strip()
        clean_return_url = str(return_url or self.settings.docusign_return_url or "").strip()

        if not clean_envelope_id:
            raise DocusignError("envelope_id vacio")
        if not clean_signer_name:
            raise DocusignError("signer_name vacio")
        if not clean_signer_email:
            raise DocusignError("signer_email vacio")
        if not clean_client_user_id:
            raise DocusignError("client_user_id vacio")
        if not clean_return_url:
            raise DocusignError("return_url vacio")

        payload = {
            "returnUrl": clean_return_url,
            "authenticationMethod": "none",
            "userName": clean_signer_name,
            "email": clean_signer_email,
            "clientUserId": clean_client_user_id,
        }
        data = self._request_json(
            "POST",
            (
                f"/v2.1/accounts/{self.settings.docusign_account_id}/envelopes/"
                f"{clean_envelope_id}/views/recipient"
            ),
            payload=payload,
        )
        url = str(data.get("url", "") or "").strip()
        if not url:
            raise DocusignError("DocuSign no devolvio URL de firma")
        return url

    def exchange_authorization_code(
        self,
        *,
        code: str,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        integration_key = str(self.settings.docusign_integration_key or "").strip()
        secret_key = str(self.settings.docusign_secret_key or "").strip()
        clean_code = str(code or "").strip()
        clean_redirect_uri = str(redirect_uri or self.settings.docusign_return_url or "").strip()

        if not integration_key:
            raise DocusignError("DOCUSIGN_INTEGRATION_KEY vacio")
        if not secret_key:
            raise DocusignError("DOCUSIGN_SECRET_KEY vacio")
        if not clean_code:
            raise DocusignError("authorization code vacio")
        if not clean_redirect_uri:
            raise DocusignError("redirect_uri vacio")

        basic_token = base64.b64encode(f"{integration_key}:{secret_key}".encode("utf-8")).decode(
            "ascii"
        )
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "code": clean_code,
                "redirect_uri": clean_redirect_uri,
            }
        ).encode("utf-8")
        headers = {
            "Authorization": f"Basic {basic_token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "TravelExpenseAgent/1.0",
        }
        token_response = self._request_json_absolute(
            method="POST",
            url="https://account-d.docusign.com/oauth/token",
            headers=headers,
            body=body,
        )
        self._persist_tokens_from_response(token_response)
        return token_response

    def refresh_access_token(self) -> dict[str, Any]:
        integration_key = str(self.settings.docusign_integration_key or "").strip()
        secret_key = str(self.settings.docusign_secret_key or "").strip()
        refresh_token = str(self.settings.docusign_refresh_token or "").strip()
        if not integration_key:
            raise DocusignError("DOCUSIGN_INTEGRATION_KEY vacio")
        if not secret_key:
            raise DocusignError("DOCUSIGN_SECRET_KEY vacio")
        if not refresh_token:
            raise DocusignError("DOCUSIGN_REFRESH_TOKEN vacio")

        basic_token = base64.b64encode(f"{integration_key}:{secret_key}".encode("utf-8")).decode(
            "ascii"
        )
        body = urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        ).encode("utf-8")
        headers = {
            "Authorization": f"Basic {basic_token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "TravelExpenseAgent/1.0",
        }
        token_response = self._request_json_absolute(
            method="POST",
            url="https://account-d.docusign.com/oauth/token",
            headers=headers,
            body=body,
        )
        self._persist_tokens_from_response(token_response)
        logger.info(
            "DocuSign access token refreshed expires_in=%s",
            token_response.get("expires_in"),
        )
        return token_response

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        base_url = str(self.settings.docusign_base_url or "").strip().rstrip("/")
        if not base_url:
            raise DocusignError("DOCUSIGN_BASE_URL vacio")

        url = f"{base_url}{path}"
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        return self._request_json_with_auto_refresh(
            method=method,
            url=url,
            body=body,
            allow_refresh=True,
        )

    def _request_json_with_auto_refresh(
        self,
        *,
        method: str,
        url: str,
        body: bytes | None,
        allow_refresh: bool,
    ) -> dict[str, Any]:
        token = str(self.settings.docusign_access_token or "").strip()
        if not token:
            raise DocusignError("DOCUSIGN_ACCESS_TOKEN vacio")

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "TravelExpenseAgent/1.0",
        }
        request = Request(url, method=method.upper(), headers=headers, data=body)
        try:
            return self._read_json_response(request)
        except DocusignHttpError as exc:
            if exc.status_code != 401 or not allow_refresh or not self._can_auto_refresh_token():
                raise
            logger.warning("DocuSign token expired; refreshing token and retrying request")
            with self._token_refresh_lock:
                self.refresh_access_token()
            return self._request_json_with_auto_refresh(
                method=method,
                url=url,
                body=body,
                allow_refresh=False,
            )

    def _request_json_absolute(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        body: bytes | None = None,
    ) -> dict[str, Any]:
        request = Request(url, method=method.upper(), headers=headers, data=body)
        return self._read_json_response(request)

    def _can_auto_refresh_token(self) -> bool:
        return bool(
            str(self.settings.docusign_integration_key or "").strip()
            and str(self.settings.docusign_secret_key or "").strip()
            and str(self.settings.docusign_refresh_token or "").strip()
        )

    def _persist_tokens_from_response(self, token_response: dict[str, Any]) -> None:
        access_token = str(token_response.get("access_token", "") or "").strip()
        refresh_token = str(token_response.get("refresh_token", "") or "").strip()
        if access_token:
            self.settings.docusign_access_token = access_token
        if refresh_token:
            self.settings.docusign_refresh_token = refresh_token

    def _read_json_response(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            logger.warning("DocuSign HTTP error status=%s details=%s", exc.code, details)
            if exc.code == 401:
                raise DocusignHttpError(401, "DocuSign access token invalido o expirado") from exc
            raise DocusignHttpError(exc.code, f"DocuSign respondio HTTP {exc.code}") from exc
        except URLError as exc:
            raise DocusignError("No se pudo conectar con DocuSign") from exc

        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DocusignError("Respuesta invalida de DocuSign") from exc
        if not isinstance(parsed, dict):
            raise DocusignError("Respuesta inesperada de DocuSign")
        return parsed
