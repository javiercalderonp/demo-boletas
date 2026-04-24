#!/usr/bin/env python3
"""Siembra datos demo realistas en Google Sheets para el MVP de rendiciones.

Pobla:
  - 3 empresas (ripley, acme, globex)
  - 10 empleados con datos bancarios y de contacto completos
  - 1 usuario backoffice admin
  - 5 casos de rendición (ExpenseCases) en estados distintos del ciclo de vida:
      1. open                         → WAIT_RECEIPT    (carga en curso)
      2. pending_company_review       → DONE            (revisión interna)
      3. pending_user_confirmation    → WAIT_SUBMISSION_CLOSURE_CONFIRMATION
      4. approved                     → DONE            (firmado, pendiente liquidación)
      5. closed                       → DONE            (liquidación resuelta)
  - Gastos con mezcla de status (pending_approval, pending_review, approved,
    rejected, observed, needs_manual_review) y review scores.
  - Conversations una por caso activo.
  - ExpenseCaseDocuments con signature_status distintos para los casos que
    pasaron por cierre documental.

Uso:
  .venv/bin/python scripts/seed_demo_data.py --credentials ./viaticos-*.json \
      --spreadsheet-id <SPREADSHEET_ID> --confirm

Por defecto hace dry-run (muestra lo que escribiría). Para escribir requiere
--confirm explícito. Para borrar filas previas manteniendo headers usar
--clear-data.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import gspread
from google.oauth2.service_account import Credentials


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Headers completos, incluyendo las columnas de review score que el backoffice
# consume pero que la hoja base no declaraba.
EXPENSES_HEADERS = [
    "expense_id",
    "phone",
    "case_id",
    "trip_id",
    "merchant",
    "date",
    "currency",
    "total",
    "total_clp",
    "category",
    "country",
    "shared",
    "status",
    "processing_status",
    "case_lookup_status",
    "review_reason",
    "review_score",
    "review_status",
    "review_breakdown",
    "review_flags",
    "primary_review_reason",
    "source_message_id",
    "receipt_storage_provider",
    "receipt_object_key",
    "image_url",
    "document_url",
    "created_at",
    "updated_at",
]

SHEET_HEADERS: dict[str, list[str]] = {
    "empresas": [
        "company_id",
        "name",
        "rut",
        "bank_name",
        "account_type",
        "account_number",
        "account_holder",
        "account_holder_rut",
        "finance_email",
        "active",
    ],
    "Employees": [
        "phone",
        "first_name",
        "last_name",
        "name",
        "rut",
        "email",
        "company_id",
        "bank_name",
        "account_type",
        "account_number",
        "account_holder",
        "account_holder_rut",
        "active",
        "last_activity_at",
        "created_at",
        "updated_at",
    ],
    "BackofficeUsers": [
        "id",
        "name",
        "email",
        "password_hash",
        "role",
        "active",
        "created_at",
        "updated_at",
    ],
    "ExpenseCases": [
        "case_id",
        "phone",
        "employee_phone",
        "company_id",
        "context_label",
        "closure_method",
        "destination",
        "country",
        "opened_at",
        "due_date",
        "start_date",
        "end_date",
        "policy_limit",
        "budget",
        "status",
        "closure_status",
        "closure_prompted_at",
        "closure_deadline_at",
        "closure_response",
        "closure_responded_at",
        "closed_at",
        "closure_reason",
        "created_at",
        "updated_at",
        "notes",
        "fondos_entregados",
        "rendicion_status",
        "user_confirmed_at",
        "user_confirmation_status",
        "settlement_direction",
        "settlement_status",
        "settlement_amount_clp",
        "settlement_net_clp",
        "settlement_calculated_at",
        "settlement_resolved_at",
    ],
    "Expenses": EXPENSES_HEADERS,
    "Conversations": ["phone", "case_id", "state", "current_step", "context_json", "updated_at"],
    "ExpenseCaseDocuments": [
        "document_id",
        "phone",
        "case_id",
        "trip_id",
        "storage_provider",
        "object_key",
        "expense_count",
        "total_clp",
        "status",
        "created_at",
        "updated_at",
        "signature_provider",
        "signature_status",
        "docusign_envelope_id",
        "signature_url",
        "signature_sent_at",
        "signature_completed_at",
        "signature_declined_at",
        "signature_expired_at",
        "signed_storage_provider",
        "signed_object_key",
        "signature_error",
    ],
}


ADMIN_EMAIL = "admin@example.com"
# Hash correspondiente a password "admin123" usando pbkdf2_sha256 del proyecto.
ADMIN_PASSWORD_HASH = (
    "pbkdf2_sha256$demo_admin_salt$c50d61b32ad63e371fd7eb113494b6618957faccba1402364269262edcef4889"
)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)


# ---------- datos ----------


def build_companies() -> list[list[Any]]:
    return [
        ["ripley", "Ripley Retail Chile SpA", "76.123.456-7", "Banco de Chile", "Cuenta Corriente", "0012345678", "Ripley Retail Chile SpA", "76.123.456-7", "tesoreria@ripley-demo.cl", "TRUE"],
        ["acme", "Acme Servicios SpA", "77.234.567-8", "Banco Santander", "Cuenta Vista", "9876543210", "Acme Servicios SpA", "77.234.567-8", "pagos@acme-demo.cl", "TRUE"],
        ["globex", "Globex Chile Ltda.", "78.345.678-9", "BCI", "Cuenta Corriente", "1122334455", "Globex Chile Ltda.", "78.345.678-9", "finanzas@globex-demo.cl", "TRUE"],
    ]


EMPLOYEES_SPEC = [
    # (first, last, phone, rut, email, company, bank, acct_type, acct_num)
    ("Javier", "Calderon", "+56974340422", "12.345.678-9", "javier.calderon@ripley-demo.cl", "ripley", "Banco de Chile", "Cuenta Corriente", "100000001"),
    ("Camila", "Rojas", "+56961230001", "11.111.111-1", "camila.rojas@ripley-demo.cl", "ripley", "Banco Santander", "Cuenta Vista", "100000002"),
    ("Martin", "Poblete", "+56961230002", "12.222.222-2", "martin.poblete@ripley-demo.cl", "ripley", "BCI", "Cuenta Corriente", "100000003"),
    ("Valentina", "Soto", "+56961230003", "13.333.333-3", "valentina.soto@acme-demo.cl", "acme", "BancoEstado", "Cuenta Ahorro", "100000004"),
    ("Tomas", "Fernandez", "+56961230004", "14.444.444-4", "tomas.fernandez@acme-demo.cl", "acme", "Banco de Chile", "Cuenta Corriente", "100000005"),
    ("Fernanda", "Muñoz", "+56961230005", "15.555.555-5", "fernanda.munoz@acme-demo.cl", "acme", "Itaú", "Cuenta Vista", "100000006"),
    ("Diego", "Silva", "+56961230006", "16.666.666-6", "diego.silva@globex-demo.cl", "globex", "Scotiabank", "Cuenta Corriente", "100000007"),
    ("Antonia", "Perez", "+56961230007", "17.777.777-7", "antonia.perez@globex-demo.cl", "globex", "Banco Falabella", "Cuenta Vista", "100000008"),
    ("Benjamin", "Contreras", "+56961230008", "18.888.888-8", "benjamin.contreras@globex-demo.cl", "globex", "Banco Santander", "Cuenta Corriente", "100000009"),
    ("Isidora", "Araya", "+56961230009", "19.999.999-9", "isidora.araya@ripley-demo.cl", "ripley", "BancoEstado", "Cuenta Vista", "100000010"),
]


def build_employees(now_iso: str) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for first, last, phone, rut, email, company, bank, acct_type, acct_num in EMPLOYEES_SPEC:
        rows.append(
            [
                phone,
                first,
                last,
                f"{first} {last}",
                rut,
                email,
                company,
                bank,
                acct_type,
                acct_num,
                f"{first} {last}",
                rut,
                "TRUE",
                now_iso,
                now_iso,
                now_iso,
            ]
        )
    return rows


def build_backoffice_users(now_iso: str) -> list[list[Any]]:
    return [
        [
            "usr-demo-admin",
            "Demo Admin",
            ADMIN_EMAIL,
            ADMIN_PASSWORD_HASH,
            "admin",
            "TRUE",
            now_iso,
            now_iso,
        ]
    ]


@dataclass
class CaseSpec:
    case_id: str
    employee_idx: int  # índice 0-based en EMPLOYEES_SPEC
    context_label: str
    destination: str
    country: str
    fondos_entregados: int
    rendicion_status: str  # open | pending_company_review | pending_user_confirmation | approved | closed
    case_status: str  # active | closed
    closure_method: str  # docusign | simple
    settlement_direction: str  # '' | balanced | company_owes_employee | employee_owes_company
    settlement_status: str  # '' | settlement_pending | settled
    conversation_state: str
    opened_days_ago: int
    expenses: list[dict[str, Any]]
    document_signature_status: str = ""  # '' | sent | completed


CASES: list[CaseSpec] = [
    CaseSpec(
        case_id="CASE-001",
        employee_idx=0,  # Javier
        context_label="Viaje comercial Santiago - Concepción",
        destination="Concepción",
        country="Chile",
        fondos_entregados=500000,
        rendicion_status="open",
        case_status="active",
        closure_method="docusign",
        settlement_direction="",
        settlement_status="",
        conversation_state="WAIT_RECEIPT",
        opened_days_ago=2,
        expenses=[
            {
                "merchant": "Starbucks",
                "category": "Meals",
                "total": 9800,
                "status": "pending_approval",
                "review_status": "pending_review",
                "review_score": 72,
                "flags": [],
                "days_ago": 1,
            },
            {
                "merchant": "Shell",
                "category": "Transport",
                "total": 45000,
                "status": "pending_approval",
                "review_status": "pending_review",
                "review_score": 78,
                "flags": [],
                "days_ago": 1,
            },
        ],
    ),
    CaseSpec(
        case_id="CASE-002",
        employee_idx=1,  # Camila
        context_label="Viaje Puerto Montt - Conferencia retail",
        destination="Puerto Montt",
        country="Chile",
        fondos_entregados=800000,
        rendicion_status="pending_company_review",
        case_status="active",
        closure_method="docusign",
        settlement_direction="",
        settlement_status="",
        conversation_state="DONE",
        opened_days_ago=8,
        expenses=[
            {
                "merchant": "Hotel Cumbres Puerto Varas",
                "category": "Lodging",
                "total": 285000,
                "status": "approved",
                "review_status": "approved",
                "review_score": 92,
                "flags": [],
                "days_ago": 7,
            },
            {
                "merchant": "LATAM Airlines",
                "category": "Transport",
                "total": 178000,
                "status": "approved",
                "review_status": "approved",
                "review_score": 89,
                "flags": [],
                "days_ago": 7,
            },
            {
                "merchant": "La Marmita Restaurante",
                "category": "Meals",
                "total": 38500,
                "status": "pending_review",
                "review_status": "pending_review",
                "review_score": 58,
                "flags": ["date_out_of_range"],
                "days_ago": 5,
            },
            {
                "merchant": "Uber",
                "category": "Transport",
                "total": 12400,
                "status": "observed",
                "review_status": "observed",
                "review_score": 48,
                "flags": ["missing_receipt_image"],
                "days_ago": 6,
            },
            {
                "merchant": "Supermercado Jumbo",
                "category": "Other",
                "total": 22300,
                "status": "needs_manual_review",
                "review_status": "needs_manual_review",
                "review_score": 35,
                "flags": ["category_mismatch", "low_ocr_quality"],
                "days_ago": 5,
            },
        ],
    ),
    CaseSpec(
        case_id="CASE-003",
        employee_idx=2,  # Martin
        context_label="Capacitación técnica Lima",
        destination="Lima",
        country="Peru",
        fondos_entregados=1200000,
        rendicion_status="pending_user_confirmation",
        case_status="active",
        closure_method="docusign",
        settlement_direction="",
        settlement_status="",
        conversation_state="WAIT_SUBMISSION_CLOSURE_CONFIRMATION",
        opened_days_ago=14,
        document_signature_status="sent",
        expenses=[
            {
                "merchant": "Hotel Casa Andina Miraflores",
                "category": "Lodging",
                "total": 1850,
                "currency": "PEN",
                "country": "Peru",
                "status": "approved",
                "review_status": "approved",
                "review_score": 94,
                "flags": [],
                "days_ago": 12,
            },
            {
                "merchant": "LATAM Airlines",
                "category": "Transport",
                "total": 420000,
                "status": "approved",
                "review_status": "approved",
                "review_score": 91,
                "flags": [],
                "days_ago": 13,
            },
            {
                "merchant": "Central Restaurante",
                "category": "Meals",
                "total": 320,
                "currency": "PEN",
                "country": "Peru",
                "status": "approved",
                "review_status": "approved",
                "review_score": 88,
                "flags": [],
                "days_ago": 11,
            },
            {
                "merchant": "Taxi Satelital",
                "category": "Transport",
                "total": 85,
                "currency": "PEN",
                "country": "Peru",
                "status": "approved",
                "review_status": "approved",
                "review_score": 82,
                "flags": [],
                "days_ago": 11,
            },
            {
                "merchant": "Souvenirs Andinos",
                "category": "Other",
                "total": 45,
                "currency": "PEN",
                "country": "Peru",
                "status": "rejected",
                "review_status": "rejected",
                "review_score": 20,
                "flags": ["non_business_expense"],
                "days_ago": 10,
            },
        ],
    ),
    CaseSpec(
        case_id="CASE-004",
        employee_idx=3,  # Valentina
        context_label="Reunión estratégica Valparaíso",
        destination="Valparaíso",
        country="Chile",
        fondos_entregados=350000,
        rendicion_status="approved",
        case_status="active",
        closure_method="docusign",
        settlement_direction="company_owes_employee",
        settlement_status="settlement_pending",
        conversation_state="DONE",
        opened_days_ago=20,
        document_signature_status="completed",
        expenses=[
            {
                "merchant": "Hotel Gervasoni",
                "category": "Lodging",
                "total": 185000,
                "status": "approved",
                "review_status": "approved",
                "review_score": 95,
                "flags": [],
                "days_ago": 18,
            },
            {
                "merchant": "Restaurante Fauna Cerro Alegre",
                "category": "Meals",
                "total": 78500,
                "status": "approved",
                "review_status": "approved",
                "review_score": 90,
                "flags": [],
                "days_ago": 18,
            },
            {
                "merchant": "Uber",
                "category": "Transport",
                "total": 128000,
                "status": "approved",
                "review_status": "approved",
                "review_score": 86,
                "flags": [],
                "days_ago": 19,
            },
        ],
    ),
    CaseSpec(
        case_id="CASE-005",
        employee_idx=4,  # Tomas
        context_label="Auditoria interna Antofagasta",
        destination="Antofagasta",
        country="Chile",
        fondos_entregados=450000,
        rendicion_status="closed",
        case_status="closed",
        closure_method="simple",
        settlement_direction="employee_owes_company",
        settlement_status="settled",
        conversation_state="DONE",
        opened_days_ago=45,
        document_signature_status="completed",
        expenses=[
            {
                "merchant": "Hotel Antofagasta",
                "category": "Lodging",
                "total": 95000,
                "status": "approved",
                "review_status": "approved",
                "review_score": 93,
                "flags": [],
                "days_ago": 42,
            },
            {
                "merchant": "Sky Airline",
                "category": "Transport",
                "total": 145000,
                "status": "approved",
                "review_status": "approved",
                "review_score": 91,
                "flags": [],
                "days_ago": 43,
            },
            {
                "merchant": "Restaurante La Calma",
                "category": "Meals",
                "total": 42000,
                "status": "approved",
                "review_status": "approved",
                "review_score": 88,
                "flags": [],
                "days_ago": 41,
            },
            {
                "merchant": "Uber",
                "category": "Transport",
                "total": 38500,
                "status": "approved",
                "review_status": "approved",
                "review_score": 87,
                "flags": [],
                "days_ago": 40,
            },
        ],
    ),
]


def build_case_rows(now: datetime) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for spec in CASES:
        employee = EMPLOYEES_SPEC[spec.employee_idx]
        phone = employee[2]
        company = employee[5]
        opened_at = now - timedelta(days=spec.opened_days_ago)
        due_date = (opened_at + timedelta(days=30)).date().isoformat()
        start_date = opened_at.date().isoformat()
        end_date = (opened_at + timedelta(days=5)).date().isoformat()

        approved_total_clp = sum(
            _amount_to_clp(exp.get("total"), exp.get("currency", "CLP"))
            for exp in spec.expenses
            if exp["status"] == "approved"
        )

        closed_at = ""
        closure_status = ""
        closure_reason = ""
        user_confirmed_at = ""
        user_confirmation_status = ""
        settlement_amount_clp = ""
        settlement_net_clp = ""
        settlement_calculated_at = ""
        settlement_resolved_at = ""

        if spec.rendicion_status in ("pending_user_confirmation", "approved", "closed"):
            user_confirmed_at = _iso(opened_at + timedelta(days=max(spec.opened_days_ago - 3, 1)))
            user_confirmation_status = "confirmed" if spec.rendicion_status != "pending_user_confirmation" else ""
        if spec.rendicion_status in ("approved", "closed"):
            settlement_amount_clp = abs(spec.fondos_entregados - approved_total_clp)
            if spec.settlement_direction == "company_owes_employee":
                settlement_net_clp = approved_total_clp - spec.fondos_entregados
            elif spec.settlement_direction == "employee_owes_company":
                settlement_net_clp = spec.fondos_entregados - approved_total_clp
            else:
                settlement_net_clp = 0
            settlement_calculated_at = _iso(opened_at + timedelta(days=max(spec.opened_days_ago - 2, 1)))
        if spec.rendicion_status == "closed":
            closed_at = _iso(opened_at + timedelta(days=spec.opened_days_ago - 1))
            closure_status = "closed"
            closure_reason = "settlement_resolved"
            settlement_resolved_at = closed_at

        rows.append(
            [
                spec.case_id,
                phone,
                phone,
                company,
                spec.context_label,
                spec.closure_method,
                spec.destination,
                spec.country,
                _iso(opened_at),  # opened_at
                due_date,
                start_date,
                end_date,
                spec.fondos_entregados,
                spec.fondos_entregados,  # budget (legacy alias)
                spec.case_status,
                closure_status,
                "",  # closure_prompted_at
                "",  # closure_deadline_at
                "",  # closure_response
                "",  # closure_responded_at
                closed_at,
                closure_reason,
                _iso(opened_at),
                _iso(now - timedelta(hours=2)),
                "",  # notes
                spec.fondos_entregados,
                spec.rendicion_status,
                user_confirmed_at,
                user_confirmation_status,
                spec.settlement_direction,
                spec.settlement_status,
                settlement_amount_clp,
                settlement_net_clp,
                settlement_calculated_at,
                settlement_resolved_at,
            ]
        )
    return rows


def _amount_to_clp(total: Any, currency: str) -> int:
    try:
        amount = float(total or 0)
    except (TypeError, ValueError):
        return 0
    code = (currency or "CLP").upper()
    # Factores aproximados para estimación de total_clp en demo.
    factor = {
        "CLP": 1,
        "USD": 950,
        "PEN": 260,
        "CNY": 130,
        "EUR": 1020,
    }.get(code, 1)
    return int(round(amount * factor))


def build_expense_rows(now: datetime) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for spec in CASES:
        employee = EMPLOYEES_SPEC[spec.employee_idx]
        phone = employee[2]
        for idx, exp in enumerate(spec.expenses, start=1):
            expense_id = f"{spec.case_id}-EXP-{idx:02d}"
            currency = exp.get("currency", "CLP")
            total = exp.get("total", 0)
            total_clp = _amount_to_clp(total, currency)
            country = exp.get("country", spec.country)
            created_at = _iso(now - timedelta(days=exp.get("days_ago", 1), hours=idx))
            updated_at = created_at
            review_flags = ",".join(exp.get("flags", []))
            breakdown = (
                "document_quality:80|extraction_quality:80|field_completeness:80|"
                "document_type_confidence:80|policy_risk:80|duplicate_risk:90"
            )
            primary_reason = exp.get("flags", [""])[0] if exp.get("flags") else ""
            rows.append(
                [
                    expense_id,
                    phone,
                    spec.case_id,
                    spec.case_id,  # trip_id alias
                    exp["merchant"],
                    (now - timedelta(days=exp.get("days_ago", 1))).date().isoformat(),
                    currency,
                    total,
                    total_clp,
                    exp["category"],
                    country,
                    "FALSE",
                    exp["status"],
                    "confirmed",
                    "active_case_linked",
                    "",  # review_reason
                    exp.get("review_score", 70),
                    exp.get("review_status", "pending_review"),
                    breakdown,
                    review_flags,
                    primary_reason,
                    "",  # source_message_id
                    "",  # receipt_storage_provider
                    "",  # receipt_object_key
                    "",  # image_url
                    "",  # document_url
                    created_at,
                    updated_at,
                ]
            )
    return rows


def build_conversation_rows(now: datetime) -> list[list[Any]]:
    rows: list[list[Any]] = []
    default_context = (
        '{"draft_expense":{},"missing_fields":[],"last_question":null,"message_log":[],'
        '"scheduler":{"sent_reminders":{}},"submission_closure":{},"trip_closure":{}}'
    )
    for spec in CASES:
        employee = EMPLOYEES_SPEC[spec.employee_idx]
        phone = employee[2]
        current_step = ""
        if spec.conversation_state == "WAIT_SUBMISSION_CLOSURE_CONFIRMATION":
            current_step = "awaiting_docusign"
        rows.append(
            [
                phone,
                spec.case_id,
                spec.conversation_state,
                current_step,
                default_context,
                _iso(now - timedelta(hours=1)),
            ]
        )
    return rows


def build_case_document_rows(now: datetime) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for spec in CASES:
        if not spec.document_signature_status:
            continue
        employee = EMPLOYEES_SPEC[spec.employee_idx]
        phone = employee[2]
        approved_total_clp = sum(
            _amount_to_clp(exp.get("total"), exp.get("currency", "CLP"))
            for exp in spec.expenses
            if exp["status"] == "approved"
        )
        approved_count = sum(1 for exp in spec.expenses if exp["status"] == "approved")
        created_at = _iso(now - timedelta(days=max(spec.opened_days_ago - 3, 1)))
        signed_completed_at = ""
        signed_object_key = ""
        signature_sent_at = created_at
        if spec.document_signature_status == "completed":
            signed_completed_at = _iso(now - timedelta(days=max(spec.opened_days_ago - 2, 1)))
            signed_object_key = f"reports/{spec.case_id}-signed.pdf"

        rows.append(
            [
                f"{spec.case_id}-DOC-01",
                phone,
                spec.case_id,
                spec.case_id,
                "gcs",
                f"reports/{spec.case_id}-consolidated.pdf",
                approved_count,
                approved_total_clp,
                "generated",
                created_at,
                _iso(now - timedelta(hours=3)),
                "docusign",
                spec.document_signature_status,
                f"envelope-demo-{spec.case_id.lower()}",
                "",  # signature_url
                signature_sent_at,
                signed_completed_at,
                "",  # declined_at
                "",  # expired_at
                "gcs" if signed_object_key else "",
                signed_object_key,
                "",  # signature_error
            ]
        )
    return rows


# ---------- runtime ----------


def get_client(credentials_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    return gspread.authorize(creds)


def ensure_worksheet(spreadsheet: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=200, cols=40)


def set_headers(ws: gspread.Worksheet, headers: list[str]) -> None:
    ws.update("A1", [headers])


def clear_rows_keep_headers(ws: gspread.Worksheet) -> None:
    row_count = ws.row_count
    if row_count > 1:
        ws.batch_clear([f"A2:AZ{row_count}"])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Siembra datos demo en Google Sheets")
    parser.add_argument(
        "--spreadsheet-id",
        default=os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", ""),
    )
    parser.add_argument(
        "--credentials",
        dest="credentials_path",
        default=os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
    )
    parser.add_argument("--clear-data", action="store_true", help="Borra filas existentes antes de sembrar")
    parser.add_argument("--confirm", action="store_true", help="Confirma escritura en Google Sheets (por defecto dry-run)")
    args = parser.parse_args()
    if not args.spreadsheet_id:
        parser.error("Falta --spreadsheet-id (o env GOOGLE_SHEETS_SPREADSHEET_ID)")
    if not args.credentials_path:
        parser.error("Falta --credentials (o env GOOGLE_APPLICATION_CREDENTIALS)")
    if not os.path.exists(args.credentials_path):
        parser.error(f"No existe el archivo de credenciales: {args.credentials_path}")
    return args


def main() -> int:
    args = parse_args()
    now = _utc_now()
    now_iso = _iso(now)

    rows_by_sheet: dict[str, list[list[Any]]] = {
        "empresas": build_companies(),
        "Employees": build_employees(now_iso),
        "BackofficeUsers": build_backoffice_users(now_iso),
        "ExpenseCases": build_case_rows(now),
        "Expenses": build_expense_rows(now),
        "Conversations": build_conversation_rows(now),
        "ExpenseCaseDocuments": build_case_document_rows(now),
    }

    print(f"Spreadsheet target: {args.spreadsheet_id}")
    for sheet_name, rows in rows_by_sheet.items():
        print(f"  {sheet_name}: {len(rows)} filas")

    if not args.confirm:
        print("\nDry-run (sin --confirm). No se escribió nada.")
        return 0

    client = get_client(args.credentials_path)
    spreadsheet = client.open_by_key(args.spreadsheet_id)
    print(f"\nAbriendo: {spreadsheet.title}")

    for sheet_name, headers in SHEET_HEADERS.items():
        ws = ensure_worksheet(spreadsheet, sheet_name)
        set_headers(ws, headers)
        if args.clear_data:
            clear_rows_keep_headers(ws)
        print(f"OK headers -> {sheet_name}")

    for sheet_name, rows in rows_by_sheet.items():
        if not rows:
            continue
        ws = spreadsheet.worksheet(sheet_name)
        ws.append_rows(rows, value_input_option="RAW")
        print(f"OK seed -> {sheet_name}: {len(rows)} filas")

    print("\nListo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
