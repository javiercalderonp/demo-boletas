from __future__ import annotations

import re
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")


def validate_strong_password(value: str) -> str:
    password = str(value or "")
    if len(password) < 8:
        raise ValueError("La contraseña debe tener al menos 8 caracteres")
    if not re.search(r"[A-Z]", password):
        raise ValueError("La contraseña debe incluir al menos una mayúscula")
    if not re.search(r"\d", password):
        raise ValueError("La contraseña debe incluir al menos un número")
    if not re.search(r"[^A-Za-z0-9]", password):
        raise ValueError("La contraseña debe incluir al menos un carácter especial")
    return password


def validate_e164_phone(value: str) -> str:
    phone = str(value or "").strip()
    if not _E164_RE.fullmatch(phone):
        raise ValueError("El teléfono debe estar en formato E.164, por ejemplo +56912345678")
    return phone


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class SetupPasswordRequest(BaseModel):
    email: str


class SetupPasswordPayload(BaseModel):
    email: str
    name: str = ""
    password: str = Field(min_length=8)

    @field_validator("password")
    @classmethod
    def password_is_strong(cls, value: str) -> str:
        return validate_strong_password(value)


class BackofficeUserPayload(BaseModel):
    name: str = ""
    email: str
    role: str = "company_admin"
    scope_type: str = "company"
    company_ids: list[str] = Field(default_factory=list)
    company_id: str = ""
    active: bool = True


class EmployeePayload(BaseModel):
    phone: str
    first_name: str = ""
    last_name: str = ""
    name: str = ""
    rut: str = ""
    email: str = ""
    company_id: str = ""
    bank_name: str = ""
    account_type: str = ""
    account_number: str = ""
    account_holder: str = ""
    account_holder_rut: str = ""
    active: bool = True
    last_activity_at: str = ""

    @field_validator("phone")
    @classmethod
    def phone_is_e164(cls, value: str) -> str:
        return validate_e164_phone(value)


class CasePayload(BaseModel):
    case_id: Optional[str] = None
    context_label: str = ""
    cost_centers: list[str] = Field(default_factory=list)
    company_id: str = ""
    employee_phone: str
    closure_method: str = "docusign"
    daily_reminders_enabled: bool = True
    status: str = "active"
    fondos_entregados: Optional[Union[float, str]] = None
    fondos_por_centro: Optional[dict[str, float]] = None
    rendicion_status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    notes: str = ""

    @field_validator("employee_phone")
    @classmethod
    def employee_phone_is_e164(cls, value: str) -> str:
        return validate_e164_phone(value)


class ExpensePayload(BaseModel):
    merchant: Optional[str] = None
    date: Optional[str] = None
    currency: Optional[str] = None
    total: Optional[Union[float, str]] = None
    total_clp: Optional[Union[float, str]] = None
    category: Optional[str] = None
    cost_center: Optional[str] = None
    country: Optional[str] = None
    shared: Optional[Union[bool, str]] = None
    status: Optional[str] = None
    image_url: Optional[str] = None
    document_url: Optional[str] = None
    updated_at: Optional[str] = None


class ConversationPayload(BaseModel):
    case_id: Optional[str] = None
    state: Optional[str] = None
    current_step: Optional[str] = None
    context_json: Optional[dict[str, Any]] = None
    updated_at: Optional[str] = None


class AccountingExportPayload(BaseModel):
    company_id: str = Field(min_length=1)
    year: int = Field(ge=2000, le=2100)
    month: int = Field(ge=1, le=12)
    cost_center: str = ""
    case_status: str = ""
    expense_status: str = ""
    date_from: str = ""
    date_to: str = ""
    include_csv: bool = True


class PortaExportPayload(BaseModel):
    company_id: str = Field(min_length=1)
    scope: Literal["case", "month", "range", "company"]
    case_id: str = ""
    year: Optional[int] = Field(default=None, ge=2000, le=2100)
    month: Optional[int] = Field(default=None, ge=1, le=12)
    date_from: str = ""
    date_to: str = ""
    date_source: Literal["document_date", "case_closed_at"] = "document_date"

    @model_validator(mode="after")
    def validate_scope_fields(self):
        if self.scope == "case" and not self.case_id.strip():
            raise ValueError("Debes indicar un caso")
        if self.scope == "month" and (self.year is None or self.month is None):
            raise ValueError("Debes indicar año y mes")
        if self.scope == "range" and (not self.date_from or not self.date_to):
            raise ValueError("Debes indicar las fechas desde y hasta")
        return self


class DashboardResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class StatusActionPayload(BaseModel):
    action: Literal[
        "approve", "reject", "observe", "manual_review", "close", "reopen", "deactivate", "activate", "resolve",
        "request_user_confirmation", "resolve_settlement", "close_rendicion",
        "approve_settlement_proof", "reject_settlement_proof",
    ]
    reason: Optional[str] = Field(default=None, max_length=500)
    force: bool = False


class SendMessagePayload(BaseModel):
    message: str = Field(min_length=1, max_length=4096)


class SendTemplatePayload(BaseModel):
    template_name: str = Field(default="hello_world", min_length=1, max_length=512)
    language_code: str = Field(default="en_US", min_length=2, max_length=16)
    body_parameters: list[str] = Field(default_factory=list)


class CaseChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class CaseChatPayload(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[CaseChatMessage] = Field(default_factory=list)
