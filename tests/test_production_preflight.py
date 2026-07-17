from __future__ import annotations

import os
from unittest.mock import patch

from scripts import production_preflight


VALID_ENV = {
    "APP_ENV": "prod",
    "DEBUG": "false",
    "PUBLIC_BASE_URL": "https://api.example.com",
    "BACKOFFICE_FRONTEND_ORIGIN": "https://backoffice.example.com",
    "WHATSAPP_PROVIDER": "meta",
    "GCS_BUCKET_NAME": "private-docs",
    "DOCUMENT_AI_PROJECT_ID": "project-1",
    "DOCUMENT_AI_LOCATION": "us",
    "DOCUMENT_AI_PROCESSOR_ID": "processor-1",
    "DOCUSIGN_ENABLED": "true",
    "DOCUSIGN_BASE_URL": "https://na4.docusign.net/restapi",
    "DOCUSIGN_ACCOUNT_ID": "account-1",
    "DOCUSIGN_RETURN_URL": "https://api.example.com/docusign/callback",
    "BACKOFFICE_AUTH_SECRET": "a" * 64,
    "BACKOFFICE_DEFAULT_ADMIN_EMAIL": "admin@example.com",
    "BACKOFFICE_DEFAULT_ADMIN_PASSWORD": "Secure!123",
    "META_ACCESS_TOKEN": "meta-token",
    "META_APP_SECRET": "meta-secret",
    "META_VERIFY_TOKEN": "verify-token",
    "OPENAI_API_KEY": "openai-key",
    "SCHEDULER_ENDPOINT_TOKEN": "scheduler-token",
    "META_VALIDATE_SIGNATURE": "true",
}


def run_preflight(env: dict[str, str]) -> int:
    clean_env = {key: value for key, value in env.items()}
    with patch.dict(os.environ, clean_env, clear=True), patch(
        "sys.argv", ["production_preflight.py", "--env-file", "/tmp/does-not-exist"]
    ):
        return production_preflight.main()


def test_preflight_passes_for_valid_meta_environment():
    assert run_preflight(VALID_ENV) == 0


def test_preflight_fails_for_debug_and_docusign_demo():
    env = {
        **VALID_ENV,
        "DEBUG": "true",
        "DOCUSIGN_BASE_URL": "https://demo.docusign.net/restapi",
    }

    assert run_preflight(env) == 1


def test_preflight_fails_for_insecure_backoffice_secret():
    env = {
        **VALID_ENV,
        "BACKOFFICE_AUTH_SECRET": "admin123",
    }

    assert run_preflight(env) == 1
