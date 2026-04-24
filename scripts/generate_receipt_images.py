#!/usr/bin/env python3
"""Genera imágenes sintéticas de boletas y facturas chilenas.

Uso:
  python scripts/generate_receipt_images.py --count 10 --output-dir /tmp/receipts
  python scripts/generate_receipt_images.py --count 1 --type factura --merchant Starbucks
"""

from __future__ import annotations

import argparse
import math
import os
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ── Merchant pool ──────────────────────────────────────────────────

MERCHANTS = [
    ("Starbucks Coffee", "Av. Providencia 2124, Providencia"),
    ("Presto", "Av. Libertador B. O'Higgins 949, Santiago"),
    ("Juan Maestro", "Paseo Huérfanos 1055, Santiago"),
    ("McDonald's", "Av. Apoquindo 3200, Las Condes"),
    ("Copec", "Ruta 5 Sur Km 15, Santiago"),
    ("Shell", "Av. Vicuña Mackenna 1234, Ñuñoa"),
    ("Uber", "Santiago, Chile"),
    ("Farmacias Cruz Verde", "Av. Irarrázaval 2401, Ñuñoa"),
    ("Falabella", "Av. Kennedy 9001, Las Condes"),
    ("Jumbo", "Av. Las Condes 13451, Las Condes"),
    ("Líder Express", "Av. Matta 1150, Santiago Centro"),
    ("Hotel Marriott", "Av. Kennedy 5741, Las Condes"),
    ("Hotel Crowne Plaza", "Av. Libertador B. O'Higgins 136, Santiago"),
    ("Café Colonia", "Av. Italia 1298, Providencia"),
    ("Restaurant El Caramaño", "San Pablo 1295, Santiago"),
    ("Sodimac", "Camino Melipilla 8780, Cerrillos"),
    ("LATAM Airlines", "Santiago, Chile"),
    ("Easy", "Av. Américo Vespucio 1801, Cerrillos"),
    ("Cencosud", "Av. Kennedy 9001, Las Condes"),
    ("Telepizza", "Av. Providencia 1650, Providencia"),
    ("Papa John's", "Merced 838, Santiago Centro"),
    ("Doggis", "Av. Apoquindo 4500, Las Condes"),
]

ITEM_POOL = [
    "Café americano", "Café latte", "Cappuccino", "Sándwich jamón queso",
    "Empanada de pino", "Completo italiano", "Hamburguesa clásica",
    "Papas fritas", "Bebida 500ml", "Agua mineral", "Jugo natural",
    "Ensalada César", "Pizza margarita", "Almuerzo ejecutivo",
    "Combustible 95", "Diesel", "Lavado auto", "Estacionamiento",
    "Hospedaje 1 noche", "Room service", "Minibar", "Lavandería",
    "Pasaje aéreo", "Taxi aeropuerto", "Peaje", "Medicamento",
    "Útiles oficina", "Impresión documentos", "Cena ejecutiva",
]

PAYMENT_METHODS = [
    "Tarjeta de Débito", "Tarjeta de Crédito", "Efectivo",
    "Transferencia", "Tarjeta Prepago",
]


# ── RUT generation ─────────────────────────────────────────────────

def _compute_rut_dv(body: int) -> str:
    """Dígito verificador con módulo 11."""
    s = 0
    multiplier = 2
    for digit in reversed(str(body)):
        s += int(digit) * multiplier
        multiplier = multiplier + 1 if multiplier < 7 else 2
    remainder = 11 - (s % 11)
    if remainder == 11:
        return "0"
    if remainder == 10:
        return "K"
    return str(remainder)


def generate_rut() -> str:
    body = random.randint(50_000_000, 99_999_999)
    dv = _compute_rut_dv(body)
    formatted = f"{body:,}".replace(",", ".")
    return f"{formatted}-{dv}"


# ── Data model ─────────────────────────────────────────────────────

@dataclass
class ReceiptData:
    merchant: str
    address: str
    rut: str
    date: str
    items: list[tuple[str, int]] = field(default_factory=list)
    total: int = 0
    document_type: str = "boleta"  # boleta | factura
    folio: str = ""
    payment_method: str = ""
    net_amount: int = 0
    iva_amount: int = 0


def generate_random_receipt(
    *,
    document_type: str | None = None,
    merchant_name: str | None = None,
) -> ReceiptData:
    if merchant_name:
        match = next((m for m in MERCHANTS if merchant_name.lower() in m[0].lower()), None)
        if match:
            merchant, address = match
        else:
            merchant, address = merchant_name, "Santiago, Chile"
    else:
        merchant, address = random.choice(MERCHANTS)

    doc_type = document_type or (random.choices(["boleta", "factura"], weights=[70, 30])[0])
    num_items = random.randint(1, 6)
    items: list[tuple[str, int]] = []
    for _ in range(num_items):
        item_name = random.choice(ITEM_POOL)
        price = random.randint(800, 35_000)
        price = round(price / 100) * 100  # round to nearest 100
        items.append((item_name, price))

    subtotal = sum(p for _, p in items)

    if doc_type == "factura":
        net_amount = subtotal
        iva_amount = math.ceil(net_amount * 0.19)
        total = net_amount + iva_amount
    else:
        total = subtotal
        net_amount = 0
        iva_amount = 0

    receipt_date = date.today() - timedelta(days=random.randint(0, 30))

    return ReceiptData(
        merchant=merchant,
        address=address,
        rut=generate_rut(),
        date=receipt_date.strftime("%d/%m/%Y"),
        items=items,
        total=total,
        document_type=doc_type,
        folio=str(random.randint(1000, 99999)).zfill(8),
        payment_method=random.choice(PAYMENT_METHODS),
        net_amount=net_amount,
        iva_amount=iva_amount,
    )


