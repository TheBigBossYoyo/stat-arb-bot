"""Stationarity testing (Augmented Dickey-Fuller wrapper)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from statsmodels.tsa.stattools import adfuller


@dataclass
class ADFResult:
    statistic: float
    pvalue: float
    n_lags: int
    n_obs: int
    critical_values: dict[str, float] = field(default_factory=dict)

    def is_stationary(self, alpha: float = 0.05) -> bool:
        return self.pvalue < alpha


def adf_test(series: np.ndarray, regression: str = "c", autolag: str = "AIC") -> ADFResult:
    """ADF test. H0: unit root (non-stationary). Low p-value => stationary."""
    series = np.asarray(series, dtype=float)
    series = series[~np.isnan(series)]
    if len(series) < 20:
        raise ValueError(f"need >= 20 observations for ADF, got {len(series)}")
    stat, pvalue, n_lags, n_obs, crit, _ = adfuller(series, regression=regression, autolag=autolag)
    return ADFResult(
        statistic=float(stat),
        pvalue=float(pvalue),
        n_lags=int(n_lags),
        n_obs=int(n_obs),
        critical_values={k: float(v) for k, v in crit.items()},
    )
