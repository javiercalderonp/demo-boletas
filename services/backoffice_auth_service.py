from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from app.config import Settings
from app.schemas.backoffice import validate_strong_password
from services.backoffice_permissions import GLOBAL_SCOPE, SUPER_ADMIN_ROLE, serialize_access
from services.sheets_service import SheetsService
from utils.helpers import make_id, utc_now_iso


_INSECURE_AUTH_SECRETS = {"change-me", "changeme", "secret", "password", "admin", "test"}


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}".encode("ascii"))


@dataclass
class BackofficeAuthService:
    settings: Settings
    sheets_service: SheetsService

    def _auth_secret(self) -> str:
        secret = str(self.settings.backoffice_auth_secret or "").strip()
        if not secret:
            raise RuntimeError("BACKOFFICE_AUTH_SECRET is required")
        if secret.lower() in _INSECURE_AUTH_SECRETS or len(secret) < 32:
            raise RuntimeError("BACKOFFICE_AUTH_SECRET must be a strong secret")
        return secret

    def ensure_default_admin(self) -> None:
        email = os.getenv("BACKOFFICE_DEFAULT_ADMIN_EMAIL", "").strip().lower()
        password = os.getenv("BACKOFFICE_DEFAULT_ADMIN_PASSWORD", "").strip()
        name = os.getenv("BACKOFFICE_DEFAULT_ADMIN_NAME", "Admin").strip() or "Admin"

        if not email and not password:
            return
        if not email or not password:
            raise RuntimeError(
                "BACKOFFICE_DEFAULT_ADMIN_EMAIL and BACKOFFICE_DEFAULT_ADMIN_PASSWORD "
                "must be configured together"
            )
        validate_strong_password(password)
        existing = self.sheets_service.get_user_by_email(email)
        if existing:
            return
        now = utc_now_iso()
        self.sheets_service.upsert_user(
            make_id("usr"),
            {
                "name": name,
                "email": email,
                "password_hash": self.hash_password(password),
                "role": SUPER_ADMIN_ROLE,
                "scope_type": GLOBAL_SCOPE,
                "company_ids": "",
                "company_id": "",
                "active": True,
                "created_at": now,
                "updated_at": now,
            },
        )

    def hash_password(self, password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120_000,
        )
        return f"pbkdf2_sha256${salt}${digest.hex()}"

    def verify_password(self, password: str, stored_hash: str) -> bool:
        try:
            scheme, salt, digest = str(stored_hash or "").split("$", 2)
        except ValueError:
            return False
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            120_000,
        ).hex()
        return hmac.compare_digest(candidate, digest)

    def user_has_password(self, user: dict[str, Any] | None) -> bool:
        return bool(str((user or {}).get("password_hash", "") or "").strip())

    def authenticate(self, email: str, password: str) -> dict[str, Any] | None:
        user = self.sheets_service.get_user_by_email(email)
        if not user or not user.get("active"):
            return None
        if not self.user_has_password(user):
            return None
        if not self.verify_password(password, str(user.get("password_hash", "") or "")):
            return None
        return user

    def can_setup_password(self, email: str) -> dict[str, Any] | None:
        user = self.sheets_service.get_user_by_email(email)
        if not user or not user.get("active") or self.user_has_password(user):
            return None
        return user

    def setup_password(self, email: str, password: str, *, name: str = "") -> dict[str, Any] | None:
        validate_strong_password(password)
        user = self.can_setup_password(email)
        if not user:
            return None
        now = utc_now_iso()
        clean_name = str(name or "").strip()
        payload: dict[str, Any] = {
            "password_hash": self.hash_password(password),
            "updated_at": now,
        }
        if clean_name:
            payload["name"] = clean_name
        elif not str(user.get("name", "") or "").strip():
            payload["name"] = str(user.get("email", "") or "").split("@", 1)[0]
        return self.sheets_service.upsert_user(str(user.get("id", "")), payload)

    def create_access_token(self, user: dict[str, Any]) -> str:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(seconds=self.settings.backoffice_token_ttl_seconds)
        payload = {
            "typ": "access",
            "sub": str(user.get("id", "")),
            "email": str(user.get("email", "")),
            "name": str(user.get("name", "")),
            "role": str(user.get("role", "operator") or "operator"),
            **serialize_access(user),
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        return jwt.encode(payload, self._auth_secret(), algorithm="HS256")

    def verify_access_token(self, token: str) -> dict[str, Any] | None:
        payload = self._decode_access_token_payload(token)
        if not payload:
            return None
        user = self.sheets_service.get_user_by_email(str(payload.get("email", "")))
        if not user or not user.get("active"):
            return None
        return user

    def _decode_access_token_payload(self, token: str) -> dict[str, Any] | None:
        try:
            payload = jwt.decode(str(token or ""), self._auth_secret(), algorithms=["HS256"])
            if payload.get("typ") and payload.get("typ") != "access":
                return None
            return payload
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return self._decode_legacy_access_token_payload(token)

    def _decode_legacy_access_token_payload(self, token: str) -> dict[str, Any] | None:
        try:
            body, provided_signature = str(token or "").split(".", 1)
        except ValueError:
            return None
        expected_signature = _b64url_encode(
            hmac.new(
                self._auth_secret().encode("utf-8"),
                body.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(expected_signature, provided_signature):
            return None
        try:
            payload = json.loads(_b64url_decode(body).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return None
        if int(payload.get("exp", 0) or 0) < int(datetime.now(timezone.utc).timestamp()):
            return None
        return payload
