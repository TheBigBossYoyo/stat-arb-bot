"""Funding-rate carry as a futures weight function (Path B).

The classic perp carry: SHORT the perps paying the richest *persistent* positive
funding (you receive funding while short), optionally LONG the perps paying
deeply negative funding (you receive funding while long). On a futures-only book
this is directional in the perp; the delta-neutral spot-hedged version is the
research backtest in `app/research/funding_carry.py`. Here it is a sleeve the
futures engine and ensemble can run, with entry/exit hysteresis on trailing
annualized funding to avoid churning near-tied names.

Consumes the funding panel via `aux["funding"]` (a window aligned to the close
window the engine passes).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

PERIODS_PER_YEAR = 3 * 365.0


class FundingCarryConfig(BaseModel):
    lookback_bars: int = 10            # trailing funding window (bars)
    top_k: int = 3
    entry_apr: float = 0.05            # short a perp when trailing funding APR clears this
    long_neg_apr: float = -0.05        # long a perp when funding APR below this (you receive)
    gross_target: float = 1.0
    max_weight: float = 0.34


class FundingCarry:
    """Stateful funding-carry sleeve (reads aux funding window)."""

    wants_aux = True

    def __init__(self, config: FundingCarryConfig | None = None) -> None:
        self.cfg = config or FundingCarryConfig()

    def __call__(self, close_window: pd.DataFrame, aux: dict | None = None) -> pd.Series:
        cfg = self.cfg
        zero = pd.Series(0.0, index=close_window.columns)
        if not aux or "funding" not in aux:
            return zero
        funding = aux["funding"]
        if funding is None or len(funding) <= cfg.lookback_bars:
            return zero
        trailing_apr = funding.iloc[-cfg.lookback_bars:].mean() * PERIODS_PER_YEAR
        trailing_apr = trailing_apr.reindex(close_window.columns).dropna()
        if trailing_apr.empty:
            return zero
        w = pd.Series(0.0, index=close_window.columns)
        shorts = trailing_apr[trailing_apr > cfg.entry_apr].nlargest(cfg.top_k).index
        longs = trailing_apr[trailing_apr < cfg.long_neg_apr].nsmallest(cfg.top_k).index
        for s in shorts:
            w[s] = -1.0
        for s in longs:
            w[s] = 1.0
        gross = float(w.abs().sum())
        if gross == 0:
            return zero
        w = (w / gross * cfg.gross_target).clip(-cfg.max_weight, cfg.max_weight)
        g = float(w.abs().sum())
        return w * (cfg.gross_target / g) if g > 0 else w

    def __repr__(self) -> str:
        return "FundingCarry()"


def make_funding_carry_weight_fn(config: FundingCarryConfig | None = None) -> FundingCarry:
    return FundingCarry(config)
