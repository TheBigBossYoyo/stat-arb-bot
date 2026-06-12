"""Engle-Granger cointegration testing and spread construction.

Why correlation is not enough: two assets can be highly correlated in returns
while their *price levels* drift apart forever (no mean reversion to trade).
Cointegration tests whether a linear combination of the price levels —
spread = log(A) - beta*log(B) - alpha — is stationary, i.e. departures from
the long-run relationship tend to revert.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from statsmodels.tsa.stattools import coint

from app.core.math_utils import half_life_of_mean_reversion, ols_hedge_ratio
from app.research.stationarity import adf_test


@dataclass
class CointegrationResult:
    beta: float
    alpha: float
    eg_pvalue: float            # Engle-Granger test p-value
    eg_statistic: float
    adf_pvalue: float           # ADF on the OLS residual spread
    half_life: float            # bars; inf if non-reverting
    correlation: float          # log-return correlation
    spread_std: float
    n_obs: int

    @property
    def spread_is_stationary(self) -> bool:
        return self.adf_pvalue < 0.05

    def is_tradeable(
        self,
        max_eg_pvalue: float = 0.05,
        max_adf_pvalue: float = 0.05,
        min_half_life: float = 3.0,
        max_half_life: float = 100.0,
        min_spread_std: float = 0.0,
    ) -> bool:
        return (
            self.eg_pvalue < max_eg_pvalue
            and self.adf_pvalue < max_adf_pvalue
            and min_half_life <= self.half_life <= max_half_life
            and self.spread_std >= min_spread_std
            and self.beta > 0  # negative hedge ratios are not pair trades
        )


def compute_spread(log_a: np.ndarray, log_b: np.ndarray, beta: float, alpha: float) -> np.ndarray:
    return np.asarray(log_a, float) - (alpha + beta * np.asarray(log_b, float))


def engle_granger_test(log_a: np.ndarray, log_b: np.ndarray) -> tuple[float, float]:
    """Engle-Granger cointegration test of A on B. Returns (statistic, pvalue)."""
    stat, pvalue, _ = coint(log_a, log_b)
    return float(stat), float(pvalue)


def cointegration_test(log_a: np.ndarray, log_b: np.ndarray) -> CointegrationResult:
    """Full pair analysis: hedge ratio, EG test, residual ADF, half-life."""
    log_a = np.asarray(log_a, dtype=float)
    log_b = np.asarray(log_b, dtype=float)
    if log_a.shape != log_b.shape or log_a.ndim != 1:
        raise ValueError("log_a and log_b must be 1-D arrays of equal length")
    if len(log_a) < 100:
        raise ValueError(f"need >= 100 observations for a cointegration test, got {len(log_a)}")

    beta, alpha = ols_hedge_ratio(log_a, log_b)
    spread = compute_spread(log_a, log_b, beta, alpha)
    eg_stat, eg_pvalue = engle_granger_test(log_a, log_b)
    adf = adf_test(spread)
    try:
        half_life = half_life_of_mean_reversion(spread)
    except ValueError:
        half_life = float("inf")

    returns_a = np.diff(log_a)
    returns_b = np.diff(log_b)
    correlation = float(np.corrcoef(returns_a, returns_b)[0, 1])

    return CointegrationResult(
        beta=beta,
        alpha=alpha,
        eg_pvalue=eg_pvalue,
        eg_statistic=eg_stat,
        adf_pvalue=adf.pvalue,
        half_life=half_life,
        correlation=correlation,
        spread_std=float(np.std(spread, ddof=1)),
        n_obs=len(log_a),
    )
