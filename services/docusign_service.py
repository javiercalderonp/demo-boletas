from __future__ import annotations

import json
import logging
import base64
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.config import Settings

logger = logging.getLogger(__name__)


class DocusignError(RuntimeError):
    pass


@dataclass
class DocusignService:
    settings: Settings

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
        clean_document_name = str(document_name or "").strip() or "Reporte viaticos"
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
            "emailSubject": email_subject or "Firma requerida - reporte de viaticos",
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
        return self._request_json_absolute(
            method="POST",
            url="https://account-d.docusign.com/oauth/token",
            headers=headers,
            body=body,
        )

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        base_url = str(self.settings.docusign_base_url or "").strip().rstrip("/")
        if not base_url:
            raise DocusignError("DOCUSIGN_BASE_URL vacio")

        url = f"{base_url}{path}"
        token = str(self.settings.docusign_access_token or "").strip()
        if not token:
            raise DocusignError("DOCUSIGN_ACCESS_TOKEN vacio")

        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "TravelExpenseAgent/1.0",
        }
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = Request(url, method=method.upper(), headers=headers, data=body)
        return self._read_json_response(request)

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

    def _read_json_response(self, request: Request) -> dict[str, Any]:
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            logger.warning("DocuSign HTTP error status=%s details=%s", exc.code, details)
            if exc.code == 401:
                raise DocusignError("DocuSign access token invalido o expirado") from exc
            raise DocusignError(f"DocuSign respondio HTTP {exc.code}") from exc
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
