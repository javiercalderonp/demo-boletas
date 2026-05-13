from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.expense_service import DOCUMENT_CLASSIFICATION_CONFIDENCE_THRESHOLD, ExpenseService
from utils.helpers import json_loads


WAIT_RECEIPT = "WAIT_RECEIPT"
PROCESSING = "PROCESSING"
NEEDS_INFO = "NEEDS_INFO"
CONFIRM_SUMMARY = "CONFIRM_SUMMARY"
DONE = "DONE"
WAIT_SUBMISSION_CLOSURE_CONFIRMATION = "WAIT_SUBMISSION_CLOSURE_CONFIRMATION"

FIELD_PROMPTS = {
    "document_type": "No pude identificar con seguridad si este documento es una boleta, factura o boleta de honorarios. ¿Cuál es?",
    "merchant": "¿Cuál es el comercio/merchant?",
    "date": "¿Cuál es la fecha? (formato YYYY-MM-DD)",
    "total": "¿Cuál es el total del gasto? (solo número)",
    "currency": "¿Cuál es la moneda?\n1. CLP\n2. USD\n3. PEN\n4. CNY\n5. EUR",
    "category": "¿Cuál es la categoría?\n1. Meals\n2. Transport\n3. Lodging\n4. Other",
    "country": "¿En qué país fue el gasto?\n1. Chile\n2. Peru\n3. China\n4. Otro (escribir texto)",
}

DOCUMENT_TYPE_OPTIONS = {"1": "receipt", "2": "invoice", "3": "professional_fee_receipt"}
DOCUMENT_TYPE_LABELS = {
    "receipt": "boleta",
    "invoice": "factura",
    "professional_fee_receipt": "boleta de honorarios",
}

CURRENCY_OPTIONS = {"1": "CLP", "2": "USD", "3": "PEN", "4": "CNY", "5": "EUR"}
CATEGORY_OPTIONS = {"1": "Meals", "2": "Transport", "3": "Lodging", "4": "Other"}
COUNTRY_OPTIONS = {"1": "Chile", "2": "Peru", "3": "China"}
OTHER_COUNTRY_SENTINEL = "__other_country__"
CORRECTION_FIELD_OPTIONS = {
    "1": "merchant",
    "2": "date",
    "3": "total",
    "4": "currency",
    "5": "category",
    "6": "country",
}
CORRECTION_FIELD_ALIASES = {
    "merchant": "merchant",
    "comercio": "merchant",
    "tienda": "merchant",
    "fecha": "date",
    "date": "date",
    "total": "total",
    "monto": "total",
    "importe": "total",
    "moneda": "currency",
    "currency": "currency",
    "categoria": "category",
    "categoría": "category",
    "category": "category",
    "pais": "country",
    "país": "country",
    "country": "country",
}
CORRECTION_FIELD_LABELS = {
    "merchant": "merchant",
    "date": "fecha",
    "total": "total",
    "currency": "moneda",
    "category": "categoría",
    "country": "país",
}


