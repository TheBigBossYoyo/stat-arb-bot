"""Paper-session monitoring engine (Phases 1-2, 6-8).

One place that, after every daily run or on demand, reads the recorded session,
assembles the full operator metric set, computes the explainable health score,
evaluates + persists alerts, records a health snapshot for the time-series charts,
and derives the milestone flags (weekly due, final-review ready) and the single
suggested next action.

It composes the existing building blocks — `paper_supervisor.health`,
`paper_vs_backtest.compare`, `paper_health_score`, `paper_alerts` — rather than
recomputing them, so the monitor can never disagree with the daily routine.
Nothing here trades or connects. Live is never in scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from app.core.types import utc_now
from app.execution import paper_supervisor as ps
from app.execution.paper_supervisor import DAILY_SUMMARY_NAME, StopThresholds
from app.execution.supervised_paper import SupervisedPaperStore
from app.research.paper_alerts import CRITICAL, WARNING, AlertStore, evaluate_alert_specs
from app.research.paper_health_score import compute_health_score

PRODUCT = "long_only_t212"
TARGET_DAYS_DEFAULT = 90
SNAPSHOTS_NAME = "paper_health_snapshots.jsonl"


@dataclass
class MonitorResult:
    product: str
    generated_at: str
    session_id: str | None
    active: bool
    metrics: dict = field(default_factory=dict)
    health: dict = field(default_factory=dict)
    health_score: dict = field(default_factory=dict)
    alerts: list[dict] = field(default_factory=list)
    alert_counts: dict = field(default_factory=dict)
    paper_vs_backtest: dict = field(default_factory=dict)
    suggested_next_action: str = ""

    def as_dict(self) -> dict:
        return {
            "product": self.product, "generated_at": self.generated_at,
            "session_id": self.session_id, "active": self.active,
            "metrics": self.metrics, "health": self.health,
            "health_score": self.health_score, "alerts": self.alerts,
            "alert_counts": self.alert_counts, "paper_vs_backtest": self.paper_vs_backtest,
            "suggested_next_action": self.suggested_next_action, "live_eligible": False,
        }


def _today() -> date:
    return utc_now().replace(tzinfo=None).date()


def business_days_between(start: date, end: date) -> int:
    """Mon-Fri count in [start, end] inclusive (holiday-blind)."""
    if end < start:
        return 0
    n, d = 0, start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def next_business_day(after: date) -> date:
    d = after + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _pvb_status(verdict: str) -> str:
    v = (verdict or "").lower()
    if "severely" in v:
        return "severely_degraded"
    if "mildly" in v:
        return "mildly_degraded"
    if "invalid" in v or "not comparable" in v:
        return "invalid"
    return "within"


def _weekly_due(runtime_dir: Path, forward_days: int) -> bool:
    """A weekly review is due if there is at least one forward day and no weekly
    report has been written in the last 7 calendar days."""
    if forward_days < 1:
        return False
    paper_dir = Path(runtime_dir) / "paper"
    latest: date | None = None
    for p in paper_dir.glob("weekly_report_*.md"):
        try:
            d = date.fromisoformat(p.stem.replace("weekly_report_", "")[:10])
        except ValueError:
            continue
        latest = d if latest is None or d > latest else latest
    if latest is None:
        return True
    return (_today() - latest).days >= 7


def _append_snapshot(runtime_dir: Path, product: str, row: dict) -> None:
    """Append a health snapshot, keeping at most one row per date (latest wins)."""
    import json
    path = Path(runtime_dir) / "paper" / product / SNAPSHOTS_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if path.exists():
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
    rows = [r for r in rows if str(r.get("date")) != str(row.get("date"))]
    rows.append(row)
    path.write_text("\n".join(json.dumps(r, default=str) for r in rows) + "\n",
                    encoding="utf-8")


def load_snapshots(runtime_dir: Path, product: str = PRODUCT) -> list[dict]:
    import json
    path = Path(runtime_dir) / "paper" / product / SNAPSHOTS_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _suggested_action(active_alerts, h: dict, *, ran_today: bool, missed: int,
                      weekly_due: bool) -> str:
    crit = [a for a in active_alerts if a.severity == CRITICAL and not a.resolved]
    warn = [a for a in active_alerts if a.severity == WARNING and not a.resolved]
    if crit:
        return f"Resolve the critical alert: {crit[0].title}. {crit[0].suggested_action}"
    state = str(h.get("state", "")).upper()
    if state == "FAILED":
        return "The period is FAILED — investigate, then restart with --reset."
    if missed >= 1 and not ran_today:
        return "Run today's paper day to catch up the missed day(s)."
    if h.get("can_generate_final_report"):
        return "Generate the final supervised-paper report (minimum forward days reached)."
    if not ran_today:
        return "Run today's shadow/demo-preview paper day."
    if warn:
        return f"Review {len(warn)} warning alert(s) on the Paper Monitoring page."
    if weekly_due:
        return "Generate this week's weekly review report."
    return "No action needed — today's paper day is complete and the session is healthy."


def run_monitor(settings, storage, *, product: str = PRODUCT, min_days: int = 30,
                target_days: int = TARGET_DAYS_DEFAULT, duplicate_day_blocked: bool = False,
                data_stale: bool | None = None, last_bar_date: str | None = None,
                persist: bool = True) -> MonitorResult:
    """Evaluate the session and (optionally) persist alerts + a health snapshot."""
    from app.execution.paper_vs_backtest import compare

    now = utc_now().replace(tzinfo=None)
    now_iso = now.isoformat()
    store = SupervisedPaperStore(settings.runtime_dir, product)
    session = store.current_session()
    kill = ps._kill_switch_active(settings)
    is_candidate, decision_status, _ps = ps.product_status(settings, storage, product)

    if session is None:
        result = MonitorResult(
            product=product, generated_at=now_iso, session_id=None, active=False,
            metrics={"message": "no session — run supervised-paper-start"},
            suggested_next_action="Start a supervised paper session.")
        return result

    h = ps.health(store, settings, kill_switch_active=kill, decision_status=decision_status,
                  min_days=min_days)
    stop_rules = h.get("stop_rules", {"state": "OK", "triggered": []})
    pvb = compare(store, product=product)
    pvb_rows = {r.metric: r for r in pvb.rows}

    forward = int(h.get("forward_days_completed", 0) or 0)
    started = session.started_at
    try:
        start_d = date.fromisoformat(str(started)[:10])
    except ValueError:
        start_d = _today()
    expected = business_days_between(start_d, _today())
    missed = max(0, expected - forward)
    last_run = h.get("last_run_date")
    ran_today = str(last_run)[:10] == _today().isoformat() if last_run else False
    try:
        last_run_d = date.fromisoformat(str(last_run)[:10]) if last_run else None
    except ValueError:
        last_run_d = None
    next_run = (next_business_day(last_run_d) if last_run_d else _today()).isoformat()

    paper_pnl = h.get("paper_pnl_pct")
    bench_pnl = h.get("benchmark_pnl_pct")
    excess = (round(float(paper_pnl) - float(bench_pnl), 2)
              if paper_pnl is not None and bench_pnl is not None else None)

    t = StopThresholds()
    daily = [r for r in store.load("daily_reports") if not r.get("replay")]
    n_orders = sum(int(r.get("n_orders", 0)) for r in daily)
    rejected = int(h.get("rejected_orders", 0) or 0)
    reject_rate = round(100.0 * rejected / max(1, n_orders + rejected), 2)
    cash_drag = pvb_rows["cash_drag_pct"].actual if "cash_drag_pct" in pvb_rows else None
    n_holdings = daily[-1].get("n_holdings") if daily else None
    beta = pvb_rows["benchmark_beta"].actual if "benchmark_beta" in pvb_rows else None
    summary_exists = (Path(settings.runtime_dir) / "paper" / DAILY_SUMMARY_NAME).exists()

    if data_stale is None:
        data_stale = False

    metrics = {
        "session_id": session.session_id, "mode": session.mode, "started_at": started,
        "status": session.status,
        "forward_days_completed": forward, "expected_trading_days": expected,
        "missed_days": missed, "days_remaining_to_min": max(0, min_days - forward),
        "days_remaining_to_target": max(0, target_days - forward),
        "min_days": min_days, "target_days": target_days,
        "last_run_date": last_run, "ran_today": ran_today, "next_expected_run": next_run,
        "paper_pnl_pct": paper_pnl, "benchmark_pnl_pct": bench_pnl, "excess_return_pct": excess,
        "tracking_error_pct_daily": h.get("tracking_error_pct_daily"),
        "current_drawdown_pct": h.get("current_drawdown_pct"),
        "concentration_top_weight": h.get("concentration_top_weight"),
        "turnover_per_year": h.get("turnover_per_year"), "expected_turnover": 30.0,
        "cash_drag_pct": cash_drag, "n_holdings": n_holdings, "benchmark_beta": beta,
        "max_reconciliation_drift": h.get("max_reconciliation_drift"),
        "avg_slippage_bps": h.get("avg_slippage_bps"), "expected_slippage_bps": 5.0,
        "order_count": n_orders, "rejected_orders": rejected, "skipped_orders": rejected,
        "total_order_attempts": n_orders + rejected, "reject_rate_pct": reject_rate,
        "broker_errors": int(h.get("broker_errors", 0) or 0),
        "risk_breaches": int(h.get("risk_breaches", 0) or 0),
        "data_quality_events": int(h.get("data_quality_events", 0) or 0),
        "data_stale": bool(data_stale), "last_bar_date": last_bar_date,
        "missing_days_gap": int(h.get("missing_days_gap", 0) or 0),
        "duplicate_day_blocked": bool(duplicate_day_blocked),
        "report_missing": not summary_exists,
        "can_generate_final_report": bool(h.get("can_generate_final_report")),
        "paper_vs_backtest_status": _pvb_status(pvb.verdict),
        "paper_vs_backtest_verdict": pvb.verdict,
        "stop_state": stop_rules.get("state", "OK"),
        "kill_switch_active": bool(kill), "live_trading_allowed": settings.live_trading_allowed,
        "decision_is_candidate": bool(is_candidate), "decision_status": decision_status,
        "session_status": session.status,
        "fail_drawdown_pct": t.fail_drawdown_pct, "pause_drawdown_pct": t.pause_drawdown_pct,
        "weekly_due": _weekly_due(settings.runtime_dir, forward),
        "final_review_ready": bool(h.get("can_generate_final_report")),
    }

    score = compute_health_score(metrics)
    specs = evaluate_alert_specs(metrics)

    alert_store = AlertStore(settings.runtime_dir, product)
    if persist:
        alerts = alert_store.sync(specs, session_id=session.session_id, now=now_iso)
    else:
        alerts = alert_store.load()
    active = [a for a in alerts if not a.resolved]
    counts = {
        "critical": sum(1 for a in active if a.severity == CRITICAL),
        "warning": sum(1 for a in active if a.severity == WARNING),
        "info": sum(1 for a in active if a.severity not in (CRITICAL, WARNING)),
        "active_total": len(active), "resolved_total": sum(1 for a in alerts if a.resolved),
    }

    if persist:
        _append_snapshot(settings.runtime_dir, product, {
            "date": _today().isoformat(), "timestamp": now_iso,
            "score": score.score, "classification": score.classification,
            "paper_pnl_pct": paper_pnl, "benchmark_pnl_pct": bench_pnl,
            "drawdown_pct": metrics["current_drawdown_pct"],
            "concentration_top_weight": metrics["concentration_top_weight"],
            "turnover_per_year": metrics["turnover_per_year"],
            "active_alerts": counts["active_total"], "critical_alerts": counts["critical"],
            "warning_alerts": counts["warning"],
        })

    suggested = _suggested_action(active, h, ran_today=ran_today, missed=missed,
                                  weekly_due=metrics["weekly_due"])

    return MonitorResult(
        product=product, generated_at=now_iso, session_id=session.session_id, active=True,
        metrics=metrics, health=h, health_score=score.as_dict(),
        alerts=[a.as_dict() for a in alerts], alert_counts=counts,
        paper_vs_backtest=pvb.as_dict(), suggested_next_action=suggested)
