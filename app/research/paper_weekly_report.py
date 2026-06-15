"""Weekly review report for the supervised paper period (Phase 7).

Aggregates a trailing 7-calendar-day window of the forward shadow/paper record
into one operator-facing review with an explicit recommendation:

    continue | pause | investigate | fail session

It reuses the same stop-rule engine that drives daily health, so the weekly
recommendation can never be more permissive than the live stop rules. Output is
written to ``runtime/paper/weekly_report_YYYY-MM-DD.md``. Live is never in scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from app.execution.paper_supervisor import (
    _forward_daily,
    _kill_switch_active,
    evaluate_stop_rules,
    product_status,
)
from app.execution.supervised_paper import SupervisedPaperStore


@dataclass
class WeeklyReport:
    product: str
    as_of: str
    window_start: str
    window_end: str
    days_completed: int
    expected_trading_days: int
    missed_days: int
    paper_return_pct: float | None
    benchmark_return_pct: float | None
    excess_return_pct: float | None
    volatility_annual_pct: float | None
    drawdown_pct: float
    turnover_window: float
    max_concentration: float
    order_rejects: int
    skipped_orders: int
    broker_errors: int
    data_quality_events: int
    untradable_events: int
    avg_slippage_bps: float
    fees: float
    warnings: list[str] = field(default_factory=list)
    recommendation: str = "continue"
    stop_state: str = "OK"

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def _returns(series: list[float]) -> list[float]:
    return [series[i] / series[i - 1] - 1.0 for i in range(1, len(series)) if series[i - 1]]


def _business_days(start: date, end: date) -> int:
    """Mon-Fri count in [start, end] inclusive (holiday-blind approximation)."""
    if end < start:
        return 0
    n = 0
    d = start
    while d <= end:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def compute_weekly_report(store: SupervisedPaperStore, settings, *,
                          as_of: str | None = None, window_days: int = 7,
                          decision_status: str | None = None,
                          kill_switch_active: bool | None = None) -> WeeklyReport:
    daily = _forward_daily(store)
    end_date = (date.fromisoformat(as_of) if as_of
                else (date.fromisoformat(str(daily[-1]["date"])[:10]) if daily
                      else date.today()))
    start_date = end_date - timedelta(days=window_days - 1)

    def in_window(row: dict) -> bool:
        d = str(row.get("date", ""))[:10]
        try:
            return start_date <= date.fromisoformat(d) <= end_date
        except ValueError:
            return False

    win = [r for r in daily if in_window(r)]
    win_dates = sorted({str(r["date"])[:10] for r in win})
    days_completed = len(win_dates)
    # Only count expected trading days from when the session actually started — a
    # session begun mid-window is not "missing" the days before it existed.
    session = store.current_session()
    expected_from = start_date
    if session and session.started_at:
        try:
            expected_from = max(start_date, date.fromisoformat(str(session.started_at)[:10]))
        except ValueError:
            pass
    expected = _business_days(expected_from, end_date)
    missed = max(0, expected - days_completed)

    eq = [float(r["equity"]) for r in win if r.get("equity") is not None]
    paper_ret = round(100.0 * (eq[-1] / eq[0] - 1.0), 2) if len(eq) >= 2 and eq[0] else None
    daily_rets = _returns(eq)
    vol_annual = round(100.0 * _std(daily_rets) * (252 ** 0.5), 2) if len(daily_rets) >= 2 else None
    drawdown = round(min((float(r.get("drawdown_pct", 0.0)) for r in win), default=0.0), 2)
    max_conc = round(max((float(r.get("top_weight", 0.0)) for r in win), default=0.0), 4)
    rejects = sum(int(r.get("n_rejected", 0)) for r in win)
    broker_errors = sum(int(r.get("broker_errors", 0)) for r in win)
    dq = sum(int(r.get("data_quality_events", 0)) for r in win)
    untradable = sum(int(r.get("n_untradable", 0)) for r in win)

    # benchmark window return (aligned on window dates)
    bench = [b for b in store.load("benchmark_snapshots") if in_window(b)]
    spy = [float(b["spy_equity"]) for b in bench if b.get("spy_equity") is not None]
    bench_ret = round(100.0 * (spy[-1] / spy[0] - 1.0), 2) if len(spy) >= 2 and spy[0] else None
    excess = (round(paper_ret - bench_ret, 2)
              if paper_ret is not None and bench_ret is not None else None)

    # turnover within the window (sum of order notional / mean equity)
    orders = [o for o in store.load("orders") if in_window(o)]
    notional = sum(float(o.get("notional", 0.0)) for o in orders)
    mean_eq = sum(eq) / len(eq) if eq else 0.0
    turnover = round(notional / mean_eq, 3) if mean_eq else 0.0

    tca = [t for t in store.load("tca") if in_window(t)]
    slips = [float(t["realized_slippage_bps"]) for t in tca
             if t.get("realized_slippage_bps") is not None]
    avg_slip = round(sum(slips) / len(slips), 2) if slips else 0.0
    fees = round(sum(float(t.get("fees", 0.0)) for t in tca), 2)

    if kill_switch_active is None:
        kill_switch_active = _kill_switch_active(settings)
    rules = evaluate_stop_rules(store, settings, kill_switch_active=kill_switch_active,
                                decision_status=decision_status)
    warnings = [f"{r.severity}: {r.rule} — {r.detail}" for r in rules.triggered]

    # recommendation: never more permissive than the stop-rule state
    if rules.state == "FAILED":
        recommendation = "fail session"
    elif rules.state == "PAUSED":
        recommendation = "pause"
    elif missed >= 3 or (excess is not None and excess < -10.0) or abs(drawdown) > 12.0:
        recommendation = "investigate"
        if missed >= 3:
            warnings.append(f"{missed} expected trading day(s) missed in the window")
        if excess is not None and excess < -10.0:
            warnings.append(f"excess return {excess}ppt vs benchmark in the window")
        if abs(drawdown) > 12.0:
            warnings.append(f"window drawdown {drawdown}% is elevated")
    else:
        recommendation = "continue"

    return WeeklyReport(
        product=store.product, as_of=end_date.isoformat(),
        window_start=start_date.isoformat(), window_end=end_date.isoformat(),
        days_completed=days_completed, expected_trading_days=expected, missed_days=missed,
        paper_return_pct=paper_ret, benchmark_return_pct=bench_ret, excess_return_pct=excess,
        volatility_annual_pct=vol_annual, drawdown_pct=drawdown, turnover_window=turnover,
        max_concentration=max_conc, order_rejects=rejects, skipped_orders=rejects,
        broker_errors=broker_errors, data_quality_events=dq, untradable_events=untradable,
        avg_slippage_bps=avg_slip, fees=fees, warnings=warnings,
        recommendation=recommendation, stop_state=rules.state)


def render_weekly_report(rep: WeeklyReport) -> str:
    rec_note = {
        "continue": "Continue the supervised period; nothing requires intervention this week.",
        "pause": "Pause and resolve the active stop rule(s) before the next paper day.",
        "investigate": "Investigate the flagged item(s); the period can continue meanwhile.",
        "fail session": "A terminal stop rule fired — the period is invalid; do not continue.",
    }[rep.recommendation]
    rows = [
        ("Window", f"{rep.window_start} → {rep.window_end}"),
        ("Days completed (forward)", rep.days_completed),
        ("Expected trading days (Mon-Fri)", rep.expected_trading_days),
        ("Missed days", rep.missed_days),
        ("Paper return", f"{rep.paper_return_pct}%" if rep.paper_return_pct is not None else "n/a"),
        ("Benchmark return",
         f"{rep.benchmark_return_pct}%" if rep.benchmark_return_pct is not None else "n/a"),
        ("Excess return", f"{rep.excess_return_pct}ppt" if rep.excess_return_pct is not None else "n/a"),
        ("Volatility (annualised)",
         f"{rep.volatility_annual_pct}%" if rep.volatility_annual_pct is not None else "n/a"),
        ("Window drawdown", f"{rep.drawdown_pct}%"),
        ("Turnover (window, one-way)", rep.turnover_window),
        ("Max concentration (top weight)", f"{rep.max_concentration:.2%}"),
        ("Order rejects / skipped", rep.order_rejects),
        ("Broker errors", rep.broker_errors),
        ("Data-quality events", rep.data_quality_events),
        ("Untradable-name events", rep.untradable_events),
        ("Avg realised slippage", f"{rep.avg_slippage_bps} bps"),
        ("Fees", rep.fees),
        ("Stop-rule state", rep.stop_state),
    ]
    lines = [
        f"# Weekly Paper Review — {rep.product} (as of {rep.as_of})",
        "",
        "_Generated by `statarb supervised-paper-weekly-report`. **NOT LIVE ELIGIBLE.**_",
        "",
        f"## Recommendation: {rep.recommendation.upper()}",
        "",
        rec_note,
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        *[f"| {k} | {v} |" for k, v in rows],
        "",
        "## Warnings",
        "",
        *([f"- {w}" for w in rep.warnings] or ["- (none)"]),
        "",
        "---",
        "_NOT LIVE ELIGIBLE — this report reviews a paper/shadow period only._",
    ]
    return "\n".join(lines) + "\n"


def write_weekly_report(settings, store: SupervisedPaperStore, *, storage=None,
                        as_of: str | None = None) -> tuple[Path, WeeklyReport]:
    """Compute, render and persist the weekly report; returns (path, report).

    When `storage` is supplied the product-eligibility stop rule is evaluated; if
    it is None that single rule is skipped (the daily routine and final report
    cover eligibility separately)."""
    decision_status = None
    if storage is not None:
        try:
            _ok, decision_status, _ps = product_status(settings, storage, store.product)
        except Exception:  # noqa: BLE001 - degrade gracefully; the rule is just skipped
            decision_status = None
    rep = compute_weekly_report(store, settings, as_of=as_of, decision_status=decision_status)
    md = render_weekly_report(rep)
    out = Path(settings.runtime_dir) / "paper" / f"weekly_report_{rep.as_of}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    return out, rep
