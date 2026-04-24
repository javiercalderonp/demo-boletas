import unittest
from unittest.mock import Mock

from app.config import Settings
from services.docusign_service import DocusignError, DocusignHttpError, DocusignService


class DocusignServiceAutoRefreshTests(unittest.TestCase):
    def _build_service(self, **overrides):
        defaults = {
            "docusign_enabled": True,
            "docusign_base_url": "https://demo.docusign.net/restapi",
            "docusign_account_id": "acc-1",
            "docusign_access_token": "expired-token",
            "docusign_refresh_token": "refresh-token",
            "docusign_integration_key": "integration-key",
            "docusign_secret_key": "secret-key",
        }
        defaults.update(overrides)
        settings = Settings(
            **defaults,
        )
        return DocusignService(settings=settings)

    def test_create_envelope_refreshes_token_once_on_401(self):
        service = self._build_service()
        service._read_json_response = Mock(
            side_effect=[
                DocusignHttpError(401, "DocuSign access token invalido o expirado"),
                {"envelopeId": "env-123"},
            ]
        )
        service.refresh_access_token = Mock(
            return_value={"access_token": "new-token", "refresh_token": "new-refresh"}
        )

        response = service.create_envelope_from_remote_pdf(
            signer_name="Test User",
            signer_email="test@example.com",
            document_name="Doc",
            document_url="https://example.com/doc.pdf",
        )

        self.assertEqual(response.get("envelopeId"), "env-123")
        service.refresh_access_token.assert_called_once()
        self.assertEqual(service._read_json_response.call_count, 2)

    def test_create_envelope_raises_401_without_refresh_token(self):
        service = self._build_service(docusign_refresh_token="")
        service._read_json_response = Mock(
            side_effect=DocusignHttpError(401, "DocuSign access token invalido o expirado")
        )
        service.refresh_access_token = Mock()

        with self.assertRaises(DocusignError):
            service.create_envelope_from_remote_pdf(
                signer_name="Test User",
                signer_email="test@example.com",
                document_name="Doc",
                document_url="https://example.com/doc.pdf",
            )

        service.refresh_access_token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
