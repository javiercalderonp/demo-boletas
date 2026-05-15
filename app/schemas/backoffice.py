from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


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


class CasePayload(BaseModel):
    case_id: Optional[str] = None
    context_label: str = ""
    cost_centers: list[str] = Field(default_factory=list)
    company_id: str = ""
    employee_phone: str
    closure_method: str = "docusign"
    status: str = "active"
    fondos_entregados: Optional[Union[float, str]] = None
    fondos_por_centro: Optional[dict[str, float]] = None
    rendicion_status: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    notes: str = ""


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


class DashboardResponse(BaseModel):
    model_config = ConfigDict(extra="allow")


class StatusActionPayload(BaseModel):
    action: Literal[
        "approve", "reject", "close", "reopen", "deactivate", "activate", "resolve",
        "request_user_confirmation", "resolve_settlement", "close_rendicion",
    ]
    reason: Optional[str] = Field(default=None, max_length=500)


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
