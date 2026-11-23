"""Structured JSON logging with request-ID correlation.

Every log record carries the current request ID (set by middleware through a
``ContextVar``) so a single request can be traced across retrieval, LLM and
database log lines. Never pass secrets or full document text to the logger.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}
_REDACT_KEYS = {"password", "token", "api_key", "authorization", "secret", "jwt"}


def _redact(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(marker in lowered for marker in _REDACT_KEYS):
        return "***"
    return value


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if (rid := request_id_ctx.get()) is not None:
            payload["request_id"] = rid
        if (uid := user_id_ctx.get()) is not None:
            payload["user_id"] = uid
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = _redact(key, value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-friendly formatter for local development."""

    def format(self, record: logging.LogRecord) -> str:
        extras = {
            k: _redact(k, v)
            for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_")
        }
        rid = request_id_ctx.get()
        base = f"{record.levelname:<7} {record.name}: {record.getMessage()}"
        if rid:
            base += f" [rid={rid}]"
        if extras:
            base += " " + " ".join(f"{k}={v}" for k, v in extras.items())
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    """Configure the root logger once at application start-up."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_logs else ConsoleFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Third-party libraries are noisy at INFO.
    for noisy in ("httpx", "httpcore", "LiteLLM", "litellm", "sentence_transformers", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger."""
    return logging.getLogger(name)
