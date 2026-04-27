from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv_file(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists() or not env_path.is_file():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


_load_dotenv_file()


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class Settings:
    app_name: str = os.getenv("APP_NAME", "Expense Submission AI Agent")
    app_env: str = os.getenv("APP_ENV", "dev")
    debug: bool = _as_bool(os.getenv("DEBUG"), default=True)
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "")

    whatsapp_provider: str = os.getenv("WHATSAPP_PROVIDER", "meta").strip().lower()

    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "")
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "")
    twilio_whatsapp_from: str = os.getenv("TWILIO_WHATSAPP_FROM", "")
    twilio_validate_signature: bool = _as_bool(
        os.getenv("TWILIO_VALIDATE_SIGNATURE"), default=False
    )

    meta_access_token: str = os.getenv("META_ACCESS_TOKEN", "")
    meta_phone_number_id: str = os.getenv("META_PHONE_NUMBER_ID", "")
    meta_waba_id: str = os.getenv("META_WABA_ID", "")
    meta_verify_token: str = os.getenv("META_VERIFY_TOKEN", "")
    meta_app_secret: str = os.getenv("META_APP_SECRET", "")
    meta_validate_signature: bool = _as_bool(
        os.getenv("META_VALIDATE_SIGNATURE"), default=False
    )
    meta_graph_version: str = os.getenv("META_GRAPH_VERSION", "v22.0")

    google_application_credentials: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    google_sheets_spreadsheet_id: str = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    google_sheets_timeout_seconds: float = float(
        os.getenv("GOOGLE_SHEETS_TIMEOUT_SECONDS", "15") or "15"
    )
    google_sheets_record_cache_ttl_seconds: float = float(
        os.getenv("GOOGLE_SHEETS_RECORD_CACHE_TTL_SECONDS", "15") or "15"
    )
    google_sheets_stale_cache_ttl_seconds: float = float(
        os.getenv("GOOGLE_SHEETS_STALE_CACHE_TTL_SECONDS", "300") or "300"
    )
    google_sheets_read_cooldown_seconds: float = float(
        os.getenv("GOOGLE_SHEETS_READ_COOLDOWN_SECONDS", "60") or "60"
    )
    gcs_bucket_name: str = os.getenv("GCS_BUCKET_NAME", "")
    gcs_receipts_prefix: str = os.getenv("GCS_RECEIPTS_PREFIX", "receipts/")
    gcs_reports_prefix: str = os.getenv("GCS_REPORTS_PREFIX", "reports/")
    gcs_signed_url_ttl_seconds: int = int(
        os.getenv("GCS_SIGNED_URL_TTL_SECONDS", "900") or "900"
    )
    consolidated_report_logo_path: str = os.getenv(
        "CONSOLIDATED_REPORT_LOGO_PATH", "./assets/ripley-logo.png"
    )
    docusign_enabled: bool = _as_bool(os.getenv("DOCUSIGN_ENABLED"), default=False)
    docusign_base_url: str = os.getenv(
        "DOCUSIGN_BASE_URL", "https://demo.docusign.net/restapi"
    )
    docusign_account_id: str = os.getenv("DOCUSIGN_ACCOUNT_ID", "")
    docusign_integration_key: str = os.getenv("DOCUSIGN_INTEGRATION_KEY", "")
    docusign_secret_key: str = os.getenv("DOCUSIGN_SECRET_KEY", "")
    docusign_access_token: str = os.getenv("DOCUSIGN_ACCESS_TOKEN", "")
    docusign_refresh_token: str = os.getenv("DOCUSIGN_REFRESH_TOKEN", "")
    docusign_return_url: str = os.getenv(
        "DOCUSIGN_RETURN_URL", "https://example.com/docusign/return"
    )
    docusign_document_url_ttl_seconds: int = int(
        os.getenv("DOCUSIGN_DOCUMENT_URL_TTL_SECONDS", "1800") or "1800"
    )

    document_ai_project_id: str = os.getenv("DOCUMENT_AI_PROJECT_ID", "")
    document_ai_location: str = os.getenv("DOCUMENT_AI_LOCATION", "us")
    document_ai_processor_id: str = os.getenv("DOCUMENT_AI_PROCESSOR_ID", "")
    document_ai_timeout_seconds: int = int(
        os.getenv("DOCUMENT_AI_TIMEOUT_SECONDS", "12") or "12"
    )

    expense_category_llm_enabled: bool = _as_bool(
        os.getenv("EXPENSE_CATEGORY_LLM_ENABLED"), default=False
    )
    chat_assistant_enabled: bool = _as_bool(
        os.getenv("CHAT_ASSISTANT_ENABLED"), default=True
    )
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_timeout_seconds: int = int(os.getenv("OPENAI_TIMEOUT_SECONDS", "12") or "12")

    default_timezone: str = os.getenv("DEFAULT_TIMEZONE", "America/Santiago")
    scheduler_endpoint_token: str = os.getenv("SCHEDULER_ENDPOINT_TOKEN", "")
    scheduler_reminder_window_minutes: int = int(
        os.getenv("SCHEDULER_REMINDER_WINDOW_MINUTES", "10") or "10"
    )
    scheduler_morning_hour_local: int = int(
        os.getenv("SCHEDULER_MORNING_HOUR_LOCAL", "9") or "9"
    )
    scheduler_evening_hour_local: int = int(
        os.getenv("SCHEDULER_EVENING_HOUR_LOCAL", "20") or "20"
    )
    backoffice_auth_secret: str = os.getenv("BACKOFFICE_AUTH_SECRET", "change-me")
    backoffice_token_ttl_seconds: int = int(
        os.getenv("BACKOFFICE_TOKEN_TTL_SECONDS", "28800") or "28800"
    )
    backoffice_frontend_origin: str = os.getenv(
        "BACKOFFICE_FRONTEND_ORIGIN", "https://viaticos-backoffice.vercel.app"
    )
    backoffice_frontend_origins: str = os.getenv("BACKOFFICE_FRONTEND_ORIGINS", "")
    deploy_commit: str = os.getenv("DEPLOY_COMMIT", "")
    deploy_time: str = os.getenv("DEPLOY_TIME", "")

    @property
    def google_sheets_enabled(self) -> bool:
        return bool(self.google_sheets_spreadsheet_id)

    @property
    def gcs_storage_enabled(self) -> bool:
        return bool(self.gcs_bucket_name)


settings = Settings()
