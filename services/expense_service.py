from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from services.llm_service import LLMService
from services.review_score_service import ReviewScoreService
from services.sheets_service import SheetsService
from services.statuses import ExpenseStatus
from utils.exchange_rate import convert_to_clp
from utils.helpers import json_loads, make_id, normalize_whatsapp_phone, parse_float, utc_now_iso


logger = logging.getLogger(__name__)

_GENERIC_MERCHANT_VALUES = {
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
    "recibo",
    "ticket",
    "tarjeta de debito",
    "tarjeta de débito",
    "tarjeta de credito",
    "tarjeta de crédito",
    "visa debito",
    "visa débito",
    "visa credito",
    "visa crédito",
    "mastercard",
    "copia cliente",
}


REQUIRED_EXPENSE_FIELDS = [
    "merchant",
    "date",
    "total",
    "currency",
    "country",
]

# Campos mínimos obligatorios por tipo de documento
REQUIRED_FIELDS_BY_DOCUMENT_TYPE: dict[str, list[str]] = {
    "receipt": ["merchant", "date", "total", "currency", "country"],
    "invoice": ["merchant", "date", "total", "currency", "country"],
    "professional_fee_receipt": [
        "merchant",
        "date",
        "total",
        "currency",
        "invoice_number",
        "issuer_tax_id",
    ],
}

# Campos que generan advertencia si faltan en factura
INVOICE_WARNING_FIELDS = ["invoice_number", "tax_amount"]

DOCUMENT_CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.7

CHILE_PROFESSIONAL_FEE_WITHHOLDING_RATES_BY_YEAR: dict[int, float] = {
    2020: 10.75,
    2021: 11.5,
    2022: 12.25,
    2023: 13.0,
    2024: 13.75,
    2025: 14.5,
    2026: 15.25,
    2027: 16.0,
    2028: 17.0,
}

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Meals": (
        "restaurant",
        "restaurante",
        "cafe",
        "cafeteria",
        "coffee",
        "bar",
        "food",
        "pizza",
        "burger",
        "mcdonald",
        "starbucks",
        "kfc",
        "subway",
        "sushi",
        "grill",
    ),
    "Lodging": (
        "hotel",
        "hostal",
        "hostel",
        "inn",
        "resort",
        "lodging",
        "airbnb",
        "booking",
        "motel",
    ),
    "Transport": (
        "uber",
        "cabify",
        "didi",
        "taxi",
        "bus",
        "metro",
        "train",
        "tren",
        "flight",
        "airline",
        "aerolinea",
        "airport",
        "peaje",
        "toll",
        "gas",
        "gasolina",
        "combustible",
        "shell",
        "copec",
        "esso",
    ),
}

_COUNTRY_TO_CURRENCY: dict[str, str] = {
    "chile": "CLP",
    "peru": "PEN",
    "perú": "PEN",
    "china": "CNY",
    "spain": "EUR",
    "españa": "EUR",
    "france": "EUR",
    "italy": "EUR",
    "germany": "EUR",
    "usa": "USD",
    "eeuu": "USD",
    "estados unidos": "USD",
    "united states": "USD",
    "mexico": "MXN",
    "méxico": "MXN",
    "argentina": "ARS",
    "brazil": "BRL",
    "brasil": "BRL",
    "colombia": "COP",
}

_KNOWN_CURRENCY_CODES = {"CLP", "USD", "PEN", "CNY", "EUR", "MXN", "ARS", "BRL", "COP"}

_MAX_HISTORY_TURNS = 10


