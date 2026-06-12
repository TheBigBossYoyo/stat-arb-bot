"""Shared quantitative helpers used by research, strategies and backtesting."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.core.types import interval_minutes

CRYPTO_MINUTES_PER_YEAR = 365.25 * 24 * 60


def periods_per_year(interval: str) -> float:
    """Bars per year for a 24/7 (crypto) calendar."""
    return CRYPTO_MINUTES_PER_YEAR / interval_minutes(interval)


def annualization_factor(interval: str) -> float:
    return math.sqrt(periods_per_year(interval))


def log_prices(prices: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return np.log(prices)


def ols_hedge_ratio(y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    """OLS of y on x with intercept. Returns (beta, alpha)."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    if y.shape != x.shape or y.ndim != 1:
        raise ValueError("y and x must be 1-D arrays of equal length")
    if len(y) < 3:
        raise ValueError("need at least 3 observations")
    x_mean, y_mean = x.mean(), y.mean()
    var_x = float(np.sum((x - x_mean) ** 2))
    if var_x == 0.0:
        raise ValueError("x has zero variance")
    beta = float(np.sum((x - x_mean) * (y - y_mean)) / var_x)
    alpha = float(y_mean - beta * x_mean)
    return beta, alpha


def rolling_zscore(series: pd.Series, lookback: int) -> pd.Series:
    """(x - rolling_mean) / rolling_std with a full window (no partial windows)."""
    if lookback < 2:
        raise ValueError("lookback must be >= 2")
    mean = series.rolling(lookback, min_periods=lookback).mean()
    std = series.rolling(lookback, min_periods=lookback).std(ddof=1)
    return (series - mean) / std.replace(0.0, np.nan)


def zscore_last(values: np.ndarray) -> tuple[float, float, float]:
    """Z-score of the final element against the whole window.

    Returns (z, mean, std). std uses ddof=1; returns z=0 for degenerate windows.
    """
    values = np.asarray(values, dtype=float)
    mean = float(values.mean())
    std = float(values.std(ddof=1))
    if std <= 0.0 or not math.isfinite(std):
        return 0.0, mean, 0.0
    return (float(values[-1]) - mean) / std, mean, std


def half_life_of_mean_reversion(spread: np.ndarray) -> float:
    """Half-life (in bars) from an AR(1) / OU discretization.

    Regress d(spread) on lagged spread:  ds_t = a + b * s_{t-1} + e.
    Half-life = -ln(2)/b for b < 0; returns +inf if the series is not
    mean-reverting (b >= 0).
    """
    spread = np.asarray(spread, dtype=float)
    if len(spread) < 20:
        raise ValueError("need at least 20 observations for a half-life estimate")
    lagged = spread[:-1]
    delta = np.diff(spread)
    b, _ = ols_hedge_ratio(delta, lagged)
    if b >= 0:
        return float("inf")
    return float(-math.log(2.0) / b)


def safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0 or not math.isfinite(denominator):
        return default
    return numerator / denominator
