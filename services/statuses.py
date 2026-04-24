from __future__ import annotations

from typing import Any


class ExpenseStatus:
    """Persisted operational status for an expense/document.

    These values are already stored in Sheets and consumed by the current UI,
    so this module centralizes them without changing runtime behavior yet.
    """

    PENDING_APPROVAL = "pending_approval"
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    OBSERVED = "observed"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"


class ExpenseReviewStatus:
    """Review/prioritization status for an expense."""

    PENDING_REVIEW = "pending_review"
    READY_TO_APPROVE = "ready_to_approve"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"
    OBSERVED = "observed"
    APPROVED = "approved"
    REJECTED = "rejected"


class CaseStatus:
    """Operational case container status."""

    ACTIVE = "active"
    CLOSED = "closed"


class RendicionStatus:
    """Current persisted lifecycle status for the expense case."""

    OPEN = "open"
    PENDING_USER_CONFIRMATION = "pending_user_confirmation"
    PENDING_COMPANY_REVIEW = "pending_company_review"
    APPROVED = "approved"
    CLOSED = "closed"


class SettlementDirection:
    BALANCED = "balanced"
    COMPANY_OWES_EMPLOYEE = "company_owes_employee"
    EMPLOYEE_OWES_COMPANY = "employee_owes_company"


class SettlementStatus:
    PENDING = "settlement_pending"
    SETTLED = "settled"


EXPENSE_PENDING_STATUSES = frozenset(
    {
        ExpenseStatus.PENDING_APPROVAL,
        ExpenseStatus.PENDING_REVIEW,
    }
)

EXPENSE_RESOLVED_STATUSES = frozenset(
    {
        ExpenseStatus.APPROVED,
        ExpenseStatus.REJECTED,
    }
)

EXPENSE_REVIEW_BLOCKING_STATUSES = frozenset(
    {
        ExpenseStatus.PENDING_APPROVAL,
        ExpenseStatus.PENDING_REVIEW,
        ExpenseStatus.OBSERVED,
        ExpenseStatus.NEEDS_MANUAL_REVIEW,
    }
)

REVIEW_NEEDS_ATTENTION_STATUSES = frozenset(
    {
        ExpenseReviewStatus.NEEDS_MANUAL_REVIEW,
        ExpenseReviewStatus.PENDING_REVIEW,
    }
)

RENDICION_PENDING_REVIEW_STATUSES = frozenset(
    {
        RendicionStatus.PENDING_USER_CONFIRMATION,
    }
)

REVIEW_PRIORITY_ORDER: dict[str, int] = {
    ExpenseReviewStatus.NEEDS_MANUAL_REVIEW: 0,
    ExpenseReviewStatus.PENDING_REVIEW: 1,
    ExpenseReviewStatus.READY_TO_APPROVE: 2,
    ExpenseReviewStatus.OBSERVED: 3,
    ExpenseReviewStatus.APPROVED: 4,
    ExpenseReviewStatus.REJECTED: 5,
}

# Canonical mapping defined in rendicion-workflow.md. We are not persisting
# these values yet; this is a helper layer to bridge the current model.
CANONICAL_DOCUMENT_STATUS_BY_CURRENT: dict[str, str] = {
    ExpenseStatus.PENDING_APPROVAL: "pending_submission_review",
    ExpenseStatus.PENDING_REVIEW: "internal_manual_review",
    ExpenseStatus.APPROVED: "approved",
    ExpenseStatus.REJECTED: "rejected_final",
    ExpenseStatus.OBSERVED: "awaiting_employee_input",
    ExpenseStatus.NEEDS_MANUAL_REVIEW: "internal_manual_review",
}


def normalize_state(value: Any, default: str = "") -> str:
    normalized = str(value or "").strip().lower()
    return normalized or default


def normalize_expense_status(value: Any, default: str = "") -> str:
    return normalize_state(value, default=default)


def normalize_review_status(value: Any, *, expense_status: Any = None, default: str = "") -> str:
    review_status = normalize_state(value)
    if review_status:
        return review_status
    return normalize_expense_status(expense_status, default=default)


def normalize_rendicion_status(value: Any, default: str = RendicionStatus.OPEN) -> str:
    return normalize_state(value, default=default)


def is_resolved_expense_status(value: Any) -> bool:
    return normalize_expense_status(value) in EXPENSE_RESOLVED_STATUSES


def is_review_blocking_expense_status(value: Any) -> bool:
    return normalize_expense_status(value) in EXPENSE_REVIEW_BLOCKING_STATUSES


def to_canonical_document_status(value: Any) -> str:
    current = normalize_expense_status(value)
    return CANONICAL_DOCUMENT_STATUS_BY_CURRENT.get(current, current)


def resolve_canonical_document_status(*, expense_status: Any = None, review_status: Any = None) -> str:
    status = normalize_expense_status(expense_status)
    if status:
        return to_canonical_document_status(status)
    normalized_review = normalize_review_status(review_status)
    if normalized_review in {
        ExpenseReviewStatus.APPROVED,
        ExpenseReviewStatus.REJECTED,
        ExpenseReviewStatus.OBSERVED,
        ExpenseReviewStatus.NEEDS_MANUAL_REVIEW,
    }:
        return to_canonical_document_status(normalized_review)
    return normalized_review
