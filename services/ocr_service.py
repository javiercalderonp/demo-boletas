from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


_ENTITY_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "merchant": (
        "supplier_name",
        "merchant_name",
        "vendor_name",
        "seller_name",
        "company_name",
        "issuer_name",
        "provider_name",
    ),
    "date": (
        "receipt_date",
        "invoice_date",
        "transaction_date",
        "payment_date",
        "date",
    ),
    "total": (
        "total_amount",
        "amount_due",
        "grand_total",
        "total",
        "net_amount",
    ),
    "currency": (
        "currency",
        "currency_code",
    ),
    "country": (
        "country",
        "merchant_country",
        "supplier_address.country",
        "vendor_address.country",
    ),
    "invoice_number": (
        "invoice_id",
        "invoice_number",
        "receipt_number",
        "document_number",
        "folio",
    ),
    "tax_amount": (
        "tax_amount",
        "total_tax_amount",
        "vat_amount",
        "iva",
    ),
    "gross_amount": (
        "gross_amount",
        "subtotal",
        "net_amount",
        "total_honorarios",
        "monto_bruto",
    ),
    "withholding_amount": (
        "withholding_amount",
        "retention_amount",
        "retencion",
        "retención",
        "tax_withheld",
    ),
    "net_amount": (
        "net_payable",
        "amount_paid",
        "total_boleta",
        "monto_liquido",
        "monto_líquido",
    ),
    "issuer_tax_id": (
        "supplier_tax_id",
        "vendor_tax_id",
        "seller_tax_id",
        "supplier_registration",
    ),
    "receiver_tax_id": (
        "receiver_tax_id",
        "customer_tax_id",
        "buyer_tax_id",
    ),
    "receiver_name": (
        "receiver_name",
        "customer_name",
        "buyer_name",
    ),
    "service_description": (
        "service_description",
        "description",
        "concept",
        "detalle",
    ),
    "payment_method": (
        "payment_method",
        "payment_type",
    ),
}

_GENERIC_MERCHANT_TERMS = {
    "comprobante de venta",
    "boleta",
    "boleta de honorarios",
    "boleta de honorarios electronica",
    "boleta de honorarios electrónica",
    "boleta electronica",
    "boleta electrónica",
    "factura",
    "factura electronica",
    "factura electrónica",
    "ticket",
    "recibo",
    "tarjeta de debito",
    "tarjeta de débito",
    "tarjeta de credito",
    "tarjeta de crédito",
    "visa",
    "visa debito",
    "visa débito",
    "mastercard",
    "copia cliente",
}

_DOCUMENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "boleta_honorarios": (
        "boleta de honorarios",
        "boleta honorarios",
        "boleta de honorarios electronica",
        "boleta de honorarios electrónica",
        "honorarios",
        "retencion",
        "retención",
    ),
    "factura": (
        "factura",
        "invoice",
    ),
    "boleta": (
        "boleta",
        "boleta electronica",
        "boleta electrónica",
    ),
    "ticket": (
        "ticket",
    ),
    "comprobante": (
        "comprobante",
        "comprobante de venta",
        "voucher",
        "recibo",
        "receipt",
    ),
}


