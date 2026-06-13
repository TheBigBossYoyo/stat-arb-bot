"""Automatic demotion / retirement triggers (STRATEGY_ACCEPTANCE_CRITERIA.md).

Promotion is manual and gated; demotion is automatic and fast. A live strategy
that decays, slips, or loses its venue should not wait for a human to notice.
These are pure functions over monitoring evidence — the live monitor (Phase 10)
and the dashboard call them; `promotion.py`/the registry execute the action.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DemotionDecision:
    triggered: bool
    severity: str                 # none | demote | retire
    reasons: list[str]


def evaluate_demotion(evidence: dict) -> DemotionDecision:
    """Decide whether a live strategy should be demoted or retired.

    evidence keys (optional):
      rolling60_sharpe, oos_sharpe_p5  -> decay (demote)
      slippage_ratio (realized/model), slippage_breach_days -> slippage (critical)
      tracking_error_unexplained_days -> tracking (demote)
      data_verdict -> data quality (demote if not acceptable)
      venue_capability_lost (bool) -> critical (retire + flatten)
      self_caused_risk_breach (bool) -> critical
    """
    reasons: list[str] = []
    critical = False

    p5 = evidence.get("oos_sharpe_p5")
    r60 = evidence.get("rolling60_sharpe")
    if p5 is not None and r60 is not None and r60 < p5:
        reasons.append(f"decay: rolling-60d Sharpe {r60:.2f} below OOS 5th pct {p5:.2f}")

    if (evidence.get("slippage_ratio") or 0) > 2.0 and (evidence.get("slippage_breach_days") or 0) >= 10:
        reasons.append("realized slippage > 2x model for >=10 consecutive days")
        critical = True

    if (evidence.get("tracking_error_unexplained_days") or 0) >= 15:
        reasons.append("tracking error vs paper/backtest unexplained for >=15 days")

    if evidence.get("data_verdict") not in (None, "ok", "research_only"):
        reasons.append(f"data-quality gate red ({evidence.get('data_verdict')})")

    if evidence.get("venue_capability_lost"):
        reasons.append("venue capability changed (e.g. borrow withdrawn) — flatten now")
        critical = True

    if evidence.get("self_caused_risk_breach"):
        reasons.append("risk-manager breach caused by this strategy's own orders")
        critical = True

    if not reasons:
        return DemotionDecision(False, "none", [])
    # two triggers in window OR one critical => retire; otherwise demote one stage
    severity = "retire" if critical or len(reasons) >= 2 else "demote"
    return DemotionDecision(True, severity, reasons)
