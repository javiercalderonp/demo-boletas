#!/usr/bin/env python3
"""Inicializa headers y carga datos demo en Google Sheets para el MVP.

Uso:
  python scripts/seed_sheets.py \
    --credentials ./service-account.json \
    --spreadsheet-id <SPREADSHEET_ID> \
    --clear-data \
    --seed-demo

Requisitos:
  pip install gspread google-auth
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import gspread
from google.oauth2.service_account import Credentials


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
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
    "Expenses": [
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
        "receipt_storage_provider",
        "receipt_object_key",
        "image_url",
        "document_url",
        "created_at",
        "updated_at",
    ],
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


@dataclass
class SeedConfig:
    spreadsheet_id: str
    credentials_path: str
    clear_data: bool
    seed_demo: bool
    employee_phone: str
    employee_name: str
    employee_rut: str
    employee_email: str
    collaborator_phone: str


def parse_args() -> SeedConfig:
    parser = argparse.ArgumentParser(
        description="Inicializa headers y datos demo para Expense_Submission_Agent_MVP"
    )
    parser.add_argument(
        "--spreadsheet-id",
        default=os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", ""),
        help="ID del Google Spreadsheet",
    )
    parser.add_argument(
        "--credentials",
        dest="credentials_path",
        default=os.getenv("GOOGLE_APPLICATION_CREDENTIALS", ""),
        help="Path al JSON de Service Account",
    )
    parser.add_argument(
        "--clear-data",
        action="store_true",
        help="Borra filas existentes (mantiene headers)",
    )
    parser.add_argument(
        "--seed-demo",
        action="store_true",
        help="Carga filas de ejemplo después de crear headers",
    )
    parser.add_argument(
        "--employee-phone",
        default="+56974340422",
        help="Teléfono del empleado demo (E.164)",
    )
    parser.add_argument(
        "--employee-name",
        default="Javier Calderon",
        help="Nombre del empleado demo",
    )
    parser.add_argument(
        "--employee-rut",
        default="12.345.678-9",
        help="RUT del empleado demo",
    )
    parser.add_argument(
        "--employee-email",
        default="",
        help="Email del empleado demo para firma DocuSign",
    )
    parser.add_argument(
        "--collaborator-phone",
        default="+56970000000",
        help="Teléfono colaborador demo para shared expense",
    )

    args = parser.parse_args()

    if not args.spreadsheet_id:
        parser.error("Falta --spreadsheet-id (o env GOOGLE_SHEETS_SPREADSHEET_ID)")
    if not args.credentials_path:
        parser.error("Falta --credentials (o env GOOGLE_APPLICATION_CREDENTIALS)")
    if not os.path.exists(args.credentials_path):
        parser.error(f"No existe el archivo de credenciales: {args.credentials_path}")

    return SeedConfig(
        spreadsheet_id=args.spreadsheet_id,
        credentials_path=args.credentials_path,
        clear_data=args.clear_data,
        seed_demo=args.seed_demo,
        employee_phone=args.employee_phone,
        employee_name=args.employee_name,
        employee_rut=args.employee_rut,
        employee_email=args.employee_email,
        collaborator_phone=args.collaborator_phone,
    )


def get_client(credentials_path: str) -> gspread.Client:
    creds = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
    return gspread.authorize(creds)


def ensure_worksheet(spreadsheet: gspread.Spreadsheet, title: str) -> gspread.Worksheet:
    try:
        return spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        # Tamaño pequeño suficiente para MVP; se puede ajustar luego.
        return spreadsheet.add_worksheet(title=title, rows=200, cols=20)


def set_headers(ws: gspread.Worksheet, headers: list[str]) -> None:
    ws.update("A1", [headers])


def clear_rows_keep_headers(ws: gspread.Worksheet) -> None:
    row_count = ws.row_count
    if row_count > 1:
        ws.batch_clear([f"A2:Z{row_count}"])


def build_demo_employees(cfg: SeedConfig, *, created_at: str) -> list[list[Any]]:
    employee_specs = [
        ("Javier", "Calderon", cfg.employee_phone, cfg.employee_rut, cfg.employee_email or "javier.calderon@ripley-demo.cl", "ripley", "Banco de Chile", "Cuenta Corriente", "100000001", cfg.employee_name or "Javier Calderon", cfg.employee_rut, "2026-04-16T09:10:00Z"),
        ("Camila", "Rojas", "+56961230001", "11.111.111-1", "camila.rojas@ripley-demo.cl", "ripley", "Banco Santander", "Cuenta Vista", "100000002", "Camila Rojas", "11.111.111-1", "2026-04-16T08:45:00Z"),
        ("Martin", "Poblete", "+56961230002", "12.222.222-2", "martin.poblete@ripley-demo.cl", "ripley", "BCI", "Cuenta Corriente", "100000003", "Martin Poblete", "12.222.222-2", "2026-04-15T18:20:00Z"),
        ("Valentina", "Soto", "+56961230003", "13.333.333-3", "valentina.soto@acme-demo.cl", "acme", "BancoEstado", "Cuenta Ahorro", "100000004", "Valentina Soto", "13.333.333-3", "2026-04-15T14:05:00Z"),
        ("Tomas", "Fernandez", "+56961230004", "14.444.444-4", "tomas.fernandez@acme-demo.cl", "acme", "Banco de Chile", "Cuenta Corriente", "100000005", "Tomas Fernandez", "14.444.444-4", "2026-04-14T19:30:00Z"),
        ("Fernanda", "Muñoz", "+56961230005", "15.555.555-5", "fernanda.munoz@acme-demo.cl", "acme", "Itaú", "Cuenta Vista", "100000006", "Fernanda Muñoz", "15.555.555-5", "2026-04-14T11:15:00Z"),
        ("Diego", "Silva", "+56961230006", "16.666.666-6", "diego.silva@globex-demo.cl", "globex", "Scotiabank", "Cuenta Corriente", "100000007", "Diego Silva", "16.666.666-6", "2026-04-13T17:40:00Z"),
        ("Antonia", "Perez", "+56961230007", "17.777.777-7", "antonia.perez@globex-demo.cl", "globex", "Banco Falabella", "Cuenta Vista", "100000008", "Antonia Perez", "17.777.777-7", "2026-04-13T10:20:00Z"),
        ("Benjamin", "Contreras", "+56961230008", "18.888.888-8", "benjamin.contreras@globex-demo.cl", "globex", "Banco Santander", "Cuenta Corriente", "100000009", "Benjamin Contreras", "18.888.888-8", "2026-04-12T16:50:00Z"),
        ("Isidora", "Araya", "+56961230009", "19.999.999-9", "isidora.araya@ripley-demo.cl", "ripley", "BancoEstado", "Cuenta Vista", "100000010", "Isidora Araya", "19.999.999-9", "2026-04-12T09:05:00Z"),
        ("Nicolas", "Guzman", "+56961230010", "20.101.010-0", "nicolas.guzman@acme-demo.cl", "acme", "BCI", "Cuenta Corriente", "100000011", "Nicolas Guzman", "20.101.010-0", "2026-04-11T15:00:00Z"),
        ("Catalina", "Vega", "+56961230011", "21.121.212-1", "catalina.vega@globex-demo.cl", "globex", "Banco de Chile", "Cuenta Ahorro", "100000012", "Catalina Vega", "21.121.212-1", "2026-04-11T12:35:00Z"),
        ("Sebastian", "Morales", "+56961230012", "22.232.323-2", "sebastian.morales@ripley-demo.cl", "ripley", "Itaú", "Cuenta Corriente", "100000013", "Sebastian Morales", "22.232.323-2", "2026-04-10T18:10:00Z"),
        ("Josefa", "Herrera", "+56961230013", "23.343.434-3", "josefa.herrera@acme-demo.cl", "acme", "Scotiabank", "Cuenta Vista", "100000014", "Josefa Herrera", "23.343.434-3", "2026-04-10T10:55:00Z"),
        ("Matias", "Navarro", "+56961230014", "24.454.545-4", "matias.navarro@globex-demo.cl", "globex", "Banco Falabella", "Cuenta Corriente", "100000015", "Matias Navarro", "24.454.545-4", "2026-04-09T17:25:00Z"),
    ]

    rows: list[list[Any]] = []
    for (
        first_name,
        last_name,
        phone,
        rut,
        email,
        company_id,
        bank_name,
        account_type,
        account_number,
        account_holder,
        account_holder_rut,
        last_activity_at,
    ) in employee_specs:
        rows.append(
            [
                phone,
                first_name,
                last_name,
                f"{first_name} {last_name}",
                rut,
                email,
                company_id,
                bank_name,
                account_type,
                account_number,
                account_holder,
                account_holder_rut,
                "TRUE",
                last_activity_at,
                created_at,
                created_at,
            ]
        )
    return rows


def demo_rows(cfg: SeedConfig) -> dict[str, list[list[Any]]]:
    created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    return {
        "empresas": [
            [
                "ripley",
                "Ripley Retail Chile SpA",
                "76.123.456-7",
                "Banco de Chile",
                "Cuenta Corriente",
                "0012345678",
                "Ripley Retail Chile SpA",
                "76.123.456-7",
                "tesoreria@ripley-demo.cl",
                "TRUE",
            ],
            [
                "acme",
                "Acme Servicios SpA",
                "77.234.567-8",
                "Banco Santander",
                "Cuenta Vista",
                "9876543210",
                "Acme Servicios SpA",
                "77.234.567-8",
                "pagos@acme-demo.cl",
                "TRUE",
            ],
            [
                "globex",
                "Globex Chile Ltda.",
                "78.345.678-9",
                "BCI",
                "Cuenta Corriente",
                "1122334455",
                "Globex Chile Ltda.",
                "78.345.678-9",
                "finanzas@globex-demo.cl",
                "TRUE",
            ],
        ],
        "Employees": build_demo_employees(cfg, created_at=created_at),
        "BackofficeUsers": [
            [
                "usr-demo-admin",
                "Demo Admin",
                "admin@example.com",
                "pbkdf2_sha256$demo_admin_salt$c50d61b32ad63e371fd7eb113494b6618957faccba1402364269262edcef4889",
                "admin",
                "TRUE",
                created_at,
                created_at,
            ]
        ],
        "ExpenseCases": [],
        "Expenses": [],
        "Conversations": [],
        "ExpenseCaseDocuments": [],
    }


def append_rows(ws: gspread.Worksheet, rows: list[list[Any]]) -> None:
    if rows:
        # RAW preserva formatos como '+569...' para teléfonos.
        ws.append_rows(rows, value_input_option="RAW")


def main() -> int:
    cfg = parse_args()
    client = get_client(cfg.credentials_path)
    spreadsheet = client.open_by_key(cfg.spreadsheet_id)

    print(f"Spreadsheet: {spreadsheet.title} ({cfg.spreadsheet_id})")

    for sheet_name, headers in SHEET_HEADERS.items():
        ws = ensure_worksheet(spreadsheet, sheet_name)
        set_headers(ws, headers)
        if cfg.clear_data:
            clear_rows_keep_headers(ws)
        print(f"OK headers -> {sheet_name}")

    if cfg.seed_demo:
        rows_by_sheet = demo_rows(cfg)
        for sheet_name, rows in rows_by_sheet.items():
            ws = spreadsheet.worksheet(sheet_name)
            append_rows(ws, rows)
            print(f"OK seed rows -> {sheet_name}: {len(rows)}")

    print("Listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
