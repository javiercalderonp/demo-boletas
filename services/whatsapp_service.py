from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from html import escape
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import Settings

logger = logging.getLogger(__name__)


class TwilioDailyLimitExceededError(RuntimeError):
    """Raised when Twilio blocks outbound send due to daily quota."""


class MetaAccessTokenExpiredError(RuntimeError):
    """Raised when Meta rejects the request because the access token expired."""


@dataclass
class WhatsAppService:
    settings: Settings

    @property
    def provider(self) -> str:
        return (self.settings.whatsapp_provider or "meta").strip().lower()

    def validate_incoming_request(
        self, url: str, form_data: dict[str, Any], signature: str | None
    ) -> bool:
        if self.provider != "twilio":
            return True
        if not self.settings.twilio_validate_signature:
            return True
        if not signature:
            return False
        try:
            from twilio.request_validator import RequestValidator
        except ImportError:
            return False
        validator = RequestValidator(self.settings.twilio_auth_token)
        return bool(validator.validate(url, form_data, signature))

    def validate_meta_signature(self, body: bytes, signature: str | None) -> bool:
        if self.provider != "meta":
            return True
        if not self.settings.meta_validate_signature:
            return True
        app_secret = (self.settings.meta_app_secret or "").strip()
        if not signature or not app_secret:
            return False
        prefix = "sha256="
        if not signature.startswith(prefix):
            return False
        expected = hmac.new(
            app_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(signature[len(prefix) :], expected)

    def is_meta_webhook_verification_valid(self, mode: str | None, token: str | None) -> bool:
        return (
            self.provider == "meta"
            and (mode or "").strip() == "subscribe"
            and (token or "").strip() == (self.settings.meta_verify_token or "").strip()
        )

    def build_twiml_message(self, message: str) -> str:
        safe_msg = escape(message or "")
        return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{safe_msg}</Message></Response>'

    def build_empty_twiml(self) -> str:
        return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

    def send_outbound_text(
        self,
        to_phone: str,
        message: str,
        *,
        reply_to_message_id: str | None = None,
    ) -> dict[str, Any]:
        if self.provider == "meta":
            try:
                return self._send_outbound_text_meta(
                    to_phone,
                    message,
                    reply_to_message_id=reply_to_message_id,
                )
            except MetaAccessTokenExpiredError:
                raise
            except Exception:
                if reply_to_message_id:
                    logger.exception(
                        "Meta text send with reply context failed, retrying without context to_phone=%s",
                        to_phone,
                    )
                    return self._send_outbound_text_meta(
                        to_phone,
                        message,
                        reply_to_message_id=None,
                    )
                raise

        account_sid = (self.settings.twilio_account_sid or "").strip()
        auth_token = (self.settings.twilio_auth_token or "").strip()
        from_whatsapp = (self.settings.twilio_whatsapp_from or "").strip()
        if not account_sid or not auth_token or not from_whatsapp:
            raise RuntimeError(
                "Faltan credenciales/config de Twilio para envío saliente "
                "(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM)."
            )

        if not from_whatsapp.startswith("whatsapp:"):
            from_whatsapp = f"whatsapp:{from_whatsapp}"
        to_whatsapp = to_phone if str(to_phone).startswith("whatsapp:") else f"whatsapp:{to_phone}"

        try:
            from twilio.rest import Client
        except ImportError as exc:
            raise RuntimeError("Falta dependencia twilio para envío saliente.") from exc

        client = Client(account_sid, auth_token)
        try:
            twilio_message = client.messages.create(
                from_=from_whatsapp,
                to=to_whatsapp,
                body=message or "",
            )
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code == 63038:
                logger.warning("Twilio daily outbound message limit reached account_sid=%s", account_sid)
                raise TwilioDailyLimitExceededError(str(exc)) from exc
            raise
        return {
            "sid": getattr(twilio_message, "sid", None),
            "status": getattr(twilio_message, "status", None),
            "to": to_whatsapp,
            "from": from_whatsapp,
        }

    def send_outbound_buttons(
        self,
        to_phone: str,
        *,
        body: str,
        buttons: list[dict[str, str]],
        reply_to_message_id: str | None = None,
    ) -> dict[str, Any]:
        clean_buttons = [
            {
                "id": str(button.get("id") or "").strip(),
                "title": str(button.get("title") or "").strip(),
            }
            for button in (buttons or [])
            if str(button.get("id") or "").strip() and str(button.get("title") or "").strip()
        ][:3]
        if not clean_buttons:
            return self.send_outbound_text(
                to_phone,
                body,
                reply_to_message_id=reply_to_message_id,
            )

        if self.provider == "meta":
            try:
                return self._send_outbound_buttons_meta(
                    to_phone,
                    body=body,
                    buttons=clean_buttons,
                    reply_to_message_id=reply_to_message_id,
                )
            except Exception:
                logger.exception(
                    "Meta interactive buttons failed, falling back to text to_phone=%s",
                    to_phone,
                )
                fallback_lines = [body.rstrip(), ""]
                for index, button in enumerate(clean_buttons, start=1):
                    fallback_lines.append(f"{index}. {button['title']}")
                return self.send_outbound_text(
                    to_phone,
                    "\n".join(fallback_lines).strip(),
                    reply_to_message_id=reply_to_message_id,
                )

        fallback_lines = [body.rstrip(), ""]
        for index, button in enumerate(clean_buttons, start=1):
            fallback_lines.append(f"{index}. {button['title']}")
        return self.send_outbound_text(
            to_phone,
            "\n".join(fallback_lines).strip(),
            reply_to_message_id=reply_to_message_id,
        )

    def send_outbound_list(
        self,
        to_phone: str,
        *,
        body: str,
        button_text: str,
        items: list[dict[str, str]],
        reply_to_message_id: str | None = None,
    ) -> dict[str, Any]:
        clean_items = [
            {
                "id": str(item.get("id") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "description": str(item.get("description") or "").strip(),
            }
            for item in (items or [])
            if str(item.get("id") or "").strip() and str(item.get("title") or "").strip()
        ][:10]
        if not clean_items:
            return self.send_outbound_text(
                to_phone,
                body,
                reply_to_message_id=reply_to_message_id,
            )

        if self.provider == "meta":
            try:
                return self._send_outbound_list_meta(
                    to_phone,
                    body=body,
                    button_text=button_text,
                    items=clean_items,
                    reply_to_message_id=reply_to_message_id,
                )
            except Exception:
                logger.exception(
                    "Meta interactive list failed, falling back to text to_phone=%s",
                    to_phone,
                )
                fallback_lines = [body.rstrip(), ""]
                for index, item in enumerate(clean_items, start=1):
                    fallback_lines.append(f"{index}. {item['title']}")
                return self.send_outbound_text(
                    to_phone,
                    "\n".join(fallback_lines).strip(),
                    reply_to_message_id=reply_to_message_id,
                )

        fallback_lines = [body.rstrip(), ""]
        for index, item in enumerate(clean_items, start=1):
            fallback_lines.append(f"{index}. {item['title']}")
        return self.send_outbound_text(
            to_phone,
            "\n".join(fallback_lines).strip(),
            reply_to_message_id=reply_to_message_id,
        )

    def send_outbound_document(
        self,
        to_phone: str,
        document_url: str,
        *,
        filename: str,
        caption: str = "",
    ) -> dict[str, Any]:
        clean_document_url = str(document_url or "").strip()
        clean_filename = str(filename or "").strip() or "documento.pdf"
        if not clean_document_url:
            raise RuntimeError("document_url vacio para envio WhatsApp")

        if self.provider == "meta":
            return self._send_outbound_document_meta(
                to_phone,
                clean_document_url,
                filename=clean_filename,
                caption=caption,
            )

        account_sid = (self.settings.twilio_account_sid or "").strip()
        auth_token = (self.settings.twilio_auth_token or "").strip()
        from_whatsapp = (self.settings.twilio_whatsapp_from or "").strip()
        if not account_sid or not auth_token or not from_whatsapp:
            raise RuntimeError(
                "Faltan credenciales/config de Twilio para envio saliente "
                "(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM)."
            )

        if not from_whatsapp.startswith("whatsapp:"):
            from_whatsapp = f"whatsapp:{from_whatsapp}"
        to_whatsapp = to_phone if str(to_phone).startswith("whatsapp:") else f"whatsapp:{to_phone}"

        try:
            from twilio.rest import Client
        except ImportError as exc:
            raise RuntimeError("Falta dependencia twilio para envio saliente.") from exc

        client = Client(account_sid, auth_token)
        try:
            twilio_message = client.messages.create(
                from_=from_whatsapp,
                to=to_whatsapp,
                body=caption or "",
                media_url=[clean_document_url],
            )
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code == 63038:
                logger.warning("Twilio daily outbound message limit reached account_sid=%s", account_sid)
                raise TwilioDailyLimitExceededError(str(exc)) from exc
            raise
        return {
            "sid": getattr(twilio_message, "sid", None),
            "status": getattr(twilio_message, "status", None),
            "to": to_whatsapp,
            "from": from_whatsapp,
            "filename": clean_filename,
        }

    def parse_meta_webhook_messages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for entry in payload.get("entry", []) or []:
            if not isinstance(entry, dict):
                continue
            for change in entry.get("changes", []) or []:
                if not isinstance(change, dict):
                    continue
                value = change.get("value", {})
                if not isinstance(value, dict):
                    continue
                contacts = value.get("contacts", []) or []
                contact = contacts[0] if contacts and isinstance(contacts[0], dict) else {}
                profile = contact.get("profile", {}) if isinstance(contact, dict) else {}
                contact_name = profile.get("name") if isinstance(profile, dict) else None
                for message in value.get("messages", []) or []:
                    if not isinstance(message, dict):
                        continue
                    message_type = str(message.get("type") or "").strip().lower()
                    body = ""
                    media_entries: list[dict[str, str]] = []
                    if message_type == "text":
                        text_obj = message.get("text", {})
                        if isinstance(text_obj, dict):
                            body = str(text_obj.get("body") or "").strip()
                    elif message_type in {"image", "document"}:
                        media_obj = message.get(message_type, {})
                        if isinstance(media_obj, dict) and media_obj.get("id"):
                            media_entries.append(
                                {
                                    "media_id": str(media_obj.get("id") or "").strip(),
                                    "media_url": "",
                                    "media_content_type": str(
                                        media_obj.get("mime_type") or ""
                                    ).strip(),
                                    "message_id": str(message.get("id") or "").strip(),
                                }
                            )
                            body = str(media_obj.get("caption") or "").strip()
                    elif message_type == "interactive":
                        interactive = message.get("interactive", {})
                        if isinstance(interactive, dict):
                            button_reply = interactive.get("button_reply", {})
                            list_reply = interactive.get("list_reply", {})
                            button_body = ""
                            list_body = ""
                            if isinstance(button_reply, dict):
                                button_body = str(
                                    button_reply.get("title") or button_reply.get("id") or ""
                                ).strip()
                            if isinstance(list_reply, dict):
                                list_body = str(
                                    list_reply.get("title") or list_reply.get("id") or ""
                                ).strip()
                            body = button_body or list_body

                    events.append(
                        {
                            "phone": str(message.get("from") or "").strip(),
                            "body": body,
                            "message_type": message_type,
                            "media_entries": media_entries,
                            "message_id": str(message.get("id") or "").strip(),
                            "contact_name": contact_name,
                        }
                    )
        return [event for event in events if event.get("phone")]

    def get_meta_media_url(self, media_id: str) -> tuple[str, str]:
        if self.provider != "meta":
            raise RuntimeError("Resolución de media Meta no disponible con proveedor actual.")
        response = self._meta_request_json(
            method="GET",
            path=f"/{media_id}",
        )
        media_url = str(response.get("url") or "").strip()
        mime_type = str(response.get("mime_type") or "").strip()
        if not media_url:
            raise RuntimeError("Meta no devolvió URL temporal para el adjunto.")
        return media_url, mime_type

    def get_media_download_auth_header(self) -> str | None:
        if self.provider == "meta":
            token = (self.settings.meta_access_token or "").strip()
            return f"Bearer {token}" if token else None

        sid = (self.settings.twilio_account_sid or "").strip()
        token = (self.settings.twilio_auth_token or "").strip()
        if not sid or not token:
            return None
        raw = f"{sid}:{token}".encode("utf-8")
        import base64

        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _send_outbound_text_meta(
        self,
        to_phone: str,
        message: str,
        *,
        reply_to_message_id: str | None = None,
    ) -> dict[str, Any]:
        phone_number_id = (self.settings.meta_phone_number_id or "").strip()
        access_token = (self.settings.meta_access_token or "").strip()
        if not phone_number_id or not access_token:
            raise RuntimeError(
                "Faltan credenciales/config de Meta para envío saliente "
                "(META_ACCESS_TOKEN, META_PHONE_NUMBER_ID)."
            )

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_meta_recipient(to_phone),
            "type": "text",
            "text": {
                "preview_url": False,
                "body": message or "",
            },
        }
        if str(reply_to_message_id or "").strip():
            payload["context"] = {"message_id": str(reply_to_message_id).strip()}

        logger.warning(
            "Meta outbound text sending to=%s reply_to=%s body_preview=%s",
            self._normalize_meta_recipient(to_phone),
            str(reply_to_message_id or "").strip() or None,
            (message or "")[:80],
        )
        response = self._meta_request_json(
            method="POST",
            path=f"/{phone_number_id}/messages",
            payload=payload,
        )
        messages = response.get("messages", []) or []
        message_id = None
        if messages and isinstance(messages[0], dict):
            message_id = messages[0].get("id")
        logger.warning(
            "Meta outbound text sent to=%s message_id=%s",
            self._normalize_meta_recipient(to_phone),
            message_id,
        )
        return {
            "id": message_id,
            "to": self._normalize_meta_recipient(to_phone),
            "provider": "meta",
        }

    def _send_outbound_buttons_meta(
        self,
        to_phone: str,
        *,
        body: str,
        buttons: list[dict[str, str]],
        reply_to_message_id: str | None = None,
    ) -> dict[str, Any]:
        phone_number_id = (self.settings.meta_phone_number_id or "").strip()
        access_token = (self.settings.meta_access_token or "").strip()
        if not phone_number_id or not access_token:
            raise RuntimeError(
                "Faltan credenciales/config de Meta para envío saliente "
                "(META_ACCESS_TOKEN, META_PHONE_NUMBER_ID)."
            )

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_meta_recipient(to_phone),
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body or ""},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {
                                "id": button["id"],
                                "title": button["title"],
                            },
                        }
                        for button in buttons
                    ]
                },
            },
        }
        if str(reply_to_message_id or "").strip():
            payload["context"] = {"message_id": str(reply_to_message_id).strip()}

        response = self._meta_request_json(
            method="POST",
            path=f"/{phone_number_id}/messages",
            payload=payload,
        )
        messages = response.get("messages", []) or []
        message_id = None
        if messages and isinstance(messages[0], dict):
            message_id = messages[0].get("id")
        return {
            "id": message_id,
            "to": self._normalize_meta_recipient(to_phone),
            "provider": "meta",
            "message_type": "interactive",
        }

    def _send_outbound_list_meta(
        self,
        to_phone: str,
        *,
        body: str,
        button_text: str,
        items: list[dict[str, str]],
        reply_to_message_id: str | None = None,
    ) -> dict[str, Any]:
        phone_number_id = (self.settings.meta_phone_number_id or "").strip()
        access_token = (self.settings.meta_access_token or "").strip()
        if not phone_number_id or not access_token:
            raise RuntimeError(
                "Faltan credenciales/config de Meta para envío saliente "
                "(META_ACCESS_TOKEN, META_PHONE_NUMBER_ID)."
            )

        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": self._normalize_meta_recipient(to_phone),
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body or ""},
                "action": {
                    "button": button_text or "Ver opciones",
                    "sections": [
                        {
                            "title": "Opciones",
                            "rows": [
                                {
                                    "id": item["id"],
                                    "title": item["title"],
                                    **(
                                        {"description": item["description"]}
                                        if item.get("description")
                                        else {}
                                    ),
                                }
                                for item in items
                            ],
                        }
                    ],
                },
            },
        }
        if str(reply_to_message_id or "").strip():
            payload["context"] = {"message_id": str(reply_to_message_id).strip()}

        response = self._meta_request_json(
            method="POST",
            path=f"/{phone_number_id}/messages",
            payload=payload,
        )
        messages = response.get("messages", []) or []
        message_id = None
        if messages and isinstance(messages[0], dict):
            message_id = messages[0].get("id")
        return {
            "id": message_id,
            "to": self._normalize_meta_recipient(to_phone),
            "provider": "meta",
            "message_type": "interactive",
        }

    def _send_outbound_document_meta(
        self,
        to_phone: str,
        document_url: str,
        *,
        filename: str,
        caption: str = "",
    ) -> dict[str, Any]:
        phone_number_id = (self.settings.meta_phone_number_id or "").strip()
        access_token = (self.settings.meta_access_token or "").strip()
        if not phone_number_id or not access_token:
            raise RuntimeError(
                "Faltan credenciales/config de Meta para envio saliente "
                "(META_ACCESS_TOKEN, META_PHONE_NUMBER_ID)."
            )

        document_payload: dict[str, Any] = {
            "link": document_url,
            "filename": filename,
        }
        if caption:
            document_payload["caption"] = caption

        response = self._meta_request_json(
            method="POST",
            path=f"/{phone_number_id}/messages",
            payload={
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": self._normalize_meta_recipient(to_phone),
                "type": "document",
                "document": document_payload,
            },
        )
        messages = response.get("messages", []) or []
        message_id = None
        if messages and isinstance(messages[0], dict):
            message_id = messages[0].get("id")
        return {
            "id": message_id,
            "to": self._normalize_meta_recipient(to_phone),
            "provider": "meta",
            "filename": filename,
        }

    def _meta_request_json(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        access_token = (self.settings.meta_access_token or "").strip()
        if not access_token:
            raise RuntimeError("Falta META_ACCESS_TOKEN.")

        graph_version = (self.settings.meta_graph_version or "v22.0").strip()
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = f"https://graph.facebook.com/{graph_version}{normalized_path}"

        body = None
        headers = {
            "Authorization": f"Bearer {access_token}",
            "User-Agent": "TravelExpenseAgent/1.0",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url, data=body, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=20) as response:
                raw = response.read().decode("utf-8") if response else ""
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if self._is_meta_access_token_expired(exc.code, detail):
                raise MetaAccessTokenExpiredError(
                    "Meta access token expired. Update META_ACCESS_TOKEN and retry."
                ) from exc
            raise RuntimeError(f"Meta API error HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError("No se pudo conectar con Meta WhatsApp Cloud API.") from exc

        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Meta devolvió una respuesta JSON inválida.") from exc

    def _normalize_meta_recipient(self, to_phone: str) -> str:
        normalized = str(to_phone or "").strip()
        if normalized.startswith("whatsapp:"):
            normalized = normalized.split(":", 1)[1]
        if normalized.startswith("+"):
            normalized = normalized[1:]
        return normalized

    def _is_meta_access_token_expired(self, status_code: int, detail: str) -> bool:
        if status_code != 401:
            return False
        try:
            payload = json.loads(detail or "{}")
        except json.JSONDecodeError:
            payload = {}
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        code = error.get("code")
        subcode = error.get("error_subcode")
        message = str(error.get("message") or detail or "").lower()
        return (
            code == 190
            and subcode == 463
            or "session has expired" in message
            or "error validating access token" in message
        )
