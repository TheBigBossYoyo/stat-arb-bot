"""Momentum basket strategies (Phase 7).

Two of the most persistent return premia run by systematic funds
(Moskowitz-Ooi-Pedersen "Time Series Momentum", Jegadeesh-Titman
cross-sectional momentum):

* **TSMOM** — per asset, go with the sign of its own trailing return,
  inverse-volatility weighted so every asset contributes similar risk.
  Directional (NOT market-neutral): in a broad crypto rally every weight can
  be long. It is the natural complement to the mean-reversion sleeves, which
  bleed precisely when trends run.
* **XSMOM** — rank assets by trailing return; long the strongest, short the
  weakest. Dollar-neutral by construction.

Both skip the most recent `skip_bars` when measuring momentum: the last few
bars are dominated by short-term reversal (the very effect xsec_reversion
trades), and including them poisons the momentum signal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.backtesting.basket_engine import WeightFn, rank_weights


class TSMOMConfig(BaseModel):
    lookback_bars: int = 672      # 1 week of 15m bars
    skip_bars: int = 12           # ignore the most recent 3h (reversal zone)
    vol_window: int = 96          # trailing window for inverse-vol weights
    gross_target: float = 1.0
    max_weight: float = 0.30      # per-asset cap before re-normalization
    long_only: bool = False       # spot accounts: drop the short legs


class XSMOMConfig(BaseModel):
    lookback_bars: int = 336      # ~3.5 days of 15m bars
    skip_bars: int = 12
    top_k: int = 2
    # if > 0, overrides top_k with round(top_frac * n_assets): the classic
    # Jegadeesh-Titman spec is DECILE portfolios, so the book scales with
    # universe breadth instead of concentrating as the universe grows
    top_frac: float = 0.0
    gross_target: float = 1.0
    long_only: bool = False


def _momentum_scores(close_window: pd.DataFrame, lookback: int, skip: int) -> pd.Series | None:
    """Log return over [t-lookback, t-skip], NaN-safe. None if too little data."""
    if len(close_window) <= lookback + skip + 1:
        return None
    log_close = np.log(close_window)
    past = log_close.iloc[-(lookback + skip + 1)]
    recent = log_close.iloc[-(skip + 1)]
    momentum = recent - past
    return momentum.replace([np.inf, -np.inf], np.nan)


def make_tsmom_weight_fn(config: TSMOMConfig | None = None) -> WeightFn:
    cfg = config or TSMOMConfig()

    def weight_fn(close_window: pd.DataFrame) -> pd.Series:
        zero = pd.Series(0.0, index=close_window.columns)
        momentum = _momentum_scores(close_window, cfg.lookback_bars, cfg.skip_bars)
        if momentum is None:
            return zero
        returns = np.log(close_window).diff().iloc[-cfg.vol_window:]
        vol = returns.std(ddof=1)
        raw = np.sign(momentum) / vol.replace(0.0, np.nan)
        raw = raw.replace([np.inf, -np.inf], np.nan).dropna()
        if cfg.long_only:
            raw = raw[raw > 0]
        if raw.empty:
            return zero
        weights = raw * (cfg.gross_target / raw.abs().sum())
        weights = weights.clip(-cfg.max_weight, cfg.max_weight)
        gross = weights.abs().sum()
        if gross > 0:
            weights *= cfg.gross_target / gross
        return weights.reindex(close_window.columns).fillna(0.0)

    return weight_fn


def make_xsmom_weight_fn(config: XSMOMConfig | None = None) -> WeightFn:
    cfg = config or XSMOMConfig()

    def weight_fn(close_window: pd.DataFrame) -> pd.Series:
        momentum = _momentum_scores(close_window, cfg.lookback_bars, cfg.skip_bars)
        if momentum is None:
            return pd.Series(0.0, index=close_window.columns)
        top_k = cfg.top_k
        if cfg.top_frac > 0:
            top_k = max(2, round(cfg.top_frac * close_window.shape[1]))
        # rank_weights longs the most NEGATIVE scores (mean-reversion
        # convention), so feed it negated momentum: winners become longs.
        return rank_weights(-momentum, top_k, cfg.gross_target, cfg.long_only)

    return weight_fn
