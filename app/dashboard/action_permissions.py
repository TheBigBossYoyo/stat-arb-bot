"""Per-action safety gates for the dashboard orchestrator (Phase 2 / 14).

Every dashboard action is described by an `ActionSpec`: the minimum role, the
confirmation level, the exact confirmation phrase, and whether it needs the demo
environment gate, an acknowledgement checkbox, a healthy product decision, or is
blocked while the kill switch is engaged.

`evaluate_gates` is the single chokepoint: the API calls it, the orchestrator
calls it, and it re-derives every decision from `settings` server-side. There is
no `ActionSpec` that can reach a live order — the most powerful broker action is
a Trading 212 DEMO order, and even that needs ADMIN + phrase + env + checkbox.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config.settings import Settings
from app.dashboard.action_schemas import (
    ActionRequest,
    ConfirmLevel,
    JobType,
    SafetyLevel,
)
from app.dashboard.permissions import Role, current_role
from app.data.storage import Storage

# Confirmation phrases owned by the orchestrator (kill switch resolves per operation).
PHRASE_RUN_DEMO_PAPER_DAY = "RUN DEMO PAPER DAY"
PHRASE_STOP_PAPER_SESSION = "STOP PAPER SESSION"
PHRASE_SEND_DEMO_ORDERS = "SEND DEMO ORDERS"
PHRASE_ACTIVATE_KILL_SWITCH = "ACTIVATE KILL SWITCH"
PHRASE_DISENGAGE_KILL_SWITCH = "DISENGAGE KILL SWITCH"


class ActionRefused(Exception):
    """A safety gate rejected the action. `reason` is shown to the operator and
    is written verbatim to the audit trail; the action never runs."""

    def __init__(self, reason: str, *, status_code: int = 400) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code


@dataclass(frozen=True)
class ActionSpec:
    job_type: JobType
    safety_level: SafetyLevel
    min_role: Role
    confirm_level: ConfirmLevel = ConfirmLevel.NONE
    phrase: str = ""
    needs_demo_env: bool = False
    needs_acknowledge: bool = False
    blocks_when_killed: bool = True
    requires_product_ok: bool = False


_R = Role
_S = SafetyLevel
_C = ConfirmLevel

ACTION_SPECS: dict[JobType, ActionSpec] = {
    JobType.PRODUCT_DECISION: ActionSpec(
        JobType.PRODUCT_DECISION, _S.RESEARCH, _R.RESEARCHER, _C.ROLE,
        blocks_when_killed=False),
    JobType.LONG_ONLY_READINESS: ActionSpec(
        JobType.LONG_ONLY_READINESS, _S.RESEARCH, _R.RESEARCHER, _C.ROLE,
        blocks_when_killed=False),
    JobType.CONCENTRATION_ANALYSIS: ActionSpec(
        JobType.CONCENTRATION_ANALYSIS, _S.RESEARCH, _R.RESEARCHER, _C.ROLE,
        blocks_when_killed=False),
    JobType.COMPARE_CONCENTRATION_FIXES: ActionSpec(
        JobType.COMPARE_CONCENTRATION_FIXES, _S.RESEARCH, _R.RESEARCHER, _C.ROLE,
        blocks_when_killed=False),
    JobType.SURVIVORSHIP_STRESS: ActionSpec(
        JobType.SURVIVORSHIP_STRESS, _S.RESEARCH, _R.RESEARCHER, _C.ROLE,
        blocks_when_killed=False),
    JobType.CRISIS_TEST: ActionSpec(
        JobType.CRISIS_TEST, _S.RESEARCH, _R.RESEARCHER, _C.ROLE,
        blocks_when_killed=False),
    JobType.TRADING212_SETUP_CHECK: ActionSpec(
        JobType.TRADING212_SETUP_CHECK, _S.DEMO, _R.TRADER, _C.ROLE),
    JobType.ORDER_PREVIEW: ActionSpec(
        JobType.ORDER_PREVIEW, _S.PAPER, _R.RESEARCHER, _C.ROLE,
        blocks_when_killed=False),
    JobType.SUPERVISED_PAPER_START: ActionSpec(
        JobType.SUPERVISED_PAPER_START, _S.PAPER, _R.TRADER, _C.ROLE,
        requires_product_ok=True),
    JobType.SUPERVISED_PAPER_DAILY_SHADOW: ActionSpec(
        JobType.SUPERVISED_PAPER_DAILY_SHADOW, _S.PAPER, _R.TRADER, _C.ROLE,
        requires_product_ok=True),
    JobType.SUPERVISED_PAPER_DAILY_DEMO_PREVIEW: ActionSpec(
        JobType.SUPERVISED_PAPER_DAILY_DEMO_PREVIEW, _S.DEMO, _R.TRADER, _C.ROLE,
        requires_product_ok=True),
    JobType.SUPERVISED_PAPER_DAILY_DEMO_EXECUTE: ActionSpec(
        JobType.SUPERVISED_PAPER_DAILY_DEMO_EXECUTE, _S.DEMO, _R.ADMIN, _C.PHRASE_ENV,
        phrase=PHRASE_RUN_DEMO_PAPER_DAY, needs_demo_env=True, requires_product_ok=True),
    JobType.SUPERVISED_PAPER_HEALTH: ActionSpec(
        JobType.SUPERVISED_PAPER_HEALTH, _S.READ, _R.VIEWER, _C.NONE,
        blocks_when_killed=False),
    JobType.SUPERVISED_PAPER_FINAL_REPORT: ActionSpec(
        JobType.SUPERVISED_PAPER_FINAL_REPORT, _S.RESEARCH, _R.RESEARCHER, _C.ROLE,
        blocks_when_killed=False),
    JobType.SUPERVISED_PAPER_STOP: ActionSpec(
        JobType.SUPERVISED_PAPER_STOP, _S.DANGER, _R.ADMIN, _C.PHRASE,
        phrase=PHRASE_STOP_PAPER_SESSION, blocks_when_killed=False),
    JobType.PAPER_VS_BACKTEST: ActionSpec(
        JobType.PAPER_VS_BACKTEST, _S.READ, _R.VIEWER, _C.NONE, blocks_when_killed=False),
    JobType.REPORT_GENERATION: ActionSpec(
        JobType.REPORT_GENERATION, _S.RESEARCH, _R.RESEARCHER, _C.ROLE,
        blocks_when_killed=False),
    JobType.KILL_SWITCH_ACTION: ActionSpec(
        JobType.KILL_SWITCH_ACTION, _S.DANGER, _R.TRADER, _C.PHRASE,
        blocks_when_killed=False),
}


def _kill_switch_active(settings: Settings) -> bool:
    from app.risk.kill_switch import KillSwitch
    return KillSwitch(settings.runtime_dir / "kill_switch.flag").is_active


def _kill_switch_requirements(request: ActionRequest) -> tuple[Role, str]:
    """Engage needs TRADER + ACTIVATE phrase; disengage is stricter (ADMIN +
    DISENGAGE phrase) — you must never be able to lift the halt as easily as you
    set it."""
    op = str(request.params.get("operation", "")).lower()
    if op in ("disengage", "deactivate", "off", "release"):
        return Role.ADMIN, PHRASE_DISENGAGE_KILL_SWITCH
    if op in ("engage", "activate", "on"):
        return Role.TRADER, PHRASE_ACTIVATE_KILL_SWITCH
    raise ActionRefused("kill switch action needs params.operation = 'engage' | 'disengage'")


def _product_decision_ok(settings: Settings, storage: Storage, product: str) -> tuple[bool, str]:
    from app.execution.paper_supervisor import product_status
    ok, status, _ps = product_status(settings, storage, product)
    return ok, status


def evaluate_gates(settings: Settings, storage: Storage, request: ActionRequest) -> dict:
    """Validate every gate for `request`. Returns a context dict (e.g.
    `confirm_demo`) on success, or raises `ActionRefused` with a clear reason.

    Order matters: controls -> role -> kill switch -> phrase -> env -> checkbox
    -> product. The first failure is the one reported."""
    spec = ACTION_SPECS.get(request.job_type)
    if spec is None:
        raise ActionRefused(f"unknown action {request.job_type}")

    min_role = spec.min_role
    expected_phrase = spec.phrase
    if request.job_type == JobType.KILL_SWITCH_ACTION:
        min_role, expected_phrase = _kill_switch_requirements(request)

    # 1) controls enabled + role
    if spec.confirm_level != ConfirmLevel.NONE:
        if not settings.dashboard_controls_enabled:
            raise ActionRefused(
                "dashboard is READ-ONLY — set DASHBOARD_CONTROLS_ENABLED=true (keep the "
                "server bound to 127.0.0.1) to enable controls.", status_code=403)
        role = current_role(settings)
        if role < min_role:
            raise ActionRefused(
                f"this action requires the '{min_role.name.lower()}' role.", status_code=403)

    # 2) kill switch
    if spec.blocks_when_killed and _kill_switch_active(settings):
        raise ActionRefused("kill switch is ENGAGED — disengage it before running actions.")

    # 3) confirmation phrase
    if spec.confirm_level in (ConfirmLevel.PHRASE, ConfirmLevel.PHRASE_ENV):
        if request.confirm_phrase.strip() != expected_phrase:
            raise ActionRefused(f'confirmation phrase mismatch: type exactly "{expected_phrase}".')

    # 4) demo environment gate
    if spec.needs_demo_env:
        if not (settings.trading212_enabled and settings.trading212_mode == "demo"
                and settings.trading212_allow_demo_orders):
            raise ActionRefused(
                "demo orders are blocked: set TRADING212_ENABLED=true, TRADING212_MODE=demo "
                "and TRADING212_ALLOW_DEMO_ORDERS=true (live remains hard-blocked).")
        if settings.trading212_allow_live_orders:
            # defence in depth: this flag is never consulted by the executor, but if
            # someone set it we refuse loudly rather than proceed.
            raise ActionRefused("refusing: TRADING212_ALLOW_LIVE_ORDERS is set — unset it.")

    # 5) acknowledgement checkbox
    if spec.needs_acknowledge and not request.acknowledge:
        raise ActionRefused("you must tick the acknowledgement checkbox to proceed.")

    # 6) product decision must be valid for paper/demo session actions
    if spec.requires_product_ok:
        product = str(request.params.get("product", "long_only_t212"))
        ok, status = _product_decision_ok(settings, storage, product)
        if not ok:
            raise ActionRefused(
                f"product '{product}' is not paper-eligible (decision: {status}).")

    confirm_demo = request.job_type == JobType.SUPERVISED_PAPER_DAILY_DEMO_EXECUTE
    return {"confirm_demo": confirm_demo, "min_role": min_role.name.lower(),
            "safety_level": spec.safety_level.value}
