#!/usr/bin/env python3
"""Simula conversaciones WhatsApp completas contra el servidor local.

Genera boletas sintéticas, las sirve via HTTP local, y envía mensajes
al endpoint /test/simulate para probar el flujo de principio a fin.

Uso:
  python scripts/simulate_conversation.py --phone +56912345678 --count 1 --verbose
  python scripts/simulate_conversation.py --phone +56912345678 --count 5
  python scripts/simulate_conversation.py --phone +56912345678 --scenario correction

Requiere que el servidor esté corriendo:
  python -m uvicorn app.main:app --reload
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

import requests

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.generate_receipt_images import generate_random_receipt, render_receipt_image, generate_filename


# ── Local media server ─────────────────────────────────────────────

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        pass  # suppress request logs


def start_media_server(directory: str, port: int = 8001) -> HTTPServer:
    os.chdir(directory)
    server = HTTPServer(("127.0.0.1", port), QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ── Simulator ──────────────────────────────────────────────────────

class ConversationSimulator:
    def __init__(
        self,
        phone: str,
        server_url: str = "http://localhost:8000",
        media_server_url: str = "http://localhost:8001",
        verbose: bool = False,
    ):
        self.phone = phone
        self.server_url = server_url.rstrip("/")
        self.media_server_url = media_server_url.rstrip("/")
        self.verbose = verbose
        self.log: list[tuple[str, str]] = []

    def send_media(self, media_url: str, content_type: str = "image/png") -> dict:
        resp = requests.post(
            f"{self.server_url}/test/simulate",
            json={
                "phone": self.phone,
                "type": "media",
                "media_url": media_url,
                "media_content_type": content_type,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._log("bot", data.get("reply", ""))
        return data

    def send_text(self, body: str) -> dict:
        self._log("user", body)
        resp = requests.post(
            f"{self.server_url}/test/simulate",
            json={
                "phone": self.phone,
                "type": "text",
                "body": body,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self._log("bot", data.get("reply", ""))
        return data

    def reset(self) -> None:
        resp = requests.post(
            f"{self.server_url}/test/reset",
            json={"phone": self.phone},
            timeout=10,
        )
        resp.raise_for_status()
        self.log = []
        if self.verbose:
            print("  [reset] Conversación reseteada a WAIT_RECEIPT")

    def auto_answer(self, bot_reply: str) -> str:
        """Genera respuesta automática basada en la pregunta del bot."""
        reply_lower = bot_reply.lower()

        # Currency selection
        if "moneda" in reply_lower or "currency" in reply_lower:
            return "1"  # CLP

        # Category selection
        if "categoría" in reply_lower or "category" in reply_lower:
            return "1"  # first option

        # Country selection
        if "país" in reply_lower or "country" in reply_lower:
            return "1"  # Chile

        # Document type
        if ("boleta" in reply_lower and "factura" in reply_lower and
                ("tipo" in reply_lower or "qué" in reply_lower or "selecciona" in reply_lower)):
            return "1"  # boleta

        # Merchant
        if "comercio" in reply_lower or "merchant" in reply_lower or "nombre del" in reply_lower:
            return "Restaurante Test"

        # Date
        if "fecha" in reply_lower or "date" in reply_lower:
            from datetime import date
            return date.today().strftime("%d/%m/%Y")

        # Total
        if "total" in reply_lower or "monto" in reply_lower:
            return "15000"

        # Generic numbered option
        return "1"

    def is_waiting_for_input(self, data: dict) -> bool:
        state = data.get("state", "")
        return state in ("NEEDS_INFO", "CONFIRM_SUMMARY")

    def is_needs_info(self, data: dict) -> bool:
        return data.get("state", "") == "NEEDS_INFO"

    def is_confirm_summary(self, data: dict) -> bool:
        return data.get("state", "") == "CONFIRM_SUMMARY"

    def is_done(self, data: dict) -> bool:
        state = data.get("state", "")
        reply = data.get("reply", "").lower()
        return state == "WAIT_RECEIPT" and ("guardado" in reply or "gasto" in reply)

    def run_happy_path(self, receipt_filename: str) -> dict:
        """Flujo completo: enviar imagen → responder preguntas → confirmar."""
        media_url = f"{self.media_server_url}/{receipt_filename}"
        self._log("user", f"[imagen: {receipt_filename}]")

        # Step 1: Send image
        data = self.send_media(media_url)

        # Step 2: Answer bot questions (NEEDS_INFO)
        max_turns = 15
        turns = 0
        while self.is_needs_info(data) and turns < max_turns:
            answer = self.auto_answer(data.get("reply", ""))
            data = self.send_text(answer)
            turns += 1

        # Step 3: Confirm summary
        if self.is_confirm_summary(data):
            data = self.send_text("1")  # confirmar

        # Check for save result (could be multi-message)
        success = "guardado" in data.get("reply", "").lower()

        return {
            "success": success,
            "final_state": data.get("state", ""),
            "final_reply": data.get("reply", ""),
            "turns": turns + 2,  # +1 for media, +1 for confirm
        }

    def run_correction_flow(self, receipt_filename: str) -> dict:
        """Flujo con corrección: enviar imagen → llegar a summary → corregir → confirmar."""
        media_url = f"{self.media_server_url}/{receipt_filename}"
        self._log("user", f"[imagen: {receipt_filename}]")

        data = self.send_media(media_url)
        max_turns = 15
        turns = 0
        while self.is_needs_info(data) and turns < max_turns:
            answer = self.auto_answer(data.get("reply", ""))
            data = self.send_text(answer)
            turns += 1

        if self.is_confirm_summary(data):
            # Send "2" to correct
            data = self.send_text("2")
            # Select field to correct (e.g., "1" for first option)
            if self.is_confirm_summary(data) or "corregir" in data.get("reply", "").lower() or "campo" in data.get("reply", "").lower():
                data = self.send_text("1")
                # Provide new value
                data = self.send_text("Starbucks Corregido")
                # Should go back to CONFIRM_SUMMARY or NEEDS_INFO
                while self.is_needs_info(data) and turns < max_turns:
                    answer = self.auto_answer(data.get("reply", ""))
                    data = self.send_text(answer)
                    turns += 1
                if self.is_confirm_summary(data):
                    data = self.send_text("1")  # confirm

        success = "guardado" in data.get("reply", "").lower()
        return {
            "success": success,
            "final_state": data.get("state", ""),
            "final_reply": data.get("reply", ""),
            "turns": turns,
            "scenario": "correction",
        }

    def run_cancel_flow(self, receipt_filename: str) -> dict:
        """Flujo con cancelación en medio."""
        media_url = f"{self.media_server_url}/{receipt_filename}"
        self._log("user", f"[imagen: {receipt_filename}]")

        data = self.send_media(media_url)
        # Cancel immediately
        data = self.send_text("cancelar")

        cancelled = "cancelado" in data.get("reply", "").lower() or "reiniciado" in data.get("reply", "").lower()
        return {
            "success": cancelled,
            "final_state": data.get("state", ""),
            "final_reply": data.get("reply", ""),
            "scenario": "cancel",
        }

    def _log(self, role: str, text: str) -> None:
        self.log.append((role, text))
        if self.verbose:
            prefix = "  👤" if role == "user" else "  🤖"
            # Truncate long messages for display
            display = text[:200] + "..." if len(text) > 200 else text
            for line in display.split("\n"):
                print(f"{prefix} {line}")
                prefix = "    "

    def print_summary(self, result: dict, receipt_idx: int) -> None:
        status_icon = "✅" if result.get("success") else "❌"
        scenario = result.get("scenario", "happy_path")
        print(f"  {status_icon} Boleta #{receipt_idx}: {scenario} — state={result.get('final_state', '?')} turns={result.get('turns', '?')}")


# ── Main ───────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Simula conversaciones WhatsApp con boletas sintéticas")
    parser.add_argument("--phone", required=True, help="Teléfono E.164 del empleado de prueba")
    parser.add_argument("--count", type=int, default=1, help="Cantidad de boletas a enviar")
    parser.add_argument("--server", default="http://localhost:8000", help="URL del servidor FastAPI")
    parser.add_argument("--media-port", type=int, default=8001, help="Puerto del media server local")
    parser.add_argument("--verbose", "-v", action="store_true", help="Mostrar conversación completa")
    parser.add_argument(
        "--scenario",
        choices=["happy", "correction", "cancel", "mixed"],
        default="happy",
        help="Escenario a ejecutar",
    )
    parser.add_argument("--no-reset", action="store_true", help="No resetear conversación antes de cada boleta")
    args = parser.parse_args()

    # 1. Generate receipt images
    tmp_dir = Path("/tmp/sim_receipts")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    receipts = []
    for i in range(args.count):
        data = generate_random_receipt()
        img_bytes = render_receipt_image(data)
        filename = generate_filename(data, i + 1)
        (tmp_dir / filename).write_bytes(img_bytes)
        receipts.append((filename, data))

    # 2. Start local media server
    media_server = start_media_server(str(tmp_dir), args.media_port)
    media_url = f"http://localhost:{args.media_port}"

    # 3. Verify server is up
    try:
        resp = requests.get(f"{args.server}/health", timeout=5)
        resp.raise_for_status()
        print(f"Servidor OK: {args.server}")
    except Exception as e:
        print(f"Error: no se puede conectar al servidor en {args.server}")
        print(f"  {e}")
        print("Asegúrate de que esté corriendo: python -m uvicorn app.main:app --reload")
        return

    # 4. Run simulations
    sim = ConversationSimulator(
        phone=args.phone,
        server_url=args.server,
        media_server_url=media_url,
        verbose=args.verbose,
    )

    print(f"\nSimulando {args.count} conversación(es) para {args.phone}...")
    print(f"Escenario: {args.scenario}\n")

    successes = 0
    failures = 0

    for i, (filename, receipt_data) in enumerate(receipts, 1):
        if not args.no_reset:
            sim.reset()

        if args.verbose:
            print(f"\n{'─' * 50}")
            print(f"Boleta #{i}: {receipt_data.merchant} — ${receipt_data.total:,} CLP ({receipt_data.document_type})")
            print(f"{'─' * 50}")

        try:
            if args.scenario == "happy":
                result = sim.run_happy_path(filename)
            elif args.scenario == "correction":
                result = sim.run_correction_flow(filename)
            elif args.scenario == "cancel":
                result = sim.run_cancel_flow(filename)
            elif args.scenario == "mixed":
                scenarios = ["happy", "correction", "cancel"]
                scenario_choice = scenarios[i % len(scenarios)]
                if scenario_choice == "happy":
                    result = sim.run_happy_path(filename)
                elif scenario_choice == "correction":
                    result = sim.run_correction_flow(filename)
                else:
                    result = sim.run_cancel_flow(filename)
            else:
                result = sim.run_happy_path(filename)

            sim.print_summary(result, i)

            if result.get("success"):
                successes += 1
            else:
                failures += 1

        except requests.exceptions.RequestException as e:
            print(f"  ❌ Boleta #{i}: error de conexión — {e}")
            failures += 1
        except Exception as e:
            print(f"  ❌ Boleta #{i}: error inesperado — {e}")
            failures += 1

    # 5. Summary
    print(f"\n{'═' * 50}")
    print(f"Resultado: {successes}/{args.count} exitosas, {failures} fallidas")
    print(f"{'═' * 50}")

    # Cleanup
    media_server.shutdown()


if __name__ == "__main__":
    main()