# ── Image renderer ─────────────────────────────────────────────────

def _get_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    mono_paths = [
        "/System/Library/Fonts/Courier.dfont",
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ]
    for p in mono_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render_receipt_image(data: ReceiptData) -> bytes:
    width = 420
    margin = 20
    line_height_small = 16
    line_height_normal = 20
    line_height_large = 26

    # Pre-calculate height
    height = 60  # top margin + header
    height += line_height_large  # merchant
    height += line_height_small * 3  # address, rut, separator
    height += line_height_large  # document type
    height += line_height_normal  # folio
    height += line_height_normal  # date
    height += line_height_small  # separator
    height += line_height_normal * len(data.items)  # items
    height += line_height_small  # separator
    if data.document_type == "factura":
        height += line_height_normal * 3  # net, iva, total
    else:
        height += line_height_large  # total
    height += line_height_normal  # payment
    height += line_height_small * 3  # separator + sii + footer
    height += 40  # bottom margin

    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    font_small = _get_font(11)
    font_normal = _get_font(13)
    font_large = _get_font(16)
    font_title = _get_font(18)

    y = 20
    sep = "─" * 40

    # Header
    draw.text((margin, y), data.merchant.upper(), fill="black", font=font_title)
    y += line_height_large
    draw.text((margin, y), data.address, fill="gray", font=font_small)
    y += line_height_small
    draw.text((margin, y), f"RUT: {data.rut}", fill="gray", font=font_small)
    y += line_height_small + 4

    # Separator
    draw.text((margin, y), sep, fill="gray", font=font_small)
    y += line_height_small

    # Document type
    doc_label = "BOLETA ELECTRÓNICA" if data.document_type == "boleta" else "FACTURA ELECTRÓNICA"
    draw.text((margin, y), doc_label, fill="black", font=font_large)
    y += line_height_large

    # Folio and date
    draw.text((margin, y), f"Folio: {data.folio}", fill="black", font=font_normal)
    y += line_height_normal
    draw.text((margin, y), f"Fecha: {data.date}", fill="black", font=font_normal)
    y += line_height_normal + 4

    # Separator
    draw.text((margin, y), sep, fill="gray", font=font_small)
    y += line_height_small

    # Items
    for item_name, price in data.items:
        price_str = f"${price:,}".replace(",", ".")
        draw.text((margin, y), item_name, fill="black", font=font_normal)
        draw.text((width - margin - 80, y), price_str, fill="black", font=font_normal)
        y += line_height_normal

    # Separator
    draw.text((margin, y), sep, fill="gray", font=font_small)
    y += line_height_small + 4

    # Total section
    if data.document_type == "factura":
        net_str = f"${data.net_amount:,}".replace(",", ".")
        iva_str = f"${data.iva_amount:,}".replace(",", ".")
        total_str = f"${data.total:,}".replace(",", ".")
        draw.text((margin, y), "NETO:", fill="black", font=font_normal)
        draw.text((width - margin - 80, y), net_str, fill="black", font=font_normal)
        y += line_height_normal
        draw.text((margin, y), "IVA 19%:", fill="black", font=font_normal)
        draw.text((width - margin - 80, y), iva_str, fill="black", font=font_normal)
        y += line_height_normal
        draw.text((margin, y), "TOTAL:", fill="black", font=font_large)
        draw.text((width - margin - 80, y), total_str, fill="black", font=font_large)
        y += line_height_large
    else:
        total_str = f"${data.total:,}".replace(",", ".")
        draw.text((margin, y), "TOTAL:", fill="black", font=font_large)
        draw.text((width - margin - 80, y), total_str, fill="black", font=font_large)
        y += line_height_large

    y += 4
    draw.text((margin, y), f"Pago: {data.payment_method}", fill="gray", font=font_small)
    y += line_height_small + 8

    # Footer
    draw.text((margin, y), sep, fill="gray", font=font_small)
    y += line_height_small
    draw.text((margin, y), "Timbre Electrónico SII.CL", fill="gray", font=font_small)
    y += line_height_small
    draw.text((margin, y), "Res. Ex. SII N°80 - Verifique en www.sii.cl", fill="gray", font=font_small)

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def generate_filename(data: ReceiptData, index: int) -> str:
    """Genera filename con hints para _placeholder_extract del OCR."""
    merchant_slug = data.merchant.lower().split()[0].replace("'", "")
    return f"{data.document_type}_{merchant_slug}_{index:03d}.png"


# ── CLI ────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Genera boletas/facturas chilenas sintéticas")
    parser.add_argument("--count", type=int, default=5, help="Cantidad de imágenes a generar")
    parser.add_argument("--output-dir", default="/tmp/receipts", help="Directorio de salida")
    parser.add_argument("--type", choices=["boleta", "factura"], default=None, help="Forzar tipo de documento")
    parser.add_argument("--merchant", default=None, help="Forzar nombre de merchant")
    args = parser.parse_args()

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)

    for i in range(args.count):
        data = generate_random_receipt(document_type=args.type, merchant_name=args.merchant)
        img_bytes = render_receipt_image(data)
        filename = generate_filename(data, i + 1)
        path = output / filename
        path.write_bytes(img_bytes)
        print(f"  {filename}  ({data.document_type}, {data.merchant}, ${data.total:,} CLP)")

    print(f"\n{args.count} imágenes generadas en {output}")


if __name__ == "__main__":
    main()
