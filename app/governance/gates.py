"""Hard promotion gates (STRATEGY_ACCEPTANCE_CRITERIA.md, Phase 7).

A gate is a named, evaluable condition with an explicit pass/fail and a reason.
Gates are grouped by the pipeline transition they guard. Nothing here promotes
anything — `promotion.py` consumes these results and refuses transitions whose
gates do not all pass. The point is that "is this strategy allowed to advance?"
becomes a function of recorded evidence, not opinion.

Evidence is supplied as a plain dict (assembled by the CLI from validation
runs, the data audit, and the registry), so gates stay pure and testable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str
    blocking: bool = True        # a non-blocking gate warns but does not refuse

    @property
    def status(self) -> str:
        if self.passed:
            return "PASS"
        return "FAIL" if self.blocking else "WARN"


@dataclass
class GateReport:
    stage_from: str
    stage_to: str
    results: list[GateResult]

    @property
    def approved(self) -> bool:
        return all(r.passed or not r.blocking for r in self.results)

    @property
    def blocking_failures(self) -> list[GateResult]:
        return [r for r in self.results if not r.passed and r.blocking]

    def summary(self) -> str:
        head = f"{self.stage_from} -> {self.stage_to}: {'APPROVED' if self.approved else 'BLOCKED'}"
        lines = [head] + [f"  [{r.status}] {r.name}: {r.detail}" for r in self.results]
        return "\n".join(lines)


def _g(name: str, passed: bool, detail: str, blocking: bool = True) -> GateResult:
    return GateResult(name, bool(passed), detail, blocking)


def evaluate_gates(stage_to: str, evidence: dict, *, stage_from: str = "") -> GateReport:
    """Evaluate the gates guarding entry into `stage_to`.

    `evidence` keys (all optional; a missing key fails the gate that needs it):
      n_years, n_regimes, net_sharpe, deflated_sharpe_pass, max_month_pct,
      max_position_pct, turnover_affordable, oos_sharpe, oos_sharpe_degradation,
      oos_folds_positive_frac, param_stable, survives_costs_x2,
      survives_slippage_x2, survives_delay, survives_drop_best5,
      capacity_ok, max_drawdown_pct, dd_mandate_pct, paper_days, paper_decisions,
      paper_slippage_ok, no_unexplained_breaks, executable_venues,
      requires_short, requires_leverage, data_verdict, governance_signoff.
    """
    e = evidence
    results: list[GateResult] = []

    if stage_to == "walk_forward":
        results += [
            _g("history_depth", (e.get("n_years") or 0) >= 5 or e.get("crypto_max_history", False),
               f"{e.get('n_years', 0)}y (need >=5y equity / max crypto)"),
            _g("regime_breadth", (e.get("n_regimes") or 0) >= 3,
               f"{e.get('n_regimes', 0)} regimes (need >=3)"),
            _g("net_sharpe_positive", (e.get("net_sharpe") or 0) > 0,
               f"net Sharpe {e.get('net_sharpe')}"),
            _g("deflated_sharpe", bool(e.get("deflated_sharpe_pass")),
               "P(true>benchmark) >= 0.95 vs recorded trial count"),
            _g("no_month_dominates", (e.get("max_month_pct") or 100) <= 25.0,
               f"worst month = {e.get('max_month_pct')}% of PnL (need <=25%)"),
            _g("costs_x2_survives", bool(e.get("survives_costs_x2")),
               "net return > 0 at 2x modeled costs"),
            _g("data_acceptable", e.get("data_verdict") in ("ok", "research_only"),
               f"data verdict = {e.get('data_verdict')}"),
        ]
    elif stage_to == "stress":
        floor = 0.8 if e.get("is_flagship") else 0.5
        results += [
            _g("oos_sharpe_floor", (e.get("oos_sharpe") or 0) >= floor,
               f"OOS Sharpe {e.get('oos_sharpe')} (need >={floor})"),
            _g("degradation", (e.get("oos_sharpe_degradation") or 1.0) < 0.5,
               f"IS->OOS degradation {e.get('oos_sharpe_degradation')} (need <0.5)"),
            _g("oos_windows_positive", (e.get("oos_folds_positive_frac") or 0) >= 0.6,
               f"{e.get('oos_folds_positive_frac')} of OOS folds positive (need >=0.6)"),
            _g("param_stability", bool(e.get("param_stable")),
               "±50% parameter perturbation keeps OOS Sharpe within 40%", blocking=False),
        ]
    elif stage_to == "paper":
        results += [
            _g("survives_costs_x2", bool(e.get("survives_costs_x2")), "positive at 2x costs"),
            _g("survives_slippage_x2", bool(e.get("survives_slippage_x2")), "positive at 2x slippage"),
            _g("survives_delay", bool(e.get("survives_delay")), "positive with 1-bar delay"),
            _g("survives_drop_best5", bool(e.get("survives_drop_best5")),
               "positive after removing best 5% of trades", blocking=False),
            _g("drawdown_mandate",
               abs(e.get("max_drawdown_pct") or 100) <= (e.get("dd_mandate_pct") or 15),
               f"max DD {e.get('max_drawdown_pct')}% vs mandate {e.get('dd_mandate_pct', 15)}%"),
            _g("capacity_ok", bool(e.get("capacity_ok")),
               "participation <5% ADV and net Sharpe holds at intended capital"),
        ]
    elif stage_to in ("shadow_live", "live_tiny", "live_scaled"):
        venues = e.get("executable_venues") or []
        venue_ok = bool(venues)
        if e.get("requires_short") and not e.get("venue_supports_short", False):
            venue_ok = False
        if e.get("requires_leverage") and not e.get("venue_supports_margin", False):
            venue_ok = False
        results += [
            _g("venue_gate", venue_ok,
               f"executable venues={venues}; short={e.get('requires_short')} "
               f"leverage={e.get('requires_leverage')} — venue must support what the strategy needs"),
            _g("paper_period", (e.get("paper_days") or 0) >= 30
               and (e.get("paper_decisions") or 0) >= 20,
               f"{e.get('paper_days', 0)} paper days / {e.get('paper_decisions', 0)} decisions "
               "(need >=30d, >=20)"),
            _g("paper_slippage_ok", bool(e.get("paper_slippage_ok")),
               "realized paper slippage <= modeled"),
            _g("no_unexplained_breaks", bool(e.get("no_unexplained_breaks")),
               "no unexplained reconciliation/risk breaks in the paper period"),
            _g("connectors_exercised", bool(e.get("connectors_exercised")),
               "place/cancel/fill/partial/reject observed on testnet/demo"),
            _g("governance_signoff", bool(e.get("governance_signoff")),
               "human approval recorded"),
        ]
    else:
        results.append(_g("known_stage", False, f"no gates defined for stage {stage_to!r}"))

    return GateReport(stage_from=stage_from, stage_to=stage_to, results=results)
