"""Funding-rate carry research backtest (delta-neutral, perp vs spot).

The trade: long spot + short an equal notional of the USDT perpetual. Price
risk nets out (up to basis noise); the position collects the funding rate
every 8 hours while it is positive. Hedge funds run this as a carry book,
rotating into the perps with the richest *persistent* funding.

What this backtest models — and what it does not:

* return per period = held weights x realized funding, minus turnover costs
  when the book changes (entering carry = 2 legs: buy spot, sell perp);
* it does NOT model basis convergence/divergence, margin interest, liquidation
  risk on the short perp leg, or borrow limits. Results are an upper bound on
  the funding leg only. RESEARCH ONLY: no futures account is connected.

No lookahead by construction: weights chosen after observing the funding
print at t-1 earn the funding paid at t.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.metrics import compute_metrics

PERIODS_PER_YEAR = 3 * 365.0          # 8h funding periods, 24/7 calendar


@dataclass
class CarryConfig:
    lookback_periods: int = 30        # trailing funding window (~10 days)
    top_k: int = 3
    # entry/exit hysteresis on ANNUALIZED trailing funding: enter a perp only
    # when its carry clears entry_apr, hold it until carry decays through
    # exit_apr. Re-ranking the book every 8h flipped near-tied names
    # constantly — at 30bps per change the churn burned 46% in two years
    # while the carry itself averaged ~5%/yr.
    entry_apr: float = 0.05
    exit_apr: float = 0.0
    cost_bps: float = 30.0            # both legs in AND out per unit traded
    starting_cash: float = 10_000.0
    label: str = "funding_carry"


@dataclass
class CarryResult:
    equity: pd.Series
    weights: pd.DataFrame             # weights held during each funding period
    metrics: dict
    config: CarryConfig
    warnings: list[str] = field(default_factory=list)


def run_carry_backtest(funding: pd.DataFrame, config: CarryConfig | None = None) -> CarryResult:
    """`funding`: index = funding timestamps (8h grid), columns = symbols,
    values = decimal funding rate received by the SHORT perp leg per period."""
    cfg = config or CarryConfig()
    n = len(funding)
    if n <= cfg.lookback_periods + 1:
        raise ValueError(f"need more than {cfg.lookback_periods + 1} periods, got {n}")

    columns = list(funding.columns)
    rates = funding.fillna(0.0).to_numpy(dtype=float)
    equity = np.full(n, np.nan)
    equity[: cfg.lookback_periods] = cfg.starting_cash
    level = cfg.starting_cash
    current = np.zeros(len(columns))
    weight_rows: dict[pd.Timestamp, np.ndarray] = {}
    cost_paid = 0.0
    traded = 0.0

    held: set[int] = set()
    for t in range(cfg.lookback_periods, n):
        # decided from funding prints up to t-1; earns the print paid at t
        trailing_apr = rates[t - cfg.lookback_periods: t].mean(axis=0) * PERIODS_PER_YEAR
        held = {i for i in held if trailing_apr[i] > cfg.exit_apr}
        for i in np.argsort(trailing_apr)[::-1]:     # richest candidates first
            if len(held) >= cfg.top_k or trailing_apr[i] < cfg.entry_apr:
                break
            held.add(int(i))
        target = np.zeros(len(columns))
        if held:
            target[list(held)] = 1.0 / cfg.top_k     # unfilled slots stay in cash
        turnover = float(np.abs(target - current).sum())
        traded += turnover * level
        cost_paid += turnover * cfg.cost_bps / 10_000.0 * level
        level *= 1.0 - turnover * cfg.cost_bps / 10_000.0
        current = target
        level *= 1.0 + float((current * rates[t]).sum())
        equity[t] = level
        weight_rows[funding.index[t]] = current.copy()

    equity_series = pd.Series(equity, index=funding.index, name="equity").ffill()
    metrics = compute_metrics(
        equity_series.iloc[cfg.lookback_periods - 1:], [], interval="8h",
        starting_cash=cfg.starting_cash, bars_per_year=PERIODS_PER_YEAR,
        extras={"total_fees": cost_paid, "traded_notional": traded},
    )
    warnings = [
        f"Costs: {cfg.cost_bps}bps per unit turnover (both legs).",
        "Funding leg only: basis risk, margin interest and liquidation risk on "
        "the short perp are NOT modeled. Research only — no futures account.",
    ]
    return CarryResult(
        equity=equity_series,
        weights=pd.DataFrame(weight_rows, index=columns).T,
        metrics=metrics, config=cfg, warnings=warnings,
    )
