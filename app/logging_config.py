from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id",
    default="-",
)

_previous_record_factory = logging.getLogRecordFactory()
_configured = False


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def _record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    record = _previous_record_factory(*args, **kwargs)
    record.request_id = request_id_context.get()
    return record


def configure_logging(*, level: str = "INFO", log_format: str = "text") -> None:
    global _configured
    if not _configured:
        logging.setLogRecordFactory(_record_factory)
        _configured = True

    normalized_level = str(level or "INFO").upper()
    log_level = getattr(logging, normalized_level, logging.INFO)
    if str(log_format or "").strip().lower() == "json":
        formatter: logging.Formatter = JsonLogFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
        )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    handler = root_logger.handlers[0] if root_logger.handlers else logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(formatter)
    if not root_logger.handlers:
        root_logger.addHandler(handler)
