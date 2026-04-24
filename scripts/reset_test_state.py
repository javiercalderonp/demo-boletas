#!/usr/bin/env python3
"""Resetea conversación y recrea una rendición de prueba usando el último caso del usuario.

Uso:
  python scripts/reset_test_state.py --phone +569XXXXXXXX

Comportamiento:
- Busca el último caso/rendición del teléfono indicado.
- Marca casos activos actuales como `completed` para evitar ambigüedad.
- Crea un nuevo caso con los mismos datos base y fechas frescas desde hoy.
- Resetea la conversación a WAIT_RECEIPT.
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta

from app.config import settings
from services.conversation_service import ConversationService
from services.expense_service import ExpenseService
from services.sheets_service import SHEET_NAMES, SheetsService
from utils.helpers import make_id, normalize_whatsapp_phone


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset de conversación y recreación de rendición de prueba")
    parser.add_argument("--phone", required=True, help="Teléfono E.164 del usuario de prueba")
    parser.add_argument(
        "--duration-days",
        type=int,
        default=3,
        help="Duración del nuevo caso en días desde hoy, incluyendo hoy",
    )
    return parser.parse_args()


def _pick_latest_case(cases: list[dict]) -> dict | None:
    latest_case = None
    latest_end_date = ""
    for expense_case in cases:
        end_date = str(expense_case.get("due_date", expense_case.get("end_date", "")) or "").strip()
        if latest_case is None or end_date >= latest_end_date:
            latest_case = expense_case
            latest_end_date = end_date
    return latest_case


def main() -> None:
    args = parse_args()
    phone = normalize_whatsapp_phone(args.phone)
    if not phone:
        raise SystemExit("El teléfono no es válido")

    sheets = SheetsService(settings=settings)
    conversation_service = ConversationService(
        expense_service=ExpenseService(sheets_service=sheets)
    )

    employee = sheets.get_employee_by_phone(phone)
    if not employee:
        raise SystemExit(f"No existe empleado activo para {phone}")

    cases = sheets.list_active_expense_cases_by_phone(phone)
    if not cases:
        for row in sheets._get_records(SHEET_NAMES["expense_cases"]):  # noqa: SLF001 - utility script
            if normalize_whatsapp_phone(row.get("phone", "")) == phone:
                cases.append(row)
    base_case = _pick_latest_case(cases)
    if not base_case:
        raise SystemExit(f"No encontré casos previos para {phone}")

    for expense_case in sheets.list_active_expense_cases_by_phone(phone):
        case_id = str(expense_case.get("case_id", expense_case.get("trip_id", "")) or "").strip()
        if not case_id:
            continue
        sheets.update_expense_case(
            case_id,
            {
                **expense_case,
                "status": "completed",
                "closure_status": str(expense_case.get("closure_status", "") or "").strip() or "reset_for_retest",
            },
        )

    start_date = date.today()
    end_date = start_date + timedelta(days=max(args.duration_days - 1, 0))
    new_case_id = make_id("CASE")
    new_case = dict(base_case)
    new_case.update(
        {
            "case_id": new_case_id,
            "trip_id": new_case_id,
            "phone": phone,
            "opened_at": start_date.isoformat(),
            "due_date": end_date.isoformat(),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "status": "active",
            "closure_status": "",
            "closure_prompted_at": "",
            "closure_deadline_at": "",
            "closure_response": "",
            "closure_responded_at": "",
            "closed_at": "",
            "closure_reason": "",
        }
    )
    sheets._append_row(SHEET_NAMES["expense_cases"], new_case)  # noqa: SLF001 - utility script

    reset_conversation = {
        "phone": phone,
        "state": "WAIT_RECEIPT",
        "current_step": "",
        "context_json": conversation_service.default_context(),
    }
    sheets.update_conversation(phone, reset_conversation)

    print("Reset completado")
    print(f"phone={phone}")
    print(f"employee_name={employee.get('name', '')}")
    print(f"new_case_id={new_case_id}")
    print(f"context_label={new_case.get('context_label', new_case.get('destination', ''))}")
    print(f"country={new_case.get('country', '')}")
    print(f"opened_at={new_case.get('opened_at', new_case.get('start_date', ''))}")
    print(f"due_date={new_case.get('due_date', new_case.get('end_date', ''))}")


if __name__ == "__main__":
    main()
