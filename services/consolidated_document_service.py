from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from services.sheets_service import SheetsService
from services.storage_service import GCSStorageService
from utils.exchange_rate import convert_to_clp
from utils.helpers import make_id, normalize_whatsapp_phone, parse_float, utc_now_iso

logger = logging.getLogger(__name__)


@dataclass
class ConsolidatedDocumentService:
    sheets_service: SheetsService
    storage_service: GCSStorageService

    def generate_for_trip(
        self,
        *,
        phone: str,
        trip_id: str,
        include_signed_url: bool = True,
    ) -> dict[str, Any]:
        normalized_phone = normalize_whatsapp_phone(phone)
        target_trip_id = str(trip_id or "").strip()
        if not normalized_phone:
            raise ValueError("phone invalido")
        if not target_trip_id:
            raise ValueError("trip_id vacio")
        if not self.storage_service.enabled:
            raise RuntimeError("Storage privado no habilitado para guardar el documento")

        trip = self.sheets_service.get_trip_by_id(target_trip_id)
        if not trip:
            raise ValueError(f"No existe trip_id={target_trip_id}")

        trip_phone = normalize_whatsapp_phone(trip.get("phone"))
        if trip_phone and trip_phone != normalized_phone:
            raise ValueError("El trip no pertenece al telefono indicado")

        expenses = self.sheets_service.list_expenses_by_phone_trip(
            phone=normalized_phone,
            trip_id=target_trip_id,
        )
        sorted_expenses = sorted(
            expenses,
            key=lambda item: (
                str(item.get("date", "") or ""),
                str(item.get("created_at", "") or ""),
                str(item.get("expense_id", "") or ""),
            ),
        )

        report_data = self._build_report_data(trip=trip, expenses=sorted_expenses)
        pdf_content = self._render_pdf(
            phone=normalized_phone,
            trip_id=target_trip_id,
            trip=trip,
            report_data=report_data,
        )

        upload_result = self.storage_service.upload_report_pdf(
            phone=normalized_phone,
            trip_id=target_trip_id,
            content=pdf_content,
        )

        document = {
            "document_id": make_id("DOC"),
            "phone": normalized_phone,
            "trip_id": target_trip_id,
            "storage_provider": upload_result["storage_provider"],
            "object_key": upload_result["object_key"],
            "expense_count": len(sorted_expenses),
            "total_clp": round(report_data["total_clp"], 2),
            "status": "generated",
            "created_at": utc_now_iso(),
            "updated_at": "",
            "signature_provider": "",
            "signature_status": "",
            "docusign_envelope_id": "",
            "signature_url": "",
            "signature_sent_at": "",
            "signature_completed_at": "",
            "signature_declined_at": "",
            "signature_expired_at": "",
            "signed_storage_provider": "",
            "signed_object_key": "",
            "signature_error": "",
        }
        self.sheets_service.create_trip_document(document)

        response = document.copy()
        if include_signed_url:
            response["signed_url"] = self.storage_service.generate_signed_url(
                object_key=upload_result["object_key"]
            )
        return response

    def _build_report_data(
        self,
        *,
        trip: dict[str, Any],
        expenses: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total_clp = 0.0
        by_category: dict[str, float] = {}
        by_day: dict[str, float] = {}
        detail_rows: list[dict[str, Any]] = []

        for expense in expenses:
            category = str(expense.get("category", "") or "").strip() or "Uncategorized"
            day = str(expense.get("date", "") or "").strip() or "sin_fecha"
            currency = str(expense.get("currency", "") or "").strip().upper() or "CLP"
            total = parse_float(expense.get("total")) or 0.0
            total_clp_row = parse_float(expense.get("total_clp"))
            if total_clp_row is None:
                total_clp_row = float(convert_to_clp(total, currency))

            by_category[category] = by_category.get(category, 0.0) + total_clp_row
            by_day[day] = by_day.get(day, 0.0) + total_clp_row
            total_clp += total_clp_row

            detail_rows.append(
                {
                    "expense_id": str(expense.get("expense_id", "") or ""),
                    "date": day,
                    "merchant": str(expense.get("merchant", "") or "").strip() or "-",
                    "category": category,
                    "currency": currency,
                    "total": total,
                    "total_clp": total_clp_row,
                    "receipt_reference": self._build_receipt_reference(expense),
                    "receipt_storage_provider": str(
                        expense.get("receipt_storage_provider", "") or ""
                    ).strip(),
                    "receipt_object_key": str(expense.get("receipt_object_key", "") or "").strip(),
                }
            )

        sorted_categories = sorted(by_category.items(), key=lambda x: x[0].lower())
        sorted_days = sorted(by_day.items(), key=lambda x: x[0])
        return {
            "trip": trip,
            "total_clp": total_clp,
            "by_category": sorted_categories,
            "by_day": sorted_days,
            "detail_rows": detail_rows,
        }

    def _build_receipt_reference(self, expense: dict[str, Any]) -> str:
        provider = str(expense.get("receipt_storage_provider", "") or "").strip().lower()
        object_key = str(expense.get("receipt_object_key", "") or "").strip()
        if not provider and not object_key:
            return "sin_referencia"
        if provider == "gcs" and object_key:
            bucket_name = str(self.storage_service.settings.gcs_bucket_name or "").strip()
            if bucket_name:
                return f"gcs://{bucket_name}/{object_key}"
        return f"{provider}:{object_key}".strip(":")

    def _render_pdf(
        self,
        *,
        phone: str,
        trip_id: str,
        trip: dict[str, Any],
        report_data: dict[str, Any],
    ) -> bytes:
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                Image,
                PageBreak,
                Paragraph,
                SimpleDocTemplate,
                Spacer,
                Table,
                TableStyle,
            )
        except ImportError as exc:
            raise RuntimeError("Falta dependencia reportlab para generar PDF") from exc

        stream = BytesIO()
        doc = SimpleDocTemplate(
            stream,
            pagesize=A4,
            leftMargin=12 * mm,
            rightMargin=12 * mm,
            topMargin=12 * mm,
            bottomMargin=12 * mm,
            title=f"Reporte Consolidado de Viaticos {trip_id}",
        )

        styles = getSampleStyleSheet()
        detail_label_style = ParagraphStyle(
            "detail_label",
            parent=styles["Normal"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
        )
        detail_value_style = ParagraphStyle(
            "detail_value",
            parent=styles["Normal"],
            fontSize=8,
            leading=10,
            wordWrap="CJK",
            splitLongWords=True,
        )
        story: list[Any] = []

        story.extend(
            self._build_header_with_logo(
                trip_id=trip_id,
                image_class=Image,
                paragraph_class=Paragraph,
                spacer_class=Spacer,
                table_class=Table,
                table_style_class=TableStyle,
                text_style=styles["Normal"],
                mm=mm,
            )
        )
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
        story.append(Paragraph(f"Generado (UTC): {generated_at}", styles["Normal"]))
        story.append(Spacer(1, 6))

        trip_summary = [
            ["Telefono", phone],
            ["ID Viaje", trip_id],
            ["Destino", str(trip.get("destination", "") or "-")],
            ["Pais", str(trip.get("country", "") or "-")],
            ["Fecha Inicio", str(trip.get("start_date", "") or "-")],
            ["Fecha Fin", str(trip.get("end_date", "") or "-")],
            ["Boletas", str(len(report_data["detail_rows"]))],
            ["Total CLP", self._format_clp(report_data["total_clp"])],
        ]
        trip_table = Table(trip_summary, colWidths=[45 * mm, 130 * mm])
        trip_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        story.append(trip_table)
        story.append(Spacer(1, 10))

        story.append(Paragraph("Resumen por categoria (CLP)", styles["Heading3"]))
        category_rows = [["Categoria", "Total CLP"]]
        for category, amount in report_data["by_category"]:
            category_rows.append([category, self._format_clp(amount)])
        if len(category_rows) == 1:
            category_rows.append(["Sin boletas", "0"])
        category_table = Table(category_rows, colWidths=[110 * mm, 65 * mm])
        category_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ]
            )
        )
        story.append(category_table)
        story.append(Spacer(1, 10))

        story.append(Paragraph("Resumen por dia (CLP)", styles["Heading3"]))
        day_rows = [["Fecha", "Total CLP"]]
        for day, amount in report_data["by_day"]:
            day_rows.append([day, self._format_clp(amount)])
        if len(day_rows) == 1:
            day_rows.append(["Sin boletas", "0"])
        day_table = Table(day_rows, colWidths=[110 * mm, 65 * mm])
        day_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFEFEF")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (1, 1), (1, -1), "RIGHT"),
                ]
            )
        )
        story.append(day_table)
        story.append(Spacer(1, 10))

        story.append(Paragraph("Detalle de boletas", styles["Heading3"]))
        detail_rows: list[list[Any]] = [
            [
                Paragraph("Boleta", detail_label_style),
                Paragraph("Detalle", detail_label_style),
                Paragraph("Imagen boleta", detail_label_style),
            ]
        ]
        for row in report_data["detail_rows"]:
            expense_summary = Paragraph(
                (
                    f"<b>Fecha:</b> {self._escape_text(row['date'])}<br/>"
                    f"<b>Categoria:</b> {self._escape_text(row['category'])}<br/>"
                    f"<b>Moneda:</b> {self._escape_text(row['currency'])}<br/>"
                    f"<b>Total:</b> {self._escape_text(self._format_generic_amount(row['total']))}<br/>"
                    f"<b>Total CLP:</b> {self._escape_text(self._format_clp(row['total_clp']))}"
                ),
                detail_value_style,
            )
            detail_text = Paragraph(
                (
                    f"<b>Comercio:</b> {self._escape_text(row['merchant'])}<br/>"
                    f"<b>ID gasto:</b> {self._escape_text(row['expense_id'])}<br/>"
                    f"<b>Referencia:</b> {self._escape_text(row['receipt_reference'])}"
                ),
                detail_value_style,
            )
            receipt_image = self._build_receipt_preview_flowable(
                row=row,
                image_class=Image,
                paragraph_class=Paragraph,
                text_style=detail_value_style,
                mm=mm,
            )
            detail_rows.append(
                [
                    expense_summary,
                    detail_text,
                    receipt_image,
                ]
            )
        if len(detail_rows) == 1:
            detail_rows.append(
                [
                    Paragraph("-", detail_value_style),
                    Paragraph("Sin boletas", detail_value_style),
                    Paragraph("Sin imagen", detail_value_style),
                ]
            )

        detail_table = Table(
            detail_rows,
            colWidths=[42 * mm, 84 * mm, 48 * mm],
            repeatRows=1,
        )
        detail_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCE6F2")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FBFF")]),
                ]
            )
        )
        story.append(detail_table)
        story.append(PageBreak())
        story.extend(
            self._build_signature_section(
                phone=phone,
                trip=trip,
                paragraph_class=Paragraph,
                spacer_class=Spacer,
                table_class=Table,
                table_style_class=TableStyle,
                text_style=styles["Normal"],
                heading_style=styles["Heading3"],
                mm=mm,
                colors=colors,
            )
        )

        doc.build(story)
        return stream.getvalue()

    def _format_clp(self, amount: float) -> str:
        rounded = int(round(amount))
        return f"CLP {rounded:,}"

    def _format_generic_amount(self, amount: float) -> str:
        return f"{amount:,.2f}"

    def _build_receipt_preview_flowable(
        self,
        *,
        row: dict[str, Any],
        image_class,
        paragraph_class,
        text_style,
        mm,
    ):
        provider = str(row.get("receipt_storage_provider", "") or "").strip().lower()
        object_key = str(row.get("receipt_object_key", "") or "").strip()
        if provider != "gcs" or not object_key:
            return paragraph_class("Imagen no disponible", text_style)

        if object_key.lower().endswith(".pdf"):
            return paragraph_class("Boleta en PDF (sin miniatura)", text_style)

        try:
            signed_url = self.storage_service.generate_signed_url(object_key=object_key)
            request = Request(signed_url, headers={"User-Agent": "TravelExpenseAgent/1.0"})
            with urlopen(request, timeout=20) as response:
                content = response.read()
            if not content:
                return paragraph_class("Imagen no disponible", text_style)
            image_flowable = image_class(BytesIO(content))
            self._fit_image_size(image_flowable, max_width=44 * mm, max_height=34 * mm)
            return image_flowable
        except (HTTPError, URLError, RuntimeError, ValueError):
            return paragraph_class("Error descargando imagen", text_style)
        except Exception:
            return paragraph_class("Miniatura no disponible", text_style)

    def _fit_image_size(self, image_flowable, *, max_width: float, max_height: float) -> None:
        width = float(getattr(image_flowable, "imageWidth", 0) or 0)
        height = float(getattr(image_flowable, "imageHeight", 0) or 0)
        if width <= 0 or height <= 0:
            image_flowable.drawWidth = max_width
            image_flowable.drawHeight = max_height
            return
        scale = min(max_width / width, max_height / height)
        scale = min(scale, 1.0)
        image_flowable.drawWidth = width * scale
        image_flowable.drawHeight = height * scale

    def _escape_text(self, value: Any) -> str:
        text = str(value or "")
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _build_header_with_logo(
        self,
        *,
        trip_id: str,
        image_class,
        paragraph_class,
        spacer_class,
        table_class,
        table_style_class,
        text_style,
        mm,
    ) -> list[Any]:
        logo_flowable: Any = paragraph_class("", text_style)
        logo_path = self._resolve_logo_path()
        if logo_path:
            try:
                logo_image = image_class(str(logo_path))
                self._fit_image_size(logo_image, max_width=34 * mm, max_height=18 * mm)
                logo_flowable = logo_image
            except Exception:
                logo_flowable = paragraph_class("", text_style)

        title = paragraph_class(
            f"<b>Reporte Consolidado de Viaticos</b><br/>Viaje: {self._escape_text(trip_id)}",
            text_style,
        )
        header_table = table_class([[title, logo_flowable]], colWidths=[140 * mm, 35 * mm])
        header_table.setStyle(
            table_style_class(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        return [header_table, spacer_class(1, 6)]

    def _build_signature_section(
        self,
        *,
        phone: str,
        trip: dict[str, Any],
        paragraph_class,
        spacer_class,
        table_class,
        table_style_class,
        text_style,
        heading_style,
        mm,
        colors,
    ) -> list[Any]:
        employee = self.sheets_service.get_employee_by_phone(phone) or {}
        full_name = str(employee.get("name", "") or "").strip() or "Nombre no informado"
        rut = str(employee.get("rut", "") or "").strip() or "RUT no informado"
        destination = str(trip.get("destination", "") or "").strip() or "-"
        signed_at = datetime.now(timezone.utc)
        signed_day = signed_at.strftime("%d")
        signed_month = signed_at.strftime("%m")
        signed_year = signed_at.strftime("%Y")

        items: list[Any] = [
            paragraph_class("Firma del colaborador", heading_style),
            spacer_class(1, 8),
            paragraph_class(
                (
                    "Al firmar este documento, el colaborador declara que la información "
                    "registrada en este reporte de viáticos es correcta y completa."
                ),
                text_style,
            ),
            spacer_class(1, 8),
            paragraph_class(
                (
                    "Los desembolsos anteriores señalados han sido necesarios para la "
                    "realización de la labor encomendada a mi persona."
                ),
                text_style,
            ),
            spacer_class(1, 8),
            paragraph_class(
                (
                    "Me afirmo y ratifico con lo expresado, en señal de lo cual firmo el "
                    f"presente documento en la ciudad de {self._escape_text(destination)}, "
                    f"al día {signed_day} del mes {signed_month} de {signed_year}."
                ),
                text_style,
            ),
            spacer_class(1, 12),
        ]

        signature_placeholder = paragraph_class(
            (
                "<b>Firma:</b><br/><br/><br/>"
                "<font size='1'>[[DS_SIGN_HERE]]</font>"
            ),
            text_style,
        )

        signature_box = table_class(
            [
                ["Firma del colaborador", signature_placeholder],
                ["Nombre completo", full_name],
                ["RUT", rut],
                ["Destino", destination],
            ],
            colWidths=[48 * mm, 122 * mm],
            rowHeights=[38 * mm, 12 * mm, 12 * mm, 12 * mm],
        )
        signature_box.setStyle(
            table_style_class(
                [
                    ("GRID", (0, 0), (-1, -1), 0.8, colors.black),
                    ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 1), (1, -1), "Helvetica"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        items.append(signature_box)
        items.append(spacer_class(1, 8))
        manager_box = table_class(
            [
                ["Firma gerente de área", ""],
                ["Nombre completo", "Rodrigo Guajardo"],
                ["RUT", "18.638.282-8"],
                ["Cargo", "Gerente de área"],
            ],
            colWidths=[48 * mm, 122 * mm],
            rowHeights=[32 * mm, 12 * mm, 12 * mm, 12 * mm],
        )
        manager_box.setStyle(
            table_style_class(
                [
                    ("GRID", (0, 0), (-1, -1), 0.8, colors.black),
                    ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                    ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                    ("FONTNAME", (1, 1), (1, -1), "Helvetica"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        items.append(manager_box)
        items.append(spacer_class(1, 8))
        items.append(
            paragraph_class(
                "La firma electrónica del colaborador debe quedar dentro del recuadro superior derecho.",
                text_style,
            )
        )
        return items

    def _resolve_logo_path(self) -> Path | None:
        raw_path = str(self.storage_service.settings.consolidated_report_logo_path or "").strip()
        if not raw_path:
            return None

        configured = Path(raw_path).expanduser()
        project_root = Path(__file__).resolve().parents[1]
        candidates = [configured]
        if not configured.is_absolute():
            candidates.append((Path.cwd() / configured).resolve())
            candidates.append((project_root / configured).resolve())

        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate

        logger.warning(
            "Consolidated report logo not found. configured_path=%s cwd=%s project_root=%s",
            raw_path,
            Path.cwd(),
            project_root,
        )
        return None
