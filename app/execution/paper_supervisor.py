"""Supervised paper-period supervision (operator mission, Phases 2-4).

A single home for the operator-facing supervision logic that the CLI
(`supervised-paper-daily`, `supervised-paper-health`) and the dashboard both
call, so the rules live in one auditable place:

* **PRE-FLIGHT gates** — the hard conditions that must hold *before* a paper day
  is recorded: the product is still `paper_candidate`, live trading is disabled,
  the kill switch is off, and `demo_execute` was explicitly confirmed. A failed
  gate REFUSES the day (records nothing).
* **STOP RULES** — the conditions that, once days are recorded, mark the period
  PAUSED (recoverable / transient — fix and continue) or FAILED (terminal — the
  period is invalid). Every rule carries a plain reason and a remediation step.
* **HEALTH** — the one status the operator reads each morning, reduced to
  NOT STARTED / IN PROGRESS / PAUSED / FAILED / READY FOR FINAL REVIEW.

Nothing here trades, connects, or sends orders. Live is never in scope; every
report restates that the system is not live-eligible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.execution.supervised_paper import SupervisedPaperStore

# The supervised product id ("long_only_t212") maps to the product-decision
# engine's product id ("long_only_equity"); keep the mapping in one place.
PRODUCT_DECISION_ID = {"long_only_t212": "long_only_equity"}

DAILY_SUMMARY_NAME = "latest_daily_summary.md"

MODES = ("shadow", "demo_preview", "demo_execute")


# --------------------------------------------------------------------------------
# pre-flight gates
# --------------------------------------------------------------------------------

@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Preflight:
    ok: bool
    checks: list[Check]
    refusal_reason: str
    terminal: bool          # True => the failure should FAIL the session, not just refuse

    def failed_names(self) -> list[str]:
        return [c.name for c in self.checks if not c.ok]


def product_status(settings, storage, product: str):
    """Return (is_paper_candidate, status_str, ProductStatus|None) for a product."""
    from app.research.product_decision import evaluate_products

    decision = evaluate_products(settings, storage)
    did = PRODUCT_DECISION_ID.get(product, product)
    ps = next((p for p in decision.products if p.product_id == did), None)
    if ps is None:
        return False, "not_evaluated", None
    return ps.status == "paper_candidate", ps.status, ps


def _kill_switch_active(settings) -> bool:
    from app.risk.kill_switch import KillSwitch

    return KillSwitch(settings.runtime_dir / "kill_switch.flag").is_active


def preflight(settings, storage, *, product: str, mode: str,
              confirm_demo: bool, kill_switch_active: bool | None = None) -> Preflight:
    """Evaluate every hard gate that must hold before a paper day is recorded."""
    if kill_switch_active is None:
        kill_switch_active = _kill_switch_active(settings)
    is_candidate, status, _ps = product_status(settings, storage, product)
    live_off = not settings.live_trading_allowed

    checks: list[Check] = [
        Check("mode is valid", mode in MODES, f"mode={mode!r}; choose {MODES}"),
        Check("product-decision still paper_candidate", is_candidate,
              f"product-decision status is '{status}', not 'paper_candidate'"),
        Check("live trading disabled", live_off,
              "global live-trading gate is ON — refusing (this product is paper-only)"),
        Check("kill switch off", not kill_switch_active, "kill switch is ENGAGED"),
    ]
    if mode == "demo_execute":
        checks.append(Check("--confirm-demo provided for demo_execute", confirm_demo,
                            "demo_execute requires explicit --confirm-demo"))

    ok = all(c.ok for c in checks)
    refusal = "; ".join(c.detail for c in checks if not c.ok)
    # losing eligibility or a live flag flip is terminal; the rest are recoverable
    terminal = (not is_candidate) or (not live_off)
    return Preflight(ok=ok, checks=checks, refusal_reason=refusal, terminal=terminal)


# --------------------------------------------------------------------------------
# stop rules
# --------------------------------------------------------------------------------

@dataclass
class StopThresholds:
    """Hard limits for the supervised period. Conservative by design."""

    pause_drawdown_pct: float = 20.0        # |paper drawdown| above this -> PAUSE
    fail_drawdown_pct: float = 35.0         # ... above this -> FAIL
    max_reject_rate_pct: float = 10.0       # order reject rate -> PAUSE
    max_broker_errors: int = 3              # cumulative demo broker errors -> PAUSE
    max_concentration: float = 0.25         # top-name weight -> PAUSE
    slippage_spike_mult: float = 3.0        # realized vs expected slippage -> PAUSE
    slippage_floor_bps: float = 25.0        # ... only once realized exceeds this floor
    underperform_ppt: float = 20.0          # paper minus benchmark return (ppt) -> PAUSE
    underperform_min_days: int = 15         # ... only judged after this many forward days
    stale_days: int = 4                     # forward gap (calendar days) -> PAUSE
    max_data_quality_events: int = 3        # cumulative data-quality events -> PAUSE
    max_drift: float = 0.10                 # reconciliation gross drift -> PAUSE


@dataclass
class StopRule:
    rule: str
    severity: str           # PAUSED | FAILED
    detail: str
    remediation: str

    def as_dict(self) -> dict:
        return {"rule": self.rule, "severity": self.severity,
                "detail": self.detail, "remediation": self.remediation}


@dataclass
class StopRulesResult:
    state: str                                  # OK | PAUSED | FAILED
    triggered: list[StopRule] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"state": self.state, "triggered": [r.as_dict() for r in self.triggered]}


def _forward_daily(store: SupervisedPaperStore) -> list[dict]:
    rows = [r for r in store.load("daily_reports") if not r.get("replay", False)]
    return sorted(rows, key=lambda r: str(r.get("date", "")))


def _equity_by_date(rows: list[dict], key: str = "equity") -> dict[str, float]:
    out: dict[str, float] = {}
    for r in rows:
        d = str(r.get("date", ""))[:10]
        v = r.get(key)
        if d and v is not None:
            out[d] = float(v)
    return out


def _returns(series: list[float]) -> list[float]:
    return [series[i] / series[i - 1] - 1.0 for i in range(1, len(series))
            if series[i - 1]]


def _gap_days(last_date: str | None) -> int:
    """Calendar days since the last forward run (0 if today / unknown)."""
    if not last_date:
        return 0
    from datetime import date

    from app.core.types import utc_now
    try:
        last = date.fromisoformat(str(last_date)[:10])
    except ValueError:
        return 0
    return max(0, (utc_now().replace(tzinfo=None).date() - last).days)


def evaluate_stop_rules(store: SupervisedPaperStore, settings, *,
                        kill_switch_active: bool | None = None,
                        decision_status: str | None = None,
                        thresholds: StopThresholds | None = None) -> StopRulesResult:
    """Evaluate every stop rule against the recorded period + live context.

    PAUSED rules are transient (clear when the condition clears); FAILED rules
    are terminal integrity violations. Live is never in scope here."""
    t = thresholds or StopThresholds()
    if kill_switch_active is None:
        kill_switch_active = _kill_switch_active(settings)
    # `decision_status` is supplied by callers that already evaluated the product
    # decision (CLI / dashboard). If absent we simply skip the eligibility rule
    # rather than re-deriving it without a storage handle.

    triggered: list[StopRule] = []

    def trip(rule: str, severity: str, detail: str, remediation: str) -> None:
        triggered.append(StopRule(rule, severity, detail, remediation))

    daily = _forward_daily(store)
    recon = store.load("reconciliations")
    risk = store.load("risk_snapshots")
    tca = store.load("tca")
    bench = store.load("benchmark_snapshots")

    # --- 1) live trading accidentally enabled (terminal) ---
    if settings.live_trading_allowed:
        trip("live trading enabled", "FAILED",
             "the global live-trading gate is ON",
             "set LIVE_TRADING=false and CONFIRM_LIVE_TRADING=false; this product is paper-only")

    # --- 2) kill switch engaged (pause) ---
    if kill_switch_active:
        trip("kill switch engaged", "PAUSED",
             "the kill switch flag is active",
             "investigate the cause, then `statarb kill-switch --off` to resume")

    # --- 3/4) lost paper eligibility / not paper_candidate (terminal) ---
    if decision_status and decision_status != "paper_candidate":
        trip("product no longer paper_candidate", "FAILED",
             f"product-decision status is '{decision_status}'",
             "re-run the readiness gates (long-only-readiness --full) and restart the period")

    # --- 5) missing data / staleness (pause) ---
    last_date = daily[-1]["date"] if daily else None
    gap = _gap_days(last_date)
    if daily and gap > t.stale_days:
        trip("missing data / stale period", "PAUSED",
             f"{gap} calendar days since the last forward run ({last_date})",
             "refresh market data and run `supervised-paper-daily` to catch up")
    dq = sum(int(r.get("data_quality_events", 0)) for r in daily)
    if dq > t.max_data_quality_events:
        trip("data-quality events exceeded", "PAUSED",
             f"{dq} data-quality events recorded (> {t.max_data_quality_events})",
             "audit the data feed (`statarb data-audit`) before continuing")

    # --- 6) order rejects exceed threshold (pause) ---
    sent = sum(int(r.get("demo_orders_sent", 0)) for r in daily)
    n_orders = sum(int(r.get("n_orders", 0)) for r in daily)
    rejected = sum(int(r.get("n_rejected", 0)) for r in daily)
    denom = max(1, n_orders + rejected)
    reject_rate = 100.0 * rejected / denom
    if (n_orders + rejected) >= 10 and reject_rate > t.max_reject_rate_pct:
        trip("order reject rate too high", "PAUSED",
             f"reject rate {reject_rate:.1f}% (> {t.max_reject_rate_pct}%)",
             "inspect rejected orders in the daily report; check instrument tradability / min order value")

    # --- 7) demo broker errors exceed threshold (pause) ---
    broker_errors = sum(int(r.get("broker_errors", 0)) for r in daily)
    if broker_errors > t.max_broker_errors:
        trip("demo broker errors exceeded", "PAUSED",
             f"{broker_errors} demo broker errors (> {t.max_broker_errors})",
             "run `statarb trading212-demo-setup-check`; verify demo keys/connectivity")

    # --- 8) paper drawdown exceeds limit (pause/fail) ---
    drawdowns = [float(r.get("drawdown_pct", 0.0)) for r in daily]
    worst_dd = min(drawdowns) if drawdowns else 0.0
    if abs(worst_dd) > t.fail_drawdown_pct:
        trip("paper drawdown beyond hard limit", "FAILED",
             f"paper drawdown {worst_dd:.1f}% (> {t.fail_drawdown_pct}% hard limit)",
             "the period is invalid; review the strategy before any restart")
    elif abs(worst_dd) > t.pause_drawdown_pct:
        trip("paper drawdown beyond policy", "PAUSED",
             f"paper drawdown {worst_dd:.1f}% (> {t.pause_drawdown_pct}% policy)",
             "pause and review risk; resume only if the drawdown is understood")

    # --- 9) underperformance vs benchmark (pause, only on enough days) ---
    paper_ret = bench_ret = None
    eq = [float(r["equity"]) for r in daily if r.get("equity") is not None]
    if len(eq) >= 2 and eq[0]:
        paper_ret = 100.0 * (eq[-1] / eq[0] - 1.0)
    spy = [float(r["spy_equity"]) for r in bench if r.get("spy_equity") is not None]
    if len(spy) >= 2 and spy[0]:
        bench_ret = 100.0 * (spy[-1] / spy[0] - 1.0)
    if (paper_ret is not None and bench_ret is not None
            and len(daily) >= t.underperform_min_days
            and (paper_ret - bench_ret) < -t.underperform_ppt):
        trip("severe underperformance vs benchmark", "PAUSED",
             f"paper {paper_ret:.1f}% vs benchmark {bench_ret:.1f}% "
             f"(> {t.underperform_ppt}ppt behind)",
             "review whether paper behaviour matches the backtest (`paper-vs-backtest`)")

    # --- 10) TCA slippage far worse than expected (pause) ---
    for row in tca:
        exp = float(row.get("avg_expected_slippage_bps", 0.0) or 0.0)
        real = float(row.get("realized_slippage_bps", 0.0) or 0.0)
        if real > t.slippage_floor_bps and exp > 0 and real > t.slippage_spike_mult * exp:
            trip("TCA slippage far worse than expected", "PAUSED",
                 f"realized {real:.0f}bps vs expected {exp:.0f}bps on {row.get('date')}",
                 "check liquidity / limit offsets; widen the marketable-limit band if justified")
            break

    # --- 11) concentration reappears above limit (pause) ---
    top = max((float(r.get("top_weight", 0.0)) for r in daily), default=0.0)
    if top > t.max_concentration + 1e-6:
        trip("concentration above limit", "PAUSED",
             f"top-name weight {top:.1%} (> {t.max_concentration:.0%})",
             "confirm EWMA smoothing is active; re-run concentration-fix-backtest if it recurs")

    # --- 12) EWMA smoothing fails its constraint checks (terminal) ---
    if any(r.get("smoothing_ok") is False for r in daily):
        bad = next(r for r in daily if r.get("smoothing_ok") is False)
        trip("EWMA smoothing constraint failure", "FAILED",
             f"smoothed weights violated long-only/no-leverage constraints on {bad.get('date')}",
             "this is a code-level invariant breach; fix the smoother before any restart")

    # --- 13) instrument became untradable (pause) ---
    untradable = sum(int(r.get("n_untradable", 0)) for r in daily)
    if untradable > 0:
        last_bad = next((r for r in reversed(daily) if int(r.get("n_untradable", 0)) > 0), {})
        trip("instrument(s) became untradable", "PAUSED",
             f"{int(last_bad.get('n_untradable', 0))} target name(s) not tradable on Invest/ISA "
             f"on {last_bad.get('date')}",
             "refresh the instrument cache (`statarb trading212-instruments`); the name may be delisted")

    # --- 14) market-hours logic fails (pause) ---
    if any(r.get("market_hours_ok") is False for r in daily):
        bad = next(r for r in daily if r.get("market_hours_ok") is False)
        trip("market-hours logic failed", "PAUSED",
             f"the market-open check raised on {bad.get('date')}",
             "inspect order_validation.is_us_market_open; the broker is the final authority")

    # --- 15) reconciliation fails / shorts appear ---
    n_short = max((int(r.get("n_short_positions", 0)) for r in recon), default=0)
    if n_short > 0:
        trip("short position detected", "FAILED",
             f"{n_short} short position(s) — impossible on long-only Invest/ISA",
             "the period is invalid; investigate the order path immediately")
    max_drift = max((float(r.get("total_abs_drift", 0.0)) for r in recon), default=0.0)
    if max_drift > t.max_drift:
        trip("reconciliation drift too high", "PAUSED",
             f"gross drift {max_drift:.1%} between target and broker book",
             "reconcile positions; re-plan to bring the book back to target")

    risk_breaches = sum(1 for r in risk if r.get("breach"))
    if risk_breaches > 0:
        trip("risk-snapshot breach", "PAUSED",
             f"{risk_breaches} day(s) breached the risk snapshot limits",
             "review risk (`statarb supervised-paper-daily-report`) and pause if it recurs")

    _ = sent  # documented above; kept for parity with final report accounting
    state = ("FAILED" if any(r.severity == "FAILED" for r in triggered)
             else "PAUSED" if triggered else "OK")
    return StopRulesResult(state=state, triggered=triggered)


# --------------------------------------------------------------------------------
# health
# --------------------------------------------------------------------------------

def _daily_returns_aligned(daily: list[dict], bench: list[dict]) -> tuple[list[float], list[float]]:
    """Paper & benchmark daily returns aligned on common dates (forward only)."""
    p_by = _equity_by_date(daily, "equity")
    b_by = _equity_by_date(bench, "spy_equity")
    dates = sorted(set(p_by) & set(b_by))
    p = [p_by[d] for d in dates]
    b = [b_by[d] for d in dates]
    return _returns(p), _returns(b)


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def health(store: SupervisedPaperStore, settings, *,
           kill_switch_active: bool | None = None,
           decision_status: str | None = None,
           thresholds: StopThresholds | None = None,
           min_days: int = 30) -> dict:
    """One consolidated health status for the operator."""
    session = store.current_session()
    if session is None:
        return {"state": "NOT STARTED", "product": store.product,
                "message": "no session — run `statarb supervised-paper-start`",
                "can_generate_final_report": False}

    daily = _forward_daily(store)
    replay = [r for r in store.load("daily_reports") if r.get("replay", False)]
    recon = store.load("reconciliations")
    risk = store.load("risk_snapshots")
    tca = store.load("tca")
    bench = store.load("benchmark_snapshots")

    forward_days = len({str(r["date"])[:10] for r in daily})
    last_date = daily[-1]["date"] if daily else None

    eq = [float(r["equity"]) for r in daily if r.get("equity") is not None]
    paper_pnl = round(100.0 * (eq[-1] / eq[0] - 1.0), 2) if len(eq) >= 2 and eq[0] else 0.0
    spy = [float(r["spy_equity"]) for r in bench if r.get("spy_equity") is not None]
    bench_pnl = round(100.0 * (spy[-1] / spy[0] - 1.0), 2) if len(spy) >= 2 and spy[0] else None

    p_ret, b_ret = _daily_returns_aligned(daily, bench)
    n = min(len(p_ret), len(b_ret))
    tracking_error = (round(100.0 * _std([p_ret[i] - b_ret[i] for i in range(n)]), 3)
                      if n >= 2 else None)

    rejected = sum(int(r.get("n_rejected", 0)) for r in daily)
    broker_errors = sum(int(r.get("broker_errors", 0)) for r in daily)
    cur_dd = float(daily[-1].get("drawdown_pct", 0.0)) if daily else 0.0
    top = max((float(r.get("top_weight", 0.0)) for r in daily), default=0.0)
    risk_breaches = sum(1 for r in risk if r.get("breach"))
    dq = sum(int(r.get("data_quality_events", 0)) for r in daily)
    avg_slip = ([float(r["realized_slippage_bps"]) for r in tca
                 if r.get("realized_slippage_bps") is not None])
    avg_slip = round(sum(avg_slip) / len(avg_slip), 2) if avg_slip else 0.0
    max_drift = round(max((float(r.get("total_abs_drift", 0.0)) for r in recon), default=0.0), 4)

    # turnover during paper: mean one-way daily turnover (orders notional / equity), annualised
    orders = store.load("orders")
    notional_by_date: dict[str, float] = {}
    for o in orders:
        notional_by_date[str(o.get("date", ""))[:10]] = (
            notional_by_date.get(str(o.get("date", ""))[:10], 0.0) + float(o.get("notional", 0.0)))
    eq_by = _equity_by_date(daily, "equity")
    turns = [notional_by_date.get(d, 0.0) / eq_by[d] for d in eq_by if eq_by[d]]
    turnover_annual = round((sum(turns) / len(turns)) * 252, 1) if turns else 0.0

    rules = evaluate_stop_rules(store, settings, kill_switch_active=kill_switch_active,
                                decision_status=decision_status, thresholds=thresholds)

    if session.status == "stopped":
        state = "FAILED"
    elif rules.state == "FAILED":
        state = "FAILED"
    elif rules.state == "PAUSED":
        state = "PAUSED"
    elif forward_days >= min_days:
        state = "READY FOR FINAL REVIEW"
    else:
        state = "IN PROGRESS"

    return {
        "state": state,
        "product": store.product,
        "session_id": session.session_id,
        "session_status": session.status,
        "stop_reason": session.stop_reason,
        "mode": session.mode,
        "started_at": session.started_at,
        "min_days": min_days,
        "forward_days_completed": forward_days,
        "days_remaining": max(0, min_days - forward_days),
        "replay_days_recorded": len({str(r["date"])[:10] for r in replay}),
        "last_run_date": last_date,
        "missing_days_gap": _gap_days(last_date),
        "rejected_orders": rejected,
        "broker_errors": broker_errors,
        "paper_pnl_pct": paper_pnl,
        "benchmark_pnl_pct": bench_pnl,
        "tracking_error_pct_daily": tracking_error,
        "current_drawdown_pct": round(cur_dd, 2),
        "concentration_top_weight": round(top, 4),
        "turnover_per_year": turnover_annual,
        "avg_slippage_bps": avg_slip,
        "max_reconciliation_drift": max_drift,
        "risk_breaches": risk_breaches,
        "data_quality_events": dq,
        "can_generate_final_report": forward_days >= min_days and state != "FAILED",
        "stop_rules": rules.as_dict(),
        "live_eligible": False,
    }


def health_for(settings, storage, *, product: str = "long_only_t212", min_days: int = 30) -> dict:
    """Convenience wrapper that gathers live context (kill switch, decision)."""
    store = SupervisedPaperStore(settings.runtime_dir, product)
    _ok, status, _ps = product_status(settings, storage, product)
    return health(store, settings, kill_switch_active=_kill_switch_active(settings),
                  decision_status=status, min_days=min_days)


def operator_checklist(settings, h: dict, decision_status: str,
                       *, kill_switch_active: bool | None = None) -> list[dict]:
    """The operator's daily checklist, each item with a computed done/blocked flag."""
    from datetime import date  # noqa: F401 - kept for readability of the today comparison

    from app.core.types import utc_now
    if kill_switch_active is None:
        kill_switch_active = _kill_switch_active(settings)
    today = utc_now().replace(tzinfo=None).date().isoformat()
    sr_state = (h.get("stop_rules") or {}).get("state", "OK")
    items = [
        ("Product still paper_candidate", decision_status == "paper_candidate",
         f"status = {decision_status}"),
        ("Live trading disabled", not settings.live_trading_allowed, ""),
        ("Kill switch off", not kill_switch_active, ""),
        ("Today's paper day recorded", h.get("last_run_date") == today,
         f"last run {h.get('last_run_date')}"),
        ("No stop rules triggered", sr_state == "OK", f"stop rules: {sr_state}"),
        ("Reconciliation drift low (<= 2%)",
         float(h.get("max_reconciliation_drift") or 0.0) <= 0.02, ""),
        ("Concentration within 25%",
         float(h.get("concentration_top_weight") or 0.0) <= 0.25, ""),
    ]
    return [{"item": i, "done": bool(done), "note": note} for i, done, note in items]


