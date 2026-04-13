#!/usr/bin/env python3
"""Resetea conversación y recrea un viaje de prueba usando el último viaje del usuario.

Uso:
  python scripts/reset_test_state.py --phone +569XXXXXXXX

Comportamiento:
- Busca el último viaje del teléfono indicado.
- Marca viajes activos actuales como `completed` para evitar ambigüedad.
- Crea un nuevo viaje con los mismos datos base y fechas frescas desde hoy.
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
    parser = argparse.ArgumentParser(description="Reset de conversación y recreación de viaje de prueba")
    parser.add_argument("--phone", required=True, help="Teléfono E.164 del usuario de prueba")
    parser.add_argument(
        "--duration-days",
        type=int,
        default=3,
        help="Duración del nuevo viaje en días desde hoy, incluyendo hoy",
    )
    return parser.parse_args()


def _pick_latest_trip(trips: list[dict]) -> dict | None:
    latest_trip = None
    latest_end_date = ""
    for trip in trips:
        end_date = str(trip.get("end_date", "") or "").strip()
        if latest_trip is None or end_date >= latest_end_date:
            latest_trip = trip
            latest_end_date = end_date
    return latest_trip


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

    trips = sheets.list_active_trips_by_phone(phone)
    if not trips:
        for row in sheets._get_records(SHEET_NAMES["trips"]):  # noqa: SLF001 - utility script
            if normalize_whatsapp_phone(row.get("phone", "")) == phone:
                trips.append(row)
    base_trip = _pick_latest_trip(trips)
    if not base_trip:
        raise SystemExit(f"No encontré viajes previos para {phone}")

    for trip in sheets.list_active_trips_by_phone(phone):
        trip_id = str(trip.get("trip_id", "") or "").strip()
        if not trip_id:
            continue
        sheets.update_trip(
            trip_id,
            {
                **trip,
                "status": "completed",
                "closure_status": str(trip.get("closure_status", "") or "").strip() or "reset_for_retest",
            },
        )

    start_date = date.today()
    end_date = start_date + timedelta(days=max(args.duration_days - 1, 0))
    new_trip_id = make_id("TRIP")
    new_trip = dict(base_trip)
    new_trip.update(
        {
            "trip_id": new_trip_id,
            "phone": phone,
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
    sheets._append_row(SHEET_NAMES["trips"], new_trip)  # noqa: SLF001 - utility script

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
    print(f"new_trip_id={new_trip_id}")
    print(f"destination={new_trip.get('destination', '')}")
    print(f"country={new_trip.get('country', '')}")
    print(f"start_date={new_trip.get('start_date', '')}")
    print(f"end_date={new_trip.get('end_date', '')}")


if __name__ == "__main__":
    main()
