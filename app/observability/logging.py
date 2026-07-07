"""
Structured JSON logger.
Provides a consistent logger with request_id and trace_id context.
"""
import logging
import json
import sys
from datetime import datetime, timezone
from app.core.config import get_settings


def get_logger(name: str) -> logging.Logger:
    """Return a stdlib logger configured for JSON output."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def log_request_event(
    logger: logging.Logger,
    event: str,
    request_id: str,
    trace_id: str,
    **kwargs,
) -> None:
    """
    Emit a structured JSON log event for a request lifecycle step.
    Never include full question text, full chunk content, or secrets.
    """
    payload = {
        "event": event,
        "request_id": request_id,
        "trace_id": trace_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        **kwargs,
    }
    logger.info(json.dumps(payload))


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # If the message is already JSON (from log_request_event), pass it through
        try:
            json.loads(record.getMessage())
            return record.getMessage()
        except (json.JSONDecodeError, TypeError):
            return json.dumps({
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "ts": datetime.now(timezone.utc).isoformat(),
            })
