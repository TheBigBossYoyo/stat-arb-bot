"""Capacity analysis (audit W-09): how large can this strategy run before its
edge decays?

A backtest at $10k that ignores impact tells you nothing about $1M. This module
re-runs a basket strategy across a grid of capital levels, charging a
square-root market-impact cost on top of the flat spread cost. Impact scales
with participation = order notional / average daily dollar volume, so larger
capital concentrated in the same names pays progressively more — and the
capacity curve (net Sharpe vs capital) shows where the edge dies.

Impact model (standard practitioner form): cost_bps = base_bps + eta * sqrt(P)
where P is the per-name participation fraction and eta the impact coefficient.
We translate this into a per-asset cost dict by averaging participation over
the backtest from the strategy's own turnover and the universe's dollar volume.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from app.backtesting.basket_engine import BasketConfig, WeightFn, run_basket_backtest


@dataclass
class CapacityPoint:
    capital: float
    net_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    avg_participation_pct: float   # mean per-rebalance participation in ADV
    impact_cost_bps: float         # mean impact added on top of base spread


@dataclass
class CapacityCurve:
    points: list[CapacityPoint]
    base_cost_bps: float
    impact_coeff: float
    bottleneck_symbols: list[str]  # names with the highest participation

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([p.__dict__ for p in self.points]).set_index("capital")

    def capacity_at_sharpe_floor(self, floor_frac: float = 0.8) -> float:
        """Largest capital whose Sharpe stays >= floor_frac of the small-capital
        Sharpe (the acceptance-criteria capacity test)."""
        if not self.points:
            return 0.0
        base_sharpe = self.points[0].sharpe
        if base_sharpe <= 0:
            return self.points[0].capital
        ok = [p.capital for p in self.points if p.sharpe >= floor_frac * base_sharpe]
        return max(ok) if ok else self.points[0].capital


def _mean_dollar_volume(close: pd.DataFrame, volume: pd.DataFrame | None) -> pd.Series:
    """Per-symbol average daily dollar volume; falls back to a large constant
    when volume is unavailable (then impact is ~0 and the curve is flat — the
    honest signal that capacity cannot be assessed without volume data)."""
    if volume is None:
        return pd.Series(1e12, index=close.columns)
    dollar = (close * volume).replace(0.0, np.nan)
    return dollar.mean().fillna(dollar.stack().median() if dollar.notna().any().any() else 1e12)


def run_capacity_analysis(
    close: pd.DataFrame,
    weight_fn: WeightFn,
    config: BasketConfig,
    capital_grid: list[float],
    *,
    aux: dict[str, pd.DataFrame] | None = None,
    open_: pd.DataFrame | None = None,
    volume: pd.DataFrame | None = None,
    impact_coeff: float = 10.0,
) -> CapacityCurve:
    """Run the strategy at each capital level with square-root impact costs.

    `impact_coeff` (bps per sqrt(participation)) ~ 10 is a common liquid-equity
    estimate; raise it for less liquid universes. The strategy is run once at
    each capital with a per-asset cost = base + impact(participation at that
    capital). Participation is estimated from a probe run's realized turnover.
    """
    adv = _mean_dollar_volume(close, volume)

    # probe run at base cost to estimate per-name turnover (dollar traded/name)
    probe = run_basket_backtest(close, weight_fn, replace(config, label="probe"),
                                aux=aux, open_=open_)
    weights = probe.weights
    if weights.empty:
        return CapacityCurve([], config.cost_bps, impact_coeff, [])
    # per-rebalance turnover per symbol (fraction of equity), averaged
    turn = weights.diff().abs()
    turn.iloc[0] = weights.iloc[0].abs()
    mean_turn_frac = turn.mean()                       # fraction of equity per rebalance per name
    bottleneck = list(mean_turn_frac.sort_values(ascending=False).head(5).index)

    points: list[CapacityPoint] = []
    for capital in capital_grid:
        # participation per name = (turnover fraction * capital) / ADV
        participation = (mean_turn_frac * capital / adv).reindex(close.columns).fillna(0.0)
        impact_bps = impact_coeff * np.sqrt(participation.clip(lower=0.0))
        per_asset = {sym: float(config.cost_bps + impact_bps.get(sym, 0.0))
                     for sym in close.columns}
        cfg = replace(config, starting_cash=capital, per_asset_cost_bps=per_asset,
                      label=f"capacity_{int(capital)}")
        res = run_basket_backtest(close, weight_fn, cfg, aux=aux, open_=open_)
        points.append(CapacityPoint(
            capital=capital,
            net_return_pct=res.metrics.get("total_return_pct", 0.0) or 0.0,
            sharpe=res.metrics.get("sharpe", 0.0) or 0.0,
            max_drawdown_pct=res.metrics.get("max_drawdown_pct", 0.0) or 0.0,
            avg_participation_pct=float(100 * participation.mean()),
            impact_cost_bps=float(impact_bps.mean()),
        ))
    return CapacityCurve(points, config.cost_bps, impact_coeff, bottleneck)
