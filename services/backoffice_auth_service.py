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

from app.config import Settings
from services.sheets_service import SheetsService
from utils.helpers import make_id, utc_now_iso


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(f"{data}{padding}".encode("ascii"))


@dataclass
class BackofficeAuthService:
    settings: Settings
    sheets_service: SheetsService

    def ensure_default_admin(self) -> None:
        email = os.getenv("BACKOFFICE_DEFAULT_ADMIN_EMAIL", "").strip().lower()
        password = os.getenv("BACKOFFICE_DEFAULT_ADMIN_PASSWORD", "").strip()
        name = os.getenv("BACKOFFICE_DEFAULT_ADMIN_NAME", "Admin").strip() or "Admin"

        if not email and not self.sheets_service.list_users():
            email = "admin@example.com"
            password = "admin123"
            name = "Demo Admin"

        if not email or not password:
            return
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
                "role": "admin",
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

    def authenticate(self, email: str, password: str) -> dict[str, Any] | None:
        user = self.sheets_service.get_user_by_email(email)
        if not user or not user.get("active"):
            return None
        if not self.verify_password(password, str(user.get("password_hash", "") or "")):
            return None
        return user

    def create_access_token(self, user: dict[str, Any]) -> str:
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self.settings.backoffice_token_ttl_seconds
        )
        payload = {
            "sub": str(user.get("id", "")),
            "email": str(user.get("email", "")),
            "name": str(user.get("name", "")),
            "role": str(user.get("role", "operator") or "operator"),
            "exp": int(expires_at.timestamp()),
        }
        body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = hmac.new(
            self.settings.backoffice_auth_secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return f"{body}.{_b64url_encode(signature)}"

    def verify_access_token(self, token: str) -> dict[str, Any] | None:
        try:
            body, provided_signature = str(token or "").split(".", 1)
        except ValueError:
            return None
        expected_signature = _b64url_encode(
            hmac.new(
                self.settings.backoffice_auth_secret.encode("utf-8"),
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
        user = self.sheets_service.get_user_by_email(str(payload.get("email", "")))
        if not user or not user.get("active"):
            return None
        return user
