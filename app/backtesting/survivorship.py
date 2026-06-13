"""Survivorship-bias stress: bound the dependence on the survivor set (Phase 3).

Run a strategy on many random sub-universes (names dropped/swapped) and look at
the distribution of its Sharpe/return. The logic:

* if the result barely moves when 20% of names are randomly removed, the edge is
  a property of the *strategy*, not of the lucky survivor list — survivorship
  risk is bounded;
* if it collapses (or the spread is huge), the headline number leans on
  specific survivors and must be discounted.

This does not eliminate survivorship bias (only point-in-time membership data
can), but it puts an honest, quantified bound on it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.data.point_in_time import perturbed_universes


@dataclass
class SurvivorshipResult:
    full_sharpe: float
    full_return_pct: float
    sub_sharpes: list[float]
    sub_returns: list[float]
    drop_frac: float
    n: int

    @property
    def sharpe_mean(self) -> float:
        return float(np.mean(self.sub_sharpes)) if self.sub_sharpes else float("nan")

    @property
    def sharpe_std(self) -> float:
        return float(np.std(self.sub_sharpes, ddof=1)) if len(self.sub_sharpes) > 1 else 0.0

    @property
    def sharpe_p05(self) -> float:
        return float(np.percentile(self.sub_sharpes, 5)) if self.sub_sharpes else float("nan")

    @property
    def bounded(self) -> bool:
        """Survivorship risk is 'bounded' if the 5th-percentile sub-universe
        Sharpe stays clearly positive and within a reasonable band of the full
        Sharpe (the edge does not hinge on the exact survivor set)."""
        if not self.sub_sharpes or np.isnan(self.full_sharpe):
            return False
        return self.sharpe_p05 > 0.4 and self.sharpe_p05 > 0.5 * self.full_sharpe

    def summary(self) -> dict:
        return {
            "full_sharpe": round(self.full_sharpe, 3),
            "sub_sharpe_mean": round(self.sharpe_mean, 3),
            "sub_sharpe_std": round(self.sharpe_std, 3),
            "sub_sharpe_p05": round(self.sharpe_p05, 3),
            "drop_frac": self.drop_frac,
            "n_subuniverses": self.n,
            "survivorship_bounded": self.bounded,
        }


def run_survivorship_stress(
    universe: str,
    run_on_symbols: Callable[[list[str]], dict],
    *,
    n: int = 12,
    drop_frac: float = 0.2,
    seed: int = 7,
) -> SurvivorshipResult:
    """`run_on_symbols(symbols) -> metrics dict` (needs 'sharpe','total_return_pct').

    Runs on the full universe then `n` perturbed sub-universes."""
    from app.data.universe import get_universe

    full = run_on_symbols(get_universe(universe))
    subs = []
    for syms in perturbed_universes(universe, n, drop_frac=drop_frac, seed=seed):
        try:
            subs.append(run_on_symbols(syms))
        except Exception:  # noqa: BLE001 - a degenerate subset is skipped, not fatal
            continue
    return SurvivorshipResult(
        full_sharpe=float(full.get("sharpe") or 0.0),
        full_return_pct=float(full.get("total_return_pct") or 0.0),
        sub_sharpes=[float(m.get("sharpe") or 0.0) for m in subs],
        sub_returns=[float(m.get("total_return_pct") or 0.0) for m in subs],
        drop_frac=drop_frac, n=len(subs),
    )
