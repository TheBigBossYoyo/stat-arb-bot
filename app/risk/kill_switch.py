"""Kill switch.

When engaged, all new order flow is blocked everywhere (risk manager checks
it first on every validation). File-backed so it survives restarts and can be
engaged from a separate terminal (`statarb kill-switch --engage`), or
in-memory for backtests.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.logging import audit, get_logger

log = get_logger(__name__)


class KillSwitch:
    def __init__(self, flag_path: Path | None = None) -> None:
        """flag_path=None -> in-memory switch (used by backtests/tests)."""
        self.flag_path = Path(flag_path) if flag_path else None
        self._active = False
        self._reason = ""
        if self.flag_path and self.flag_path.exists():
            self._active = True
            try:
                self._reason = json.loads(self.flag_path.read_text())["reason"]
            except Exception:
                self._reason = "unknown (flag file unreadable)"

    @property
    def is_active(self) -> bool:
        if self.flag_path:
            return self.flag_path.exists()
        return self._active

    @property
    def reason(self) -> str:
        return self._reason

    def engage(self, reason: str) -> None:
        self._active = True
        self._reason = reason
        if self.flag_path:
            self.flag_path.parent.mkdir(parents=True, exist_ok=True)
            self.flag_path.write_text(
                json.dumps({"reason": reason, "engaged_at": datetime.now(UTC).isoformat()})
            )
        log.critical("KILL SWITCH ENGAGED: %s", reason)
        audit("kill_switch_engaged", reason=reason)

    def disengage(self) -> None:
        self._active = False
        self._reason = ""
        if self.flag_path and self.flag_path.exists():
            self.flag_path.unlink()
        log.warning("kill switch disengaged")
        audit("kill_switch_disengaged")

    def status(self) -> dict:
        return {"active": self.is_active, "reason": self._reason}
