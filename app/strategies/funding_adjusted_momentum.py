"""Funding-adjusted momentum on perps (Path B).

Trend, but net of expected carry. A perp momentum long that pays 50%/yr funding
is not a good long; a momentum short that *also* collects funding is doubly
attractive. This sleeve takes the crypto TSMOM signal and penalizes each name's
score by its trailing funding cost FOR THE DIRECTION the trend implies:

* long candidates are docked when funding is high-positive (longs pay),
* short candidates are docked when funding is deeply negative (shorts pay),

then re-ranks. Names whose carry cancels the trend edge drop out. Consumes
`aux["funding"]`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.strategies.crypto_tsmom_futures import _trend_vote

PERIODS_PER_YEAR = 3 * 365.0


class FundingAdjMomentumConfig(BaseModel):
    lookback_bars: list[int] = [20, 60, 120]
    skip_bars: int = 2
    funding_lookback: int = 10
    vol_window: int = 30
    funding_penalty: float = 1.0       # how hard expected carry docks the signal
    gross_target: float = 1.0
    max_weight: float = 0.30


class FundingAdjMomentum:
    wants_aux = True

    def __init__(self, config: FundingAdjMomentumConfig | None = None) -> None:
        self.cfg = config or FundingAdjMomentumConfig()

    def __call__(self, close_window: pd.DataFrame, aux: dict | None = None) -> pd.Series:
        cfg = self.cfg
        zero = pd.Series(0.0, index=close_window.columns)
        votes = _trend_vote(close_window, cfg.lookback_bars, cfg.skip_bars)
        if votes is None:
            return zero
        rets = np.log(close_window).diff().iloc[-cfg.vol_window:]
        vol = rets.std(ddof=1).replace(0.0, np.nan)
        raw = (votes / vol).replace([np.inf, -np.inf], np.nan).dropna()
        # funding adjustment: expected carry per period for the trend direction
        if aux and "funding" in aux and aux["funding"] is not None:
            f = aux["funding"]
            if len(f) > cfg.funding_lookback:
                apr = f.iloc[-cfg.funding_lookback:].mean() * PERIODS_PER_YEAR
                apr = apr.reindex(raw.index).fillna(0.0)
                # a long pays +funding; a short pays -funding. expected carry on the
                # trend direction = -sign(raw) * apr (negative = a cost). dock score.
                carry = -np.sign(raw) * apr
                raw = raw + cfg.funding_penalty * carry * raw.abs()
                raw = raw[np.sign(raw) == np.sign(votes.reindex(raw.index))]  # drop sign flips
        raw = raw.dropna()
        if raw.empty:
            return zero
        w = (raw * (cfg.gross_target / raw.abs().sum())).clip(-cfg.max_weight, cfg.max_weight)
        g = float(w.abs().sum())
        return (w * (cfg.gross_target / g) if g > 0 else w).reindex(close_window.columns).fillna(0.0)


def make_funding_adjusted_momentum(config: FundingAdjMomentumConfig | None = None):
    return FundingAdjMomentum(config)