# --------------------------------------------------------------------------------
# daily notification summary (Phase 8)
# --------------------------------------------------------------------------------

def render_daily_summary(day_info: dict, *, health_state: str, next_action: str,
                         status_line: str) -> str:
    """Render the operator's daily summary (Markdown). Structured so it can later
    be pushed to Telegram/Discord/email without changing the producer."""
    weights = day_info.get("target_weights", {})
    top = sorted(weights.items(), key=lambda kv: -kv[1])[:10]
    orders = day_info.get("planned_orders", [])
    refused = day_info.get("refused_orders", [])
    lines = [
        f"# Supervised paper daily summary — {day_info.get('product', 'long_only_t212')}",
        "",
        f"- **Date**: {day_info.get('date')} ({'REPLAY' if day_info.get('replay') else 'FORWARD'})",
        f"- **Mode**: {day_info.get('mode')}",
        f"- **Session health**: {health_state}",
        f"- **Result**: {status_line}",
        "",
        "## Result snapshot",
        f"- Equity: {day_info.get('equity')}",
        f"- Day paper PnL: {day_info.get('paper_pnl_day')}",
        f"- Cumulative paper PnL: {day_info.get('paper_pnl_pct')}%",
        f"- Benchmark (SPY) PnL: {day_info.get('benchmark_pnl_pct')}%",
        f"- Gross exposure: {day_info.get('gross_exposure')}",
        f"- Top-name weight: {day_info.get('top_weight')}",
        f"- Drawdown: {day_info.get('drawdown_pct')}%",
        f"- Risk status: {day_info.get('risk_status')}",
        f"- TCA (expected/realized slippage bps): "
        f"{day_info.get('expected_slippage_bps')} / {day_info.get('realized_slippage_bps')}",
        f"- Demo orders submitted: {day_info.get('demo_orders_sent', 0)}; "
        f"broker errors: {day_info.get('broker_errors', 0)}",
        "",
        f"## Target weights (top {len(top)})",
        *([f"- {s}: {w:.2%}" for s, w in top] or ["- (none)"]),
        "",
        f"## Planned orders ({len(orders)})",
        *([f"- {o['side']} {o['symbol']} qty {round(float(o['quantity']), 4)} "
           f"@ {o.get('limit_price') or 'mkt'} (notional {o.get('notional')})"
           for o in orders[:25]] or ["- (none — book already at target)"]),
        "",
        f"## Refused / skipped orders ({len(refused)})",
        *([f"- {sym}: {reason}" for sym, reason in refused[:25]] or ["- (none)"]),
        "",
        "## Next action",
        f"{next_action}",
        "",
        "---",
        "_NOT LIVE ELIGIBLE — no real-money orders can be placed by this system._",
    ]
    return "\n".join(lines) + "\n"


def write_daily_summary(runtime_dir: Path, markdown: str) -> Path:
    out = Path(runtime_dir) / "paper" / DAILY_SUMMARY_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, encoding="utf-8")
    return out
