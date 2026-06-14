"""Paper-vs-backtest behaviour comparison (operator mission, Phase 5).

A forward supervised period is too short to judge ALPHA — a handful of days
cannot confirm or deny a Sharpe of 1.65. What a short period CAN do is reveal
whether the live pipeline *behaves operationally* like the backtest: does it hold
a similar number of names, turn over at a similar rate, stay near fully invested,
keep concentration capped, and execute with the expected slippage and reject
rate? Divergence there means the paper run is not a faithful forward image of the
backtest, regardless of PnL.

So this module compares operational behaviour against the backtest expectation
and returns a verdict — within / mildly degraded / severely degraded / invalid —
while reporting return-shaped metrics (volatility, drawdown, beta, alpha) as
*informational only* until the sample is large enough to mean anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.execution.supervised_paper import SupervisedPaperStore

# Backtest expectations for the long-only Trading 212 candidate, taken from the
# validated long-only readiness backtest (the lead product). Operational ranges
# are deliberately wide — we are catching gross divergence, not fine-tuning.
BACKTEST_EXPECTATIONS = {
    "long_only_t212": {
        "oos_sharpe": 1.65,
        "turnover_per_year": 30.0,          # ~30x/year after EWMA smoothing
        "max_drawdown_pct": -16.9,
        "worst_month_concentration_pct": 23.5,
        "gross_exposure": (0.85, 1.001),    # near fully invested, no leverage
        "avg_holdings": (8, 30),            # top-momentum names in us_stocks_50
        "concentration_top_weight_max": 0.25,
        "expected_slippage_bps": 5.0,
        "reject_rate_pct_max": 5.0,
    }
}

MIN_DAYS_FOR_COMPARISON = 5            # below this, operational behaviour isn't comparable
MIN_DAYS_FOR_RETURNS = 15             # below this, return-shaped metrics stay informational


@dataclass
class MetricRow:
    metric: str
    expected: str
    actual: object
    status: str            # within | mildly_degraded | severely_degraded | not_comparable | informational
    operational: bool
    note: str = ""

    def as_dict(self) -> dict:
        return {"metric": self.metric, "expected": self.expected, "actual": self.actual,
                "status": self.status, "operational": self.operational, "note": self.note}


@dataclass
class ComparisonReport:
    product: str
    forward_days: int
    verdict: str
    rows: list[MetricRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"product": self.product, "forward_days": self.forward_days,
                "verdict": self.verdict, "rows": [r.as_dict() for r in self.rows],
                "notes": self.notes, "live_eligible": False}


def _forward(store: SupervisedPaperStore) -> list[dict]:
    rows = [r for r in store.load("daily_reports") if not r.get("replay", False)]
    return sorted(rows, key=lambda r: str(r.get("date", "")))


def _returns(series: list[float]) -> list[float]:
    return [series[i] / series[i - 1] - 1.0 for i in range(1, len(series)) if series[i - 1]]


def _band(value: float, within: tuple[float, float], mild: tuple[float, float]) -> str:
    lo, hi = within
    if lo <= value <= hi:
        return "within"
    mlo, mhi = mild
    if mlo <= value <= mhi:
        return "mildly_degraded"
    return "severely_degraded"


def compare(store: SupervisedPaperStore, *, product: str = "long_only_t212") -> ComparisonReport:
    exp = BACKTEST_EXPECTATIONS.get(product, BACKTEST_EXPECTATIONS["long_only_t212"])
    daily = _forward(store)
    bench = store.load("benchmark_snapshots")
    orders = store.load("orders")
    tca = store.load("tca")
    n = len({str(r["date"])[:10] for r in daily})

    rows: list[MetricRow] = []
    notes: list[str] = []

    if n < MIN_DAYS_FOR_COMPARISON:
        notes.append(f"Only {n} forward day(s) recorded; need >= {MIN_DAYS_FOR_COMPARISON} "
                     "before operational behaviour is comparable.")
        return ComparisonReport(product=product, forward_days=n,
                                verdict="invalid / not comparable", rows=rows, notes=notes)

    eq_by = {str(r["date"])[:10]: float(r["equity"]) for r in daily if r.get("equity") is not None}

    # --- turnover (operational) ---
    notional_by_date: dict[str, float] = {}
    for o in orders:
        d = str(o.get("date", ""))[:10]
        notional_by_date[d] = notional_by_date.get(d, 0.0) + float(o.get("notional", 0.0))
    turns = [notional_by_date.get(d, 0.0) / eq_by[d] for d in eq_by if eq_by[d]]
    turnover = round((sum(turns) / len(turns)) * 252, 1) if turns else 0.0
    tgt = exp["turnover_per_year"]
    rows.append(MetricRow(
        "turnover_per_year", f"~{tgt:g}x/yr", turnover,
        _band(turnover, (0.5 * tgt, 1.5 * tgt), (0.3 * tgt, 2.5 * tgt)), True,
        "annualised one-way turnover from recorded orders"))

    # --- gross exposure (operational) ---
    gross = [float(r.get("gross_exposure", 0.0)) for r in daily]
    mean_gross = round(sum(gross) / len(gross), 3) if gross else 0.0
    lo, hi = exp["gross_exposure"]
    rows.append(MetricRow(
        "gross_exposure", f"{lo:.2f}-{hi:.2f}", mean_gross,
        _band(mean_gross, (lo, hi), (0.6, hi)), True, "mean daily gross exposure"))

    # --- cash drag (operational, informational band) ---
    cash_drag = round(100.0 * (1.0 - mean_gross), 2)
    rows.append(MetricRow(
        "cash_drag_pct", "<= 15%", cash_drag,
        "within" if cash_drag <= 15 else "mildly_degraded" if cash_drag <= 30 else "severely_degraded",
        True, "uninvested cash = 1 - gross exposure"))

    # --- average holdings (operational) ---
    holds = [int(r.get("n_holdings", 0)) for r in daily if "n_holdings" in r]
    avg_holdings = round(sum(holds) / len(holds), 1) if holds else None
    hlo, hhi = exp["avg_holdings"]
    if avg_holdings is None:
        rows.append(MetricRow("avg_holdings", f"{hlo}-{hhi}", None, "not_comparable", True,
                              "holdings count not recorded"))
    else:
        rows.append(MetricRow(
            "avg_holdings", f"{hlo}-{hhi}", avg_holdings,
            _band(avg_holdings, (hlo, hhi), (hlo - 3, hhi + 10)), True, "mean number of held names"))

    # --- concentration (operational) ---
    top = round(max((float(r.get("top_weight", 0.0)) for r in daily), default=0.0), 4)
    cmax = exp["concentration_top_weight_max"]
    rows.append(MetricRow(
        "concentration_top_weight", f"<= {cmax:.0%}", top,
        "within" if top <= cmax else "mildly_degraded" if top <= cmax + 0.05 else "severely_degraded",
        True, "max single-name weight during paper"))

    # --- reject rate (operational) ---
    n_orders = sum(int(r.get("n_orders", 0)) for r in daily)
    rejected = sum(int(r.get("n_rejected", 0)) for r in daily)
    reject_rate = round(100.0 * rejected / max(1, n_orders + rejected), 2)
    rmax = exp["reject_rate_pct_max"]
    rows.append(MetricRow(
        "reject_rate_pct", f"<= {rmax:g}%", reject_rate,
        "within" if reject_rate <= rmax else "mildly_degraded" if reject_rate <= 2 * rmax
        else "severely_degraded", True, "skipped/rejected orders as a share of attempts"))

    # --- missed orders (operational, informational count) ---
    rows.append(MetricRow("missed_orders", "low", rejected, "informational", True,
                          "cumulative refused/skipped orders"))

    # --- slippage (operational) ---
    slips = [float(r["realized_slippage_bps"]) for r in tca
             if r.get("realized_slippage_bps") is not None]
    avg_slip = round(sum(slips) / len(slips), 2) if slips else None
    esl = exp["expected_slippage_bps"]
    if avg_slip is None:
        rows.append(MetricRow("avg_slippage_bps", f"~{esl:g}", None, "not_comparable", True, ""))
    else:
        rows.append(MetricRow(
            "avg_slippage_bps", f"~{esl:g}", avg_slip,
            "within" if avg_slip <= 2 * esl else "mildly_degraded" if avg_slip <= 3 * esl
            else "severely_degraded", True, "realized slippage estimate"))

    # --- signal frequency (operational, informational) ---
    active_days = sum(1 for r in daily if int(r.get("n_orders", 0)) > 0)
    freq = round(active_days / n, 2) if n else 0.0
    rows.append(MetricRow("signal_frequency", "rebalances on schedule", freq,
                          "within" if active_days > 0 else "severely_degraded", True,
                          "fraction of days with >= 1 order"))

    # --- return-shaped metrics: informational only until the sample is large ---
    eq = [eq_by[d] for d in sorted(eq_by)]
    p_ret = _returns(eq)
    b_by = {str(r["date"])[:10]: float(r["spy_equity"]) for r in bench
            if r.get("spy_equity") is not None}
    common = sorted(set(eq_by) & set(b_by))
    pc = _returns([eq_by[d] for d in common])
    bc = _returns([b_by[d] for d in common])
    enough = n >= MIN_DAYS_FOR_RETURNS
    sample_note = "" if enough else f"sample too small (< {MIN_DAYS_FOR_RETURNS} days) — informational only"
    ret_status = "informational"

    daily_vol = round(100.0 * _std(p_ret), 3) if len(p_ret) >= 2 else None
    rows.append(MetricRow("daily_volatility_pct", "see backtest", daily_vol, ret_status, False,
                          sample_note))

    dd = round(min((float(r.get("drawdown_pct", 0.0)) for r in daily), default=0.0), 2)
    exp_dd = exp["max_drawdown_pct"]
    # drawdown is judged only very loosely (a gross breach), never finely on a small sample
    dd_status = ("severely_degraded" if abs(dd) > 2 * abs(exp_dd) else "informational")
    rows.append(MetricRow("max_drawdown_pct", f"~{exp_dd:g}% (backtest)", dd, dd_status, False,
                          "only a gross breach (>2x backtest) is treated as degraded"))

    beta = alpha = None
    if len(bc) >= 2:
        mb = sum(bc) / len(bc)
        mp = sum(pc) / len(pc)
        var_b = sum((x - mb) ** 2 for x in bc) / (len(bc) - 1)
        if var_b > 0:
            cov = sum((pc[i] - mp) * (bc[i] - mb) for i in range(len(bc))) / (len(bc) - 1)
            beta = round(cov / var_b, 3)
            alpha = round(100.0 * (mp - beta * mb) * 252, 2)   # annualised, informational
    rows.append(MetricRow("benchmark_beta", "see backtest", beta, ret_status, False, sample_note))
    rows.append(MetricRow("alpha_vs_benchmark_annual_pct", "see backtest", alpha, ret_status, False,
                          "alpha is NEVER judged on a small forward sample"))

    # --- verdict from operational metrics only ---
    op = [r for r in rows if r.operational]
    if any(r.status == "severely_degraded" for r in op):
        verdict = "severely degraded"
    elif any(r.status == "mildly_degraded" for r in op):
        verdict = "mildly degraded"
    elif any(r.status == "not_comparable" for r in op):
        verdict = "within expected range (some metrics not yet measurable)"
    else:
        verdict = "within expected range"

    if not enough:
        notes.append(f"{n} forward days: operational behaviour is judged; return/alpha metrics "
                     "are informational only.")
    return ComparisonReport(product=product, forward_days=n, verdict=verdict, rows=rows, notes=notes)


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5
