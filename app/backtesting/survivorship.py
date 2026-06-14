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
from dataclasses import dataclass, field

import numpy as np

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


# --- enhanced universe-bias report (Phase 3, long-only) -----------------------

def _sector_balanced_drop(names: list[str], sectors: dict[str, str],
                          drop_frac: float, rng) -> list[str]:
    """Drop ~drop_frac of names, spread proportionally across sectors, so the
    sub-universe keeps the same sector SHAPE (a sector-neutral survivor stress —
    harder than a plain random drop, which can wipe a whole small sector)."""
    by_sector: dict[str, list[str]] = {}
    for s in names:
        by_sector.setdefault(sectors.get(s, "other"), []).append(s)
    keep: list[str] = []
    for members in by_sector.values():
        k = max(1, int(round(len(members) * (1.0 - drop_frac))))
        keep += rng.choice(members, size=min(k, len(members)), replace=False).tolist()
    return sorted(keep)


@dataclass
class BiasScenario:
    label: str
    sharpe: float
    return_pct: float
    max_dd_pct: float
    n_names: int


@dataclass
class UniverseBiasReport:
    universe: str
    base: BiasScenario
    scenarios: list[BiasScenario] = field(default_factory=list)
    bootstrap_sharpes: list[float] = field(default_factory=list)
    pit_data_used: bool = False     # only point-in-time membership can ELIMINATE bias

    @property
    def median_sharpe(self) -> float:
        return float(np.median(self.bootstrap_sharpes)) if self.bootstrap_sharpes else float("nan")

    @property
    def sharpe_p05(self) -> float:
        return float(np.percentile(self.bootstrap_sharpes, 5)) if self.bootstrap_sharpes else float("nan")

    @property
    def worst_case_dd_pct(self) -> float:
        dds = [s.max_dd_pct for s in [self.base, *self.scenarios] if s.max_dd_pct is not None]
        return float(min(dds)) if dds else float("nan")

    def verdict(self) -> str:
        """'eliminated' is reserved for an actual point-in-time backtest. Without
        it the best honest verdict is 'bounded' — the edge survives dropping the
        biggest winners and the 5th-pct bootstrap Sharpe stays clearly positive —
        otherwise 'unresolved'."""
        if self.pit_data_used:
            return "eliminated"
        best5 = next((s for s in self.scenarios if s.label == "best_5_removed"), None)
        survives_winner_drop = bool(best5 and best5.sharpe > 0.5 * self.base.sharpe and best5.sharpe > 0.4)
        bootstrap_ok = self.sharpe_p05 > 0.4 and self.sharpe_p05 > 0.5 * self.base.sharpe
        return "bounded" if (survives_winner_drop and bootstrap_ok) else "unresolved"

    def rows(self) -> list[dict]:
        out = []
        for s in [self.base, *self.scenarios]:
            out.append({"scenario": s.label, "sharpe": round(s.sharpe, 3),
                        "return_pct": round(s.return_pct, 1),
                        "max_dd_pct": round(s.max_dd_pct, 1), "n_names": s.n_names})
        return out

    def summary(self) -> dict:
        return {
            "universe": self.universe,
            "base_sharpe": round(self.base.sharpe, 3),
            "bootstrap_median_sharpe": round(self.median_sharpe, 3),
            "bootstrap_p05_sharpe": round(self.sharpe_p05, 3),
            "worst_case_dd_pct": round(self.worst_case_dd_pct, 1),
            "verdict": self.verdict(),
        }


def run_universe_bias_report(
    universe: str,
    run_on_symbols: Callable[[list[str]], dict],
    *,
    sectors: dict[str, str] | None = None,
    name_returns: dict[str, float] | None = None,
    n_random: int = 10,
    seed: int = 7,
) -> UniverseBiasReport:
    """Full survivorship-bias bound for a (long-only) strategy.

    Scenarios: base, random 10/20/30% drop, sector-balanced 20% drop, the worst-5
    and best-5 by individual total return removed (the best-5 drop is the decisive
    survivorship test — it removes the biggest winners that today's survivor list
    is most likely to over-represent). The random drops feed a bootstrap Sharpe
    distribution (median, 5th percentile)."""
    from app.data.universe import get_universe

    names = get_universe(universe)
    sectors = sectors or {}
    rng = np.random.default_rng(seed)

    def scen(label: str, syms: list[str]) -> BiasScenario | None:
        try:
            m = run_on_symbols(syms)
        except Exception:  # noqa: BLE001 - degenerate subset is skipped
            return None
        return BiasScenario(label=label, sharpe=float(m.get("sharpe") or 0.0),
                            return_pct=float(m.get("total_return_pct") or 0.0),
                            max_dd_pct=float(m.get("max_drawdown_pct") or 0.0),
                            n_names=len(syms))

    base = scen("base", names)
    scenarios: list[BiasScenario] = []
    bootstrap: list[float] = []

    for frac in (0.10, 0.20, 0.30):
        subs = perturbed_universes(universe, n_random, drop_frac=frac, seed=seed)
        sharpes = []
        for syms in subs:
            s = scen(f"random_drop_{int(frac * 100)}pct", syms)
            if s:
                sharpes.append(s.sharpe)
                bootstrap.append(s.sharpe)
        if sharpes:
            # represent each random level by its MEDIAN run
            mid = sorted(sharpes)[len(sharpes) // 2]
            rep = BiasScenario(f"random_drop_{int(frac * 100)}pct", mid,
                               float("nan"), float("nan"),
                               int(round(len(names) * (1 - frac))))
            scenarios.append(rep)

    if sectors:
        sb = _sector_balanced_drop(names, sectors, 0.20, rng)
        s = scen("sector_balanced_drop_20pct", sb)
        if s:
            scenarios.append(s)

    if name_returns:
        ordered = sorted((n for n in names if n in name_returns), key=lambda n: name_returns[n])
        worst5 = [n for n in names if n not in ordered[:5]]
        best5 = [n for n in names if n not in ordered[-5:]]
        for label, syms in (("worst_5_removed", worst5), ("best_5_removed", best5)):
            s = scen(label, syms)
            if s:
                scenarios.append(s)

    return UniverseBiasReport(universe=universe, base=base or BiasScenario("base", 0, 0, 0, 0),
                              scenarios=scenarios, bootstrap_sharpes=bootstrap,
                              pit_data_used=False)
