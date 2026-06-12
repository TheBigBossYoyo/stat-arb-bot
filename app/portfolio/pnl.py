"""PnL aggregation helpers."""

from __future__ import annotations

import pandas as pd


def equity_curve_stats(equity: pd.Series) -> dict:
    equity = equity.dropna()
    if equity.empty:
        return {}
    daily = equity.resample("1D").last().dropna()
    return {
        "current_equity": float(equity.iloc[-1]),
        "daily_pnl": float(daily.diff().iloc[-1]) if len(daily) > 1 else 0.0,
        "total_pnl": float(equity.iloc[-1] - equity.iloc[0]),
        "high_water_mark": float(equity.cummax().iloc[-1]),
    }


def drawdown_series(equity: pd.Series) -> pd.Series:
    equity = equity.dropna()
    return equity / equity.cummax() - 1.0
