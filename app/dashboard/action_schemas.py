"""Schemas for the dashboard action/job orchestrator (Phase 2).

These describe *what the operator asked for* and *what the job did* — never
secrets, never a live-trading path. Every job type below is read / research /
paper / demo only; there is deliberately no `live_*` job type and no field that
could carry a live order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class JobType(str, Enum):
    PRODUCT_DECISION = "product_decision"
    LONG_ONLY_READINESS = "long_only_readiness"
    CONCENTRATION_ANALYSIS = "concentration_analysis"
    COMPARE_CONCENTRATION_FIXES = "compare_concentration_fixes"
    SURVIVORSHIP_STRESS = "survivorship_stress"
    CRISIS_TEST = "crisis_test"
    TRADING212_SETUP_CHECK = "trading212_setup_check"
    ORDER_PREVIEW = "order_preview"
    SUPERVISED_PAPER_START = "supervised_paper_start"
    SUPERVISED_PAPER_DAILY_SHADOW = "supervised_paper_daily_shadow"
    SUPERVISED_PAPER_DAILY_DEMO_PREVIEW = "supervised_paper_daily_demo_preview"
    SUPERVISED_PAPER_DAILY_DEMO_EXECUTE = "supervised_paper_daily_demo_execute"
    SUPERVISED_PAPER_HEALTH = "supervised_paper_health"
    SUPERVISED_PAPER_FINAL_REPORT = "supervised_paper_final_report"
    SUPERVISED_PAPER_STOP = "supervised_paper_stop"
    PAPER_VS_BACKTEST = "paper_vs_backtest"
    REPORT_GENERATION = "report_generation"
    KILL_SWITCH_ACTION = "kill_switch_action"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUSED = "refused"      # rejected by a safety gate before running
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED,
                        JobStatus.REFUSED, JobStatus.CANCELLED)


class SafetyLevel(str, Enum):
    READ = "read"            # no side effects
    RESEARCH = "research"    # writes reports / DB rows; touches no broker
    PAPER = "paper"          # simulated paper/shadow; no broker connection
    DEMO = "demo"            # Trading 212 DEMO connection (validate / demo order)
    DANGER = "danger"        # broad operational control (kill switch / stop session)


class ConfirmLevel(str, Enum):
    NONE = "none"
    ROLE = "role"            # controls enabled + sufficient role
    PHRASE = "phrase"        # + an exact typed confirmation phrase
    PHRASE_ENV = "phrase_env"  # + an environment gate (e.g. demo orders allowed)


class ActionBody(BaseModel):
    """Body for a *named* action endpoint (the route fixes the job type)."""

    params: dict[str, Any] = Field(default_factory=dict)
    confirm_phrase: str = ""
    acknowledge: bool = False     # explicit "I understand this is demo only" checkbox
    reason: str = ""


class ActionRequest(ActionBody):
    """The body the generic action endpoint accepts. Frontend is never trusted —
    the server re-derives every gate from `settings` + this request."""

    job_type: JobType


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class JobRecord:
    """Mutable server-side job record. `public()` returns the redacted view."""

    id: str
    job_type: JobType
    safety_level: SafetyLevel
    status: JobStatus
    params: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: float = 0.0
    step: str = ""
    logs: list[str] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    refusal_reason: str = ""
    audit_id: int | None = None
    report_path: str | None = None
    cancel_requested: bool = False

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "job_type": self.job_type.value,
            "safety_level": self.safety_level.value,
            "status": self.status.value,
            "params": _redact(self.params),
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "progress": round(self.progress, 3),
            "step": self.step,
            "result": self.result,
            "error": self.error,
            "refusal_reason": self.refusal_reason,
            "audit_id": self.audit_id,
            "report_path": self.report_path,
            "cancel_requested": self.cancel_requested,
            "live_eligible": False,
        }


_SECRET_KEYS = ("key", "secret", "token", "password", "passwd", "api_key", "api_secret")


def _redact(params: dict[str, Any]) -> dict[str, Any]:
    """Never echo a secret back to the client, even if one was (wrongly) posted."""
    out: dict[str, Any] = {}
    for k, v in params.items():
        if any(s in k.lower() for s in _SECRET_KEYS):
            out[k] = "***"
        else:
            out[k] = v
    return out
