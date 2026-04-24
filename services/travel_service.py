from __future__ import annotations

from dataclasses import dataclass

from services.expense_case_service import ExpenseCaseService
from services.sheets_service import SheetsService


@dataclass
class TravelService(ExpenseCaseService):
    sheets_service: SheetsService

    def get_active_trip_for_phone(self, phone: str):
        return self.get_active_case_for_phone(phone)
