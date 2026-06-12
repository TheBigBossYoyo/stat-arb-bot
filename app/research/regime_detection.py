"""Simple trend-regime filter.

Mean-reversion pair entries perform worst when one leg is in a strong trend
or breakout. This filter flags bars where the rolling drift of a series is
statistically large relative to its noise (a t-statistic on the mean return),
so strategies can skip new entries in trending regimes.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def trend_t_stat(log_close: pd.Series, window: int = 96) -> pd.Series:
    """Rolling t-statistic of the mean log return: mean / (std / sqrt(n))."""
    returns = log_close.diff()
    mean = returns.rolling(window, min_periods=window).mean()
    std = returns.rolling(window, min_periods=window).std(ddof=1)
    return mean / (std / np.sqrt(window))


def is_trending(log_close: pd.Series, window: int = 96, t_threshold: float = 3.0) -> pd.Series:
    """Boolean series: True where the asset is in a strong trend regime."""
    return trend_t_stat(log_close, window).abs() > t_threshold


def any_leg_trending(
    i: int,
    window: int,
    t_threshold: float,
    *log_series: np.ndarray,
) -> bool:
    """Bar-level check used inside strategies: True if ANY leg's trailing mean
    log return is statistically large (|t| > threshold) at bar i."""
    if i + 1 <= window:
        return False
    for series in log_series:
        returns = np.diff(series[i - window : i + 1])
        std = returns.std(ddof=1)
        if std > 0:
            t_stat = abs(returns.mean() / (std / np.sqrt(window)))
            if t_stat > t_threshold:
                return True
    return False
