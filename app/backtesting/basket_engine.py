"""Vectorized backtester for cross-sectional (basket) strategies.

A basket strategy is a weight function: given price history up to bar t it
returns target portfolio weights (signed fractions of equity). Lookahead is
prevented by construction — weights decided at t are executed and then earn
the forward return.

Execution timing (audit W-03). The legacy engine filled at the SAME close the
signal observed (`fill="same_close"`), which lets short-horizon signals harvest
the overnight move of their own trigger. The default is now `fill="next_open"`:
a weight decided at close[t] is executed at open[t+1], so the close[t]->close[t+1]
bar is earned partly on the OLD weights (close[t]->open[t+1]) and partly on the
NEW ones (open[t+1]->close[t+1]). `same_close` is kept for reproducing legacy
numbers and for close-only data, and any result computed that way carries a
warning.

Costs (audit W-07/W-09). Turnover is charged at `cost_bps` per unit traded
(or per-asset via `per_asset_cost_bps`). Short books pay a borrow rate and
levered books pay margin interest, both per bar — a market-neutral or levered
backtest with zero financing is not honest.

Strategies that need more than close prices (volume, open, high, low) set a
`wants_aux = True` attribute; the engine then calls them as
`fn(close_window, aux={name: frame_window, ...})`, every aux frame sliced to
the same rows as the close window — aux lookahead is impossible by construction.
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
    fill: str = "next_open"       # next_open (honest) | same_close (legacy/close-only)
    borrow_bps_annual: float = 0.0    # financing on the short leg's notional
    margin_bps_annual: float = 0.0    # interest on gross exposure above equity
    per_asset_cost_bps: dict[str, float] | None = None  # overrides cost_bps per symbol
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


def _per_asset_cost_vector(columns: list[str], cfg: BasketConfig) -> np.ndarray:
    """Per-symbol round-trip cost in fractional terms, aligned to `columns`."""
    base = cfg.cost_bps / 10_000.0
    if not cfg.per_asset_cost_bps:
        return np.full(len(columns), base)
    return np.array(
        [cfg.per_asset_cost_bps.get(c, cfg.cost_bps) / 10_000.0 for c in columns]
    )


def run_basket_backtest(
    close: pd.DataFrame,
    weight_fn: WeightFn,
    config: BasketConfig,
    aux: dict[str, pd.DataFrame] | None = None,
    open_: pd.DataFrame | None = None,
) -> BasketResult:
    cfg = config
    n = len(close)
    if n <= cfg.fit_window + 2:
        raise ValueError(f"need more than {cfg.fit_window + 2} bars, got {n}")
    pass_aux = bool(getattr(weight_fn, "wants_aux", False)) and aux is not None

    columns = list(close.columns)
    cost_vec = _per_asset_cost_vector(columns, cfg)
    returns = close.pct_change().fillna(0.0).to_numpy()        # close[t-1]->close[t]
    # open-relative returns for next-open fills
    if open_ is not None:
        open_np = open_.reindex(columns=columns).to_numpy()
        close_np = close.to_numpy()
        # ret from close[t] to open[t+1], and open[t+1] to close[t+1]
        c2o = np.full((n, len(columns)), 0.0)
        o2c = np.full((n, len(columns)), 0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            c2o[1:] = open_np[1:] / close_np[:-1] - 1.0       # close[t]->open[t+1] at row t+1
            o2c = close_np / open_np - 1.0                     # open[t]->close[t] at row t
        c2o = np.nan_to_num(c2o)
        o2c = np.nan_to_num(o2c)
    else:
        c2o = o2c = None

    use_next_open = cfg.fill == "next_open" and open_ is not None
    bpy = cfg.bars_per_year or 0.0
    borrow_per_bar = (cfg.borrow_bps_annual / 10_000.0 / bpy) if bpy else 0.0
    margin_per_bar = (cfg.margin_bps_annual / 10_000.0 / bpy) if bpy else 0.0

    equity = np.full(n, np.nan)
    equity[: cfg.fit_window + 1] = cfg.starting_cash
    level = cfg.starting_cash
    current = np.zeros(len(columns))
    weight_rows: dict[pd.Timestamp, np.ndarray] = {}
    traded_notional = 0.0
    cost_paid = 0.0
    financing_paid = 0.0
    gross_sum = 0.0
    bars_counted = 0

    pending_target: np.ndarray | None = None   # weights to execute at the next open

    for t in range(cfg.fit_window, n - 1):
        rebalance = (t - cfg.fit_window) % cfg.rebalance_every == 0
        if rebalance:
            lo, hi = t - cfg.fit_window + 1, t + 1
            window = close.iloc[lo:hi]                            # history up to and incl. t
            if pass_aux:
                aux_window = {name: df.iloc[lo:hi] for name, df in aux.items()}
                raw = weight_fn(window, aux=aux_window)
            else:
                raw = weight_fn(window)
            target = raw.reindex(columns).fillna(0.0).to_numpy(dtype=float)
            if use_next_open:
                pending_target = target            # execute at open[t+1]
            else:
                turnover_vec = np.abs(target - current)
                cost = float((turnover_vec * cost_vec).sum())
                traded_notional += float(turnover_vec.sum()) * level
                cost_paid += cost * level
                level *= 1.0 - cost
                current = target
                weight_rows[close.index[t]] = current.copy()

        if use_next_open:
            # earn close[t]->open[t+1] on the OLD book, then rebalance at open[t+1]
            level *= 1.0 + float((current * c2o[t + 1]).sum())
            if pending_target is not None:
                turnover_vec = np.abs(pending_target - current)
                cost = float((turnover_vec * cost_vec).sum())
                traded_notional += float(turnover_vec.sum()) * level
                cost_paid += cost * level
                level *= 1.0 - cost
                current = pending_target
                pending_target = None
                weight_rows[close.index[t]] = current.copy()
            # earn open[t+1]->close[t+1] on the NEW book
            level *= 1.0 + float((current * o2c[t + 1]).sum())
        else:
            level *= 1.0 + float((current * returns[t + 1]).sum())

        # financing: borrow on the short notional, margin interest on leverage
        if borrow_per_bar or margin_per_bar:
            short_notional = float(np.abs(np.minimum(current, 0.0)).sum())
            gross = float(np.abs(current).sum())
            fin = (borrow_per_bar * short_notional
                   + margin_per_bar * max(0.0, gross - 1.0))
            financing_paid += fin * level
            level *= 1.0 - fin

        equity[t + 1] = level
        gross_sum += float(np.abs(current).sum()) * level
        bars_counted += 1

    equity_series = pd.Series(equity, index=close.index, name="equity").ffill()
    metrics = compute_metrics(
        equity_series.iloc[cfg.fit_window:], [], interval=cfg.interval,
        starting_cash=cfg.starting_cash, bars_per_year=cfg.bars_per_year,
        extras={
            "total_fees": cost_paid,
            "financing_cost": financing_paid,
            "traded_notional": traded_notional,
            "avg_gross_exposure": gross_sum / bars_counted if bars_counted else 0.0,
        },
    )
    weights_df = pd.DataFrame(weight_rows, index=columns).T
    fill_desc = "next-open fills" if use_next_open else "same-close fills"
    warnings = [
        f"Costs: {cfg.cost_bps}bps/unit turnover; rebalance every {cfg.rebalance_every} bars.",
        f"Execution: {fill_desc}.",
    ]
    if not use_next_open and cfg.fill == "next_open":
        warnings.append(
            "WARNING: next_open requested but no open prices supplied — fell back "
            "to SAME-CLOSE fills (optimistic for short-horizon signals; audit W-03).")
    if cfg.fill == "same_close":
        warnings.append(
            "WARNING: same-close fills assume execution at the price the signal "
            "observed — optimistic for short-horizon signals (audit W-03).")
    if (cfg.borrow_bps_annual or cfg.margin_bps_annual) and not bpy:
        warnings.append(
            "WARNING: financing rates set but bars_per_year is None — financing "
            "NOT applied (cannot annualize); pass bars_per_year.")
    elif not (cfg.borrow_bps_annual or cfg.margin_bps_annual):
        warnings.append(
            "Financing NOT modeled (borrow/margin = 0). A short or levered book "
            "pays both in reality (audit W-07).")
    return BasketResult(equity=equity_series, weights=weights_df, metrics=metrics,
                        config=cfg, warnings=warnings)
