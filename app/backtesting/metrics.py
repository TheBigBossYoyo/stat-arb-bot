"""Performance metrics for backtest results."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.core.math_utils import periods_per_year, safe_div


def max_drawdown(equity: pd.Series) -> float:
    """Maximum peak-to-trough drawdown as a negative fraction (e.g. -0.12)."""
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min()) if len(drawdown) else 0.0


def compute_metrics(
    equity: pd.Series,
    trades: list,
    *,
    interval: str,
    starting_cash: float,
    extras: dict | None = None,
    bars_per_year: float | None = None,
) -> dict:
    """`bars_per_year` overrides the 24/7 crypto calendar — pass ~252 for
    daily equity/FX bars so vol/Sharpe are not inflated by phantom weekends."""
    extras = extras or {}
    equity = equity.dropna()
    if len(equity) < 2:
        return {"error": "not enough equity points"}

    ppy = bars_per_year or periods_per_year(interval)
    returns = equity.pct_change().dropna()
    n_years = len(equity) / ppy
    final = float(equity.iloc[-1])

    total_return = final / starting_cash - 1.0
    cagr = (final / starting_cash) ** (1.0 / n_years) - 1.0 if final > 0 and n_years > 0 else float("nan")
    vol = float(returns.std(ddof=1)) * math.sqrt(ppy) if len(returns) > 1 else 0.0
    mean_ret = float(returns.mean())
    sharpe = safe_div(mean_ret, float(returns.std(ddof=1))) * math.sqrt(ppy) if len(returns) > 1 else 0.0
    downside = returns[returns < 0]
    sortino = (
        safe_div(mean_ret, float(downside.std(ddof=1))) * math.sqrt(ppy)
        if len(downside) > 1 else float("nan")
    )
    mdd = max_drawdown(equity)
    calmar = safe_div(cagr, abs(mdd)) if mdd < 0 else float("nan")

    daily = equity.resample("1D").last().dropna()
    daily_returns = daily.pct_change().dropna()
    worst_day = float(daily_returns.min()) if len(daily_returns) else 0.0

    pnls = np.array([t.pnl for t in trades], dtype=float)
    holding = np.array([t.holding_bars for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]

    avg_equity = float(equity.mean())
    metrics = {
        "bars": len(equity),
        "years": round(n_years, 3),
        "total_return_pct": round(100 * total_return, 3),
        "cagr_pct": round(100 * cagr, 3) if not math.isnan(cagr) else None,
        "ann_vol_pct": round(100 * vol, 3),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3) if not math.isnan(sortino) else None,
        "calmar": round(calmar, 3) if not math.isnan(calmar) else None,
        "max_drawdown_pct": round(100 * mdd, 3),
        "worst_day_pct": round(100 * worst_day, 3),
        "n_trades": int(len(pnls)),
        "win_rate_pct": round(100 * safe_div(len(wins), len(pnls)), 2) if len(pnls) else None,
        "profit_factor": round(safe_div(wins.sum(), abs(losses.sum()), default=float("inf")), 3)
        if len(losses) else None,
        "avg_trade_pnl": round(float(pnls.mean()), 4) if len(pnls) else None,
        "median_trade_pnl": round(float(np.median(pnls)), 4) if len(pnls) else None,
        "worst_trade_pnl": round(float(pnls.min()), 4) if len(pnls) else None,
        "best_trade_pnl": round(float(pnls.max()), 4) if len(pnls) else None,
        "avg_holding_bars": round(float(holding.mean()), 2) if len(holding) else None,
        "total_fees": round(float(extras.get("total_fees", 0.0)), 4),
        "financing_cost": round(float(extras.get("financing_cost", 0.0)), 4),
        "turnover": round(safe_div(float(extras.get("traded_notional", 0.0)), avg_equity), 3),
        "avg_gross_exposure_pct": round(
            100 * safe_div(float(extras.get("avg_gross_exposure", 0.0)), avg_equity), 2
        ),
        "final_equity": round(final, 2),
    }
    return metrics
