"""Deflated Sharpe Ratio and Probability of Backtest Overfitting.

The single most important correction this project was missing (audit W-02).
When you evaluate N strategy configurations on one window and report the best
one, its Sharpe is inflated by selection — the expected MAXIMUM Sharpe of N
zero-skill trials grows like sqrt(2 ln N). Bailey & Lopez de Prado's Deflated
Sharpe Ratio asks the honest question: given that I ran N trials, and given
the non-normality of these returns, what is the probability the TRUE Sharpe is
positive?

References:
* Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio".
* Lopez de Prado (2018), "Advances in Financial Machine Learning", ch. 8 (PBO).

Everything here works on a realized return series and a trial count taken from
the experiment registry — researchers do not get to under-report trials.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats


def _moments(returns: np.ndarray) -> tuple[float, float, float, float]:
    """(sharpe per-period, skew, excess-kurtosis, n) with safe fallbacks."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = len(r)
    if n < 3 or r.std(ddof=1) == 0:
        return 0.0, 0.0, 0.0, float(n)
    sr = r.mean() / r.std(ddof=1)
    skew = float(stats.skew(r, bias=False))
    kurt = float(stats.kurtosis(r, fisher=True, bias=False))  # excess kurtosis
    return float(sr), skew, kurt, float(n)


def expected_max_sharpe(n_trials: int, trial_sharpe_std: float) -> float:
    """E[max Sharpe] of n_trials zero-skill strategies whose per-trial Sharpe
    estimates have dispersion `trial_sharpe_std` (same period units as the SR).

    Uses the standard extreme-value approximation of the max of N gaussians.
    """
    if n_trials <= 1 or trial_sharpe_std <= 0:
        return 0.0
    e = math.e
    gamma = 0.5772156649015329  # Euler-Mascheroni
    z1 = stats.norm.ppf(1.0 - 1.0 / n_trials)
    z2 = stats.norm.ppf(1.0 - 1.0 / (n_trials * e))
    return float(trial_sharpe_std * ((1.0 - gamma) * z1 + gamma * z2))


@dataclass
class DeflatedSharpeResult:
    observed_sharpe_ann: float
    deflated_prob: float          # P(true Sharpe > benchmark) after deflation
    expected_max_sharpe_ann: float
    n_trials: int
    n_obs: int
    skew: float
    excess_kurtosis: float
    periods_per_year: float
    passed: bool                  # deflated_prob above the chosen confidence?

    def summary(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"[{verdict}] observed SR {self.observed_sharpe_ann:.2f} ann | "
            f"P(true>benchmark)={self.deflated_prob:.3f} | "
            f"E[max of {self.n_trials} trials]={self.expected_max_sharpe_ann:.2f} ann | "
            f"n={self.n_obs}, skew={self.skew:.2f}, exkurt={self.excess_kurtosis:.2f}"
        )


def probabilistic_sharpe_ratio(
    returns: np.ndarray, benchmark_sr_per_period: float, periods_per_year: float
) -> float:
    """PSR: P(true Sharpe > benchmark) for a single strategy, correcting for
    the non-normality of returns and the sample length (Bailey-LdP 2012)."""
    sr, skew, kurt, n = _moments(returns)
    if n < 3:
        return 0.5
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr + (kurt) / 4.0 * sr * sr))
    z = (sr - benchmark_sr_per_period) * math.sqrt(n - 1.0) / denom
    return float(stats.norm.cdf(z))


def deflated_sharpe_ratio(
    returns: np.ndarray,
    *,
    n_trials: int,
    periods_per_year: float,
    trial_sharpe_std: float | None = None,
    confidence: float = 0.95,
) -> DeflatedSharpeResult:
    """Deflated Sharpe: PSR where the benchmark is the EXPECTED MAXIMUM Sharpe
    of `n_trials` zero-skill trials, not zero. This is the number to cite for
    any best-of-family result.

    `trial_sharpe_std`: dispersion of per-trial Sharpe estimates (per period).
    When unknown, a conservative default of 1/sqrt(n_obs) per-period is used
    (the sampling std of a single zero-skill Sharpe estimate), which is the
    right scale for "the trials were noise".
    """
    sr, skew, kurt, n = _moments(returns)
    ppy = periods_per_year
    if n < 3:
        return DeflatedSharpeResult(0.0, 0.5, 0.0, n_trials, int(n), skew, kurt, ppy, False)

    if trial_sharpe_std is None:
        trial_sharpe_std = 1.0 / math.sqrt(n)     # per-period sampling noise
    benchmark = expected_max_sharpe(n_trials, trial_sharpe_std)
    prob = probabilistic_sharpe_ratio(returns, benchmark, ppy)
    return DeflatedSharpeResult(
        observed_sharpe_ann=sr * math.sqrt(ppy),
        deflated_prob=prob,
        expected_max_sharpe_ann=benchmark * math.sqrt(ppy),
        n_trials=n_trials,
        n_obs=int(n),
        skew=skew,
        excess_kurtosis=kurt,
        periods_per_year=ppy,
        passed=prob >= confidence,
    )


def deflated_sharpe_from_trials(
    returns: np.ndarray,
    trial_sharpes_ann: list[float],
    *,
    periods_per_year: float,
    confidence: float = 0.95,
) -> DeflatedSharpeResult:
    """Convenience: estimate `trial_sharpe_std` from the family's recorded
    annualized Sharpes (experiment registry) and deflate. This is the path the
    CLI uses — the dispersion of what you actually tried is the best estimate
    of how lucky the winner could be."""
    n_trials = max(1, len(trial_sharpes_ann))
    if len(trial_sharpes_ann) >= 2:
        std_ann = float(np.std(trial_sharpes_ann, ddof=1))
        std_per_period = std_ann / math.sqrt(periods_per_year)
    else:
        std_per_period = None
    return deflated_sharpe_ratio(
        returns, n_trials=n_trials, periods_per_year=periods_per_year,
        trial_sharpe_std=std_per_period, confidence=confidence,
    )
