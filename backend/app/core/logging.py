"""Structured JSON logging with request correlation ids."""
from __future__ import annotations

import contextvars
import json
import logging
import sys
import time

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
EXTRA_FIELDS = ("method", "path", "status", "duration_ms", "org_id", "user_id", "simulation_id", "job")


def _extras(record: logging.LogRecord) -> dict:
    return {k: v for k in EXTRA_FIELDS if (v := getattr(record, k, None)) is not None}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            out["request_id"] = rid
        out.update(_extras(record))
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class DevFormatter(logging.Formatter):
    """Human-readable lines for local development, still carrying the structured fields."""

    def __init__(self):
        super().__init__("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extra = " ".join(f"{k}={v}" for k, v in _extras(record).items())
        return f"{line} {extra}" if extra else line


def setup_logging(level: str = "INFO", json_logs: bool = True) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter() if json_logs else DevFormatter())
    root.addHandler(h)
    root.setLevel(level)
    for noisy in ("httpx", "httpcore", "uvicorn.access", "aiosqlite", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
