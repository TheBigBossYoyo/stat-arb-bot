"""Vectorized backtester for cross-sectional (basket) strategies.

A basket strategy is a weight function: given price history up to bar t it
returns target portfolio weights (signed fractions of equity). Lookahead is
prevented by construction — weights decided at t earn the t -> t+1 return.
Turnover is charged at `cost_bps` per unit of weight traded.

Strategies that need more than close prices (volume, open, high, low) set a
`wants_aux = True` attribute on their weight function; the engine then calls
them as `fn(close_window, aux={name: frame_window, ...})` with every aux frame
sliced to the same rows as the close window — aux lookahead is impossible by
the same construction.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.metrics import compute_metrics
from app.core.logging import get_logger

log = get_logger(__name__)

WeightFn = Callable[[pd.DataFrame], pd.Series]


@dataclass
class BasketConfig:
    interval: str = "15m"
    starting_cash: float = 10_000.0
    fit_window: int = 1500        # bars of history handed to the weight function
    rebalance_every: int = 24     # bars between weight updates
    cost_bps: float = 15.0        # commission + slippage per unit turnover
    bars_per_year: float | None = None  # ~252 for daily equity bars; None = 24/7 crypto
    label: str = ""


@dataclass
class BasketResult:
    equity: pd.Series
    weights: pd.DataFrame         # weights at each rebalance
    metrics: dict
    config: BasketConfig
    warnings: list[str] = field(default_factory=list)


def rank_weights(
    scores: pd.Series,
    top_k: int,
    gross_target: float = 1.0,
    long_only: bool = False,
) -> pd.Series:
    """Long the most NEGATIVE scores, short the most positive (mean reversion).

    Long-only mode buys the longs leg only — explicitly NOT market-neutral.
    """
    weights = pd.Series(0.0, index=scores.index)
    scores = scores.dropna()
    if len(scores) < (top_k if long_only else 2 * top_k):
        return weights
    longs = scores.nsmallest(top_k).index
    if long_only:
        weights[longs] = gross_target / top_k
        return weights
    shorts = scores.nlargest(top_k).index
    overlap = set(longs) & set(shorts)   # degenerate universe: drop ambiguous names
    longs = [s for s in longs if s not in overlap]
    shorts = [s for s in shorts if s not in overlap]
    if longs:
        weights[longs] = gross_target / 2 / len(longs)
    if shorts:
        weights[shorts] = -gross_target / 2 / len(shorts)
    return weights


def run_basket_backtest(
    close: pd.DataFrame,
    weight_fn: WeightFn,
    config: BasketConfig,
    aux: dict[str, pd.DataFrame] | None = None,
) -> BasketResult:
    cfg = config
    n = len(close)
    if n <= cfg.fit_window + 2:
        raise ValueError(f"need more than {cfg.fit_window + 2} bars, got {n}")
    pass_aux = bool(getattr(weight_fn, "wants_aux", False)) and aux is not None

    columns = list(close.columns)
    returns = close.pct_change().fillna(0.0).to_numpy()
    equity = np.full(n, np.nan)
    equity[: cfg.fit_window + 1] = cfg.starting_cash
    level = cfg.starting_cash
    current = np.zeros(len(columns))
    weight_rows: dict[pd.Timestamp, np.ndarray] = {}
    traded_notional = 0.0
    cost_paid = 0.0
    gross_sum = 0.0
    bars_counted = 0

    for t in range(cfg.fit_window, n - 1):
        if (t - cfg.fit_window) % cfg.rebalance_every == 0:
            lo, hi = t - cfg.fit_window + 1, t + 1
            window = close.iloc[lo:hi]                            # history up to and incl. t
            if pass_aux:
                aux_window = {name: df.iloc[lo:hi] for name, df in aux.items()}
                raw = weight_fn(window, aux=aux_window)
            else:
                raw = weight_fn(window)
            target = raw.reindex(columns).fillna(0.0).to_numpy(dtype=float)
            turnover = float(np.abs(target - current).sum())
            traded_notional += turnover * level
            cost_paid += turnover * cfg.cost_bps / 10_000.0 * level
            level *= 1.0 - turnover * cfg.cost_bps / 10_000.0
            current = target
            weight_rows[close.index[t]] = current.copy()
        level *= 1.0 + float((current * returns[t + 1]).sum())
        equity[t + 1] = level
        gross_sum += float(np.abs(current).sum()) * level
        bars_counted += 1

    equity_series = pd.Series(equity, index=close.index, name="equity").ffill()
    metrics = compute_metrics(
        equity_series.iloc[cfg.fit_window:], [], interval=cfg.interval,
        starting_cash=cfg.starting_cash, bars_per_year=cfg.bars_per_year,
        extras={
            "total_fees": cost_paid,
            "traded_notional": traded_notional,
            "avg_gross_exposure": gross_sum / bars_counted if bars_counted else 0.0,
        },
    )
    weights_df = pd.DataFrame(weight_rows, index=columns).T
    warnings = [
        f"Costs: {cfg.cost_bps}bps per unit turnover; rebalance every {cfg.rebalance_every} bars.",
        "Weights decided at bar t earn the t->t+1 return (no lookahead).",
    ]
    return BasketResult(equity=equity_series, weights=weights_df, metrics=metrics,
                        config=cfg, warnings=warnings)
