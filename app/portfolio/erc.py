"""Equal Risk Contribution (a.k.a. true risk parity).

Inverse-volatility weighting (what the current ensemble calls "risk parity")
equalizes risk contributions ONLY when assets are uncorrelated. With correlated
sleeves it over-allocates to a cluster of similar sleeves. ERC solves for the
weights where every asset contributes the same share of total portfolio
variance, using the correlations the inverse-vol shortcut ignores (audit W-11).

Cyclical-coordinate-descent solver (Spinu 2013) — converges quickly for the
small covariance matrices we allocate over and needs no external optimizer.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def erc_weights(cov: pd.DataFrame, *, max_iter: int = 1000, tol: float = 1e-10) -> pd.Series:
    """Equal-risk-contribution long-only weights (sum to 1) for covariance `cov`."""
    cols = list(cov.columns)
    n = len(cols)
    if n == 1:
        return pd.Series([1.0], index=cols)
    Sigma = cov.to_numpy(dtype=float)
    # guard against singular / non-positive diagonals
    d = np.diag(Sigma).copy()
    d[d <= 0] = np.nanmean(d[d > 0]) if np.any(d > 0) else 1.0
    w = 1.0 / np.sqrt(d)

    # Spinu (2013) cyclical coordinate descent on the log-barrier objective
    # f(w) = 1/2 w'Sigma w - (1/n) sum ln(w_i). The minimizer is the ERC
    # portfolio up to scale, so we iterate UNNORMALIZED and normalize once at
    # the end (normalizing each sweep breaks the fixed point).
    budget = 1.0 / n
    Sigma_w = Sigma @ w
    for _ in range(max_iter):
        w_prev = w.copy()
        for i in range(n):
            a = Sigma[i, i]
            if a <= 0:
                continue
            beta = Sigma_w[i] - w[i] * a            # (Sigma w)_i excluding own term
            w_i = (-beta + np.sqrt(beta * beta + 4.0 * a * budget)) / (2.0 * a)
            Sigma_w += Sigma[:, i] * (w_i - w[i])
            w[i] = w_i
        if np.max(np.abs(w - w_prev)) < tol:
            break
    w = np.clip(w, 0.0, None)
    s = w.sum()
    return pd.Series(w / s if s > 0 else np.ones(n) / n, index=cols)


def risk_contributions(cov: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Fractional contribution of each asset to total portfolio variance."""
    w = weights.reindex(cov.columns).fillna(0.0).to_numpy()
    Sigma = cov.to_numpy(dtype=float)
    port_var = float(w @ Sigma @ w)
    if port_var <= 0:
        return pd.Series(0.0, index=cov.columns)
    rc = w * (Sigma @ w) / port_var
    return pd.Series(rc, index=cov.columns)
