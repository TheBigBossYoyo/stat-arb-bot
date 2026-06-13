"""Crypto-futures risk model (Path B).

The futures path can short and lever, so its risk model is about not blowing up:

* **Leverage cap** — gross exposure ≤ `max_leverage` (research default 1x, hard
  cap 2x). A book emitting more is scaled down.
* **Liquidation buffer** — refuse / shrink positions whose distance to
  liquidation is too small for the asset's volatility.
* **Funding-cancels-edge** — refuse a position whose expected funding cost over
  the holding horizon exceeds its expected edge.
* **Liquidity / spread gates** — no position when the spread is abnormally wide
  or volume below a floor.
* **Kill switch** — halt on abnormal funding, spread, or a liquidation-buffer
  breach (fail-closed, mirroring the equity kill switch).

These are pre-trade checks the paper/testnet layer calls; nothing here places
orders or connects to an exchange.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class FuturesRiskLimits:
    max_leverage: float = 2.0              # hard research cap on gross
    default_leverage: float = 1.0
    min_liquidation_distance: float = 0.15  # required buffer to liquidation (frac)
    maintenance_margin_pct: float = 0.05
    max_spread_bps: float = 50.0           # refuse if spread wider than this
    min_funding_edge_ratio: float = 1.0    # expected edge must exceed funding cost x this
    abnormal_funding_apr: float = 1.0      # |funding| APR above this trips the kill switch
    abnormal_spread_bps: float = 200.0


@dataclass
class FuturesRiskResult:
    weights: pd.Series
    kill: bool = False
    reasons: list[str] = field(default_factory=list)
    min_liquidation_distance: float = 1.0


class FuturesRiskModel:
    def __init__(self, limits: FuturesRiskLimits | None = None) -> None:
        self.limits = limits or FuturesRiskLimits()

    def liquidation_distance(self, gross: float) -> float:
        """Fractional adverse move that wipes margin at this gross leverage."""
        if gross <= 0:
            return 1.0
        return max(0.0, 1.0 / gross - self.limits.maintenance_margin_pct)

    def screen(
        self,
        weights: pd.Series,
        *,
        funding_apr: pd.Series | None = None,
        spread_bps: pd.Series | None = None,
        expected_edge_apr: pd.Series | None = None,
    ) -> FuturesRiskResult:
        """Project a target book onto the feasible set and flag kill conditions."""
        lim = self.limits
        w = weights.copy()
        reasons: list[str] = []

        # 1) leverage cap
        gross = float(w.abs().sum())
        if gross > lim.max_leverage and gross > 0:
            w = w * (lim.max_leverage / gross)
            reasons.append(f"scaled to max leverage {lim.max_leverage}x")
            gross = lim.max_leverage

        # 2) liquidation buffer — shrink the whole book until the buffer is safe
        liq = self.liquidation_distance(gross)
        if gross > 0 and liq < lim.min_liquidation_distance:
            safe_gross = 1.0 / (lim.min_liquidation_distance + lim.maintenance_margin_pct)
            if gross > safe_gross:
                w = w * (safe_gross / gross)
                reasons.append(f"shrunk book to keep liquidation buffer "
                               f">= {lim.min_liquidation_distance}")
                gross = safe_gross
                liq = self.liquidation_distance(gross)

        # 3) spread gate (per-name): drop names with abnormally wide spreads
        if spread_bps is not None:
            wide = spread_bps[spread_bps > lim.max_spread_bps].index
            if len(wide):
                w[wide] = 0.0
                reasons.append(f"dropped {len(wide)} name(s) on wide spread")

        # 4) funding-cancels-edge: drop names where funding cost eats the edge
        if funding_apr is not None and expected_edge_apr is not None:
            for sym in list(w.index):
                if w[sym] == 0:
                    continue
                # cost of holding this direction: long pays +funding
                cost = float((funding_apr.get(sym, 0.0) or 0.0)) * (1 if w[sym] > 0 else -1)
                edge = float(expected_edge_apr.get(sym, 0.0) or 0.0)
                if cost > 0 and edge < cost * lim.min_funding_edge_ratio:
                    w[sym] = 0.0
                    reasons.append(f"{sym}: funding cost cancels edge")

        # 5) kill switch — abnormal funding / spread / liquidation breach
        kill = False
        if funding_apr is not None and (funding_apr.abs() > lim.abnormal_funding_apr).any():
            kill = True
            reasons.append("KILL: abnormal funding")
        if spread_bps is not None and (spread_bps > lim.abnormal_spread_bps).any():
            kill = True
            reasons.append("KILL: abnormal spread widening")
        if gross > 0 and liq <= 0:
            kill = True
            reasons.append("KILL: liquidation buffer exhausted")
        if kill:
            w = pd.Series(0.0, index=weights.index)        # fail-closed: flat

        return FuturesRiskResult(weights=w, kill=kill, reasons=reasons,
                                 min_liquidation_distance=round(self.liquidation_distance(
                                     float(w.abs().sum())), 4))
