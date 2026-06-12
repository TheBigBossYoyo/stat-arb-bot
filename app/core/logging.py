"""Structured logging.

Two channels:
  * application log  -> console (human readable) + logs/app.log (JSON lines)
  * audit log        -> logs/audit.jsonl (JSON lines, one event per line)

The audit log is append-only and records every signal, risk decision, order
and fill with full context (model version, z-score, hedge ratio, ...).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_AUDIT_LOGGER_NAME = "statarb.audit"
_configured = False


class JsonFormatter(logging.Formatter):
    """Render log records as one JSON object per line."""

    _STD_KEYS = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "taskName", "message",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in self._STD_KEYS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO", logs_dir: Path | None = None) -> None:
    """Configure root logging. Safe to call more than once."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(level.upper())

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(console)

    if logs_dir is not None:
        logs_dir = Path(logs_dir)
        logs_dir.mkdir(parents=True, exist_ok=True)

        app_file = logging.FileHandler(logs_dir / "app.log", encoding="utf-8")
        app_file.setFormatter(JsonFormatter())
        root.addHandler(app_file)

        audit_file = logging.FileHandler(logs_dir / "audit.jsonl", encoding="utf-8")
        audit_file.setFormatter(JsonFormatter())
        audit_logger = logging.getLogger(_AUDIT_LOGGER_NAME)
        audit_logger.setLevel(logging.INFO)
        audit_logger.addHandler(audit_file)
        audit_logger.propagate = False

    # Quieten noisy third-party loggers.
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def audit(event: str, **fields: Any) -> None:
    """Write a structured audit event (signal, risk decision, order, fill...)."""
    logging.getLogger(_AUDIT_LOGGER_NAME).info(event, extra={"event": event, **fields})
