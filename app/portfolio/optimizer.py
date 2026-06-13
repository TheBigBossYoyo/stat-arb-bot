"""Allocation engine: covariance shrinkage + a menu of allocators.

A single entry point, `allocate(returns, mode)`, returns long-only weights that
sum to 1 across whatever it is fed (strategy sleeves or assets). Modes:

* equal           — 1/N (the humble benchmark every fancier method must beat)
* inverse_vol     — the current ensemble's method (risk parity only if uncorrelated)
* erc             — equal risk contribution, using correlations (true risk parity)
* hrp             — hierarchical risk parity (no matrix inversion; robust)
* min_variance    — global minimum-variance with Ledoit-Wolf shrinkage
* sharpe_shrunk   — shrinkage-mean / shrinkage-cov, long-only, capped (conservative)

Covariance is Ledoit-Wolf shrunk toward a constant-correlation target by
default — raw sample covariance on few observations is exactly the noise that
makes mean-variance blow up (audit W-11). NONE of these is wired in as the
ensemble default: per the acceptance criteria, a new allocator ships as default
only after beating inverse-vol out-of-sample net of turnover.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.portfolio.erc import erc_weights
from app.portfolio.hrp import hrp_weights

MODES = ("equal", "inverse_vol", "erc", "hrp", "min_variance", "sharpe_shrunk")


def ledoit_wolf_cov(returns: pd.DataFrame) -> pd.DataFrame:
    """Ledoit-Wolf shrinkage toward a constant-correlation target.

    Falls back to the sample covariance when sklearn's estimator is unavailable
    or the sample is too short. Constant-correlation target preserves the
    individual variances while shrinking the off-diagonal correlations, which
    is what stabilizes small-sample sleeve covariance.
    """
    cols = list(returns.columns)
    X = returns.dropna()
    if len(X) < 3 or len(cols) == 1:
        return returns.cov()
    sample = np.cov(X.to_numpy(), rowvar=False)
    var = np.diag(sample)
    std = np.sqrt(np.clip(var, 1e-18, None))
    corr = sample / np.outer(std, std)
    n = len(cols)
    mask = ~np.eye(n, dtype=bool)
    mean_corr = corr[mask].mean() if n > 1 else 0.0
    target_corr = np.full((n, n), mean_corr)
    np.fill_diagonal(target_corr, 1.0)
    target = target_corr * np.outer(std, std)
    # shrinkage intensity (simplified Ledoit-Wolf): heavier with fewer obs
    t = len(X)
    shrink = float(np.clip(n / (n + t), 0.0, 1.0))
    shrunk = shrink * target + (1.0 - shrink) * sample
    return pd.DataFrame(shrunk, index=cols, columns=cols)


def _inverse_vol(returns: pd.DataFrame) -> pd.Series:
    vol = returns.std(ddof=1).replace(0.0, np.nan)
    inv = (1.0 / vol).fillna(0.0)
    s = inv.sum()
    return inv / s if s > 0 else pd.Series(1.0 / len(inv), index=inv.index)


def _min_variance(cov: pd.DataFrame) -> pd.Series:
    cols = list(cov.columns)
    try:
        inv = np.linalg.pinv(cov.to_numpy())
    except np.linalg.LinAlgError:
        return pd.Series(1.0 / len(cols), index=cols)
    ones = np.ones(len(cols))
    w = inv @ ones
    w = np.clip(w, 0.0, None)            # long-only
    s = w.sum()
    return pd.Series(w / s if s > 0 else ones / len(cols), index=cols)


def _sharpe_shrunk(returns: pd.DataFrame, cov: pd.DataFrame, max_weight: float) -> pd.Series:
    cols = list(cov.columns)
    mu = returns.mean()
    # shrink means toward the cross-sectional mean (James-Stein flavour)
    grand = mu.mean()
    mu_shrunk = 0.5 * mu + 0.5 * grand
    try:
        inv = np.linalg.pinv(cov.to_numpy())
    except np.linalg.LinAlgError:
        return _inverse_vol(returns)
    w = inv @ mu_shrunk.to_numpy()
    w = np.clip(w, 0.0, None)
    s = w.sum()
    w = w / s if s > 0 else np.ones(len(cols)) / len(cols)
    w = np.clip(w, 0.0, max_weight)
    s = w.sum()
    return pd.Series(w / s if s > 0 else np.ones(len(cols)) / len(cols), index=cols)


def allocate(
    returns: pd.DataFrame,
    mode: str = "inverse_vol",
    *,
    max_weight: float = 1.0,
    shrink_cov: bool = True,
) -> pd.Series:
    """Long-only weights (sum to 1) over the columns of `returns`."""
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; choose from {MODES}")
    cols = list(returns.columns)
    if not cols:
        return pd.Series(dtype=float)
    if len(cols) == 1:
        return pd.Series([1.0], index=cols)

    if mode == "equal":
        w = pd.Series(1.0 / len(cols), index=cols)
    elif mode == "inverse_vol":
        w = _inverse_vol(returns)
    else:
        cov = ledoit_wolf_cov(returns) if shrink_cov else returns.cov()
        if mode == "erc":
            w = erc_weights(cov)
        elif mode == "hrp":
            w = hrp_weights(returns)
        elif mode == "min_variance":
            w = _min_variance(cov)
        elif mode == "sharpe_shrunk":
            w = _sharpe_shrunk(returns, cov, max_weight)
    if max_weight < 1.0:
        w = w.clip(upper=max_weight)
        w = w / w.sum() if w.sum() > 0 else pd.Series(1.0 / len(cols), index=cols)
    return w.reindex(cols).fillna(0.0)
