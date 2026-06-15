"""Alert engine for the supervised paper period (Phase 2).

Condition-derived alerts with three severities (info / warning / critical) across
a fixed set of categories. The rule engine (`evaluate_alert_specs`) turns a
metrics dict into the set of currently-active alert specs; the `AlertStore`
reconciles that against persisted state so:

* a new active condition creates a new alert (with a stable de-dup key);
* a condition that clears auto-resolves its alert (kept in history, marked
  resolved with a note) — alerts are never deleted, only resolved;
* an operator can manually resolve an info/warning alert with a note (audited by
  the caller); a CRITICAL alert whose condition is still active cannot be hand-
  waved away — it re-fires until the underlying issue is fixed.

Persistence: `runtime/paper/<product>/paper_alerts.json` (a list, read-modify-
write — single local operator). Live is never in scope.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

INFO, WARNING, CRITICAL = "info", "warning", "critical"
SEVERITY_RANK = {INFO: 0, WARNING: 1, CRITICAL: 2}

CATEGORIES = (
    "missed_day", "duplicate_day_blocked", "data_stale", "data_missing",
    "paper_drawdown", "benchmark_underperformance", "concentration_breach",
    "turnover_drift", "cash_drag_high", "tca_degradation", "broker_error",
    "rejected_orders", "skipped_orders_high", "product_decision_changed",
    "readiness_lost", "kill_switch_active", "live_flag_detected",
    "report_missing", "final_review_ready",
)


@dataclass
class AlertSpec:
    category: str
    severity: str
    title: str
    message: str
    evidence: dict = field(default_factory=dict)
    suggested_action: str = ""

    @property
    def dedup_key(self) -> str:
        return f"{self.category}:{self.severity}"


@dataclass
class Alert:
    alert_id: str
    timestamp: str
    session_id: str
    severity: str
    category: str
    title: str
    message: str
    evidence: dict = field(default_factory=dict)
    suggested_action: str = ""
    resolved: bool = False
    resolved_at: str = ""
    resolution_note: str = ""
    dedup_key: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------------
# rule engine — metrics dict -> active alert specs (one per category, highest sev)
# --------------------------------------------------------------------------------

def evaluate_alert_specs(m: dict) -> list[AlertSpec]:
    """Return the currently-active alert specs from a monitor metrics dict.

    At most one spec per category (the highest applicable severity), so an
    escalation (warning -> critical) auto-resolves the warning and raises a fresh
    critical via the de-dup keys."""
    specs: list[AlertSpec] = []

    def add(category, severity, title, message, *, evidence=None, action=""):
        specs.append(AlertSpec(category, severity, title, message,
                               evidence or {}, action))

    # ---- safety-critical (these should essentially never fire) ----
    if m.get("live_trading_allowed"):
        add("live_flag_detected", CRITICAL,
            "Live trading flag detected",
            "The global live-trading gate is ON. This product is paper-only; stop now.",
            evidence={"live_trading_allowed": True},
            action="Set LIVE_TRADING=false and CONFIRM_LIVE_TRADING=false immediately.")
    if m.get("kill_switch_active"):
        add("kill_switch_active", CRITICAL,
            "Kill switch engaged",
            "The kill switch is active; paper runs are paused until it is disengaged.",
            action="Investigate the cause, then disengage from the Safety Center.")
    if not m.get("decision_is_candidate", True):
        add("product_decision_changed", CRITICAL,
            "Product no longer paper_candidate",
            f"Product-decision status is '{m.get('decision_status', 'unknown')}'. "
            "Paper days will be refused.",
            evidence={"decision_status": m.get("decision_status")},
            action="Re-run long-only-readiness and restart the period once eligible.")
    if m.get("readiness_lost"):
        add("readiness_lost", CRITICAL,
            "Research readiness lost",
            "The strategy no longer passes its readiness gates.",
            action="Re-run `long-only-readiness --full` and investigate the regression.")

    # ---- data ----
    if m.get("data_stale"):
        add("data_stale", WARNING,
            "Market data is stale",
            f"The latest bar ({m.get('last_bar_date', 'unknown')}) is behind today.",
            evidence={"last_bar_date": m.get("last_bar_date")},
            action="Run `statarb download-data` before the next paper day.")
    dq = int(m.get("data_quality_events", 0) or 0)
    if dq > 0:
        sev = CRITICAL if dq > 3 else WARNING
        add("data_missing", sev,
            "Data-quality events recorded",
            f"{dq} data-quality event(s) recorded during the period.",
            evidence={"data_quality_events": dq},
            action="Audit the feed with `statarb data-audit`.")

    # ---- risk / drawdown / concentration ----
    dd = abs(float(m.get("current_drawdown_pct", 0.0) or 0.0))
    fail_dd = float(m.get("fail_drawdown_pct", 35.0) or 35.0)
    pause_dd = float(m.get("pause_drawdown_pct", 20.0) or 20.0)
    if dd > fail_dd:
        add("paper_drawdown", CRITICAL,
            "Paper drawdown beyond hard limit",
            f"Drawdown {dd:.1f}% exceeds the {fail_dd:.0f}% hard limit — period invalid.",
            evidence={"drawdown_pct": -dd}, action="Stop and review the strategy.")
    elif dd > pause_dd:
        add("paper_drawdown", WARNING,
            "Paper drawdown beyond policy",
            f"Drawdown {dd:.1f}% exceeds the {pause_dd:.0f}% policy.",
            evidence={"drawdown_pct": -dd}, action="Pause and review risk.")

    top = float(m.get("concentration_top_weight", 0.0) or 0.0)
    if top > 0.30:
        add("concentration_breach", CRITICAL,
            "Concentration far above cap",
            f"Top-name weight {top:.1%} is well above the 25% cap.",
            evidence={"top_weight": top}, action="Confirm EWMA smoothing is active.")
    elif top > 0.25:
        add("concentration_breach", WARNING,
            "Concentration above cap",
            f"Top-name weight {top:.1%} exceeds the 25% cap.",
            evidence={"top_weight": top}, action="Re-check smoothing / re-run concentration-fix.")

    # ---- missed days ----
    gap = int(m.get("missing_days_gap", 0) or 0)
    missed = int(m.get("missed_days", 0) or 0)
    if gap >= 4 or missed >= 2:
        add("missed_day", CRITICAL,
            "Multiple missed paper days",
            f"{gap} day(s) since the last run; {missed} expected day(s) missed recently.",
            evidence={"missing_days_gap": gap, "missed_days": missed},
            action="Catch up the run today; investigate why days were skipped.")
    elif gap >= 2 or missed >= 1:
        add("missed_day", WARNING,
            "Missed a paper day",
            f"{gap} day(s) since the last recorded forward day.",
            evidence={"missing_days_gap": gap, "missed_days": missed},
            action="Run today's paper day to catch up.")

    if m.get("duplicate_day_blocked"):
        add("duplicate_day_blocked", INFO,
            "Duplicate run blocked",
            "A second run today was blocked — at most one forward day per calendar day.",
            action="No action needed; this is the guard working as intended.")

    # ---- benchmark / turnover / cash drag ----
    excess = m.get("excess_return_pct")
    min_days_excess = int(m.get("forward_days_completed", 0) or 0) >= 15
    if excess is not None and min_days_excess:
        excess = float(excess)
        if excess < -20:
            add("benchmark_underperformance", CRITICAL,
                "Severe underperformance vs benchmark",
                f"Paper is {excess:.1f}ppt behind the benchmark.",
                evidence={"excess_return_pct": excess},
                action="Review whether paper behaviour matches the backtest.")
        elif excess < -10:
            add("benchmark_underperformance", WARNING,
                "Underperformance vs benchmark",
                f"Paper is {excess:.1f}ppt behind the benchmark.",
                evidence={"excess_return_pct": excess},
                action="Monitor; run paper-vs-backtest.")

    turn = float(m.get("turnover_per_year", 0.0) or 0.0)
    exp_turn = float(m.get("expected_turnover", 30.0) or 30.0)
    ratio = turn / exp_turn if exp_turn else 1.0
    if turn > 0 and (ratio > 2.5 or ratio < 0.3):
        add("turnover_drift", WARNING,
            "Turnover far from expectation",
            f"Turnover {turn:.0f}x/yr vs ~{exp_turn:.0f}x expected.",
            evidence={"turnover_per_year": turn},
            action="Confirm the rebalance schedule and smoothing.")

    cash_drag = m.get("cash_drag_pct")
    if cash_drag is not None:
        cash_drag = float(cash_drag)
        if cash_drag > 30:
            add("cash_drag_high", WARNING,
                "High cash drag",
                f"Uninvested cash is {cash_drag:.0f}% of the book.",
                evidence={"cash_drag_pct": cash_drag},
                action="Check why target weights are not being filled.")

    # ---- TCA / broker / orders ----
    slip = m.get("avg_slippage_bps")
    exp_slip = float(m.get("expected_slippage_bps", 5.0) or 5.0)
    if slip is not None and float(slip) > 3 * exp_slip and float(slip) > 25:
        add("tca_degradation", WARNING,
            "Slippage worse than expected",
            f"Realised slippage {float(slip):.0f}bps vs ~{exp_slip:.0f}bps expected.",
            evidence={"avg_slippage_bps": slip},
            action="Check liquidity / limit offsets.")

    be = int(m.get("broker_errors", 0) or 0)
    if be > 3:
        add("broker_error", CRITICAL,
            "Repeated demo broker errors",
            f"{be} demo broker error(s) recorded.",
            evidence={"broker_errors": be},
            action="Run `trading212-demo-setup-check`; verify demo connectivity.")
    elif be > 0:
        add("broker_error", WARNING,
            "Demo broker error",
            f"{be} demo broker error(s) recorded.",
            evidence={"broker_errors": be},
            action="Check the demo connection.")

    reject_rate = float(m.get("reject_rate_pct", 0.0) or 0.0)
    rejected = int(m.get("rejected_orders", 0) or 0)
    if reject_rate > 10 and (m.get("total_order_attempts", 0) or 0) >= 10:
        add("rejected_orders", WARNING,
            "High order reject rate",
            f"Reject rate {reject_rate:.0f}% of attempts.",
            evidence={"reject_rate_pct": reject_rate, "rejected_orders": rejected},
            action="Inspect rejected orders; check tradability / min order value.")
    if rejected >= 20:
        add("skipped_orders_high", WARNING,
            "Many skipped/refused orders",
            f"{rejected} cumulative skipped/refused orders.",
            evidence={"rejected_orders": rejected},
            action="Review refusal reasons in the daily reports.")

    # ---- reports / milestones ----
    if m.get("report_missing"):
        add("report_missing", WARNING,
            "Daily summary missing",
            "The latest daily summary file was not found.",
            action="Re-run today's paper day to regenerate the summary.")
    if m.get("can_generate_final_report"):
        add("final_review_ready", INFO,
            "Final review available",
            f"{m.get('forward_days_completed', 0)} forward days recorded — the final "
            "review can be generated. This does NOT enable anything live.",
            action="Generate the final supervised-paper report.")

    return specs


# --------------------------------------------------------------------------------
# persistence
# --------------------------------------------------------------------------------

class AlertStore:
    """Read-modify-write list of alerts under runtime/paper/<product>/."""

    def __init__(self, runtime_dir: Path, product: str) -> None:
        self.path = Path(runtime_dir) / "paper" / product / "paper_alerts.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[Alert]:
        if not self.path.exists():
            return []
        raw = json.loads(self.path.read_text(encoding="utf-8") or "[]")
        return [Alert(**r) for r in raw]

    def save(self, alerts: list[Alert]) -> None:
        self.path.write_text(json.dumps([a.as_dict() for a in alerts], indent=2,
                                        default=str), encoding="utf-8")

    def active(self) -> list[Alert]:
        return [a for a in self.load() if not a.resolved]

    def get(self, alert_id: str) -> Alert | None:
        return next((a for a in self.load() if a.alert_id == alert_id), None)

    def sync(self, specs: list[AlertSpec], *, session_id: str, now: str) -> list[Alert]:
        """Reconcile active specs with persisted alerts (create new / auto-resolve)."""
        alerts = self.load()
        active_keys = {s.dedup_key for s in specs}
        # auto-resolve alerts whose condition has cleared
        for a in alerts:
            if not a.resolved and a.dedup_key not in active_keys:
                a.resolved = True
                a.resolved_at = now
                a.resolution_note = "condition cleared automatically"
        existing_active = {a.dedup_key for a in alerts if not a.resolved}
        for s in specs:
            if s.dedup_key in existing_active:
                continue
            alerts.append(Alert(
                alert_id=f"AL-{uuid.uuid4().hex[:10]}", timestamp=now,
                session_id=session_id, severity=s.severity, category=s.category,
                title=s.title, message=s.message, evidence=s.evidence,
                suggested_action=s.suggested_action, dedup_key=s.dedup_key))
        self.save(alerts)
        return alerts

    def resolve(self, alert_id: str, *, note: str, now: str,
                blocked_keys: set[str] | None = None) -> tuple[bool, str]:
        """Manually resolve an alert. Refuses a CRITICAL alert whose condition is
        still active (in `blocked_keys`) — fix the cause, don't hide it."""
        alerts = self.load()
        target = next((a for a in alerts if a.alert_id == alert_id), None)
        if target is None:
            return False, "alert not found"
        if target.resolved:
            return False, "alert already resolved"
        if (target.severity == CRITICAL and blocked_keys is not None
                and target.dedup_key in blocked_keys):
            return False, ("this CRITICAL alert is still active — resolve the "
                           "underlying issue; it cannot be dismissed while live")
        target.resolved = True
        target.resolved_at = now
        target.resolution_note = note or "resolved by operator"
        self.save(alerts)
        return True, "resolved"
