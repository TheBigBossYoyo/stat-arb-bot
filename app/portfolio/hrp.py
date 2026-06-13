"""Hierarchical Risk Parity (Lopez de Prado 2016).

HRP avoids the instability of mean-variance optimization (which inverts a noisy
covariance matrix and concentrates in whatever the noise says is best) by:

1. clustering assets on a correlation-distance tree,
2. quasi-diagonalizing the covariance so similar assets sit together,
3. recursive bisection, splitting risk budget between clusters by inverse
   cluster variance.

It needs no matrix inversion and no return forecasts, which is exactly right
for allocating across a handful of strategy sleeves whose covariance is
estimated on few, noisy observations (audit W-11).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.spatial.distance import squareform


def _corr_distance(corr: pd.DataFrame) -> np.ndarray:
    d = np.sqrt(np.clip((1.0 - corr.to_numpy()) / 2.0, 0.0, 1.0))
    d = (d + d.T) / 2.0            # enforce exact symmetry for squareform
    np.fill_diagonal(d, 0.0)
    return squareform(d, checks=False)


def _quasi_diag(link: np.ndarray) -> list[int]:
    """Order leaves so that similar assets sit adjacent (Lopez de Prado 2016).

    `link` is a scipy linkage matrix over `n_leaves` original observations;
    cluster ids >= n_leaves refer to merged nodes link[id - n_leaves].
    """
    link = link.astype(int)
    n_leaves = link.shape[0] + 1
    order = [link[-1, 0], link[-1, 1]]
    while any(i >= n_leaves for i in order):
        expanded: list[int] = []
        for i in order:
            if i < n_leaves:
                expanded.append(i)
            else:
                expanded.extend([link[i - n_leaves, 0], link[i - n_leaves, 1]])
        order = expanded
    return [int(i) for i in order]


def _cluster_var(cov: pd.DataFrame, items: list) -> float:
    sub = cov.loc[items, items]
    ivp = 1.0 / np.diag(sub.values)
    ivp /= ivp.sum()
    return float(ivp @ sub.values @ ivp)


def hrp_weights(returns: pd.DataFrame) -> pd.Series:
    """HRP weights (sum to 1, all >= 0) from a returns frame (cols = assets)."""
    cols = list(returns.columns)
    if len(cols) == 1:
        return pd.Series([1.0], index=cols)
    cov = returns.cov()
    corr = returns.corr().fillna(0.0)
    dist = _corr_distance(corr)
    link = linkage(dist, method="single")
    sort_ix = _quasi_diag(link)
    ordered = [cols[i] for i in sort_ix] or cols

    weights = pd.Series(1.0, index=ordered)
    clusters = [ordered]
    while clusters:
        clusters = [
            c[j:k] for c in clusters
            for j, k in ((0, len(c) // 2), (len(c) // 2, len(c)))
            if len(c) > 1 and k > j
        ]
        for i in range(0, len(clusters), 2):
            if i + 1 >= len(clusters):
                continue
            left, right = clusters[i], clusters[i + 1]
            var_l, var_r = _cluster_var(cov, left), _cluster_var(cov, right)
            alpha = 1.0 - var_l / (var_l + var_r) if (var_l + var_r) > 0 else 0.5
            weights[left] *= alpha
            weights[right] *= 1.0 - alpha
    return (weights / weights.sum()).reindex(cols).fillna(0.0)
