import unittest
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt

from app.config import Settings
from services.backoffice_auth_service import BackofficeAuthService, _b64url_encode
from services.sheets_service import SheetsService


class BackofficeAuthServiceTests(unittest.TestCase):
    def _service_with_user(self, *, ttl=28800):
        sheets = SheetsService(settings=Settings(google_sheets_spreadsheet_id=""))
        sheets.upsert_user(
            "usr_1",
            {
                "name": "Admin",
                "email": "admin@example.com",
                "password_hash": "hash",
                "role": "company_admin",
                "scope_type": "company",
                "company_ids": "acme",
                "active": True,
            },
        )
        service = BackofficeAuthService(
            settings=Settings(backoffice_auth_secret="x" * 32, backoffice_token_ttl_seconds=ttl),
            sheets_service=sheets,
        )
        return service, sheets.get_user_by_email("admin@example.com")

    def test_default_admin_is_not_created_without_explicit_credentials(self):
        sheets = SheetsService(settings=Settings(google_sheets_spreadsheet_id=""))
        service = BackofficeAuthService(
            settings=Settings(backoffice_auth_secret="x" * 32),
            sheets_service=sheets,
        )

        with patch.dict(
            "os.environ",
            {
                "BACKOFFICE_DEFAULT_ADMIN_EMAIL": "",
                "BACKOFFICE_DEFAULT_ADMIN_PASSWORD": "",
                "BACKOFFICE_DEFAULT_ADMIN_NAME": "",
            },
            clear=False,
        ):
            service.ensure_default_admin()

        self.assertIsNone(sheets.get_user_by_email("admin@example.com"))

    def test_default_admin_requires_complete_explicit_credentials(self):
        sheets = SheetsService(settings=Settings(google_sheets_spreadsheet_id=""))
        service = BackofficeAuthService(
            settings=Settings(backoffice_auth_secret="x" * 32),
            sheets_service=sheets,
        )

        with patch.dict(
            "os.environ",
            {
                "BACKOFFICE_DEFAULT_ADMIN_EMAIL": "admin@example.com",
                "BACKOFFICE_DEFAULT_ADMIN_PASSWORD": "",
            },
            clear=False,
        ):
            with self.assertRaises(RuntimeError):
                service.ensure_default_admin()

    def test_access_token_requires_strong_secret(self):
        sheets = SheetsService(settings=Settings(google_sheets_spreadsheet_id=""))
        service = BackofficeAuthService(settings=Settings(), sheets_service=sheets)

        with self.assertRaises(RuntimeError):
            service.create_access_token({"id": "usr_1", "email": "admin@example.com"})

        weak_service = BackofficeAuthService(
            settings=Settings(backoffice_auth_secret="change-me"),
            sheets_service=sheets,
        )
        with self.assertRaises(RuntimeError):
            weak_service.create_access_token({"id": "usr_1", "email": "admin@example.com"})

    def test_access_token_is_standard_jwt_and_verifies_user(self):
        service, user = self._service_with_user()

        token = service.create_access_token(user)

        self.assertEqual(len(token.split(".")), 3)
        payload = jwt.decode(token, "x" * 32, algorithms=["HS256"])
        self.assertEqual(payload["typ"], "access")
        self.assertEqual(payload["email"], "admin@example.com")
        self.assertEqual(service.verify_access_token(token)["email"], "admin@example.com")

    def test_expired_access_token_is_rejected(self):
        service, user = self._service_with_user(ttl=-1)

        token = service.create_access_token(user)

        self.assertIsNone(service.verify_access_token(token))

    def test_legacy_access_token_still_verifies_during_migration(self):
        service, _user = self._service_with_user()
        payload = {
            "sub": "usr_1",
            "email": "admin@example.com",
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        }
        body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = _b64url_encode(
            hmac.new(("x" * 32).encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
        )
        legacy_token = f"{body}.{signature}"

        self.assertEqual(service.verify_access_token(legacy_token)["email"], "admin@example.com")

    def test_invited_user_sets_password_once_and_can_login(self):
        sheets = SheetsService(settings=Settings(google_sheets_spreadsheet_id=""))
        service = BackofficeAuthService(settings=Settings(), sheets_service=sheets)
        sheets.upsert_user(
            "usr_invited",
            {
                "name": "Invited User",
                "email": "invited@example.com",
                "password_hash": "",
                "role": "company_admin",
                "scope_type": "company",
                "company_ids": "acme",
                "active": True,
            },
        )

        self.assertIsNone(service.authenticate("invited@example.com", "Strongpass1!"))

        user = service.setup_password("INVITED@example.com", "Strongpass1!", name="")

        self.assertIsNotNone(user)
        self.assertTrue(user["password_hash"].startswith("pbkdf2_sha256$"))
        self.assertIsNotNone(service.authenticate("invited@example.com", "Strongpass1!"))
        self.assertIsNone(service.setup_password("invited@example.com", "Another1!"))

    def test_setup_password_rejects_weak_password(self):
        sheets = SheetsService(settings=Settings(google_sheets_spreadsheet_id=""))
        service = BackofficeAuthService(settings=Settings(), sheets_service=sheets)
        sheets.upsert_user(
            "usr_invited",
            {
                "name": "Invited User",
                "email": "invited@example.com",
                "password_hash": "",
                "role": "company_admin",
                "scope_type": "company",
                "company_ids": "acme",
                "active": True,
            },
        )

        with self.assertRaises(ValueError):
            service.setup_password("invited@example.com", "weakpass", name="")


if __name__ == "__main__":
    unittest.main()