@dataclass
class ConversationService:
    expense_service: ExpenseService

    def default_context(self) -> dict[str, Any]:
        return {
            "draft_expense": {},
            "missing_fields": [],
            "last_question": None,
            "message_log": [],
            "scheduler": {"sent_reminders": {}},
            "submission_closure": {},
            "trip_closure": {},
        }

    def ensure_conversation(self, conversation: dict[str, Any] | None) -> dict[str, Any]:
        if not conversation:
            return {
                "state": WAIT_RECEIPT,
                "current_step": "",
                "context_json": self.default_context(),
            }
        context = conversation.get("context_json")
        if isinstance(context, str):
            context = json_loads(context, default=self.default_context())
        if not isinstance(context, dict):
            context = self.default_context()
        scheduler_ctx = context.get("scheduler")
        if not isinstance(scheduler_ctx, dict):
            scheduler_ctx = {"sent_reminders": {}}
        sent_reminders = scheduler_ctx.get("sent_reminders")
        if not isinstance(sent_reminders, dict):
            sent_reminders = {}
        normalized_context = dict(context)
        normalized_context["draft_expense"] = context.get("draft_expense", {})
        normalized_context["missing_fields"] = context.get("missing_fields", [])
        normalized_context["last_question"] = context.get("last_question")
        message_log = context.get("message_log")
        if not isinstance(message_log, list):
            message_log = []
        normalized_context["message_log"] = [item for item in message_log if isinstance(item, dict)]
        normalized_context["scheduler"] = {
            **scheduler_ctx,
            "sent_reminders": sent_reminders,
        }
        submission_closure = context.get("submission_closure", context.get("trip_closure"))
        if not isinstance(submission_closure, dict):
            submission_closure = {}
        normalized_context["submission_closure"] = submission_closure
        normalized_context["trip_closure"] = submission_closure
        conversation["context_json"] = normalized_context
        conversation.setdefault("state", WAIT_RECEIPT)
        conversation.setdefault("current_step", "")
        return conversation

    def begin_processing(self, phone: str) -> dict[str, Any]:
        return {
            "phone": phone,
            "state": PROCESSING,
            "current_step": "",
            "context_json": self.default_context(),
        }

    def process_ocr_result(
        self,
        phone: str,
        ocr_data: dict[str, Any],
        expense_case: dict[str, Any] | None,
    ) -> dict[str, Any]:
        draft = dict(ocr_data or {})
        if expense_case:
            draft.setdefault("case_id", expense_case.get("case_id"))
            draft.setdefault("cost_centers", expense_case.get("cost_centers", []))
            if not draft.get("country_hint"):
                draft["country_hint"] = expense_case.get("country")

        # Clasificar tipo de documento antes de enriquecer
        classification = self.expense_service.classify_document(draft)
        if classification:
            classified_type = classification.get("document_type", "unknown")
            confidence = classification.get("classification_confidence", 0.0)
            requires_confirmation = classification.get("requires_user_confirmation", False)

            # Mapear tipos internos de OCR a receipt/invoice
            if classified_type == "receipt":
                draft["document_type"] = "receipt"
            elif classified_type == "invoice":
                draft["document_type"] = "invoice"
            elif classified_type == "professional_fee_receipt":
                draft["document_type"] = "professional_fee_receipt"

            draft["classification_confidence"] = confidence
            draft["requires_user_confirmation"] = requires_confirmation

        draft = self.expense_service.enrich_draft_expense(draft)

        # Si el tipo de documento es incierto, preguntar al usuario primero
        if draft.get("requires_user_confirmation", False):
            return {
                "phone": phone,
                "state": NEEDS_INFO,
                "current_step": "document_type",
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": ["document_type"],
                    "last_question": "document_type",
                },
                "reply": self.prompt_for_field("document_type"),
            }

        missing = self.expense_service.find_missing_required_fields(draft)
        if missing:
            first_field = missing[0]
            return {
                "phone": phone,
                "state": NEEDS_INFO,
                "current_step": first_field,
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": missing,
                    "last_question": first_field,
                },
                "reply": self.prompt_for_field(first_field),
            }

        return {
            "phone": phone,
            "state": CONFIRM_SUMMARY,
            "current_step": "confirm_summary",
            "context_json": {
                "draft_expense": draft,
                "missing_fields": [],
                "last_question": None,
            },
            "reply": self.expense_service.build_summary_message(draft),
        }

    def handle_text_message(
        self,
        conversation: dict[str, Any],
        text: str,
        *,
        phone: str = "",
    ) -> dict[str, Any]:
        conversation = self.ensure_conversation(conversation)
        state = conversation.get("state", WAIT_RECEIPT)
        context = conversation["context_json"]
        message = (text or "").strip()
        normalized = message.lower()

        if normalized in {"cancelar", "cancel", "salir", "reiniciar", "reset"}:
            return {
                "state": WAIT_RECEIPT,
                "current_step": "",
                "context_json": self.default_context(),
                "reply": "Flujo cancelado y reiniciado. Envíame un comprobante para comenzar de nuevo.",
                "action": "cancel",
            }

        if state in {WAIT_RECEIPT, DONE}:
            # Build conversation history: all logged entries except the last one (current user message)
            raw_log = context.get("message_log", [])
            history_log = raw_log[:-1] if isinstance(raw_log, list) and raw_log else []

            # 1. Try heuristic direct answers first (no LLM needed)
            heuristic_answer = self._heuristic_answer(message, phone=phone)
            if heuristic_answer:
                return {
                    "state": WAIT_RECEIPT,
                    "current_step": "",
                    "context_json": context,
                    "reply": heuristic_answer,
                    "action": "noop",
                }

            # 2. Single LLM call with full case context and conversation history
            llm_reply = self.expense_service.chat_whatsapp_conversational(
                message, phone=phone, message_log=history_log
            )
            if llm_reply:
                return {
                    "state": WAIT_RECEIPT,
                    "current_step": "",
                    "context_json": context,
                    "reply": llm_reply,
                    "action": "noop",
                }

            # 3. No LLM — heuristic fallbacks for greetings and detected questions
            if self._is_greeting(normalized):
                return {
                    "state": WAIT_RECEIPT,
                    "current_step": "",
                    "context_json": context,
                    "reply": "¡Hola! Soy el asistente de rendición de gastos. Envíame una foto de tu boleta, factura o comprobante para registrarlo.",
                    "action": "noop",
                }
            if self._looks_like_question(message) or self._looks_like_rendicion_request(message):
                return {
                    "state": WAIT_RECEIPT,
                    "current_step": "",
                    "context_json": context,
                    "reply": "Puedo ayudarte con información de tu rendición activa o registrar gastos. Envíame una foto de tu boleta o comprobante cuando quieras.",
                    "action": "noop",
                }

            return {
                "state": WAIT_RECEIPT,
                "current_step": "",
                "context_json": context,
                "reply": "Envíame una foto de la boleta, factura o comprobante para procesar el gasto.",
                "action": "noop",
            }

        if state == PROCESSING:
            return {
                "state": PROCESSING,
                "current_step": "",
                "context_json": context,
                "reply": "Estoy procesando tu documento. Espera un momento o envía otra foto si quieres reintentar.",
                "action": "noop",
            }

        if state == NEEDS_INFO:
            return self._handle_needs_info(context, message, phone=phone)

        if state == CONFIRM_SUMMARY:
            return self._handle_confirm_summary(
                context=context,
                message=message,
                current_step=conversation.get("current_step", ""),
            )

        return {
            "state": WAIT_RECEIPT,
            "current_step": "",
            "context_json": self.default_context(),
            "reply": "No entendí el estado actual. Envíame un comprobante para comenzar.",
            "action": "reset",
        }

    def _handle_needs_info(self, context: dict[str, Any], message: str, *, phone: str = "") -> dict[str, Any]:
        draft = dict(context.get("draft_expense", {}))
        missing = list(context.get("missing_fields", []))
        current_field = missing[0] if missing else context.get("last_question")

        if not current_field:
            missing = self.expense_service.find_missing_required_fields(draft)
            current_field = missing[0] if missing else None

        if not current_field:
            return self._to_confirm_summary(draft)

        if current_field == "category":
            draft.pop("category", None)
            return self._to_confirm_summary(draft)

        parsed_value = self._parse_field_value(current_field, message)

        # Manejo especial para document_type
        if current_field == "document_type":
            parsed_value = self._parse_document_type_value(message)
            if parsed_value is None:
                return {
                    "state": NEEDS_INFO,
                    "current_step": "document_type",
                    "context_json": {
                        "draft_expense": draft,
                        "missing_fields": missing,
                        "last_question": "document_type",
                    },
                    "reply": "No entendí. Por favor indica si es boleta (1), factura (2) o boleta de honorarios (3).",
                    "action": "noop",
                }
            draft["document_type"] = parsed_value
            draft["requires_user_confirmation"] = False
            draft = self.expense_service.enrich_draft_expense(draft)
            missing = self.expense_service.find_missing_required_fields(draft)
            if missing:
                next_field = missing[0]
                doc_label = DOCUMENT_TYPE_LABELS.get(parsed_value, parsed_value)
                return {
                    "state": NEEDS_INFO,
                    "current_step": next_field,
                    "context_json": {
                        "draft_expense": draft,
                        "missing_fields": missing,
                        "last_question": next_field,
                    },
                    "reply": f"Perfecto, registrado como {doc_label}.\n{self.prompt_for_field(next_field)}",
                    "action": "noop",
                }
            return self._to_confirm_summary(draft)

        if current_field == "country" and parsed_value == OTHER_COUNTRY_SENTINEL:
            return {
                "state": NEEDS_INFO,
                "current_step": current_field,
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": missing,
                    "last_question": current_field,
                },
                "reply": "Escribe el país del gasto.",
                "action": "noop",
            }
        if parsed_value is None:
            answer = self._answer_general_question_if_needed(message, phone=phone)
            if answer:
                reply = (
                    f"{answer}\n\n"
                    f"Para continuar con este gasto:\n{self.prompt_for_field(current_field)}"
                )
            else:
                reply = f"No pude entender esa respuesta.\n{self.prompt_for_field(current_field)}"
            return {
                "state": NEEDS_INFO,
                "current_step": current_field,
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": missing,
                    "last_question": current_field,
                },
                "reply": reply,
                "action": "noop",
            }

        draft[current_field] = parsed_value
        if current_field == "country":
            inferred_currency = self.expense_service.infer_currency_from_country(parsed_value)
            if inferred_currency:
                draft["currency"] = inferred_currency
        draft = self.expense_service.enrich_draft_expense(draft)
        missing = self.expense_service.find_missing_required_fields(draft)

        if missing:
            next_field = missing[0]
            return {
                "state": NEEDS_INFO,
                "current_step": next_field,
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": missing,
                    "last_question": next_field,
                },
                "reply": self.prompt_for_field(next_field),
                "action": "noop",
            }

        return self._to_confirm_summary(draft)

    def _to_confirm_summary(self, draft: dict[str, Any]) -> dict[str, Any]:
        draft = self.expense_service.enrich_draft_expense(draft)
        return {
            "state": CONFIRM_SUMMARY,
            "current_step": "confirm_summary",
            "context_json": {
                "draft_expense": draft,
                "missing_fields": [],
                "last_question": None,
            },
            "reply": self.expense_service.build_summary_message(draft),
            "action": "noop",
        }

    def _handle_confirm_summary(
        self,
        context: dict[str, Any],
        message: str,
        current_step: str,
    ) -> dict[str, Any]:
        normalized = message.strip().lower()
        draft = dict(context.get("draft_expense", {}))

        if current_step == "select_correction_field":
            selected_field = self._parse_correction_field_choice(message)
            if selected_field:
                return self._to_needs_info_for_field(draft, selected_field)
            return {
                "state": CONFIRM_SUMMARY,
                "current_step": "select_correction_field",
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": [],
                    "last_question": None,
                },
                "reply": (
                    "No entendí qué campo quieres corregir.\n"
                    f"{self._build_correction_field_prompt()}"
                ),
                "action": "noop",
            }

        if current_step == "cost_center":
            if normalized in {"otra", "otro", "other", "manual"}:
                return {
                    "state": CONFIRM_SUMMARY,
                    "current_step": "cost_center",
                    "context_json": {
                        "draft_expense": draft,
                        "missing_fields": [],
                        "last_question": "cost_center",
                        "awaiting_manual_cost_center": True,
                    },
                    "reply": "Escribe el centro de costo manualmente.",
                    "action": "noop",
                }
            centers = self._get_draft_cost_centers(draft)
            cost_center = self._parse_cost_center_value(
                message,
                draft,
                allow_manual=bool(context.get("awaiting_manual_cost_center")),
            )
            if not cost_center and not message.strip().isdigit():
                cost_center = message.strip()
            if not cost_center:
                return {
                    "state": CONFIRM_SUMMARY,
                    "current_step": "cost_center",
                    "context_json": {
                        "draft_expense": draft,
                        "missing_fields": [],
                        "last_question": "cost_center",
                    },
                    "reply": self._build_cost_center_prompt(draft),
                    "action": "noop",
                }
            draft["cost_center"] = cost_center
            if cost_center.lower() not in {center.lower() for center in centers}:
                draft["cost_centers"] = centers + [cost_center]
            return {
                "state": DONE,
                "current_step": "",
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": [],
                    "last_question": None,
                },
                "reply": "Confirmado. Guardando gasto...",
                "action": "save_expense",
            }

        if normalized in {"1", "confirmar", "confirmo", "ok", "si", "sí"}:
            return {
                "state": CONFIRM_SUMMARY,
                "current_step": "cost_center",
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": [],
                    "last_question": "cost_center",
                },
                "reply": self._build_cost_center_prompt(draft),
                "action": "noop",
            }

        if normalized in {"2", "corregir"}:
            return {
                "state": CONFIRM_SUMMARY,
                "current_step": "select_correction_field",
                "context_json": {
                    "draft_expense": draft,
                    "missing_fields": [],
                    "last_question": None,
                },
                "reply": self._build_correction_field_prompt(),
                "action": "noop",
            }

        if normalized in {"3", "cancelar"}:
            return {
                "state": WAIT_RECEIPT,
                "current_step": "",
                "context_json": self.default_context(),
                "reply": "Operación cancelada. Cuando quieras, envíame otro comprobante o varios.",
                "action": "cancel",
            }

        return {
            "state": CONFIRM_SUMMARY,
            "current_step": "confirm_summary",
            "context_json": {
                "draft_expense": draft,
                "missing_fields": [],
                "last_question": None,
            },
            "reply": "Respuesta no válida.\nEscribe 1, 2 o 3.\n\n"
            + self.expense_service.build_summary_message(draft),
            "action": "noop",
        }

    def _build_cost_center_prompt(self, draft: dict[str, Any]) -> str:
        centers = self._get_draft_cost_centers(draft)
        if not centers:
            return "¿A qué centro de costo está dirigido este gasto? Escríbelo para registrarlo."
        options = "\n".join(f"{index}. {center}" for index, center in enumerate(centers, start=1))
        return (
            "¿A qué centro de costo está dirigido este gasto?\n"
            f"{options}\n"
            "Si el centro de costo no está en la lista, escríbelo para agregarlo al caso."
        )

    def _get_draft_cost_centers(self, draft: dict[str, Any]) -> list[str]:
        raw = draft.get("cost_centers", [])
        if isinstance(raw, str):
            parsed = json_loads(raw, default=[])
            if isinstance(parsed, list):
                raw = parsed
            else:
                raw = raw.replace("\n", ",").replace(";", ",").split(",")
        if not isinstance(raw, (list, tuple, set)):
            raw = [raw]
        centers: list[str] = []
        seen: set[str] = set()
        for item in raw:
            text = str(item or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            centers.append(text)
        return centers

    def _parse_cost_center_value(
        self,
        message: str,
        draft: dict[str, Any],
        *,
        allow_manual: bool = False,
    ) -> str:
        value = str(message or "").strip()
        if not value:
            return ""
        centers = self._get_draft_cost_centers(draft)
        if allow_manual:
            return value
        if value.isdigit():
            index = int(value) - 1
            if 0 <= index < len(centers):
                return centers[index]
        normalized = value.lower()
        for center in centers:
            if center.lower() == normalized:
                return center
        if centers:
            return ""
        return value

    def _heuristic_answer(self, message: str, *, phone: str = "") -> str | None:
        """Return a direct answer when heuristics clearly detect a question type."""
        # Direct rendicion question answerable from data (no LLM needed)
        rendicion_answer = self.expense_service.answer_rendicion_question(phone=phone, question=message)
        if rendicion_answer:
            return rendicion_answer

        # Heuristic-detected question: route through answer_general_question
        is_rendicion = self._looks_like_rendicion_request(message)
        if is_rendicion or self._looks_like_question(message):
            general_answer = self.expense_service.answer_general_question(
                message, phone=phone, case_context_hint=is_rendicion
            )
            if general_answer:
                return f"{general_answer}\n\nCuando quieras, envíame los comprobantes y los reviso."

        return None

    def _is_greeting(self, normalized: str) -> bool:
        greetings = ("hola", "buenas", "buenos dias", "buenos días", "buen dia", "buen día",
                     "buenas tardes", "buenas noches", "hi", "hello", "hey", "saludos")
        stripped = normalized.strip("!?., ")
        return any(stripped == g or normalized.startswith(g + " ") or normalized.startswith(g + "!")
                   or normalized.startswith(g + ",") or normalized.startswith(g + "?")
                   for g in greetings)

    def _answer_general_question_if_needed(self, message: str, *, phone: str = "") -> str | None:
        is_rendicion = self._looks_like_rendicion_request(message)
        if not is_rendicion and not self._looks_like_question(message):
            return None
        return self.expense_service.answer_general_question(message, phone=phone, case_context_hint=is_rendicion)

    def _looks_like_rendicion_request(self, message: str) -> bool:
        normalized = " ".join((message or "").strip().lower().split())
        if not normalized:
            return False
        signals = (
            "centro de costo",
            "centros de costo",
            "centro costo",
            "centros costo",
            "mis centros",
            "resumen",
            "saldo",
            "presupuesto",
            "fondos",
            "cuanto me queda",
            "cuánto me queda",
            "ultimo gasto",
            "último gasto",
            "ultima compra",
            "última compra",
            "mis gastos",
            "estado rendicion",
            "estado rendición",
        )
        return any(signal in normalized for signal in signals)

    def _looks_like_question(self, message: str) -> bool:
        normalized = (message or "").strip().lower()
        if not normalized:
            return False
        if "?" in normalized:
            return True
        question_starts = (
            "como",
            "cómo",
            "que ",
            "qué ",
            "donde",
            "dónde",
            "cuando",
            "cuándo",
            "cual",
            "cuál",
            "puedo",
            "se puede",
            "me ayudas",
            "ayuda",
            "explica",
        )
        return normalized.startswith(question_starts)

    def prompt_for_field(self, field_name: str) -> str:
        return FIELD_PROMPTS.get(field_name, f"Falta el campo {field_name}. Indícalo.")

    def _parse_document_type_value(self, message: str) -> str | None:
        """Parse user response for document type (boleta/factura)."""
        text = (message or "").strip().lower()
        if not text:
            return None
        # Accept option numbers
        if text in DOCUMENT_TYPE_OPTIONS:
            return DOCUMENT_TYPE_OPTIONS[text]
        # Accept natural language
        if text in ("honorarios", "boleta de honorarios", "boleta honorarios", "professional_fee_receipt"):
            return "professional_fee_receipt"
        if text in ("boleta", "receipt", "ticket"):
            return "receipt"
        if text in ("factura", "invoice"):
            return "invoice"
        # Partial matches
        if "honorario" in text or "retencion" in text or "retención" in text:
            return "professional_fee_receipt"
        if "boleta" in text or "receipt" in text:
            return "receipt"
        if "factura" in text or "invoice" in text:
            return "invoice"
        return None

    def _parse_field_value(self, field_name: str, message: str) -> Any:
        text = message.strip()
        if not text:
            return None

        if field_name == "currency":
            return CURRENCY_OPTIONS.get(text) or text.upper()
        if field_name == "category":
            return CATEGORY_OPTIONS.get(text) or text
        if field_name == "country":
            if text.lower() in {"4", "otro", "other_country"}:
                return OTHER_COUNTRY_SENTINEL
            return COUNTRY_OPTIONS.get(text) or text
        if field_name == "total":
            try:
                return float(text.replace(",", "."))
            except ValueError:
                return None
        return text

    def _build_correction_field_prompt(self) -> str:
        return (
            "¿Qué campo quieres corregir?\n"
            "1. Merchant\n"
            "2. Fecha\n"
            "3. Total\n"
            "4. Moneda\n"
            "5. Categoría\n"
            "6. País"
        )

    def _parse_correction_field_choice(self, message: str) -> str | None:
        text = (message or "").strip()
        if not text:
            return None
        return CORRECTION_FIELD_OPTIONS.get(text) or CORRECTION_FIELD_ALIASES.get(text.lower())

    def _to_needs_info_for_field(self, draft: dict[str, Any], field_name: str) -> dict[str, Any]:
        extra = ""
        if field_name == "country":
            extra = "\nActualizaré moneda automáticamente según el país."
        field_label = CORRECTION_FIELD_LABELS.get(field_name, field_name)
        return {
            "state": NEEDS_INFO,
            "current_step": field_name,
            "context_json": {
                "draft_expense": draft,
                "missing_fields": [field_name],
                "last_question": field_name,
            },
            "reply": f"Vamos a corregir {field_label}.{extra}\n{self.prompt_for_field(field_name)}",
            "action": "noop",
        }
