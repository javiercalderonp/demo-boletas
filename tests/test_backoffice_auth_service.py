import unittest

from app.config import Settings
from services.backoffice_auth_service import BackofficeAuthService
from services.sheets_service import SheetsService


class BackofficeAuthServiceTests(unittest.TestCase):
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

        self.assertIsNone(service.authenticate("invited@example.com", "supersecret"))

        user = service.setup_password("INVITED@example.com", "supersecret", name="")

        self.assertIsNotNone(user)
        self.assertTrue(user["password_hash"].startswith("pbkdf2_sha256$"))
        self.assertIsNotNone(service.authenticate("invited@example.com", "supersecret"))
        self.assertIsNone(service.setup_password("invited@example.com", "anothersecret"))


if __name__ == "__main__":
    unittest.main()
