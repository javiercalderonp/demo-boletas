from __future__ import annotations

import argparse
import os
import sys


REQUIRED_NON_SECRET = {
    "APP_ENV": "prod",
    "DEBUG": "false",
    "PUBLIC_BASE_URL": None,
    "BACKOFFICE_FRONTEND_ORIGIN": None,
    "WHATSAPP_PROVIDER": None,
    "GCS_BUCKET_NAME": None,
    "DOCUMENT_AI_PROJECT_ID": None,
    "DOCUMENT_AI_LOCATION": None,
    "DOCUMENT_AI_PROCESSOR_ID": None,
    "DOCUSIGN_ENABLED": None,
    "DOCUSIGN_BASE_URL": None,
    "DOCUSIGN_ACCOUNT_ID": None,
    "DOCUSIGN_RETURN_URL": None,
}

REQUIRED_SECRET_LIKE = (
    "BACKOFFICE_AUTH_SECRET",
    "BACKOFFICE_DEFAULT_ADMIN_EMAIL",
    "BACKOFFICE_DEFAULT_ADMIN_PASSWORD",
    "META_ACCESS_TOKEN",
    "META_APP_SECRET",
    "META_VERIFY_TOKEN",
    "OPENAI_API_KEY",
    "SCHEDULER_ENDPOINT_TOKEN",
)

INSECURE_VALUES = {
    "",
    "REPLACE_ME",
    "changeme",
    "change-me",
    "admin123",
    "secret",
    "password",
    "example",
}


def load_env_file(path: str) -> None:
    if not path or not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'\"")
            os.environ.setdefault(key, value)


def value_is_insecure(value: str) -> bool:
    return value.strip() in INSECURE_VALUES or value.strip().lower() in INSECURE_VALUES


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate production environment variables.")
    parser.add_argument("--env-file", default=".env", help="Optional dotenv file to load first.")
    args = parser.parse_args()
    load_env_file(args.env_file)

    errors: list[str] = []
    for key, expected in REQUIRED_NON_SECRET.items():
        value = os.getenv(key, "").strip()
        if not value:
            errors.append(f"{key} is required")
            continue
        if expected is not None and value.lower() != expected:
            errors.append(f"{key} must be {expected!r}, got {value!r}")

    for key in REQUIRED_SECRET_LIKE:
        value = os.getenv(key, "").strip()
        if value_is_insecure(value):
            errors.append(f"{key} is missing or insecure")

    auth_secret = os.getenv("BACKOFFICE_AUTH_SECRET", "")
    if auth_secret and len(auth_secret) < 32:
        errors.append("BACKOFFICE_AUTH_SECRET must be at least 32 characters")

    provider = os.getenv("WHATSAPP_PROVIDER", "").strip().lower()
    if provider == "meta":
        if os.getenv("META_VALIDATE_SIGNATURE", "true").strip().lower() != "true":
            errors.append("META_VALIDATE_SIGNATURE must be true for Meta production")
    if provider == "twilio":
        if os.getenv("TWILIO_VALIDATE_SIGNATURE", "false").strip().lower() != "true":
            errors.append("TWILIO_VALIDATE_SIGNATURE must be true for Twilio production")

    docusign_base_url = os.getenv("DOCUSIGN_BASE_URL", "")
    if "demo.docusign.net" in docusign_base_url:
        errors.append("DOCUSIGN_BASE_URL still points to demo.docusign.net")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("Production preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
