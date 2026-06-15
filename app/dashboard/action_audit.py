"""Audit linkage for dashboard actions (Phase 2).

Every dashboard action — accepted *or* refused — is written here, to the same
audit table the CLI uses, with secrets stripped from the payload. The returned
audit id is stored on the job so the operator can trace a job back to its audit
record (and vice-versa).
"""

from __future__ import annotations

from typing import Any

from app.config.settings import Settings
from app.core.logging import audit as audit_log
from app.dashboard.action_schemas import _redact
from app.data.storage import Storage


def record_action(storage: Storage, settings: Settings, *, action: str, confirmed: bool,
                  payload: dict[str, Any], result: str) -> int:
    """Write one audit event and return its id. Mode is reported as the real
    operating mode (`live` is structurally impossible here, so it is `paper`)."""
    mode = "live" if settings.live_trading_allowed else "paper"
    safe_payload = _redact(payload or {})
    audit_id = storage.record_audit_event(
        actor="dashboard", action=action, mode=mode,
        confirmed=confirmed, payload=safe_payload, result=result[:500])
    audit_log(f"dashboard_action_{action}", confirmed=confirmed,
              result=result[:200], **{k: v for k, v in safe_payload.items()
                                      if isinstance(v, (str, int, float, bool))})
    return audit_id