class OCRProcessingError(RuntimeError):
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
class OCRService:
    settings: Any | None = None

    def extract_receipt_data(self, media_url: str, media_content_type: str | None = None) -> dict[str, Any]:
        if not self._document_ai_enabled:
            return self._placeholder_extract(media_url)

        content, mime_type = self._download_media(media_url, media_content_type)
        document = self._process_document_ai(content, mime_type)
        extracted = self._map_document_to_expense_fields(document)
        extracted["category"] = None
        return extracted

    @property
    def _document_ai_enabled(self) -> bool:
        if not self.settings:
            return False
        return bool(
            getattr(self.settings, "document_ai_project_id", "")
            and getattr(self.settings, "document_ai_location", "")
            and getattr(self.settings, "document_ai_processor_id", "")
        )

    def _placeholder_extract(self, media_url: str) -> dict[str, Any]:
        url = (media_url or "").lower()
        today = date.today().isoformat()
        document_type = "comprobante"

        currency = "CLP"
        country = None
        merchant = "Comercio OCR"
        total = 12500.0

        if "usd" in url:
            currency = "USD"
            total = 12.5
        if "pen" in url or "lima" in url or "peru" in url:
            currency = "PEN"
            country = "Peru"
            total = 35.0
        if "starbucks" in url:
            merchant = "Starbucks"
        elif "uber" in url:
            merchant = "Uber"
        elif "hotel" in url:
            merchant = "Hotel"
        elif "dog" in url or "perro" in url:
            return {
                "merchant": None,
                "date": None,
                "total": None,
                "currency": None,
                "country": None,
                "category": None,
                "document_type": None,
                "is_document": False,
                "ocr_text": None,
                "invoice_number": None,
                "tax_amount": None,
                "issuer_tax_id": None,
                "receiver_tax_id": None,
                "payment_method": None,
            }

        if "honorario" in url:
            document_type = "boleta_honorarios"
        elif "factura" in url or "invoice" in url:
            document_type = "factura"
        elif "boleta" in url:
            document_type = "boleta"
        elif "ticket" in url:
            document_type = "ticket"

        # Intencionalmente deja category/country a veces vacíos para probar slot filling.
        return {
            "merchant": merchant,
            "date": today,
            "total": total,
            "currency": currency,
            "country": country,
            "category": None,
            "document_type": document_type,
            "is_document": True,
            "invoice_number": None,
            "tax_amount": None,
            "issuer_tax_id": None,
            "receiver_tax_id": None,
            "payment_method": None,
            "gross_amount": total if document_type == "boleta_honorarios" else None,
            "withholding_rate": 15.25 if document_type == "boleta_honorarios" else None,
            "withholding_amount": 1906.25 if document_type == "boleta_honorarios" else None,
            "net_amount": 10593.75 if document_type == "boleta_honorarios" else None,
            "receiver_name": None,
            "service_description": None,
        }

    def _download_media(
        self,
        media_url: str,
        media_content_type: str | None,
    ) -> tuple[bytes, str]:
        if not media_url:
            raise OCRProcessingError("MediaUrl0 vacío")

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
        except HTTPError as exc:  # pragma: no cover - depende de red externa
            raise OCRProcessingError(f"Error HTTP descargando media WhatsApp: {exc.code}") from exc
        except URLError as exc:  # pragma: no cover - depende de red externa
            raise OCRProcessingError("No se pudo descargar la imagen de la boleta") from exc

        if not content:
            raise OCRProcessingError("La imagen descargada está vacía")

        mime_type = self._resolve_mime_type(media_url, media_content_type, response_mime)
        return content, mime_type

    def _media_authorization_header(self) -> str | None:
        if not self.settings:
            return None
        provider = (getattr(self.settings, "whatsapp_provider", "meta") or "meta").strip().lower()
        if provider == "meta":
            token = (getattr(self.settings, "meta_access_token", "") or "").strip()
            return f"Bearer {token}" if token else None

        import base64

        sid = (getattr(self.settings, "twilio_account_sid", "") or "").strip()
        token = (getattr(self.settings, "twilio_auth_token", "") or "").strip()
        if not sid or not token:
            return None
        raw = f"{sid}:{token}".encode("utf-8")
        return "Basic " + base64.b64encode(raw).decode("ascii")

    def _resolve_mime_type(
        self,
        media_url: str,
        media_content_type: str | None,
        response_mime: str | None,
    ) -> str:
        candidates = [media_content_type, response_mime]
        for candidate in candidates:
            if candidate and "/" in candidate:
                return candidate.split(";", 1)[0].strip().lower()

        guessed, _ = mimetypes.guess_type(media_url or "")
        if guessed:
            return guessed
        return "image/jpeg"

    def _process_document_ai(self, content: bytes, mime_type: str):
        try:
            from google.api_core.client_options import ClientOptions
            from google.api_core.exceptions import DeadlineExceeded
            from google.cloud import documentai
        except ImportError as exc:  # pragma: no cover - depende de instalación local
            raise OCRProcessingError(
                "Falta dependencia google-cloud-documentai. Instala requirements.txt."
            ) from exc

        location = getattr(self.settings, "document_ai_location", "us") or "us"
        client_options = None
        if location != "us":
            client_options = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
        client = documentai.DocumentProcessorServiceClient(client_options=client_options)
        name = client.processor_path(
            getattr(self.settings, "document_ai_project_id", ""),
            location,
            getattr(self.settings, "document_ai_processor_id", ""),
        )
        raw_document = documentai.RawDocument(content=content, mime_type=mime_type)
        request = documentai.ProcessRequest(name=name, raw_document=raw_document)
        timeout_seconds = float(getattr(self.settings, "document_ai_timeout_seconds", 12) or 12)
        try:
            result = client.process_document(
                request=request,
                timeout=max(timeout_seconds, 1.0),
            )
        except DeadlineExceeded as exc:  # pragma: no cover - depende de API externa
            raise OCRProcessingError(
                f"Document AI excedió el tiempo límite de {timeout_seconds:.0f}s"
            ) from exc
        except Exception as exc:  # pragma: no cover - depende de API externa
            raise OCRProcessingError(f"Document AI no pudo procesar la boleta: {exc}") from exc
        return result.document

    def _map_document_to_expense_fields(self, document: Any) -> dict[str, Any]:
        entities = self._flatten_entities(getattr(document, "entities", []) or [])
        text = getattr(document, "text", "") or ""

        merchant = self._pick_entity_text(entities, "merchant")
        merchant = self._normalize_merchant_name(merchant)
        if not merchant:
            merchant = self._infer_merchant_from_text(text)
        parsed_date = self._pick_date_value(entities) or self._extract_date_from_text(text)
        total, money_currency = self._pick_total_value(entities, text)
        currency = (
            self._pick_currency_value(entities)
            or money_currency
            or self._infer_currency_from_text(text)
        )
        country = self._pick_entity_text(entities, "country") or self._infer_country_from_text(text)
        document_type = self._classify_document_type(
            text=text,
            merchant=merchant,
            parsed_date=parsed_date,
            total=total,
            currency=currency,
        )

        invoice_number = self._pick_entity_text(entities, "invoice_number") or self._extract_invoice_number_from_text(text)
        tax_amount = self._extract_tax_amount(entities, text)
        issuer_tax_id = self._pick_entity_text(entities, "issuer_tax_id") or self._extract_tax_id_from_text(text, role="issuer")
        receiver_tax_id = self._pick_entity_text(entities, "receiver_tax_id") or self._extract_tax_id_from_text(text, role="receiver")
        payment_method = self._pick_entity_text(entities, "payment_method")
        gross_amount = self._extract_professional_fee_amount(entities, text, "gross_amount")
        withholding_amount = self._extract_professional_fee_amount(entities, text, "withholding_amount")
        net_amount = self._extract_professional_fee_amount(entities, text, "net_amount")
        withholding_rate = self._extract_withholding_rate_from_text(text)
        receiver_name = self._pick_entity_text(entities, "receiver_name")
        service_description = self._pick_entity_text(entities, "service_description")

        if document_type == "boleta_honorarios" and net_amount is not None:
            total = net_amount

        return {
            "merchant": merchant,
            "date": parsed_date,
            "total": total,
            "currency": currency,
            "country": country,
            "document_type": document_type,
            "is_document": bool(document_type),
            "ocr_text": text[:4000] if text else None,
            "invoice_number": invoice_number,
            "tax_amount": tax_amount,
            "issuer_tax_id": issuer_tax_id,
            "receiver_tax_id": receiver_tax_id,
            "payment_method": payment_method,
            "gross_amount": gross_amount,
            "withholding_rate": withholding_rate,
            "withholding_amount": withholding_amount,
            "net_amount": net_amount,
            "receiver_name": receiver_name,
            "service_description": service_description,
        }

    def _classify_document_type(
        self,
        *,
        text: str,
        merchant: str | None,
        parsed_date: str | None,
        total: float | None,
        currency: str | None,
    ) -> str | None:
        normalized_text = re.sub(r"\s+", " ", text or "").strip().lower()
        for document_type in ("boleta_honorarios", "factura", "boleta", "ticket", "comprobante"):
            keywords = _DOCUMENT_KEYWORDS[document_type]
            if any(keyword in normalized_text for keyword in keywords):
                return document_type

        if self._looks_like_expense_document(
            text=text,
            merchant=merchant,
            parsed_date=parsed_date,
            total=total,
            currency=currency,
        ):
            return "comprobante"
        return None

    def _looks_like_expense_document(
        self,
        *,
        text: str,
        merchant: str | None,
        parsed_date: str | None,
        total: float | None,
        currency: str | None,
    ) -> bool:
        upper = (text or "").upper()
        signal_count = 0

        if merchant:
            signal_count += 1
        if parsed_date:
            signal_count += 1
        if total is not None:
            signal_count += 1
        if currency:
            signal_count += 1

        textual_markers = (
            r"\bTOTAL\b",
            r"\bFECHA\b",
            r"\bDATE\b",
            r"\bRUT\b",
            r"\bRUC\b",
            r"\bCAJA\b",
            r"\bTERMINAL\b",
            r"\bTRANSACCION\b",
            r"\bTRANSACCI[ÓO]N\b",
            r"\bNETO\b",
            r"\bIVA\b",
        )
        marker_hits = sum(1 for pattern in textual_markers if re.search(pattern, upper))

        return signal_count >= 3 or (signal_count >= 2 and marker_hits >= 2)

    def _flatten_entities(self, entities: list[Any]) -> list[Any]:
        flat: list[Any] = []
        for entity in entities:
            flat.append(entity)
            children = getattr(entity, "properties", None) or []
            flat.extend(self._flatten_entities(list(children)))
        return flat

    def _pick_entity_text(self, entities: list[Any], target: str) -> str | None:
        aliases = set(_ENTITY_TYPE_ALIASES.get(target, ()))
        for entity in entities:
            entity_type = (getattr(entity, "type_", "") or "").lower()
            if entity_type in aliases:
                value = self._entity_text_value(entity)
                if value:
                    return value
        return None

    def _pick_date_value(self, entities: list[Any]) -> str | None:
        aliases = set(_ENTITY_TYPE_ALIASES["date"])
        for entity in entities:
            entity_type = (getattr(entity, "type_", "") or "").lower()
            if entity_type not in aliases:
                continue
            normalized = getattr(entity, "normalized_value", None)
            date_value = getattr(normalized, "date_value", None)
            if date_value and getattr(date_value, "year", 0):
                year = int(getattr(date_value, "year", 0))
                month = int(getattr(date_value, "month", 1) or 1)
                day = int(getattr(date_value, "day", 1) or 1)
                try:
                    return date(year, month, day).isoformat()
                except ValueError:
                    pass
            mention = self._entity_text_value(entity)
            parsed = self._normalize_date_text(mention)
            if parsed:
                return parsed
        return None

    def _pick_total_value(self, entities: list[Any], text: str) -> tuple[float | None, str | None]:
        aliases = set(_ENTITY_TYPE_ALIASES["total"])
        for entity in entities:
            entity_type = (getattr(entity, "type_", "") or "").lower()
            if entity_type not in aliases:
                continue
            normalized = getattr(entity, "normalized_value", None)
            money_value = getattr(normalized, "money_value", None)
            if money_value is not None:
                units = float(getattr(money_value, "units", 0) or 0)
                nanos = float(getattr(money_value, "nanos", 0) or 0) / 1_000_000_000
                amount = round(units + nanos, 2)
                currency = (getattr(money_value, "currency_code", "") or "").upper() or None
                if amount:
                    return amount, currency
            amount = self._parse_amount_text(self._entity_text_value(entity))
            if amount is not None:
                return amount, self._infer_currency_from_text(self._entity_text_value(entity) or "")
        return self._extract_total_from_text(text), None

    def _pick_currency_value(self, entities: list[Any]) -> str | None:
        aliases = set(_ENTITY_TYPE_ALIASES["currency"])
        for entity in entities:
            entity_type = (getattr(entity, "type_", "") or "").lower()
            if entity_type not in aliases:
                continue
            value = (self._entity_text_value(entity) or "").upper()
            if value in {"CLP", "USD", "PEN", "CNY", "EUR"}:
                return value
            if "PESO" in value:
                return "CLP"
            if re.search(r"\bSOL(?:ES)?\b", value) or re.search(r"\bPEN\b", value) or "S/" in value:
                return "PEN"
            if "DOLAR" in value or re.search(r"\bUSD\b", value) or "US$" in value:
                return "USD"
            if "EURO" in value or re.search(r"\bEUR\b", value) or "€" in value:
                return "EUR"
        return None

    def _entity_text_value(self, entity: Any) -> str | None:
        normalized = getattr(entity, "normalized_value", None)
        if normalized is not None:
            text_val = getattr(normalized, "text", None)
            if text_val:
                return str(text_val).strip()
        mention = getattr(entity, "mention_text", None)
        if mention:
            return str(mention).strip()
        return None

    def _extract_date_from_text(self, text: str) -> str | None:
        return self._normalize_date_text(text)

    def _normalize_date_text(self, text: str | None) -> str | None:
        if not text:
            return None
        text = text.strip()
        match = re.search(r"\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b", text)
        if match:
            year, month, day = map(int, match.groups())
            try:
                return date(year, month, day).isoformat()
            except ValueError:
                return None

        match = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", text)
        if not match:
            return None

        day, month, year = match.groups()
        year_i = int(year)
        if year_i < 100:
            year_i += 2000
        try:
            return date(year_i, int(month), int(day)).isoformat()
        except ValueError:
            return None

    def _extract_total_from_text(self, text: str) -> float | None:
        if not text:
            return None
        total_line_match = re.search(
            r"(?:total|importe|monto)\D{0,10}([0-9][0-9\., ]+)",
            text,
            flags=re.IGNORECASE,
        )
        if total_line_match:
            parsed = self._parse_amount_text(total_line_match.group(1))
            if parsed is not None:
                return parsed
        return None

    def _parse_amount_text(self, text: str | None) -> float | None:
        if not text:
            return None
        cleaned = re.sub(r"[^\d,.\-]", "", text)
        if not cleaned:
            return None

        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif cleaned.count(",") == 1 and cleaned.count(".") == 0:
            whole, frac = cleaned.split(",", 1)
            if len(frac) == 3 and len(whole) >= 1:
                cleaned = whole + frac
            else:
                cleaned = whole + "." + frac
        elif cleaned.count(".") == 1 and cleaned.count(",") == 0:
            whole, frac = cleaned.split(".", 1)
            if len(frac) == 3 and len(whole) >= 1:
                cleaned = whole + frac
        elif cleaned.count(".") > 1 and cleaned.count(",") == 0:
            cleaned = cleaned.replace(".", "")

        try:
            return float(cleaned)
        except ValueError:
            return None

    def _infer_currency_from_text(self, text: str) -> str | None:
        upper = (text or "").upper()
        if re.search(r"\bMONEDA\s*:\s*PESO(?:S)?\b", upper):
            return "CLP"
        # Prioriza evidencia fuerte de Chile antes de heurísticas de PEN/USD:
        # substrings cortos como "PEN" o "SOL" aparecen incidentalmente en
        # palabras comunes (PENDIENTE, SOLICITUD, SOLARIUM, etc.).
        if self._looks_like_chile_receipt(upper):
            return "CLP"
        if re.search(r"\bPEN\b", upper) or "S/" in upper or re.search(r"\bSOLES\b", upper):
            return "PEN"
        if re.search(r"\bUSD\b", upper) or "US$" in upper or "DOLAR" in upper or "DÓLAR" in upper:
            return "USD"
        if re.search(r"\bEUR\b", upper) or "EURO" in upper or "€" in text:
            return "EUR"
        if re.search(r"\bCLP\b", upper):
            return "CLP"
        if re.search(r"\bCNY\b", upper) or "RMB" in upper or "YUAN" in upper:
            return "CNY"
        return None

    def _infer_country_from_text(self, text: str) -> str | None:
        upper = (text or "").upper()
        # Prioriza evidencia de ubicación/documento por sobre el nombre del comercio.
        if self._looks_like_chile_receipt(upper):
            return "Chile"
        if "PERU" in upper or "PERÚ" in upper:
            if self._looks_like_peru_receipt(upper):
                return "Peru"
            return None
        if "CHILE" in upper:
            return "Chile"
        if "CHINA" in upper:
            return "China"
        return None

    def _looks_like_peru_receipt(self, upper_text: str) -> bool:
        hard_hits = 0
        if re.search(r"\bRUC\b", upper_text):
            hard_hits += 1
        if "SUNAT" in upper_text:
            hard_hits += 1
        if re.search(r"\b[\w.-]+\.PE\b", upper_text):
            hard_hits += 1

        soft_hits = 0
        for token in ("LIMA", "MIRAFLORES", "SAN ISIDRO", "AREQUIPA", "CUSCO", "PERU", "PERÚ"):
            if token in upper_text:
                soft_hits += 1

        return (hard_hits >= 1 and soft_hits >= 1) or soft_hits >= 2

    def _looks_like_chile_receipt(self, upper_text: str) -> bool:
        for token in (
            "CHILE",
            "SANTIAGO",
            "VITACURA",
            "LAS CONDES",
            "SII.CL",
            "RUT",
            "COMUNA",
            ".CL",
        ):
            if token in upper_text:
                return True
        return False

    def _extract_invoice_number_from_text(self, text: str) -> str | None:
        if not text:
            return None
        # Match patterns like "Folio: 123", "N° 456", "Invoice #789", "Nro. Factura: 001"
        patterns = [
            r"(?:folio|n[°º]|nro\.?\s*(?:factura|boleta)?|invoice\s*#?)\s*[:.]?\s*(\d[\d\-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _extract_tax_amount(self, entities: list[Any], text: str) -> float | None:
        # Try entities first
        aliases = set(_ENTITY_TYPE_ALIASES.get("tax_amount", ()))
        for entity in entities:
            entity_type = (getattr(entity, "type_", "") or "").lower()
            if entity_type in aliases:
                amount = self._parse_amount_text(self._entity_text_value(entity))
                if amount is not None:
                    return amount
        # Fallback: extract from text
        if not text:
            return None
        match = re.search(
            r"(?:IVA|impuesto|tax|I\.V\.A\.?)\s*[:.]?\s*\$?\s*([0-9][0-9\., ]+)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return self._parse_amount_text(match.group(1))
        return None

    def _extract_professional_fee_amount(self, entities: list[Any], text: str, target: str) -> float | None:
        aliases = set(_ENTITY_TYPE_ALIASES.get(target, ()))
        for entity in entities:
            entity_type = (getattr(entity, "type_", "") or "").lower()
            if entity_type in aliases:
                amount = self._parse_amount_text(self._entity_text_value(entity))
                if amount is not None:
                    return amount

        label_map = {
            "gross_amount": (
                "total honorarios",
                "monto bruto",
                "total bruto",
                "bruto",
                "honorarios",
            ),
            "withholding_amount": (
                "retencion",
                "retención",
                "monto retenido",
                "impuesto retenido",
            ),
            "net_amount": (
                "total boleta",
                "total liquido",
                "total líquido",
                "liquido a pagar",
                "líquido a pagar",
                "liquido",
                "líquido",
            ),
        }
        for label in label_map.get(target, ()):
            pattern = rf"{re.escape(label)}([^\n\r]{{0,80}})"
            match = re.search(pattern, text or "", flags=re.IGNORECASE)
            if match:
                candidates = re.findall(r"([0-9][0-9\., ]+)\s*(%)?", match.group(1))
                for candidate, percent_marker in candidates:
                    if percent_marker:
                        continue
                    amount = self._parse_amount_text(candidate)
                    if amount is not None:
                        return amount
        return None

    def _extract_withholding_rate_from_text(self, text: str) -> float | None:
        match = re.search(
            r"(?:retenci[oó]n|ppm)[^\d]{0,20}(\d{1,2}(?:[,.]\d{1,2})?)\s*%",
            text or "",
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return self._parse_amount_text(match.group(1).replace(",", "."))

    def _extract_tax_id_from_text(self, text: str, *, role: str = "issuer") -> str | None:
        """Extract tax IDs (RUT, RUC, RFC, CUIT, NIT) from OCR text.

        For 'issuer', returns the first tax ID found (typically the seller).
        For 'receiver', tries to find a second tax ID if present.
        """
        if not text:
            return None
        # Find all tax ID occurrences
        pattern = r"(?:RUT|RUC|RFC|CUIT|NIT)\s*[:.]?\s*([\d\.\-]+[\dkK]?)"
        matches = list(re.finditer(pattern, text, flags=re.IGNORECASE))
        if not matches:
            return None
        if role == "issuer":
            return matches[0].group(0).strip()
        if role == "receiver" and len(matches) >= 2:
            return matches[1].group(0).strip()
        return None

    def _normalize_merchant_name(self, merchant: str | None) -> str | None:
        if not merchant:
            return None
        normalized = re.sub(r"\s+", " ", merchant).strip()
        if not normalized:
            return None
        lower = normalized.lower()
        if lower in _GENERIC_MERCHANT_TERMS:
            return None
        if any(term in lower for term in _GENERIC_MERCHANT_TERMS) and len(lower) <= 40:
            return None
        return normalized

    def _infer_merchant_from_text(self, text: str) -> str | None:
        if not text:
            return None

        lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
        candidates: list[str] = []
        for line in lines[:20]:
            if not line:
                continue
            lower = line.lower()
            if len(line) < 3 or len(line) > 60:
                continue
            if not re.search(r"[a-zA-Z]", line):
                continue
            if re.search(
                r"\b(total|fecha|date|ruc|nro|numero|n[°º]|invoice|receipt|terminal|hora|monto|propina|tarjeta|visa|mastercard)\b",
                lower,
            ):
                continue
            if lower in _GENERIC_MERCHANT_TERMS or any(term in lower for term in _GENERIC_MERCHANT_TERMS):
                continue
            # Filtra líneas mayormente numéricas/código.
            digits = sum(ch.isdigit() for ch in line)
            letters = sum(ch.isalpha() for ch in line)
            if digits > letters:
                continue
            candidates.append(line)

        if not candidates:
            return None
        return candidates[0]
