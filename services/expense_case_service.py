from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.sheets_service import SheetsService


@dataclass
class ExpenseCaseService:
    sheets_service: SheetsService

    def get_active_case_for_phone(self, phone: str) -> dict[str, Any] | None:
        return self.sheets_service.get_active_expense_case_by_phone(phone)

