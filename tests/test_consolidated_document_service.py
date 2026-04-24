import unittest
from unittest.mock import Mock

from app.config import Settings
from services.consolidated_document_service import ConsolidatedDocumentService


class ConsolidatedDocumentServiceTests(unittest.TestCase):
    def _build_service(self, sheets_service):
        storage_service = Mock()
        storage_service.settings = Settings()
        return ConsolidatedDocumentService(
            sheets_service=sheets_service,
            storage_service=storage_service,
        )

    class _FakeTable:
        def __init__(self, rows, **kwargs):
            self.rows = rows
            self.kwargs = kwargs
            self.style = None

        def setStyle(self, style):
            self.style = style

    def test_resolve_company_name_uses_employee_company(self):
        sheets_service = Mock()
        sheets_service.get_expense_case_by_id.return_value = {
            "case_id": "CASE-1",
            "phone": "+56911111111",
        }
        sheets_service.get_employee_by_phone.return_value = {"company_id": "acme"}
        sheets_service.list_companies.return_value = [
            {"company_id": "acme", "name": "Acme Corp"}
        ]
        service = self._build_service(sheets_service)

        company_name = service._resolve_company_name_for_case(trip_id="CASE-1")

        self.assertEqual(company_name, "Acme Corp")

    def test_signature_section_does_not_include_manager_box(self):
        sheets_service = Mock()
        sheets_service.get_employee_by_phone.return_value = {
            "name": "Javier Calderon",
            "rut": "12.345.678-9",
        }
        service = self._build_service(sheets_service)

        items = service._build_signature_section(
            phone="+56911111111",
            trip={"context_label": "Viaje Santiago"},
            paragraph_class=lambda text, style: ("paragraph", text),
            spacer_class=lambda width, height: ("spacer", width, height),
            table_class=self._FakeTable,
            table_style_class=lambda rules: rules,
            text_style="text",
            heading_style="heading",
            mm=1,
            colors=type("Colors", (), {"black": "black", "whitesmoke": "whitesmoke"})(),
        )

        table_rows = [
            row
            for item in items
            if isinstance(item, self._FakeTable)
            for row in item.rows
        ]

        self.assertFalse(any(row[0] == "Firma gerente de área" for row in table_rows))


if __name__ == "__main__":
    unittest.main()
