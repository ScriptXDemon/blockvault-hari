from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra_fields = getattr(record, "structured", None)
        if isinstance(extra_fields, dict):
            payload.update(extra_fields)
        return json.dumps(payload, separators=(",", ":"))


def configure_logging() -> None:
    root_logger = logging.getLogger("blockvault.api")
    if getattr(root_logger, "_blockvault_configured", False):
        return

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    root_logger.propagate = False
    root_logger._blockvault_configured = True  # type: ignore[attr-defined]


def get_api_logger() -> logging.Logger:
    configure_logging()
    return logging.getLogger("blockvault.api")
