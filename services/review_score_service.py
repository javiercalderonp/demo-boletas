"""Review score calculation for expenses.

Computes a confidence/risk score (0-100) and breakdown to help
backoffice operators prioritize which expenses need manual review.

Score interpretation:
  80-100  high confidence  -> ready_to_approve
  50-79   medium           -> pending_review
  0-49    low              -> needs_manual_review

The formula is intentionally modular: each dimension returns 0-100 and
the final score is a weighted average.  Weights live in SCORE_WEIGHTS so
they can be tuned without touching the logic.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weights for the composite score (must sum to 1.0)
# ---------------------------------------------------------------------------
SCORE_WEIGHTS: dict[str, float] = {
    "document_quality": 0.15,
    "extraction_quality": 0.20,
    "field_completeness": 0.25,
    "document_type_confidence": 0.10,
    "policy_risk": 0.15,
    "duplicate_risk": 0.15,
}

# ---------------------------------------------------------------------------
# Thresholds that map a composite score to a review status
# ---------------------------------------------------------------------------
STATUS_THRESHOLDS = {
    "ready_to_approve": 80,
    "pending_review": 50,
    # below 50 -> needs_manual_review
}

# Fields that every expense should have
_CORE_FIELDS = ("merchant", "date", "total", "currency", "category", "country")

# Extra fields expected for invoices
_INVOICE_EXTRA_FIELDS = ("invoice_number",)
_PROFESSIONAL_FEE_EXTRA_FIELDS = ("invoice_number", "issuer_tax_id")

# Maximum amount (original currency) before policy flag
_HIGH_AMOUNT_THRESHOLD_CLP = 500_000
_HIGH_AMOUNT_THRESHOLD_OTHER = 1_000


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class ReviewScoreService:
    """Stateless service — receives a draft_expense dict and all related
    expenses for the same phone/case and returns review metadata."""

    def compute_review(
        self,
        draft_expense: dict[str, Any],
        *,
        existing_expenses: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Return the full review payload to be persisted alongside the expense."""

        breakdown = self._compute_breakdown(draft_expense, existing_expenses or [])
        score = self._weighted_score(breakdown)
        flags = self._collect_flags(draft_expense, breakdown, existing_expenses or [])
        review_status = self._determine_status(score, flags)
        primary_reason = flags[0] if flags else ""

        return {
            "review_score": round(score),
            "review_status": review_status,
            "review_breakdown": breakdown,
            "review_flags": flags,
            "primary_review_reason": primary_reason,
        }

    # ------------------------------------------------------------------
    # Breakdown dimensions (each returns 0–100)
    # ------------------------------------------------------------------

    def _compute_breakdown(
        self,
        draft: dict[str, Any],
        existing: list[dict[str, Any]],
    ) -> dict[str, int]:
        return {
            "document_quality": self._score_document_quality(draft),
            "extraction_quality": self._score_extraction_quality(draft),
            "field_completeness": self._score_field_completeness(draft),
            "document_type_confidence": self._score_document_type_confidence(draft),
            "policy_risk": self._score_policy_risk(draft),
            "duplicate_risk": self._score_duplicate_risk(draft, existing),
        }

    def _score_document_quality(self, draft: dict[str, Any]) -> int:
        """How good is the source document itself?"""
        score = 50  # baseline
        ocr_text = str(draft.get("ocr_text", "") or "")
        if len(ocr_text) > 200:
            score += 20
        elif len(ocr_text) > 50:
            score += 10
        # Presence of structured markers
        upper = ocr_text.upper()
        markers = (r"\bTOTAL\b", r"\bFECHA\b", r"\bRUT\b", r"\bRUC\b", r"\bIVA\b")
        hits = sum(1 for m in markers if re.search(m, upper))
        score += min(hits * 8, 30)
        if draft.get("is_document") is False:
            score = 10
        return _clamp(score)

    def _score_extraction_quality(self, draft: dict[str, Any]) -> int:
        """Were the key fields extracted with reasonable values?"""
        score = 100
        total = draft.get("total")
        if total is None:
            score -= 35
        elif not isinstance(total, (int, float)):
            score -= 20
        if not draft.get("merchant"):
            score -= 20
        if not draft.get("date"):
            score -= 20
        if not draft.get("currency"):
            score -= 15
        # Suspiciously round amount
        if isinstance(total, (int, float)) and total > 0 and total == int(total) and total >= 1000:
            score -= 5
        return _clamp(score)

    def _score_field_completeness(self, draft: dict[str, Any]) -> int:
        """Fraction of expected fields that are present."""
        doc_type = str(draft.get("document_type", "") or "").strip()
        fields = list(_CORE_FIELDS)
        if doc_type == "invoice":
            fields.extend(_INVOICE_EXTRA_FIELDS)
        elif doc_type == "professional_fee_receipt":
            fields.extend(_PROFESSIONAL_FEE_EXTRA_FIELDS)
        present = sum(
            1 for f in fields if draft.get(f) is not None and str(draft.get(f, "")).strip()
        )
        return _clamp(int(present / len(fields) * 100))

    def _score_document_type_confidence(self, draft: dict[str, Any]) -> int:
        """Was the document type classified with confidence?"""
        confidence = draft.get("classification_confidence")
        if confidence is None:
            # Fallback: check document_type string
            doc_type = str(draft.get("document_type", "") or "").strip()
            if doc_type in ("receipt", "invoice", "professional_fee_receipt"):
                return 70
            if doc_type in ("boleta", "factura", "boleta_honorarios", "ticket", "comprobante"):
                return 60
            return 20
        try:
            return _clamp(int(float(confidence) * 100))
        except (TypeError, ValueError):
            return 20

    def _score_policy_risk(self, draft: dict[str, Any]) -> int:
        """Higher score = lower risk (inverted so the weighted avg works).
        Penalties for policy concerns like high amounts or missing case."""
        score = 100
        total = draft.get("total")
        currency = str(draft.get("currency", "") or "").upper()

        if isinstance(total, (int, float)):
            threshold = (
                _HIGH_AMOUNT_THRESHOLD_CLP if currency == "CLP" else _HIGH_AMOUNT_THRESHOLD_OTHER
            )
            if total > threshold:
                score -= 30
            elif total > threshold * 0.7:
                score -= 10

        case_id = str(draft.get("case_id", draft.get("trip_id", "")) or "").strip()
        if not case_id:
            score -= 25

        review_reason = str(draft.get("review_reason", "") or "").strip()
        if review_reason:
            score -= 15

        return _clamp(score)

    def _score_duplicate_risk(
        self,
        draft: dict[str, Any],
        existing: list[dict[str, Any]],
    ) -> int:
        """Higher = less likely duplicate.  100 = no duplicates found."""
        if not existing:
            return 100

        draft_total = draft.get("total")
        draft_date = str(draft.get("date", "") or "").strip()
        draft_merchant = str(draft.get("merchant", "") or "").strip().lower()

        for exp in existing:
            same_total = exp.get("total") == draft_total and draft_total is not None
            same_date = (
                str(exp.get("date", "") or "").strip() == draft_date and draft_date
            )
            same_merchant = (
                str(exp.get("merchant", "") or "").strip().lower() == draft_merchant
                and draft_merchant
            )
            # Exact match on all three is very suspicious
            if same_total and same_date and same_merchant:
                return 10
            # Two of three
            if (same_total and same_date) or (same_total and same_merchant):
                return 35
            if same_date and same_merchant:
                return 50
        return 100

    # ------------------------------------------------------------------
    # Flag collection
    # ------------------------------------------------------------------

    def _collect_flags(
        self,
        draft: dict[str, Any],
        breakdown: dict[str, int],
        existing: list[dict[str, Any]],
    ) -> list[str]:
        flags: list[str] = []

        if breakdown["duplicate_risk"] <= 35:
            flags.append("Posible duplicado")
        elif breakdown["duplicate_risk"] <= 50:
            flags.append("Posible duplicado (parcial)")

        if not draft.get("total"):
            flags.append("Monto total faltante")
        if not draft.get("date"):
            flags.append("Fecha no detectada")
        if not draft.get("merchant"):
            flags.append("Comercio no detectado")

        doc_type = str(draft.get("document_type", "") or "").strip()
        if doc_type in ("unknown", ""):
            flags.append("Tipo de documento desconocido")
        if doc_type == "invoice" and not draft.get("invoice_number"):
            flags.append("Folio de factura faltante")
        if doc_type == "professional_fee_receipt":
            if not draft.get("invoice_number"):
                flags.append("Folio de boleta de honorarios faltante")
            if not draft.get("issuer_tax_id"):
                flags.append("RUT emisor faltante")
            if not draft.get("withholding_amount"):
                flags.append("Retención no detectada")

        if breakdown["document_type_confidence"] < 50:
            flags.append("Baja confianza en clasificación")

        if breakdown["extraction_quality"] < 50:
            flags.append("Baja calidad de extracción")

        total = draft.get("total")
        currency = str(draft.get("currency", "") or "").upper()
        if isinstance(total, (int, float)):
            threshold = (
                _HIGH_AMOUNT_THRESHOLD_CLP if currency == "CLP" else _HIGH_AMOUNT_THRESHOLD_OTHER
            )
            if total > threshold:
                flags.append("Monto elevado")

        case_id = str(draft.get("case_id", draft.get("trip_id", "")) or "").strip()
        if not case_id:
            flags.append("Sin caso activo asociado")

        review_reason = str(draft.get("review_reason", "") or "").strip()
        if review_reason and review_reason != "no_active_case":
            flags.append(f"Motivo: {review_reason}")

        return flags

    # ------------------------------------------------------------------
    # Status assignment
    # ------------------------------------------------------------------

    def _determine_status(self, score: float, flags: list[str]) -> str:
        # Critical flags force manual review regardless of score
        critical_flags = {"Posible duplicado", "Monto total faltante", "Sin caso activo asociado"}
        if any(f in critical_flags for f in flags):
            return "needs_manual_review"

        if score >= STATUS_THRESHOLDS["ready_to_approve"]:
            return "ready_to_approve"
        if score >= STATUS_THRESHOLDS["pending_review"]:
            return "pending_review"
        return "needs_manual_review"

    # ------------------------------------------------------------------
    # Weighted composite
    # ------------------------------------------------------------------

    def _weighted_score(self, breakdown: dict[str, int]) -> float:
        total = 0.0
        for dimension, weight in SCORE_WEIGHTS.items():
            total += breakdown.get(dimension, 50) * weight
        return total


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))
