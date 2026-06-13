"""Crypto-futures backtest engine (Path B).

A futures book differs from the spot/basket engine in three ways that matter:

* **Leverage** — weights are fractions of equity and their gross can exceed 1
  (capped at `leverage`). Gains and losses scale with it.
* **Funding** — every funding period a perp position pays (long) or receives
  (short) `funding_rate x notional`. Over months this dominates carry trades
  and quietly bleeds momentum longs in a high-funding regime.
* **Liquidation** — leverage means an adverse move can wipe the margin. The
  engine tracks the liquidation distance every bar and counts breaches (using
  intrabar high/low when available); the risk model refuses positions whose
  buffer is too thin.

Honest about what it is NOT: it does not simulate the full liquidation cascade,
auto-deleveraging, or exchange outages — those are stress scenarios
(`futures_stress`), not base-case mechanics. Maker/taker fees + slippage +
funding + a leverage cap + liquidation monitoring is the realistic core.
No lookahead: weights decided at t earn t->t+1.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.metrics import compute_metrics

WeightFn = Callable[[pd.DataFrame], pd.Series]


@dataclass
class FuturesConfig:
    interval: str = "1d"
    starting_cash: float = 10_000.0
    fit_window: int = 300
    rebalance_every: int = 1
    taker_fee_bps: float = 4.0            # Binance USDT-perp taker (~0.04%)
    slippage_bps: float = 3.0
    leverage: float = 1.0                 # gross cap; research default 1x
    max_leverage: float = 2.0             # hard research cap
    maintenance_margin_pct: float = 0.05  # ~5% maint for majors at low leverage
    bars_per_year: float = 365.0          # 24/7
    apply_funding: bool = True
    label: str = ""


@dataclass
class FuturesResult:
    equity: pd.Series
    weights: pd.DataFrame
    metrics: dict
    config: FuturesConfig
    funding_paid: float = 0.0
    n_liquidation_breaches: int = 0
    min_liquidation_distance: float = 1.0
    warnings: list[str] = field(default_factory=list)


def align_funding_to_bars(panel: pd.DataFrame, index: pd.DatetimeIndex,
                          columns: list[str]) -> np.ndarray | None:
    """Sum 8h funding rates falling within each bar -> per-bar funding matrix
    aligned to `index` x `columns`. Returns None if no panel."""
    if panel is None or panel.empty:
        return None
    p = panel.reindex(columns=columns)
    # assign each funding print to the bar it falls in (searchsorted on bar edges)
    bins = index
    grouped = p.groupby(bins[np.searchsorted(bins.values, p.index.values, side="right") - 1]).sum()
    out = grouped.reindex(index=index, columns=columns).fillna(0.0)
    return out.to_numpy(dtype=float)


def run_futures_backtest(
    close: pd.DataFrame,
    weight_fn: WeightFn,
    config: FuturesConfig,
    *,
    funding: pd.DataFrame | None = None,
    aux: dict | None = None,
    open_: pd.DataFrame | None = None,
) -> FuturesResult:
    cfg = config
    n = len(close)
    if n <= cfg.fit_window + 2:
        raise ValueError(f"need more than {cfg.fit_window + 2} bars, got {n}")
    lev_cap = min(cfg.leverage, cfg.max_leverage)
    columns = list(close.columns)
    pass_aux = bool(getattr(weight_fn, "wants_aux", False)) and aux is not None

    returns = close.pct_change().fillna(0.0).to_numpy()
    low = (close if open_ is None else close).to_numpy()  # placeholder; use aux low/high
    high_np = aux["high"].reindex(columns=columns).to_numpy() if (aux and "high" in aux) else None
    low_np = aux["low"].reindex(columns=columns).to_numpy() if (aux and "low" in aux) else None
    prev_close = close.shift(1).to_numpy()
    funding_np = align_funding_to_bars(funding, close.index, columns) if cfg.apply_funding else None

    cost_rate = (cfg.taker_fee_bps + cfg.slippage_bps) / 10_000.0
    equity = np.full(n, np.nan)
    equity[: cfg.fit_window + 1] = cfg.starting_cash
    level = cfg.starting_cash
    current = np.zeros(len(columns))
    weight_rows: dict[pd.Timestamp, np.ndarray] = {}
    cost_paid = funding_paid = 0.0
    traded_notional = 0.0
    gross_sum = 0.0
    bars_counted = 0
    n_breach = 0
    min_liq_dist = 1.0

    for t in range(cfg.fit_window, n - 1):
        if (t - cfg.fit_window) % cfg.rebalance_every == 0:
            lo, hi = t - cfg.fit_window + 1, t + 1
            window = close.iloc[lo:hi]
            raw = (weight_fn(window, aux={k: v.iloc[lo:hi] for k, v in aux.items()})
                   if pass_aux else weight_fn(window))
            target = np.array(raw.reindex(columns).fillna(0.0).to_numpy(dtype=float))
            gross = np.abs(target).sum()
            if gross > lev_cap and gross > 0:        # enforce leverage cap
                target *= lev_cap / gross
            turnover = np.abs(target - current).sum()
            traded_notional += float(turnover) * level
            cost = turnover * cost_rate
            cost_paid += cost * level
            level *= 1.0 - cost
            current = target
            weight_rows[close.index[t]] = current.copy()

        # earn the next bar's return on the held book
        level *= 1.0 + float((current * returns[t + 1]).sum())

        # funding: long pays positive funding, short receives
        if funding_np is not None:
            fund = float((current * funding_np[t + 1]).sum())
            funding_paid += fund * level
            level *= 1.0 - fund

        # liquidation monitoring: worst adverse intrabar excursion vs the buffer
        gross = float(np.abs(current).sum())
        if gross > 0:
            liq_dist = max(0.0, 1.0 / gross - cfg.maintenance_margin_pct)
            min_liq_dist = min(min_liq_dist, liq_dist)
            if high_np is not None and low_np is not None and prev_close[t + 1] is not None:
                with np.errstate(divide="ignore", invalid="ignore"):
                    down = np.nan_to_num(low_np[t + 1] / prev_close[t + 1] - 1.0)
                    up = np.nan_to_num(high_np[t + 1] / prev_close[t + 1] - 1.0)
                adverse = float((np.minimum(current, 0) * up + np.maximum(current, 0) * down).sum())
                if -adverse > liq_dist:
                    n_breach += 1

        equity[t + 1] = level
        gross_sum += gross * level
        bars_counted += 1

    equity_series = pd.Series(equity, index=close.index, name="equity").ffill()
    metrics = compute_metrics(
        equity_series.iloc[cfg.fit_window:], [], interval=cfg.interval,
        starting_cash=cfg.starting_cash, bars_per_year=cfg.bars_per_year,
        extras={"total_fees": cost_paid, "financing_cost": funding_paid,
                "traded_notional": traded_notional,
                "avg_gross_exposure": gross_sum / bars_counted if bars_counted else 0.0},
    )
    warnings = [
        f"Leverage cap {lev_cap}x (gross); taker {cfg.taker_fee_bps}bps + "
        f"slippage {cfg.slippage_bps}bps.",
        f"Funding {'applied' if funding_np is not None else 'NOT applied (no panel)'}.",
        "Liquidation cascade, ADL and exchange outages NOT simulated — see futures-stress.",
    ]
    if n_breach:
        warnings.append(f"WARNING: {n_breach} bars breached the liquidation buffer "
                        f"(min distance {min_liq_dist:.3f}) — leverage too high for this vol.")
    return FuturesResult(
        equity=equity_series, weights=pd.DataFrame(weight_rows, index=columns).T,
        metrics=metrics, config=cfg, funding_paid=funding_paid,
        n_liquidation_breaches=n_breach, min_liquidation_distance=round(min_liq_dist, 4),
        warnings=warnings,
    )
