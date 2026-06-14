"""Long-only momentum strategies for Trading 212 Invest/ISA (Path A).

The market-neutral flagship cannot trade on Trading 212 Invest/ISA — those
accounts cannot short, cannot use margin and cannot trade CFDs (the official
Public API exposes none of them, and we will not use anything unofficial). So
this is a *different, directional* product: it ranks the universe by the same
momentum signals but buys only the leaders and holds CASH instead of shorting
the laggards. It is NOT market-neutral and must never be described as such.

Two cash-aware building blocks:

* **long_only_xsec_momentum** — rank by trailing return, buy the top-k (or
  top-frac) names, equal-weighted, gross = the regime-scaled exposure. The rest
  of the book is cash (a real drag, modeled by construction).
* **long_only_tsmom** — hold only names whose own trailing return is positive,
  inverse-vol weighted and per-name capped. In a broad sell-off every name can
  fail the filter and the book goes fully to cash — the long-only analogue of
  TSMOM's defensiveness.

A **regime trend filter** (off-by-default-able) scales the whole book toward
cash when the equal-weight universe is below its moving average. This is the
"risk-off cash filter / market regime filter" from the spec, implemented with
an internal market proxy so it needs no extra data; the comparison command can
substitute a real SPY/QQQ trend when that series is available.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.backtesting.basket_engine import WeightFn
from app.strategies.weight_smoothing import SmoothingConfig, WeightSmoother


class RegimeFilterConfig(BaseModel):
    ma_window: int = 200          # trailing MA of the equal-weight market proxy
    risk_off_exposure: float = 0.0  # gross when proxy < MA (0 = fully to cash)
    enabled: bool = True


class LongOnlyXSMOMConfig(BaseModel):
    lookback_bars: int = 336
    skip_bars: int = 12
    top_k: int = 10
    top_frac: float = 0.0          # if > 0, top_frac * n_assets (decile-style)
    gross_target: float = 1.0      # fully invested when risk-on
    vol_weight: bool = False       # equal-weight (False) or inverse-vol (True)
    vol_window: int = 60
    max_weight: float = 0.20       # per-name cap (concentration control)
    regime: RegimeFilterConfig = RegimeFilterConfig()
    smoothing: SmoothingConfig = SmoothingConfig()   # target-weight smoothing (Phase 1)


class LongOnlyTSMOMConfig(BaseModel):
    lookback_bars: int = 252
    skip_bars: int = 12
    vol_window: int = 60
    gross_target: float = 1.0
    max_weight: float = 0.20
    regime: RegimeFilterConfig = RegimeFilterConfig()
    smoothing: SmoothingConfig = SmoothingConfig()   # target-weight smoothing (Phase 1)


def regime_scalar(close_window: pd.DataFrame, cfg: RegimeFilterConfig,
                  benchmark: pd.Series | None = None) -> float:
    """1.0 when risk-on (market >= its MA), else `risk_off_exposure`.

    Uses `benchmark` (e.g. SPY close) when provided, otherwise the equal-weight
    average of the universe as an internal market proxy."""
    if not cfg.enabled or cfg.ma_window <= 0:
        return 1.0
    proxy = benchmark if benchmark is not None else close_window.mean(axis=1)
    proxy = proxy.dropna()
    if len(proxy) < cfg.ma_window + 1:
        return 1.0
    ma = float(proxy.iloc[-cfg.ma_window:].mean())
    return 1.0 if float(proxy.iloc[-1]) >= ma else cfg.risk_off_exposure


def _momentum(close_window: pd.DataFrame, lookback: int, skip: int) -> pd.Series | None:
    if len(close_window) <= lookback + skip + 1:
        return None
    log_close = np.log(close_window)
    mom = log_close.iloc[-(skip + 1)] - log_close.iloc[-(lookback + skip + 1)]
    return mom.replace([np.inf, -np.inf], np.nan)


def make_long_only_xsmom_weight_fn(config: LongOnlyXSMOMConfig | None = None) -> WeightFn:
    cfg = config or LongOnlyXSMOMConfig()
    smoother = WeightSmoother(cfg.smoothing, max_weight=cfg.max_weight,
                              gross_target=cfg.gross_target)

    def weight_fn(close_window: pd.DataFrame) -> pd.Series:
        zero = pd.Series(0.0, index=close_window.columns)
        mom = _momentum(close_window, cfg.lookback_bars, cfg.skip_bars)
        if mom is None:
            return smoother.smooth(zero)
        mom = mom.dropna()
        if mom.empty:
            return smoother.smooth(zero)
        top_k = cfg.top_k
        if cfg.top_frac > 0:
            top_k = max(1, round(cfg.top_frac * close_window.shape[1]))
        # only POSITIVE-momentum names are eligible (no buying falling knives)
        winners = mom[mom > 0].nlargest(top_k).index
        if len(winners) == 0:
            return smoother.smooth(zero)
        if cfg.vol_weight:
            rets = np.log(close_window[winners]).diff().iloc[-cfg.vol_window:]
            inv = 1.0 / rets.std(ddof=1).replace(0.0, np.nan)
            w = inv.replace([np.inf, -np.inf], np.nan).dropna()
            weights = w / w.sum() if w.sum() > 0 else pd.Series(1.0 / len(winners), index=winners)
        else:
            weights = pd.Series(1.0 / len(winners), index=winners)
        weights = weights.clip(upper=cfg.max_weight)
        weights = weights / weights.sum()        # renormalize to fully invested
        exposure = cfg.gross_target * regime_scalar(close_window, cfg.regime)
        target = (weights * exposure).reindex(close_window.columns).fillna(0.0)
        # smooth target weights before they leave the strategy (Phase 1): blends
        # with the previously emitted book to spread rebalances (and therefore
        # PnL) across more bars, shrinking single-month concentration. method=
        # "none" (the default) is an exact pass-through.
        return smoother.smooth(target)

    return weight_fn


def make_long_only_tsmom_weight_fn(config: LongOnlyTSMOMConfig | None = None) -> WeightFn:
    cfg = config or LongOnlyTSMOMConfig()
    smoother = WeightSmoother(cfg.smoothing, max_weight=cfg.max_weight,
                              gross_target=cfg.gross_target)

    def weight_fn(close_window: pd.DataFrame) -> pd.Series:
        zero = pd.Series(0.0, index=close_window.columns)
        mom = _momentum(close_window, cfg.lookback_bars, cfg.skip_bars)
        if mom is None:
            return smoother.smooth(zero)
        eligible = mom[mom > 0].dropna().index   # only up-trending names
        if len(eligible) == 0:
            return smoother.smooth(zero)
        rets = np.log(close_window[eligible]).diff().iloc[-cfg.vol_window:]
        inv = 1.0 / rets.std(ddof=1).replace(0.0, np.nan)
        w = inv.replace([np.inf, -np.inf], np.nan).dropna()
        if w.empty:
            return smoother.smooth(zero)
        weights = (w / w.sum()).clip(upper=cfg.max_weight)
        weights = weights / weights.sum()
        exposure = cfg.gross_target * regime_scalar(close_window, cfg.regime)
        target = (weights * exposure).reindex(close_window.columns).fillna(0.0)
        return smoother.smooth(target)

    return weight_fn
