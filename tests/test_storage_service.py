import unittest
import sys
import types
from unittest.mock import Mock, patch

from app.config import Settings
from services.storage_service import GCSStorageService


class GCSStorageServiceSignedUrlTests(unittest.TestCase):
    def _build_service(self):
        service = GCSStorageService(settings=Settings(gcs_bucket_name="", google_application_credentials=""))
        service._bucket = Mock()
        service._client = Mock()
        return service

    def test_generate_signed_url_falls_back_to_iam_signing(self):
        service = self._build_service()
        blob = Mock()
        blob.generate_signed_url.side_effect = [
            AttributeError("you need a private key to sign credentials"),
            "https://example.com/signed",
        ]
        service._bucket.blob.return_value = blob

        credentials = Mock()
        credentials.service_account_email = "svc@example.iam.gserviceaccount.com"
        credentials.token = "token-123"
        service._client._credentials = credentials

        signed_url = service.generate_signed_url(object_key="reports/demo.pdf")

        self.assertEqual(signed_url, "https://example.com/signed")
        self.assertEqual(blob.generate_signed_url.call_count, 2)
        _, second_call_kwargs = blob.generate_signed_url.call_args_list[1]
        self.assertEqual(
            second_call_kwargs["service_account_email"],
            "svc@example.iam.gserviceaccount.com",
        )
        self.assertEqual(second_call_kwargs["access_token"], "token-123")

    def test_generate_signed_url_refreshes_token_for_iam_signing(self):
        service = self._build_service()
        blob = Mock()
        blob.generate_signed_url.side_effect = [
            AttributeError("you need a private key to sign credentials"),
            "https://example.com/signed",
        ]
        service._bucket.blob.return_value = blob

        credentials = Mock()
        credentials.service_account_email = "svc@example.iam.gserviceaccount.com"
        credentials.token = ""

        def refresh(_request):
            credentials.token = "fresh-token"

        credentials.refresh.side_effect = refresh
        service._client._credentials = credentials

        google_module = types.ModuleType("google")
        auth_module = types.ModuleType("google.auth")
        transport_module = types.ModuleType("google.auth.transport")
        requests_module = types.ModuleType("google.auth.transport.requests")
        request_cls = Mock()
        requests_module.Request = request_cls

        with patch.dict(
            sys.modules,
            {
                "google": google_module,
                "google.auth": auth_module,
                "google.auth.transport": transport_module,
                "google.auth.transport.requests": requests_module,
            },
        ):
            signed_url = service.generate_signed_url(object_key="reports/demo.pdf")

        self.assertEqual(signed_url, "https://example.com/signed")
        credentials.refresh.assert_called_once_with(request_cls.return_value)
        _, second_call_kwargs = blob.generate_signed_url.call_args_list[1]
        self.assertEqual(second_call_kwargs["access_token"], "fresh-token")

    def test_generate_signed_url_applies_iam_scopes_when_required(self):
        service = self._build_service()
        blob = Mock()
        blob.generate_signed_url.side_effect = [
            AttributeError("you need a private key to sign credentials"),
            "https://example.com/signed",
        ]
        service._bucket.blob.return_value = blob

        scoped_credentials = Mock()
        scoped_credentials.service_account_email = "svc@example.iam.gserviceaccount.com"
        scoped_credentials.token = "scoped-token"

        credentials = Mock()
        credentials.requires_scopes = True
        credentials.with_scopes.return_value = scoped_credentials
        service._client._credentials = credentials

        google_module = types.ModuleType("google")
        auth_module = types.ModuleType("google.auth")
        credentials_module = types.ModuleType("google.auth.credentials")
        transport_module = types.ModuleType("google.auth.transport")
        requests_module = types.ModuleType("google.auth.transport.requests")
        request_cls = Mock()
        requests_module.Request = request_cls
        credentials_module.with_scopes_if_required = Mock(return_value=scoped_credentials)

        with patch.dict(
            sys.modules,
            {
                "google": google_module,
                "google.auth": auth_module,
                "google.auth.credentials": credentials_module,
                "google.auth.transport": transport_module,
                "google.auth.transport.requests": requests_module,
            },
        ):
            signed_url = service.generate_signed_url(object_key="reports/demo.pdf")

        self.assertEqual(signed_url, "https://example.com/signed")
        credentials_module.with_scopes_if_required.assert_called_once()
        _, second_call_kwargs = blob.generate_signed_url.call_args_list[1]
        self.assertEqual(
            second_call_kwargs["service_account_email"],
            "svc@example.iam.gserviceaccount.com",
        )
        self.assertEqual(second_call_kwargs["access_token"], "scoped-token")

    def test_generate_signed_url_forces_refresh_even_when_token_exists(self):
        service = self._build_service()
        blob = Mock()
        blob.generate_signed_url.side_effect = [
            AttributeError("you need a private key to sign credentials"),
            "https://example.com/signed",
        ]
        service._bucket.blob.return_value = blob

        credentials = Mock()
        credentials.service_account_email = "svc@example.iam.gserviceaccount.com"
        credentials.token = "old-token"

        def refresh(_request):
            credentials.token = "fresh-iam-token"

        credentials.refresh.side_effect = refresh
        service._client._credentials = credentials

        google_module = types.ModuleType("google")
        auth_module = types.ModuleType("google.auth")
        credentials_module = types.ModuleType("google.auth.credentials")
        transport_module = types.ModuleType("google.auth.transport")
        requests_module = types.ModuleType("google.auth.transport.requests")
        request_cls = Mock()
        requests_module.Request = request_cls
        credentials_module.with_scopes_if_required = Mock(return_value=credentials)

        with patch.dict(
            sys.modules,
            {
                "google": google_module,
                "google.auth": auth_module,
                "google.auth.credentials": credentials_module,
                "google.auth.transport": transport_module,
                "google.auth.transport.requests": requests_module,
            },
        ):
            signed_url = service.generate_signed_url(object_key="reports/demo.pdf")

        self.assertEqual(signed_url, "https://example.com/signed")
        credentials.refresh.assert_called_once_with(request_cls.return_value)
        _, second_call_kwargs = blob.generate_signed_url.call_args_list[1]
        self.assertEqual(second_call_kwargs["access_token"], "fresh-iam-token")

    def test_generate_signed_url_uses_with_scopes_when_available(self):
        service = self._build_service()
        blob = Mock()
        blob.generate_signed_url.side_effect = [
            AttributeError("you need a private key to sign credentials"),
            "https://example.com/signed",
        ]
        service._bucket.blob.return_value = blob

        class ScopedCredentials:
            service_account_email = "svc@example.iam.gserviceaccount.com"
            token = "token-from-scoped-creds"

            def refresh(self, _request):
                return None

        class BaseCredentials:
            service_account_email = "svc@example.iam.gserviceaccount.com"
            token = ""

            def __init__(self):
                self.with_scopes_called = False

            def with_scopes(self, _scopes):
                self.with_scopes_called = True
                return ScopedCredentials()

        credentials = BaseCredentials()
        service._client._credentials = credentials

        google_module = types.ModuleType("google")
        auth_module = types.ModuleType("google.auth")
        credentials_module = types.ModuleType("google.auth.credentials")
        transport_module = types.ModuleType("google.auth.transport")
        requests_module = types.ModuleType("google.auth.transport.requests")
        request_cls = Mock()
        requests_module.Request = request_cls
        credentials_module.with_scopes_if_required = Mock(return_value=credentials)

        with patch.dict(
            sys.modules,
            {
                "google": google_module,
                "google.auth": auth_module,
                "google.auth.credentials": credentials_module,
                "google.auth.transport": transport_module,
                "google.auth.transport.requests": requests_module,
            },
        ):
            signed_url = service.generate_signed_url(object_key="reports/demo.pdf")

        self.assertEqual(signed_url, "https://example.com/signed")
        self.assertTrue(credentials.with_scopes_called)
        _, second_call_kwargs = blob.generate_signed_url.call_args_list[1]
        self.assertEqual(second_call_kwargs["access_token"], "token-from-scoped-creds")


if __name__ == "__main__":
    unittest.main()