def _message_log_to_llm_history(message_log: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    if not message_log:
        return []
    text_entries = [
        item for item in message_log
        if isinstance(item, dict) and str(item.get("type", "text")) == "text"
    ]
    recent = text_entries[-(_MAX_HISTORY_TURNS * 2):]
    history: list[dict[str, str]] = []
    for item in recent:
        speaker = str(item.get("speaker", "")).strip()
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        if speaker == "person":
            history.append({"role": "user", "content": text})
        elif speaker == "bot":
            history.append({"role": "assistant", "content": text})
    return history


@dataclass
class ExpenseService:
    sheets_service: SheetsService
    llm_service: LLMService | None = None
    review_score_service: ReviewScoreService | None = None

    def find_case_by_id_for_phone(self, phone: str, case_id: Any) -> dict[str, Any] | None:
        if not self.sheets_service:
            return None
        normalized_case_id = str(case_id or "").strip()
        if not normalized_case_id:
            return None
        expense_case = self.sheets_service.get_expense_case_by_id(normalized_case_id)
        if not expense_case:
            return None
        case_phone = normalize_whatsapp_phone(
            expense_case.get("employee_phone", expense_case.get("phone", ""))
        )
        if case_phone != normalize_whatsapp_phone(phone):
            return None
        return expense_case

    def get_active_case_for_phone(self, phone: str) -> dict[str, Any] | None:
        if not self.sheets_service:
            return None
        return self.sheets_service.get_active_expense_case_by_phone(phone)

    def enrich_draft_expense(self, draft_expense: dict[str, Any]) -> dict[str, Any]:
        draft = dict(draft_expense or {})
        case_id = str(draft.get("case_id", draft.get("trip_id", "")) or "").strip()
        if case_id:
            draft["case_id"] = case_id
            draft["trip_id"] = case_id
        normalized_currency = self._normalize_currency_candidate(draft.get("currency"))
        if normalized_currency:
            draft["currency"] = normalized_currency
        elif "currency" in draft and str(draft.get("currency", "") or "").strip():
            draft["currency"] = ""
        merchant = str(draft.get("merchant", "") or "").strip()
        if self._should_infer_merchant_with_llm(draft):
            inferred_merchant = self.infer_merchant_with_llm(draft)
            if inferred_merchant:
                draft["merchant"] = inferred_merchant
                logger.info("Expense merchant inferred source=llm merchant=%r", inferred_merchant)
            else:
                logger.info(
                    "Expense merchant not inferred by llm keeping_ocr_merchant=%r",
                    merchant or None,
                )

        rule_geo = self.infer_country_currency_from_text(draft)
        if rule_geo:
            current_country = str(draft.get("country", "") or "").strip()
            current_currency = str(draft.get("currency", "") or "").strip()
            if not current_country and rule_geo.get("country"):
                draft["country"] = rule_geo["country"]
            if not current_currency and rule_geo.get("currency"):
                draft["currency"] = rule_geo["currency"]
            logger.info(
                "Expense country/currency inferred source=rules country=%r currency=%r",
                draft.get("country"),
                draft.get("currency"),
            )

        if self._should_infer_country_currency_with_llm(draft):
            inferred_geo = self.infer_country_currency_with_llm(draft)
            if inferred_geo:
                current_country = str(draft.get("country", "") or "").strip()
                current_currency = str(draft.get("currency", "") or "").strip()
                if not current_country and inferred_geo.get("country"):
                    draft["country"] = inferred_geo["country"]
                if not current_currency and inferred_geo.get("currency"):
                    draft["currency"] = inferred_geo["currency"]
                logger.info(
                    "Expense country/currency inferred source=llm country=%r currency=%r",
                    draft.get("country"),
                    draft.get("currency"),
                )
            else:
                logger.info(
                    "Expense country/currency not inferred by llm keeping country=%r currency=%r",
                    draft.get("country"),
                    draft.get("currency"),
                )

        if not str(draft.get("currency", "") or "").strip():
            inferred_from_country = self.infer_currency_from_country(draft.get("country"))
            if inferred_from_country:
                draft["currency"] = inferred_from_country
                logger.info(
                    "Expense currency inferred from country country=%r currency=%r",
                    draft.get("country"),
                    draft["currency"],
                )

        draft = self._reconcile_country_currency(draft)
        draft = self._apply_chile_guardrails(draft)
        draft = self._normalize_professional_fee_receipt(draft)

        category = draft.get("category")
        if category is None or str(category).strip() == "":
            inferred = self.infer_category_with_fallback(draft)
            if inferred:
                draft["category"] = inferred
                logger.info(
                    "Expense category inferred category=%s merchant=%r",
                    inferred,
                    draft.get("merchant"),
                )
            else:
                logger.info(
                    "Expense category not inferred merchant=%r country=%r",
                    draft.get("merchant"),
                    draft.get("country"),
                )
        return draft

    def _normalize_professional_fee_receipt(self, draft_expense: dict[str, Any]) -> dict[str, Any]:
        doc_type = str(draft_expense.get("document_type", "") or "").strip()
        if doc_type in ("boleta_honorarios", "boleta de honorarios"):
            draft_expense = {**draft_expense, "document_type": "professional_fee_receipt"}
        elif doc_type != "professional_fee_receipt":
            return draft_expense

        draft = dict(draft_expense)
        if not str(draft.get("country", "") or "").strip():
            draft["country"] = "Chile"
        if not str(draft.get("currency", "") or "").strip():
            draft["currency"] = "CLP"

        gross = parse_float(draft.get("gross_amount"))
        net = parse_float(draft.get("net_amount"))
        withholding = parse_float(draft.get("withholding_amount"))
        rate = parse_float(draft.get("withholding_rate"))

        labeled_gross = self._extract_amount_after_labels(
            draft.get("ocr_text"),
            (
                "total honorarios",
                "monto bruto",
                "total bruto",
                "bruto",
            ),
        )
        if labeled_gross is not None:
            gross = labeled_gross
        labeled_withholding = self._extract_amount_after_labels(
            draft.get("ocr_text"),
            (
                "retencion",
                "retención",
                "monto retenido",
                "impuesto retenido",
            ),
        )
        if labeled_withholding is not None:
            withholding = labeled_withholding
        labeled_net = self._extract_amount_after_labels(
            draft.get("ocr_text"),
            (
                "total boleta",
                "total liquido",
                "total líquido",
                "liquido a pagar",
                "líquido a pagar",
                "liquido",
                "líquido",
            ),
        )
        if labeled_net is not None:
            net = labeled_net
        if rate is None:
            rate = self._extract_withholding_rate(draft.get("ocr_text"))
        if rate is None:
            rate = self._expected_professional_fee_withholding_rate(draft)
        if gross is None and net is None:
            net = parse_float(draft.get("total"))

        if gross is not None and net is not None and withholding is not None:
            if abs(gross - net) < 0.01 and withholding > 0:
                gross = round(net + withholding, 2)
        if gross is None and net is not None and withholding is not None and withholding > 0:
            gross = round(net + withholding, 2)
        if gross is None and net is not None and rate is not None:
            retained_fraction = rate / 100
            if 0 < retained_fraction < 1:
                gross = round(net / (1 - retained_fraction), 2)
                withholding = round(gross - net, 2)

        if gross is not None:
            draft["gross_amount"] = gross
        if withholding is not None:
            draft["withholding_amount"] = withholding
        if net is not None:
            draft["net_amount"] = net
        elif gross is not None and withholding is not None:
            draft["net_amount"] = round(gross - withholding, 2)

        if gross is not None:
            draft["total"] = gross
        elif net is not None:
            draft["total"] = net
        if rate is not None:
            draft["withholding_rate"] = rate
        return draft

    def _expected_professional_fee_withholding_rate(self, draft_expense: dict[str, Any]) -> float | None:
        country = str(draft_expense.get("country", "") or "").strip().lower()
        if country and country != "chile":
            return None
        date_text = str(draft_expense.get("date", "") or "")
        match = re.match(r"(\d{4})-", date_text)
        if not match:
            return None
        return CHILE_PROFESSIONAL_FEE_WITHHOLDING_RATES_BY_YEAR.get(int(match.group(1)))

    def _extract_withholding_rate(self, text: Any) -> float | None:
        raw = str(text or "")
        match = re.search(r"(?:retenci[oó]n|ppm)[^\d]{0,20}(\d{1,2}(?:[,.]\d{1,2})?)\s*%", raw, re.IGNORECASE)
        if not match:
            return None
        return parse_float(match.group(1).replace(",", "."))

    def _extract_amount_after_labels(self, text: Any, labels: tuple[str, ...]) -> float | None:
        raw = str(text or "")
        if not raw:
            return None
        for label in labels:
            pattern = rf"{re.escape(label)}([^\n\r]{{0,80}})"
            match = re.search(pattern, raw, re.IGNORECASE)
            if match:
                candidates = re.findall(r"([0-9][0-9\., ]+)\s*(%)?", match.group(1))
                for candidate, percent_marker in candidates:
                    if percent_marker:
                        continue
                    amount = self._parse_amount_text(candidate)
                    if amount is not None:
                        return amount
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
            cleaned = whole + frac if len(frac) == 3 else whole + "." + frac
        elif cleaned.count(".") == 1 and cleaned.count(",") == 0:
            whole, frac = cleaned.split(".", 1)
            if len(frac) == 3:
                cleaned = whole + frac
        elif cleaned.count(".") > 1 and cleaned.count(",") == 0:
            cleaned = cleaned.replace(".", "")
        try:
            return float(cleaned)
        except ValueError:
            return None

    def _normalize_currency_candidate(self, currency: Any) -> str | None:
        if currency is None:
            return None
        raw = str(currency).strip()
        if not raw:
            return None
        upper = raw.upper()
        if upper in _KNOWN_CURRENCY_CODES:
            return upper
        if "€" in raw or "EURO" in upper:
            return "EUR"
        if "US$" in upper or "USD" in upper or "DOLAR" in upper or "DÓLAR" in upper:
            return "USD"
        if "S/" in upper or "PEN" in upper or "SOL" in upper:
            return "PEN"
        if "CNY" in upper or "RMB" in upper or "YUAN" in upper:
            return "CNY"
        if "CLP" in upper or "PESO" in upper:
            return "CLP"
        alpha = "".join(ch for ch in upper if ch.isalpha())
        if alpha in _KNOWN_CURRENCY_CODES:
            return alpha
        return None

    def infer_currency_from_country(self, country: Any) -> str | None:
        normalized = str(country or "").strip().lower()
        if not normalized:
            return None
        return _COUNTRY_TO_CURRENCY.get(normalized)

    def infer_country_currency_from_text(self, draft_expense: dict[str, Any]) -> dict[str, str]:
        text = str(draft_expense.get("ocr_text", "") or "")
        upper = text.upper()
        if not upper:
            return {}

        country = self._infer_country_from_text(upper)
        currency = self._infer_currency_from_text(text)
        if not currency and country:
            currency = self.infer_currency_from_country(country)
        if not country and currency:
            country = self._infer_country_from_currency(currency, upper)

        result: dict[str, str] = {}
        if country:
            result["country"] = country
        if currency:
            result["currency"] = currency
        return result

    def infer_merchant_with_llm(self, draft_expense: dict[str, Any]) -> str | None:
        if not self.llm_service:
            return None
        return self.llm_service.infer_expense_merchant(draft_expense)

    def answer_general_question(self, question: str, *, phone: str = "", case_context_hint: bool = False) -> str | None:
        rendicion_answer = self.answer_rendicion_question(phone=phone, question=question)
        if rendicion_answer:
            return rendicion_answer
        if not self.llm_service:
            return None
        # When we know the question is case-related, try LLM with full case context
        if case_context_hint and self.llm_service.chat_assistant_enabled:
            case_context = self.build_case_context_text(phone)
            case_answer = self.llm_service.answer_question_with_case_context(question, case_context)
            if case_answer:
                return case_answer
        return self.llm_service.answer_general_question(question)

    def chat_whatsapp_conversational(
        self,
        message: str,
        phone: str,
        *,
        message_log: list[dict[str, Any]] | None = None,
    ) -> str | None:
        """Single LLM call with full case context and conversation history for WhatsApp replies."""
        if not self.llm_service or not self.llm_service.chat_assistant_enabled:
            return None
        case_context = self.build_case_context_text(phone)
        history = _message_log_to_llm_history(message_log)
        return self.llm_service.chat_whatsapp_with_context(
            message=message, case_context=case_context, history=history
        )

    def classify_message_intent(self, message: str) -> str:
        if not self.llm_service:
            return "unknown"
        return self.llm_service.classify_message_intent(message)

    def build_case_context_text(self, phone: str) -> str:
        expense_case = self.sheets_service.get_active_expense_case_by_phone(phone) if phone else None
        if not expense_case:
            return "El empleado no tiene una rendición activa en este momento."

        case_id = str(expense_case.get("case_id", expense_case.get("trip_id", "")) or "").strip()
        case_label = str(expense_case.get("context_label", "") or "").strip()

        cost_centers_raw = expense_case.get("cost_centers", [])
        if isinstance(cost_centers_raw, str):
            parsed_cost_centers = json_loads(cost_centers_raw, default=None)
            if isinstance(parsed_cost_centers, list):
                cost_centers_raw = parsed_cost_centers
            else:
                cost_centers_raw = [
                    c.strip() for c in cost_centers_raw.replace(";", ",").split(",") if c.strip()
                ]
        if not isinstance(cost_centers_raw, list):
            cost_centers_raw = []
        cost_centers = [str(c).strip() for c in cost_centers_raw if str(c).strip()]
        fondos_por_centro = self._normalize_fondos_por_centro(expense_case.get("fondos_por_centro"))

        fondos = parse_float(expense_case.get("fondos_entregados"))
        policy_limit = parse_float(expense_case.get("policy_limit", expense_case.get("budget")))
        budget = fondos or policy_limit

        expenses = self.sheets_service.list_expenses_by_phone_case(phone=phone, case_id=case_id) if case_id else []

        lines = []
        if case_id:
            lines.append(f"Rendición activa ID: {case_id}")
        if case_label:
            lines.append(f"Nombre de la rendición: {case_label}")
        if cost_centers:
            lines.append(f"Centros de costo disponibles: {', '.join(cost_centers)}")
        if budget:
            label = "Fondos entregados" if fondos else "Límite de referencia"
            lines.append(f"{label}: {self._format_clp(budget)} CLP")

        if expenses:
            total_spent = sum(parse_float(e.get("total_clp") or e.get("total") or 0) or 0.0 for e in expenses)
            lines.append(f"Total rendido: {self._format_clp(total_spent)} CLP ({len(expenses)} gasto(s))")
            if budget:
                remaining = budget - total_spent
                lines.append(f"Saldo restante: {self._format_clp(remaining)} CLP")

            status_labels = {
                "approved": "aprobado",
                "rejected": "rechazado",
                "pending_approval": "pendiente aprobación",
                "pending_review": "pendiente revisión",
                "needs_manual_review": "revisión manual",
                "observed": "observado",
            }
            lines.append("Detalle de gastos registrados:")
            for exp in expenses:
                merchant = str(exp.get("merchant", "") or "Sin nombre").strip()
                date = str(exp.get("date", "") or "").strip()
                amount = parse_float(exp.get("total_clp") or exp.get("total") or 0) or 0.0
                exp_status = str(exp.get("review_status") or exp.get("status") or "").strip()
                status_label = status_labels.get(exp_status, exp_status) if exp_status else "sin estado"
                parts = [f"  - {merchant}"]
                if date:
                    parts.append(f"({date})")
                parts.append(f"${self._format_clp(amount)} CLP")
                parts.append(f"[{status_label}]")
                lines.append(" ".join(parts))

            by_cc: dict[str, float] = {}
            for exp in expenses:
                cc = str(exp.get("cost_center", "") or "Sin clasificar").strip() or "Sin clasificar"
                amount = parse_float(exp.get("total_clp") or exp.get("total") or 0) or 0.0
                by_cc[cc] = by_cc.get(cc, 0.0) + amount
            if by_cc:
                lines.append("Gastos por centro de costo:")
                for cc, total in sorted(by_cc.items()):
                    lines.append(f"  {cc}: {self._format_clp(total)} CLP")
            if fondos_por_centro:
                lines.append("Presupuesto por centro de costo:")
                center_names = sorted(
                    {
                        *cost_centers,
                        *fondos_por_centro.keys(),
                        *by_cc.keys(),
                    },
                    key=str.lower,
                )
                for cc in center_names:
                    assigned = fondos_por_centro.get(cc)
                    spent = by_cc.get(cc, 0.0)
                    expense_count = sum(
                        1
                        for exp in expenses
                        if (str(exp.get("cost_center", "") or "Sin clasificar").strip() or "Sin clasificar") == cc
                    )
                    if assigned is None:
                        lines.append(
                            f"  {cc}: presupuesto no asignado; rendido {self._format_clp(spent)} CLP "
                            f"({expense_count} gasto(s))"
                        )
                    else:
                        remaining = assigned - spent
                        lines.append(
                            f"  {cc}: presupuesto {self._format_clp(assigned)} CLP; "
                            f"rendido {self._format_clp(spent)} CLP; "
                            f"saldo {self._format_clp(remaining)} CLP ({expense_count} gasto(s))"
                        )
        elif case_id:
            lines.append("Gastos registrados: ninguno aún.")
            if fondos_por_centro:
                lines.append("Presupuesto por centro de costo:")
                center_names = sorted({*cost_centers, *fondos_por_centro.keys()}, key=str.lower)
                for cc in center_names:
                    assigned = fondos_por_centro.get(cc)
                    if assigned is None:
                        lines.append(f"  {cc}: presupuesto no asignado; rendido 0 CLP; saldo no disponible")
                    else:
                        lines.append(
                            f"  {cc}: presupuesto {self._format_clp(assigned)} CLP; "
                            f"rendido 0 CLP; saldo {self._format_clp(assigned)} CLP"
                        )

        return "\n".join(lines) if lines else "Rendición activa sin datos adicionales."

    def _normalize_fondos_por_centro(self, value: Any) -> dict[str, float]:
        if isinstance(value, str):
            value = json_loads(value, default=None)
        if not isinstance(value, dict):
            return {}

        normalized: dict[str, float] = {}
        for raw_center, raw_amount in value.items():
            center = str(raw_center or "").strip()
            if not center:
                continue
            normalized[center] = parse_float(raw_amount) or 0.0
        return normalized

    def _normalize_case_cost_centers(self, expense_case: dict[str, Any]) -> list[str]:
        cost_centers_raw = expense_case.get("cost_centers", [])
        if isinstance(cost_centers_raw, str):
            parsed_cost_centers = json_loads(cost_centers_raw, default=None)
            if isinstance(parsed_cost_centers, list):
                cost_centers_raw = parsed_cost_centers
            else:
                cost_centers_raw = [
                    c.strip() for c in cost_centers_raw.replace(";", ",").split(",") if c.strip()
                ]
        if not isinstance(cost_centers_raw, (list, tuple, set)):
            cost_centers_raw = []

        centers: list[str] = []
        seen: set[str] = set()
        for item in cost_centers_raw:
            center = str(item or "").strip()
            key = center.lower()
            if center and key not in seen:
                centers.append(center)
                seen.add(key)
        return centers

    def answer_rendicion_question(self, *, phone: str, question: str) -> str | None:
        intent = self._classify_rendicion_question(question)
        if not intent:
            return None

        expense_case = self.sheets_service.get_active_expense_case_by_phone(phone)
        if not expense_case:
            return "No encontré una rendición activa asociada a tu usuario."

        case_id = str(expense_case.get("case_id", expense_case.get("trip_id", "")) or "").strip()
        if not case_id:
            return "No encontré el identificador de tu rendición activa."

        if intent == "last_expense":
            return self.build_last_expense_message(phone=phone, case_id=case_id)
        if intent == "cost_centers":
            return self.build_case_cost_centers_message(expense_case)
        if intent == "budget":
            return self.build_case_budget_message(phone=phone, case_id=case_id, expense_case=expense_case)

        status_message = self.build_policy_status_message(phone=phone, case_id=case_id)
        alert_message = self.build_policy_alert_message(phone=phone, case_id=case_id)
        if intent == "balance":
            if status_message:
                lines = status_message.splitlines()
                return "\n".join(line for line in lines if "Saldo restante:" in line) or status_message
            return "Tu rendición activa no tiene fondos entregados o límite configurado."
        if status_message and alert_message:
            return f"{status_message}\n\n{alert_message}"
        return status_message or "Tu rendición activa no tiene fondos entregados o límite configurado."

    def build_last_expense_message(self, phone: str, case_id: str) -> str:
        expenses = self.sheets_service.list_expenses_by_phone_case(phone=phone, case_id=case_id)
        if not expenses:
            return "Todavía no tengo gastos registrados en tu rendición activa."

        latest = max(
            expenses,
            key=lambda item: str(item.get("created_at") or item.get("updated_at") or item.get("date") or ""),
        )
        merchant = str(latest.get("merchant", "") or "").strip() or "sin comercio"
        date = str(latest.get("date", "") or "").strip()
        currency = str(latest.get("currency", "") or "").strip().upper() or "CLP"
        total = parse_float(latest.get("total"))
        total_clp = parse_float(latest.get("total_clp"))
        amount = self._format_clp(total_clp if total_clp is not None else total or 0)
        suffix = " CLP" if currency == "CLP" or total_clp is not None else f" {currency}"
        parts = [f"Último gasto registrado: {merchant}", f"monto {amount}{suffix}"]
        if date:
            parts.append(f"fecha {date}")
        return ", ".join(parts) + "."

    def build_case_cost_centers_message(self, expense_case: dict[str, Any]) -> str:
        cost_centers = self._normalize_case_cost_centers(expense_case)
        fondos_por_centro = self._normalize_fondos_por_centro(expense_case.get("fondos_por_centro"))

        center_names = []
        seen: set[str] = set()
        for center in [*cost_centers, *fondos_por_centro.keys()]:
            key = center.lower()
            if key not in seen:
                center_names.append(center)
                seen.add(key)

        if not center_names:
            return "Tu rendición activa no tiene centros de costo configurados."

        if fondos_por_centro:
            lines = ["Tus centros de costo son:"]
            for center in center_names:
                assigned = fondos_por_centro.get(center)
                if assigned is None:
                    lines.append(f"- {center}: sin presupuesto asignado")
                else:
                    lines.append(f"- {center}: {self._format_clp(assigned)} CLP")
            return "\n".join(lines)

        return "Tus centros de costo son: " + ", ".join(center_names) + "."

    def build_case_budget_message(
        self,
        *,
        phone: str,
        case_id: str,
        expense_case: dict[str, Any],
    ) -> str:
        fondos_por_centro = self._normalize_fondos_por_centro(expense_case.get("fondos_por_centro"))
        fondos = parse_float(expense_case.get("fondos_entregados"))
        policy_limit = parse_float(expense_case.get("policy_limit", expense_case.get("budget")))
        budget = fondos or policy_limit

        lines: list[str] = []
        if budget:
            label = "Fondos entregados" if fondos else "Límite de referencia"
            lines.append(f"{label}: {self._format_clp(budget)} CLP")

        if fondos_por_centro:
            expenses = self.sheets_service.list_expenses_by_phone_case(phone=phone, case_id=case_id)
            spent_by_center: dict[str, float] = {}
            for expense in expenses:
                center = str(expense.get("cost_center", "") or "Sin clasificar").strip() or "Sin clasificar"
                spent = parse_float(expense.get("total_clp") or expense.get("total") or 0) or 0.0
                spent_by_center[center] = spent_by_center.get(center, 0.0) + spent

            center_names = sorted(
                {
                    *self._normalize_case_cost_centers(expense_case),
                    *fondos_por_centro.keys(),
                    *spent_by_center.keys(),
                },
                key=str.lower,
            )
            lines.append("Presupuesto por centro de costo:")
            for center in center_names:
                assigned = fondos_por_centro.get(center)
                spent = spent_by_center.get(center, 0.0)
                if assigned is None:
                    lines.append(
                        f"- {center}: sin presupuesto asignado; rendido {self._format_clp(spent)} CLP"
                    )
                else:
                    remaining = assigned - spent
                    lines.append(
                        f"- {center}: {self._format_clp(assigned)} CLP; "
                        f"rendido {self._format_clp(spent)} CLP; "
                        f"saldo {self._format_clp(remaining)} CLP"
                    )

        if lines:
            return "\n".join(lines)
        return "Tu rendición activa no tiene presupuesto o fondos configurados."

    def _classify_rendicion_question(self, question: str) -> str | None:
        normalized = " ".join(str(question or "").strip().lower().split())
        if not normalized:
            return None

        cost_center_signals = (
            "centro de costo",
            "centros de costo",
            "centro costo",
            "centros costo",
            "mis centros",
        )
        if any(signal in normalized for signal in cost_center_signals):
            return "cost_centers"

        last_signals = ("ultimo gasto", "último gasto", "ultima compra", "última compra", "ultima boleta", "última boleta")
        if any(signal in normalized for signal in last_signals):
            return "last_expense"

        budget_signals = (
            "cual es mi presupuesto",
            "cuál es mi presupuesto",
            "mi presupuesto",
            "presupuesto asignado",
            "presupuesto por centro",
            "fondos asignados",
            "fondos entregados",
            "cuanto presupuesto tengo",
            "cuánto presupuesto tengo",
        )
        if any(signal in normalized for signal in budget_signals):
            return "budget"

        balance_signals = (
            "cuanto presupuesto me queda",
            "cuánto presupuesto me queda",
            "cuanto me queda",
            "cuánto me queda",
            "saldo restante",
            "saldo me queda",
            "cuanto saldo",
            "cuánto saldo",
            "saldo tengo",
            "tengo de saldo",
            "tengo disponible",
            "presupuesto restante",
            "presupuesto disponible",
            "me queda de presupuesto",
            "queda en mi",
            "queda en la rendicion",
            "queda en la rendición",
        )
        if any(signal in normalized for signal in balance_signals):
            return "balance"

        summary_signals = (
            "dame el resumen",
            "dame resumen",
            "resumen",
            "estado de mi rendicion",
            "estado de mi rendición",
            "estado rendicion",
            "estado rendición",
            "mis gastos",
        )
        if any(signal in normalized for signal in summary_signals):
            return "summary"

        return None

    def infer_category_with_fallback(self, draft_expense: dict[str, Any]) -> str | None:
        llm_category = self.infer_category_with_llm(draft_expense)
        if llm_category:
            logger.info("Category classification source=llm category=%s", llm_category)
            return llm_category
        rule_category = self.infer_category(draft_expense)
        if rule_category:
            logger.info("Category classification source=rules category=%s", rule_category)
        else:
            logger.info("Category classification source=none")
        return rule_category

    def infer_category_with_llm(self, draft_expense: dict[str, Any]) -> str | None:
        if not self.llm_service:
            return None
        return self.llm_service.classify_expense_category(draft_expense)

    def infer_country_currency_with_llm(self, draft_expense: dict[str, Any]) -> dict[str, str]:
        if not self.llm_service:
            return {}
        return self.llm_service.infer_expense_country_currency(draft_expense)

    def infer_category(self, draft_expense: dict[str, Any]) -> str | None:
        merchant = str(draft_expense.get("merchant", "") or "").strip().lower()
        if not merchant:
            return None

        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(keyword in merchant for keyword in keywords):
                return category
        return None

    def _apply_chile_guardrails(self, draft_expense: dict[str, Any]) -> dict[str, Any]:
        ocr_text = str(draft_expense.get("ocr_text", "") or "")
        if not ocr_text:
            return draft_expense
        if not self._has_strong_chile_receipt_evidence(ocr_text):
            return draft_expense

        country_before = str(draft_expense.get("country", "") or "").strip()
        if country_before.lower() != "chile":
            draft_expense["country"] = "Chile"
            logger.info(
                "Expense country overridden by Chile guardrail previous=%r new=%r",
                country_before or None,
                draft_expense["country"],
            )

        currency_before = str(draft_expense.get("currency", "") or "").strip().upper()
        looks_clp_amount = self._has_clp_amount_format(ocr_text)

        if not currency_before:
            draft_expense["currency"] = "CLP"
            logger.info("Expense currency set by Chile guardrail currency=%r", draft_expense["currency"])
        elif (
            currency_before != "CLP"
            and not self._has_explicit_currency_marker(ocr_text, currency_before)
            and looks_clp_amount
        ):
            draft_expense["currency"] = "CLP"
            logger.info(
                "Expense currency overridden by Chile guardrail previous=%r new=%r",
                currency_before,
                draft_expense["currency"],
            )
        return draft_expense

    def _reconcile_country_currency(self, draft_expense: dict[str, Any]) -> dict[str, Any]:
        country = str(draft_expense.get("country", "") or "").strip().lower()
        currency = str(draft_expense.get("currency", "") or "").strip().upper()
        ocr_text = str(draft_expense.get("ocr_text", "") or "")

        if country != "chile":
            return draft_expense

        if not currency:
            draft_expense["currency"] = "CLP"
            logger.info("Expense currency set by country reconciliation country=%r currency=%r", "Chile", "CLP")
            return draft_expense

        if currency == "CLP":
            return draft_expense

        has_peso_marker = self._has_peso_marker(ocr_text)
        looks_clp_amount = self._has_clp_amount_format(ocr_text)
        if not self._has_explicit_currency_marker(ocr_text, currency) and (has_peso_marker or looks_clp_amount):
            draft_expense["currency"] = "CLP"
            logger.info(
                "Expense currency reconciled for Chile previous=%r new=%r",
                currency,
                draft_expense["currency"],
            )
        return draft_expense

    def _has_strong_chile_receipt_evidence(self, text: str) -> bool:
        upper = (text or "").upper()
        if not upper:
            return False

        hard_hits = 0
        if re.search(r"\bRUT\b", upper):
            hard_hits += 1
        if "SII.CL" in upper:
            hard_hits += 1
        if re.search(r"\b[\w.-]+\.CL\b", upper):
            hard_hits += 1

        soft_hits = 0
        for token in ("LAS CONDES", "SANTIAGO", "PARQUE ARAUCO", "AV. KENNEDY", "COMUNA"):
            if token in upper:
                soft_hits += 1

        return hard_hits >= 2 or (hard_hits >= 1 and soft_hits >= 1)

    def _infer_country_from_text(self, upper_text: str) -> str | None:
        if self._has_strong_chile_receipt_evidence(upper_text):
            return "Chile"
        if self._has_strong_peru_receipt_evidence(upper_text):
            return "Peru"
        if self._has_strong_country_evidence(upper_text, (r"\bRFC\b",), ("MEXICO", "MÉXICO", "CDMX")):
            return "Mexico"
        if self._has_strong_country_evidence(upper_text, (r"\bCUIT\b",), ("ARGENTINA", "BUENOS AIRES")):
            return "Argentina"
        if self._has_strong_country_evidence(upper_text, (r"\bNIT\b",), ("COLOMBIA", "BOGOTA", "BOGOTÁ")):
            return "Colombia"
        for country, tokens in (
            ("China", ("CHINA", "BEIJING", "SHANGHAI")),
            ("Spain", ("ESPAÑA", "SPAIN", "MADRID", "BARCELONA")),
            ("United States", ("UNITED STATES", "USA", "U.S.A.")),
            ("Brazil", ("BRASIL", "BRAZIL", "SAO PAULO", "SÃO PAULO")),
        ):
            if any(token in upper_text for token in tokens):
                return country
        return None

    def _has_strong_peru_receipt_evidence(self, upper_text: str) -> bool:
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

    def _has_strong_country_evidence(
        self,
        upper_text: str,
        hard_patterns: tuple[str, ...],
        soft_tokens: tuple[str, ...],
    ) -> bool:
        hard_hits = sum(1 for pattern in hard_patterns if re.search(pattern, upper_text))
        soft_hits = sum(1 for token in soft_tokens if token in upper_text)
        return (hard_hits >= 1 and soft_hits >= 1) or soft_hits >= 2

    def _infer_currency_from_text(self, text: str) -> str | None:
        upper = (text or "").upper()
        if re.search(r"\bMONEDA\s*:\s*PESO(?:S)?\b", upper):
            return "CLP"
        if self._has_strong_chile_receipt_evidence(upper):
            return "CLP"
        if self._has_explicit_pen_marker(text):
            return "PEN"
        if self._has_explicit_usd_marker(text):
            return "USD"
        if self._has_explicit_eur_marker(text):
            return "EUR"
        if self._has_explicit_cny_marker(text):
            return "CNY"
        if re.search(r"\bMXN\b", upper):
            return "MXN"
        if re.search(r"\bARS\b", upper):
            return "ARS"
        if re.search(r"\bBRL\b", upper):
            return "BRL"
        if re.search(r"\bCOP\b", upper):
            return "COP"
        if re.search(r"\bCLP\b", upper):
            return "CLP"
        return None

    def _infer_country_from_currency(self, currency: str, upper_text: str) -> str | None:
        if currency == "PEN" and self._has_strong_peru_receipt_evidence(upper_text):
            return "Peru"
        if currency == "CLP" and self._has_strong_chile_receipt_evidence(upper_text):
            return "Chile"
        return None

    def _has_explicit_usd_marker(self, text: str) -> bool:
        upper = (text or "").upper()
        return bool(re.search(r"\bUSD\b|US\$|DOLAR|DÓLAR", upper))

    def _has_explicit_pen_marker(self, text: str) -> bool:
        upper = (text or "").upper()
        return bool(re.search(r"\bPEN\b|S/|\bSOLES\b", upper))

    def _has_explicit_eur_marker(self, text: str) -> bool:
        upper = (text or "").upper()
        return bool(re.search(r"\bEUR\b|EURO", upper)) or "€" in (text or "")

    def _has_explicit_cny_marker(self, text: str) -> bool:
        upper = (text or "").upper()
        return bool(re.search(r"\bCNY\b|\bRMB\b|YUAN", upper))

    def _has_explicit_currency_marker(self, text: str, currency: str) -> bool:
        code = (currency or "").strip().upper()
        if code == "USD":
            return self._has_explicit_usd_marker(text)
        if code == "PEN":
            return self._has_explicit_pen_marker(text)
        if code == "EUR":
            return self._has_explicit_eur_marker(text)
        if code == "CNY":
            return self._has_explicit_cny_marker(text)
        if code == "CLP":
            return self._has_peso_marker(text) or bool(re.search(r"\bCLP\b", (text or "").upper()))
        return False

    def _has_clp_amount_format(self, text: str) -> bool:
        return bool(re.search(r"\$\s*\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?\b", text or ""))

    def _has_peso_marker(self, text: str) -> bool:
        return bool(re.search(r"\bMONEDA\s*:\s*PESO(?:S)?\b|\bPESO(?:S)?\b", (text or "").upper()))

    def _should_infer_merchant_with_llm(self, draft_expense: dict[str, Any]) -> bool:
        if not self.llm_service:
            return False
        ocr_text = str(draft_expense.get("ocr_text", "") or "").strip()
        return bool(ocr_text)

    def _should_infer_country_currency_with_llm(self, draft_expense: dict[str, Any]) -> bool:
        if not self.llm_service:
            return False
        ocr_text = str(draft_expense.get("ocr_text", "") or "").strip()
        country = str(draft_expense.get("country", "") or "").strip()
        currency = str(draft_expense.get("currency", "") or "").strip()
        return bool(ocr_text and (not country or not currency))

    def classify_document(self, draft_expense: dict[str, Any]) -> dict[str, Any]:
        """Classify document type using rule-based hints + LLM.

        Returns structured classification result with document_type,
        classification_confidence, and requires_user_confirmation flag.
        """
        ocr_doc_type = str(draft_expense.get("document_type", "") or "").strip().lower()

        # Rule-based classification from OCR keyword detection
        if ocr_doc_type in ("boleta_honorarios", "boleta de honorarios", "professional_fee_receipt"):
            result = {
                "document_type": "professional_fee_receipt",
                "classification_confidence": 0.9,
                "reasoning": f"OCR detected keyword: {ocr_doc_type}",
            }
        elif ocr_doc_type in ("factura",):
            result = {
                "document_type": "invoice",
                "classification_confidence": 0.85,
                "reasoning": f"OCR detected keyword: {ocr_doc_type}",
            }
        elif ocr_doc_type in ("boleta", "ticket"):
            result = {
                "document_type": "receipt",
                "classification_confidence": 0.85,
                "reasoning": f"OCR detected keyword: {ocr_doc_type}",
            }
        elif ocr_doc_type == "comprobante":
            # Generic — needs LLM refinement
            result = {
                "document_type": "unknown",
                "classification_confidence": 0.3,
                "reasoning": "OCR only detected generic 'comprobante'",
            }
        else:
            result = {
                "document_type": "unknown",
                "classification_confidence": 0.0,
                "reasoning": "No document type hint from OCR",
            }

        # Try LLM classification if not confident enough
        if result["classification_confidence"] < DOCUMENT_CLASSIFICATION_CONFIDENCE_THRESHOLD:
            llm_result = self._classify_document_with_llm(draft_expense)
            if llm_result and llm_result.get("classification_confidence", 0) > result["classification_confidence"]:
                result = llm_result

        result["requires_user_confirmation"] = (
            result["document_type"] == "unknown"
            or result["classification_confidence"] < DOCUMENT_CLASSIFICATION_CONFIDENCE_THRESHOLD
        )
        return result

    def _classify_document_with_llm(self, draft_expense: dict[str, Any]) -> dict[str, Any]:
        if not self.llm_service:
            return {}
        return self.llm_service.classify_document(draft_expense)

    def build_document_extraction_result(self, draft_expense: dict[str, Any]) -> dict[str, Any]:
        """Build the structured extraction result as specified in requirements."""
        doc_type = str(draft_expense.get("document_type", "") or "").strip()
        confidence = draft_expense.get("classification_confidence", 0.0)

        warnings: list[str] = []
        missing_required: list[str] = []

        # Check required fields
        required = REQUIRED_FIELDS_BY_DOCUMENT_TYPE.get(doc_type, REQUIRED_EXPENSE_FIELDS)
        for field in required:
            value = draft_expense.get(field)
            if value is None or str(value).strip() == "":
                missing_required.append(field)

        # Validation warnings
        if draft_expense.get("total") is None:
            warnings.append("No se detectó el monto total del documento.")
        if not draft_expense.get("date"):
            warnings.append("No se detectó la fecha del documento con confianza.")

        return {
            "document_type": doc_type or "unknown",
            "classification_confidence": confidence,
            "fields": {
                "merchant_name": draft_expense.get("merchant"),
                "issue_date": draft_expense.get("date"),
                "invoice_number": draft_expense.get("invoice_number"),
                "total_amount": draft_expense.get("total"),
                "currency": draft_expense.get("currency"),
                "country": draft_expense.get("country"),
                "tax_amount": draft_expense.get("tax_amount"),
                "issuer_tax_id": draft_expense.get("issuer_tax_id"),
                "receiver_tax_id": draft_expense.get("receiver_tax_id"),
                "category": draft_expense.get("category"),
                "gross_amount": draft_expense.get("gross_amount"),
                "withholding_rate": draft_expense.get("withholding_rate"),
                "withholding_amount": draft_expense.get("withholding_amount"),
                "net_amount": draft_expense.get("net_amount"),
                "receiver_name": draft_expense.get("receiver_name"),
                "service_description": draft_expense.get("service_description"),
            },
            "missing_required_fields": missing_required,
            "warnings": warnings,
            "requires_user_confirmation": draft_expense.get("requires_user_confirmation", False),
        }

    def find_missing_required_fields(self, draft_expense: dict[str, Any]) -> list[str]:
        missing: list[str] = []
        doc_type = str(draft_expense.get("document_type", "") or "").strip()
        required = REQUIRED_FIELDS_BY_DOCUMENT_TYPE.get(doc_type, REQUIRED_EXPENSE_FIELDS)
        for field in required:
            value = draft_expense.get(field)
            if value is None or str(value).strip() == "":
                missing.append(field)
        return missing

    def build_summary_message(
        self,
        draft_expense: dict[str, Any],
        *,
        include_text_actions: bool = True,
    ) -> str:
        doc_type = str(draft_expense.get("document_type", "") or "").strip()
        warnings = self._build_validation_warnings(draft_expense)

        if doc_type == "invoice":
            summary = self._build_invoice_summary(draft_expense)
        elif doc_type == "professional_fee_receipt":
            summary = self._build_professional_fee_receipt_summary(draft_expense)
        elif doc_type == "receipt":
            summary = self._build_receipt_summary(draft_expense)
        else:
            summary = self._build_generic_summary(draft_expense)

        if warnings:
            warning_text = "\n".join(f"⚠ {w}" for w in warnings)
            summary = f"{summary}\n\n{warning_text}"

        if not include_text_actions:
            return summary
        return (
            f"{summary}\n\n"
            "1. Confirmar\n"
            "2. Corregir\n"
            "3. Cancelar"
        )

    def _build_receipt_summary(self, draft_expense: dict[str, Any]) -> str:
        lines = ["Detecté este gasto a partir de una *boleta*:"]
        lines.append(f"Comercio: {draft_expense.get('merchant', '-')}")
        lines.append(f"Fecha: {draft_expense.get('date', '-')}")
        lines.append(f"Total: {draft_expense.get('total', '-')} {draft_expense.get('currency', '-')}")
        lines.append(f"Categoría: {draft_expense.get('category', '-')}")
        lines.append(f"País: {draft_expense.get('country', '-')}")
        if draft_expense.get("payment_method"):
            lines.append(f"Medio de pago: {draft_expense.get('payment_method')}")
        return "\n".join(lines)

    def _build_invoice_summary(self, draft_expense: dict[str, Any]) -> str:
        lines = ["Detecté este gasto a partir de una *factura*:"]
        lines.append(f"Proveedor: {draft_expense.get('merchant', '-')}")
        lines.append(f"Fecha: {draft_expense.get('date', '-')}")
        lines.append(f"Folio: {draft_expense.get('invoice_number', '-')}")
        lines.append(f"Total: {draft_expense.get('total', '-')} {draft_expense.get('currency', '-')}")
        lines.append(f"Categoría: {draft_expense.get('category', '-')}")
        lines.append(f"País: {draft_expense.get('country', '-')}")
        if draft_expense.get("issuer_tax_id"):
            lines.append(f"RUT/ID emisor: {draft_expense.get('issuer_tax_id')}")
        if draft_expense.get("receiver_tax_id"):
            lines.append(f"RUT/ID receptor: {draft_expense.get('receiver_tax_id')}")
        return "\n".join(lines)

    def _build_professional_fee_receipt_summary(self, draft_expense: dict[str, Any]) -> str:
        lines = ["Detecté este gasto a partir de una *boleta de honorarios*:"]
        lines.append(f"🏢 Emisor: {draft_expense.get('merchant', '-')}")
        lines.append(f"📅 Fecha: {draft_expense.get('date', '-')}")
        lines.append(f"🔢 Folio: {draft_expense.get('invoice_number', '-')}")
        if draft_expense.get("issuer_tax_id"):
            lines.append(f"🪪 RUT emisor: {self._format_tax_id(draft_expense.get('issuer_tax_id'))}")
        if draft_expense.get("receiver_tax_id"):
            lines.append(f"🪪 RUT receptor: {self._format_tax_id(draft_expense.get('receiver_tax_id'))}")
        liquid_amount = draft_expense.get("net_amount")
        if liquid_amount is None and draft_expense.get("gross_amount") is None:
            liquid_amount = draft_expense.get("total")
        lines.append(
            f"💵 Monto líquido: {self._format_summary_amount(liquid_amount)} "
            f"{draft_expense.get('currency', '-')}"
        )
        if draft_expense.get("gross_amount") is not None:
            lines.append(
                f"💰 Monto bruto: {self._format_summary_amount(draft_expense.get('gross_amount'))} "
                f"{draft_expense.get('currency', '-')}"
            )
        return "\n".join(lines)

    def _format_tax_id(self, value: Any) -> str:
        tax_id = str(value or "").strip()
        return re.sub(r"^\s*(?:RUT|RUC|ID)\s*:?\s*", "", tax_id, flags=re.IGNORECASE).strip() or "-"

    def _format_summary_amount(self, value: Any) -> str:
        amount = parse_float(value)
        if amount is None:
            return "-"
        if amount.is_integer():
            return str(int(amount))
        return f"{amount:.2f}".rstrip("0").rstrip(".")

    def _build_generic_summary(self, draft_expense: dict[str, Any]) -> str:
        doc_label = draft_expense.get("document_type", "-")
        lines = [f"Detecté este gasto ({doc_label}):"]
        lines.append(f"Comercio: {draft_expense.get('merchant', '-')}")
        lines.append(f"Fecha: {draft_expense.get('date', '-')}")
        lines.append(f"Total: {draft_expense.get('total', '-')} {draft_expense.get('currency', '-')}")
        lines.append(f"Categoría: {draft_expense.get('category', '-')}")
        lines.append(f"País: {draft_expense.get('country', '-')}")
        return "\n".join(lines)

    def _build_validation_warnings(self, draft_expense: dict[str, Any]) -> list[str]:
        warnings: list[str] = []
        doc_type = str(draft_expense.get("document_type", "") or "").strip()
        if draft_expense.get("total") is None:
            warnings.append("No se detectó el monto total.")
        if not draft_expense.get("date"):
            warnings.append("No se detectó la fecha con confianza.")
        if doc_type == "professional_fee_receipt":
            expected_rate = self._expected_professional_fee_withholding_rate(draft_expense)
            actual_rate = parse_float(draft_expense.get("withholding_rate"))
            if expected_rate is not None and actual_rate is not None and abs(actual_rate - expected_rate) > 0.1:
                warnings.append(
                    f"La retención detectada ({actual_rate}%) no coincide con la esperada para Chile ({expected_rate}%)."
                )
        return warnings

    def build_missing_fields_message(self, draft_expense: dict[str, Any]) -> str | None:
        """Build user-facing message about missing important fields."""
        warnings = self._build_validation_warnings(draft_expense)
        if not warnings:
            return None
        missing_names = []
        doc_type = str(draft_expense.get("document_type", "")).strip()
        if not draft_expense.get("invoice_number") and doc_type in ("invoice", "professional_fee_receipt"):
            missing_names.append("folio")
        if not draft_expense.get("date"):
            missing_names.append("fecha")
        if not draft_expense.get("total"):
            missing_names.append("total")
        if missing_names:
            fields_str = " y ".join(missing_names)
            return f"Pude detectar el documento, pero faltan algunos datos importantes: {fields_str}. ¿Quieres corregirlos o enviar otra imagen?"
        return None

    def _get_review_score_service(self) -> ReviewScoreService:
        return self.review_score_service or ReviewScoreService()

    def _compute_and_attach_review(
        self,
        expense_row: dict[str, Any],
        draft_expense: dict[str, Any],
        phone: str,
    ) -> dict[str, Any]:
        """Compute review score/breakdown and merge into expense_row."""
        scorer = self._get_review_score_service()
        case_id = str(expense_row.get("case_id", "") or "").strip()
        existing_expenses = (
            self.sheets_service.list_expenses_by_phone_case(phone, case_id) if case_id else []
        )
        review = scorer.compute_review(draft_expense, existing_expenses=existing_expenses)
        expense_row["review_score"] = review["review_score"]
        expense_row["review_status"] = review["review_status"]
        expense_row["review_breakdown"] = review["review_breakdown"]
        expense_row["review_flags"] = review["review_flags"]
        expense_row["primary_review_reason"] = review["primary_review_reason"]
        return expense_row

    def compute_draft_review(self, phone: str, draft_expense: dict[str, Any]) -> dict[str, Any]:
        draft_case_id = str(draft_expense.get("case_id", draft_expense.get("trip_id", "")) or "").strip()
        expense_case = (
            self.find_case_by_id_for_phone(phone, draft_case_id)
            if draft_case_id
            else self.get_active_case_for_phone(phone)
        )
        case_id = str((expense_case or {}).get("case_id", "") or "").strip()
        existing_expenses = (
            self.sheets_service.list_expenses_by_phone_case(phone, case_id) if case_id else []
        )
        return self._get_review_score_service().compute_review(
            draft_expense,
            existing_expenses=existing_expenses,
        )

    def save_confirmed_expense(self, phone: str, draft_expense: dict[str, Any]) -> dict[str, Any]:
        total = parse_float(draft_expense.get("total"))
        if total is None:
            raise ValueError("El total no es valido")

        draft_case_id = str(draft_expense.get("case_id", draft_expense.get("trip_id", "")) or "").strip()
        expense_case = (
            self.find_case_by_id_for_phone(phone, draft_case_id)
            if draft_case_id
            else self.get_active_case_for_phone(phone)
        )
        if not expense_case:
            return self.create_expense_for_review(
                phone=phone,
                draft_expense=draft_expense,
                review_reason="no_active_case",
            )

        currency = str(draft_expense.get("currency", "CLP")).upper()
        total_clp = convert_to_clp(total, currency)
        active_case_id = str(expense_case.get("case_id", "") or "").strip()

        expense_row = {
            "expense_id": make_id("EXP"),
            "phone": phone,
            "case_id": active_case_id,
            "trip_id": active_case_id,
            "merchant": draft_expense.get("merchant", ""),
            "date": draft_expense.get("date", ""),
            "currency": currency,
            "total": total,
            "total_clp": round(total_clp, 2),
            "category": draft_expense.get("category", ""),
            "cost_center": str(draft_expense.get("cost_center", "") or "").strip(),
            "country": draft_expense.get("country", ""),
            "shared": "FALSE",
            "status": ExpenseStatus.PENDING_APPROVAL,
            "processing_status": "confirmed",
            "case_lookup_status": "active_case_linked",
            "review_reason": "",
            "source_message_id": str(draft_expense.get("source_message_id", "") or "").strip(),
            "receipt_storage_provider": draft_expense.get("receipt_storage_provider", ""),
            "receipt_object_key": draft_expense.get("receipt_object_key", ""),
            "document_type": draft_expense.get("document_type", ""),
            "invoice_number": draft_expense.get("invoice_number", ""),
            "tax_amount": draft_expense.get("tax_amount", ""),
            "issuer_tax_id": draft_expense.get("issuer_tax_id", ""),
            "receiver_tax_id": draft_expense.get("receiver_tax_id", ""),
            "gross_amount": draft_expense.get("gross_amount", ""),
            "withholding_rate": draft_expense.get("withholding_rate", ""),
            "withholding_amount": draft_expense.get("withholding_amount", ""),
            "net_amount": draft_expense.get("net_amount", ""),
            "receiver_name": draft_expense.get("receiver_name", ""),
            "service_description": draft_expense.get("service_description", ""),
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        }
        expense_row = self._compute_and_attach_review(expense_row, draft_expense, phone)
        return self.sheets_service.create_expense(expense_row)

    def create_expense_for_review(
        self,
        *,
        phone: str,
        draft_expense: dict[str, Any],
        review_reason: str,
    ) -> dict[str, Any]:
        total = parse_float(draft_expense.get("total"))
        currency = str(draft_expense.get("currency", "CLP")).upper() or "CLP"
        total_clp = convert_to_clp(total, currency) if total is not None else ""
        now = utc_now_iso()
        draft_with_reason = dict(draft_expense)
        draft_with_reason["review_reason"] = review_reason
        expense_row = {
            "expense_id": make_id("EXP"),
            "phone": phone,
            "case_id": "",
            "trip_id": "",
            "merchant": draft_expense.get("merchant", ""),
            "date": draft_expense.get("date", ""),
            "currency": currency if str(draft_expense.get("currency", "") or "").strip() else "",
            "total": total if total is not None else draft_expense.get("total", ""),
            "total_clp": round(total_clp, 2) if isinstance(total_clp, (int, float)) else "",
            "category": draft_expense.get("category", ""),
            "cost_center": str(draft_expense.get("cost_center", "") or "").strip(),
            "country": draft_expense.get("country", ""),
            "shared": "FALSE",
            "status": ExpenseStatus.PENDING_REVIEW,
            "processing_status": "review_required",
            "case_lookup_status": "no_active_case",
            "review_reason": review_reason,
            "source_message_id": str(draft_expense.get("source_message_id", "") or "").strip(),
            "receipt_storage_provider": draft_expense.get("receipt_storage_provider", ""),
            "receipt_object_key": draft_expense.get("receipt_object_key", ""),
            "document_type": draft_expense.get("document_type", ""),
            "invoice_number": draft_expense.get("invoice_number", ""),
            "tax_amount": draft_expense.get("tax_amount", ""),
            "issuer_tax_id": draft_expense.get("issuer_tax_id", ""),
            "receiver_tax_id": draft_expense.get("receiver_tax_id", ""),
            "gross_amount": draft_expense.get("gross_amount", ""),
            "withholding_rate": draft_expense.get("withholding_rate", ""),
            "withholding_amount": draft_expense.get("withholding_amount", ""),
            "net_amount": draft_expense.get("net_amount", ""),
            "receiver_name": draft_expense.get("receiver_name", ""),
            "service_description": draft_expense.get("service_description", ""),
            "created_at": now,
            "updated_at": now,
        }
        expense_row = self._compute_and_attach_review(expense_row, draft_with_reason, phone)
        return self.sheets_service.create_expense(expense_row)

    def build_policy_progress_message(self, phone: str, case_id: str) -> str | None:
        status_message = self.build_policy_status_message(phone=phone, case_id=case_id)
        alert_message = self.build_policy_alert_message(phone=phone, case_id=case_id)
        if status_message and alert_message:
            return f"{status_message}\n\n{alert_message}"
        return status_message or alert_message

    def build_policy_status_message(self, phone: str, case_id: str) -> str | None:
        progress = self.get_policy_progress(phone=phone, case_id=case_id)
        if not progress:
            return None

        budget_clp = progress["policy_limit_clp"]
        fondos = progress.get("fondos_entregados", 0)
        spent_clp = progress["spent_clp"]
        remaining_clp = progress["remaining_clp"]
        spent_pct = progress["spent_pct"]

        is_fondos = fondos and fondos > 0
        label = "Fondos entregados" if is_fondos else "Límite de referencia"

        lines = [
            "Estado de tu rendición:",
            f"- {label}: {self._format_clp(budget_clp)} CLP",
            f"- Rendido: {self._format_clp(spent_clp)} CLP ({spent_pct:.1f}%)",
            f"- Saldo restante: {self._format_clp(remaining_clp)} CLP",
        ]
        return "\n".join(lines)

    def build_policy_alert_message(self, phone: str, case_id: str) -> str | None:
        progress = self.get_policy_progress(phone=phone, case_id=case_id)
        if not progress:
            return None
        alerts = progress["alerts"]
        if not alerts:
            return None
        return "\n".join(alerts)

    def build_budget_progress_message(self, phone: str, trip_id: str) -> str | None:
        return self.build_policy_progress_message(phone=phone, case_id=trip_id)

    def get_policy_progress(self, phone: str, case_id: str) -> dict[str, Any] | None:
        expense_case = self.sheets_service.get_expense_case_by_id(case_id)
        if not expense_case:
            return None

        fondos = parse_float(expense_case.get("fondos_entregados"))
        budget_clp = fondos or parse_float(expense_case.get("policy_limit", expense_case.get("budget")))
        if budget_clp is None or budget_clp <= 0:
            return None

        is_fondos_model = fondos is not None and fondos > 0

        expenses = self.sheets_service.list_expenses_by_phone_case(phone=phone, case_id=case_id)
        total_values = [parse_float(item.get("total_clp")) or 0.0 for item in expenses]
        spent_clp = round(sum(total_values), 2)

        current_ratio = spent_clp / budget_clp
        spent_pct = round(current_ratio * 100, 1)
        remaining_clp = round(budget_clp - spent_clp, 2)

        label = "fondos entregados" if is_fondos_model else "límite de referencia"

        alerts: list[str] = []
        if spent_clp > budget_clp:
            excess = spent_clp - budget_clp
            alerts.append(f"Excediste los {label} en {self._format_clp(excess)} CLP.")

        return {
            "policy_limit_clp": budget_clp,
            "fondos_entregados": fondos or 0,
            "spent_clp": spent_clp,
            "remaining_clp": remaining_clp,
            "spent_pct": spent_pct,
            "alerts": alerts,
        }

    def get_budget_progress(self, phone: str, trip_id: str) -> dict[str, Any] | None:
        progress = self.get_policy_progress(phone=phone, case_id=trip_id)
        if not progress:
            return None
        aliased = dict(progress)
        aliased["budget_clp"] = progress["policy_limit_clp"]
        return aliased

    def _format_clp(self, amount: float) -> str:
        return f"${amount:,.0f}".replace(",", ".")
