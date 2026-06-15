"""Explainable 0-100 health score for the supervised paper period (Phase 1).

The score is a weighted blend of independent components — each scored 0-100 with
a plain-English reason — so the operator can see *why* the number is what it is,
not just the number. A few hard conditions (a FAILED stop rule, an engaged kill
switch, a stopped session) override the CLASSIFICATION regardless of score, so a
high arithmetic score can never paper over a terminal problem.

Pure functions only: no I/O, no clock, no network. The monitor (paper_monitor.py)
assembles the metrics dict and calls `compute_health_score`. Live is never in
scope; the score never asserts live eligibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# classification bands (after hard overrides)
HEALTHY_MIN = 85
WATCH_MIN = 70
DEGRADED_MIN = 50

CLASSIFICATIONS = ("healthy", "watch", "degraded", "failed", "paused")


@dataclass
class ScoreComponent:
    name: str
    score: float          # 0-100 for this component
    weight: float         # relative weight
    detail: str = ""

    @property
    def contribution(self) -> float:
        return self.score * self.weight

    def as_dict(self) -> dict:
        return {"name": self.name, "score": round(self.score, 1), "weight": self.weight,
                "weighted": round(self.contribution, 1), "detail": self.detail}


@dataclass
class HealthScore:
    score: int
    classification: str
    components: list[ScoreComponent] = field(default_factory=list)
    overrides: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"score": self.score, "classification": self.classification,
                "components": [c.as_dict() for c in self.components],
                "overrides": self.overrides, "live_eligible": False}


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _lerp_down(value: float, good: float, bad: float) -> float:
    """100 when value <= good, 0 when value >= bad, linear between (bad > good)."""
    if value <= good:
        return 100.0
    if value >= bad:
        return 0.0
    return 100.0 * (bad - value) / (bad - good)


def compute_health_score(m: dict) -> HealthScore:
    """Compute the weighted 0-100 score + classification from a metrics dict.

    Recognised keys (all optional, sensible defaults): forward_days_completed,
    expected_trading_days, missed_days, data_stale (bool), data_quality_events,
    broker_errors, risk_breaches, concentration_top_weight, current_drawdown_pct,
    fail_drawdown_pct, turnover_per_year, expected_turnover, excess_return_pct,
    paper_vs_backtest_status (within|mildly_degraded|severely_degraded|invalid),
    stop_state (OK|PAUSED|FAILED), kill_switch_active (bool),
    session_status (active|stopped), decision_is_candidate (bool).
    """
    forward = int(m.get("forward_days_completed", 0) or 0)
    expected = int(m.get("expected_trading_days", forward) or 0)
    missed = int(m.get("missed_days", max(0, expected - forward)) or 0)

    # 1) operational completeness — recorded the expected forward days?
    if expected <= 0:
        op = 100.0
        op_detail = "no expected trading days yet"
    else:
        op = _clamp(100.0 * forward / expected)
        op_detail = f"{forward}/{expected} expected forward days recorded"
    op = _clamp(op - 15.0 * missed)  # each missed day is a real penalty
    if missed:
        op_detail += f"; {missed} missed"

    # 2) data integrity
    dq = int(m.get("data_quality_events", 0) or 0)
    stale = bool(m.get("data_stale", False))
    data = _clamp(100.0 - 25.0 * dq - (40.0 if stale else 0.0))
    data_detail = (f"{dq} data-quality event(s)" if dq else "no data-quality events") \
        + (" — latest bar STALE" if stale else "")

    # 3) broker integrity (demo)
    be = int(m.get("broker_errors", 0) or 0)
    broker = _clamp(100.0 - 30.0 * be)
    broker_detail = f"{be} demo broker error(s)" if be else "no broker errors"

    # 4) risk limits
    rb = int(m.get("risk_breaches", 0) or 0)
    risk = _clamp(100.0 - 50.0 * rb)
    risk_detail = f"{rb} risk-snapshot breach(es)" if rb else "no risk breaches"

    # 5) concentration (cap 25%): full marks <= 20%, zero at >= 30%
    top = float(m.get("concentration_top_weight", 0.0) or 0.0)
    conc = _lerp_down(top, 0.20, 0.30)
    conc_detail = f"top-name weight {top:.1%} (cap 25%)"

    # 6) drawdown vs policy: full marks <= 5%, zero at the FAIL hard limit
    dd = abs(float(m.get("current_drawdown_pct", 0.0) or 0.0))
    fail_dd = float(m.get("fail_drawdown_pct", 35.0) or 35.0)
    draw = _lerp_down(dd, 5.0, fail_dd)
    draw_detail = f"drawdown {dd:.1f}% (fail limit {fail_dd:.0f}%)"

    # 7) turnover drift vs expected (full marks within 0.5x-1.5x of expected).
    # Too few days (or no rebalance yet) => not measurable, scored neutral.
    turn = float(m.get("turnover_per_year", 0.0) or 0.0)
    exp_turn = float(m.get("expected_turnover", 30.0) or 30.0)
    ratio = turn / exp_turn if exp_turn else 1.0
    if forward < 5 and turn == 0.0:
        tscore = 80.0
        turn_detail = "turnover not yet measurable (early period)"
    else:
        if 0.5 <= ratio <= 1.5:
            tscore = 100.0
        elif 0.3 <= ratio <= 2.5:
            tscore = 65.0
        else:
            tscore = 30.0
        turn_detail = f"turnover {turn:.0f}x/yr vs ~{exp_turn:.0f}x expected"

    # 8) benchmark-relative: full marks if not behind; penalise underperformance
    excess = m.get("excess_return_pct")
    if excess is None:
        bench = 80.0
        bench_detail = "benchmark comparison not yet available"
    else:
        excess = float(excess)
        bench = _clamp(100.0 + (excess if excess < 0 else 0.0) * 5.0)
        bench_detail = f"excess vs benchmark {excess:+.1f}ppt"

    # 9) paper-vs-backtest behavioural drift
    pvb = str(m.get("paper_vs_backtest_status", "invalid")).lower()
    pvb_map = {"within": 100.0, "mildly_degraded": 60.0, "severely_degraded": 20.0}
    pvb_score = pvb_map.get(pvb, 80.0)  # invalid/not-comparable => neutral, not a penalty
    pvb_detail = f"paper-vs-backtest: {pvb}"

    components = [
        ScoreComponent("operational_completeness", op, 0.20, op_detail),
        ScoreComponent("data_integrity", data, 0.12, data_detail),
        ScoreComponent("broker_integrity", broker, 0.10, broker_detail),
        ScoreComponent("risk_limits", risk, 0.12, risk_detail),
        ScoreComponent("concentration", conc, 0.12, conc_detail),
        ScoreComponent("drawdown", draw, 0.12, draw_detail),
        ScoreComponent("turnover_drift", tscore, 0.08, turn_detail),
        ScoreComponent("benchmark_relative", bench, 0.08, bench_detail),
        ScoreComponent("paper_vs_backtest", pvb_score, 0.06, pvb_detail),
    ]
    total_w = sum(c.weight for c in components)
    raw = sum(c.contribution for c in components) / total_w if total_w else 0.0
    score = int(round(_clamp(raw)))

    # --- hard overrides on CLASSIFICATION (score is informational under them) ---
    overrides: list[str] = []
    stop_state = str(m.get("stop_state", "OK")).upper()
    kill = bool(m.get("kill_switch_active", False))
    session_status = str(m.get("session_status", "active")).lower()
    decision_ok = bool(m.get("decision_is_candidate", True))

    classification: str
    if stop_state == "FAILED" or session_status == "stopped" or not decision_ok:
        classification = "failed"
        if stop_state == "FAILED":
            overrides.append("a FAILED stop rule is active")
        if session_status == "stopped":
            overrides.append("the session is stopped")
        if not decision_ok:
            overrides.append("product is no longer paper_candidate")
        score = min(score, 30)
    elif kill or stop_state == "PAUSED":
        classification = "paused"
        overrides.append("kill switch engaged" if kill else "a PAUSED stop rule is active")
        score = min(score, 60)
    elif score >= HEALTHY_MIN:
        classification = "healthy"
    elif score >= WATCH_MIN:
        classification = "watch"
    else:
        classification = "degraded"

    return HealthScore(score=score, classification=classification,
                       components=components, overrides=overrides)
