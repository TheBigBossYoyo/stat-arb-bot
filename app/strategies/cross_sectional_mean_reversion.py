"""Cross-sectional mean reversion basket strategy (Phase 6).

Standardize trailing short-term returns across the universe; buy the biggest
losers, short the biggest winners (demeaning across assets removes the common
market move, i.e. a crude beta-neutralization). Long-only mode buys losers
only and is NOT market-neutral.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.backtesting.basket_engine import WeightFn, rank_weights


class XSecReversalConfig(BaseModel):
    lookback_bars: int = 12
    top_k: int = 2
    gross_target: float = 1.0
    long_only: bool = False


def make_xsec_weight_fn(config: XSecReversalConfig | None = None) -> WeightFn:
    cfg = config or XSecReversalConfig()

    def weight_fn(close_window: pd.DataFrame) -> pd.Series:
        if len(close_window) <= cfg.lookback_bars + 1:
            return pd.Series(0.0, index=close_window.columns)
        trailing = np.log(close_window).diff(cfg.lookback_bars).iloc[-1]
        std = float(trailing.std(ddof=1))
        if std == 0 or not np.isfinite(std):
            return pd.Series(0.0, index=close_window.columns)
        scores = (trailing - trailing.mean()) / std   # high = recent winner (short candidate)
        return rank_weights(scores, cfg.top_k, cfg.gross_target, cfg.long_only)

    return weight_fn
