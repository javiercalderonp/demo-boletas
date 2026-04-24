from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.config import Settings

logger = logging.getLogger(__name__)
_IAM_SIGNING_SCOPES = (
    "https://www.googleapis.com/auth/iam",
    "https://www.googleapis.com/auth/cloud-platform",
)


class StorageUploadError(RuntimeError):
    pass


class _PreserveAuthorizationRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None

        auth_header = req.headers.get("Authorization") or req.unredirected_hdrs.get("Authorization")
        if auth_header and str(newurl).startswith("https://"):
            redirected.add_unredirected_header("Authorization", auth_header)
        return redirected


@dataclass
class GCSStorageService:
    settings: Settings

    def __post_init__(self) -> None:
        self._bucket = None
        self._client = None
        if self.enabled:
            self._connect()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.gcs_storage_enabled)

    def _connect(self) -> None:
        try:
            from google.cloud import storage
            import google.auth
        except ImportError as exc:  # pragma: no cover - dependency setup
            raise RuntimeError(
                "Faltan dependencias para GCS. Instala google-cloud-storage."
            ) from exc

        credentials_path = (self.settings.google_application_credentials or "").strip()
        if credentials_path:
            client = storage.Client.from_service_account_json(credentials_path)
        else:
            # Force ADC tokens with scopes required for IAM SignBlob fallback.
            credentials, project_id = google.auth.default(scopes=list(_IAM_SIGNING_SCOPES))
            client = storage.Client(
                project=project_id or None,
                credentials=credentials,
            )
        self._client = client
        self._bucket = client.bucket(self.settings.gcs_bucket_name)

    def upload_receipt_from_url(
        self,
        *,
        phone: str,
        media_url: str,
        media_content_type: str | None = None,
    ) -> dict[str, str]:
        if not self._bucket:
            raise StorageUploadError("GCS no está habilitado")
        if not media_url:
            raise StorageUploadError("MediaUrl0 vacío")

        content, mime_type = self._download_media(media_url, media_content_type)
        object_key = self._build_receipt_object_key(phone=phone, mime_type=mime_type)

        blob = self._bucket.blob(object_key)
        blob.upload_from_string(content, content_type=mime_type)

        return {
            "receipt_storage_provider": "gcs",
            "receipt_object_key": object_key,
        }

    def generate_signed_url(self, *, object_key: str, ttl_seconds: int | None = None) -> str:
        if not self._bucket:
            raise StorageUploadError("GCS no está habilitado")
        if not object_key:
            raise StorageUploadError("object_key vacío")

        ttl = ttl_seconds or self.settings.gcs_signed_url_ttl_seconds
        ttl = max(ttl, 1)
        blob = self._bucket.blob(object_key)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        try:
            return str(
                blob.generate_signed_url(
                    version="v4",
                    expiration=expires_at,
                    method="GET",
                )
            )
        except AttributeError as exc:
            if "you need a private key to sign credentials" not in str(exc).lower():
                raise

            signing_kwargs = self._build_iam_signing_kwargs()
            if not signing_kwargs:
                raise

            logger.info("Falling back to IAM-based GCS signed URL generation")
            return str(
                blob.generate_signed_url(
                    version="v4",
                    expiration=expires_at,
                    method="GET",
                    **signing_kwargs,
                )
            )

    def upload_report_pdf(
        self,
        *,
        phone: str,
        trip_id: str,
        content: bytes,
    ) -> dict[str, str]:
        if not self._bucket:
            raise StorageUploadError("GCS no está habilitado")
        if not content:
            raise StorageUploadError("Contenido de reporte vacío")

        object_key = self._build_report_object_key(phone=phone, trip_id=trip_id)
        blob = self._bucket.blob(object_key)
        blob.upload_from_string(content, content_type="application/pdf")
        return {
            "storage_provider": "gcs",
            "object_key": object_key,
        }

    def _download_media(self, media_url: str, media_content_type: str | None) -> tuple[bytes, str]:
        headers = {"User-Agent": "TravelExpenseAgent/1.0"}
        auth_header = self._media_authorization_header()
        if auth_header:
            headers["Authorization"] = auth_header

        request = Request(media_url, headers=headers)
        try:
            opener = build_opener(_PreserveAuthorizationRedirectHandler)
            with opener.open(request, timeout=20) as response:
                content = response.read()
                response_mime = response.headers.get_content_type()
        except HTTPError as exc:  # pragma: no cover - depends on external network
            raise StorageUploadError(f"Error HTTP descargando media WhatsApp: {exc.code}") from exc
        except URLError as exc:  # pragma: no cover - depends on external network
            raise StorageUploadError("No se pudo descargar la imagen desde WhatsApp") from exc

        if not content:
            raise StorageUploadError("La imagen descargada está vacía")

        mime_type = self._resolve_mime_type(media_content_type, response_mime)
        return content, mime_type

    def _media_authorization_header(self) -> str | None:
        provider = (self.settings.whatsapp_provider or "meta").strip().lower()
        if provider == "meta":
            token = (self.settings.meta_access_token or "").strip()
            return f"Bearer {token}" if token else None

        import base64

        sid = (self.settings.twilio_account_sid or "").strip()
        token = (self.settings.twilio_auth_token or "").strip()
        if not sid or not token:
            return None
        raw = f"{sid}:{token}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _resolve_mime_type(
        self,
        media_content_type: str | None,
        response_mime: str | None,
    ) -> str:
        for candidate in (media_content_type, response_mime):
            if candidate and "/" in candidate:
                return candidate.split(";", 1)[0].strip().lower()
        return "image/jpeg"

    def _build_receipt_object_key(self, *, phone: str, mime_type: str) -> str:
        extension = self._guess_extension(mime_type)
        prefix = (self.settings.gcs_receipts_prefix or "receipts/").strip("/")
        safe_phone = "".join(ch for ch in (phone or "") if ch.isdigit()) or "unknown"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{prefix}/{safe_phone}/receipt_{timestamp}{extension}"

    def _guess_extension(self, mime_type: str) -> str:
        if mime_type == "image/png":
            return ".png"
        if mime_type == "image/webp":
            return ".webp"
        if mime_type in {"application/pdf", "image/pdf"}:
            return ".pdf"
        return ".jpg"

    def _build_report_object_key(self, *, phone: str, trip_id: str) -> str:
        prefix = (self.settings.gcs_reports_prefix or "reports/").strip("/")
        safe_phone = "".join(ch for ch in (phone or "") if ch.isdigit()) or "unknown"
        safe_trip_id = "".join(
            ch for ch in (trip_id or "") if ch.isalnum() or ch in {"-", "_"}
        ) or "no-trip"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        return f"{prefix}/{safe_phone}/{safe_trip_id}/consolidated_{timestamp}.pdf"

    def _build_iam_signing_kwargs(self) -> dict[str, str] | None:
        credentials = self._credentials_with_iam_scopes(getattr(self._client, "_credentials", None))
        if credentials is None:
            return None

        service_account_email = str(
            getattr(credentials, "service_account_email", "")
            or getattr(self._client, "_service_account_email", "")
            or ""
        ).strip()
        if not service_account_email:
            return None

        # Force refresh to guarantee the access token includes IAM signing scopes.
        try:
            from google.auth.transport.requests import Request
        except ImportError:
            return None
        credentials.refresh(Request())
        token = str(getattr(credentials, "token", "") or "").strip()

        if not token:
            return None

        return {
            "service_account_email": service_account_email,
            "access_token": token,
        }

    def _credentials_with_iam_scopes(self, credentials):
        if credentials is None:
            return None

        try:
            from google.auth.credentials import with_scopes_if_required

            scoped = with_scopes_if_required(credentials, list(_IAM_SIGNING_SCOPES))
            if scoped is not None and scoped is not credentials:
                return scoped
        except Exception:
            pass

        has_with_scopes = callable(getattr(type(credentials), "with_scopes", None)) or (
            "with_scopes" in getattr(credentials, "__dict__", {})
            and callable(getattr(credentials, "with_scopes", None))
        )
        if has_with_scopes:
            try:
                return credentials.with_scopes(list(_IAM_SIGNING_SCOPES))
            except Exception:
                logger.warning("Could not apply IAM scopes to ADC credentials", exc_info=True)
                return credentials
        return credentials
