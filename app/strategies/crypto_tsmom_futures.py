"""Crypto time-series momentum on perpetual futures (Path B).

Multi-horizon trend (the sign of several skip-adjusted lookback returns, voted),
inverse-vol sized, with two crypto-specific controls:

* **BTC/ETH beta cap** — crypto is one big beta trade; without a cap a TSMOM
  book is just levered long BTC. The combined BTC+ETH gross is capped so the
  book expresses cross-sectional trend, not market direction.
* **Crash de-risking** — scale the whole book down when recent market vol spikes
  (the regime where trend-following crashes hardest in crypto).

Futures can short, so unlike the long-only equity path this is genuinely
two-sided. Funding-awareness is a separate sleeve (funding_adjusted_momentum).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.backtesting.futures_engine import WeightFn


class CryptoTSMOMConfig(BaseModel):
    lookback_bars: list[int] = [20, 60, 120]   # multi-horizon trend votes (daily)
    skip_bars: int = 2
    vol_window: int = 30
    gross_target: float = 1.0
    max_weight: float = 0.30
    beta_assets: list[str] = ["BTCUSDT", "ETHUSDT"]
    max_beta_gross: float = 0.50               # cap combined BTC+ETH gross
    crash_vol_window: int = 20
    crash_target_vol: float = 0.03             # per-bar market vol for full size
    long_only: bool = False                    # futures: two-sided by default


def _trend_vote(close_window: pd.DataFrame, lookbacks: list[int], skip: int) -> pd.Series | None:
    max_lb = max(lookbacks)
    if len(close_window) <= max_lb + skip + 1:
        return None
    log_close = np.log(close_window)
    votes = pd.Series(0.0, index=close_window.columns)
    for lb in lookbacks:
        past = log_close.iloc[-(lb + skip + 1)]
        recent = log_close.iloc[-(skip + 1)]
        votes = votes.add(np.sign(recent - past), fill_value=0.0)
    return (votes / len(lookbacks)).replace([np.inf, -np.inf], np.nan)


def _crash_scalar(close_window: pd.DataFrame, window: int, target: float) -> float:
    if window <= 0 or target <= 0 or len(close_window) <= window:
        return 1.0
    mkt = np.log(close_window).diff().mean(axis=1).iloc[-window:]
    vol = float(mkt.std(ddof=1)) if len(mkt) > 1 else 0.0
    return float(min(1.0, target / vol)) if vol > 1e-12 else 1.0


def make_crypto_tsmom_weight_fn(config: CryptoTSMOMConfig | None = None) -> WeightFn:
    cfg = config or CryptoTSMOMConfig()

    def weight_fn(close_window: pd.DataFrame) -> pd.Series:
        zero = pd.Series(0.0, index=close_window.columns)
        votes = _trend_vote(close_window, cfg.lookback_bars, cfg.skip_bars)
        if votes is None:
            return zero
        rets = np.log(close_window).diff().iloc[-cfg.vol_window:]
        vol = rets.std(ddof=1).replace(0.0, np.nan)
        raw = (votes / vol).replace([np.inf, -np.inf], np.nan).dropna()
        if cfg.long_only:
            raw = raw[raw > 0]
        if raw.empty:
            return zero
        w = raw * (cfg.gross_target / raw.abs().sum())
        w = w.clip(-cfg.max_weight, cfg.max_weight)
        gross = float(w.abs().sum())
        if gross > 0:
            w *= cfg.gross_target / gross
        # BTC/ETH beta cap LAST (a risk cap: gross may end below target; do NOT
        # re-normalize afterwards or the cap is undone).
        beta = [s for s in cfg.beta_assets if s in w.index]
        beta_gross = float(w[beta].abs().sum()) if beta else 0.0
        if beta_gross > cfg.max_beta_gross > 0:
            w[beta] = w[beta] * (cfg.max_beta_gross / beta_gross)
        scalar = _crash_scalar(close_window, cfg.crash_vol_window, cfg.crash_target_vol)
        return (w * scalar).reindex(close_window.columns).fillna(0.0)

    return weight_fn
