"""Multiple-hypothesis corrections for strategy families (audit W-02).

When a research family contains many configurations, the smallest p-value (or
the best Sharpe) is not what it appears. Three complementary tools:

* Bonferroni — control the family-wise error rate (very conservative).
* Benjamini-Hochberg — control the false-discovery rate (the right tool for
  sweep tables: "of the configs I call significant, what fraction are noise?").
* Bootstrap reality check (White 2000 / Hansen SPA flavour) — is the BEST
  strategy's performance better than the best you'd expect from the whole
  family under the null of zero skill, accounting for the search?

Deflated Sharpe (deflated_sharpe.py) is the per-strategy companion; these
operate across a family.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def bonferroni(pvalues: list[float], alpha: float = 0.05) -> list[bool]:
    """True where a hypothesis survives the family-wise Bonferroni threshold."""
    n = len(pvalues)
    if n == 0:
        return []
    thresh = alpha / n
    return [p <= thresh for p in pvalues]


def benjamini_hochberg(pvalues: list[float], alpha: float = 0.10) -> list[bool]:
    """Benjamini-Hochberg FDR control. Returns a rejection mask aligned to the
    INPUT order (True = discovery)."""
    n = len(pvalues)
    if n == 0:
        return []
    order = np.argsort(pvalues)
    ranked = np.asarray(pvalues, dtype=float)[order]
    thresholds = alpha * (np.arange(1, n + 1) / n)
    below = ranked <= thresholds
    keep = np.zeros(n, dtype=bool)
    if below.any():
        kmax = np.max(np.where(below)[0])
        keep[order[: kmax + 1]] = True
    return keep.tolist()


@dataclass
class RealityCheckResult:
    best_strategy: int            # index of the best mean-return strategy
    best_mean_return: float
    p_value: float                # bootstrap p-value accounting for the search
    n_strategies: int
    n_bootstrap: int

    @property
    def significant(self) -> bool:
        return self.p_value < 0.05


def bootstrap_reality_check(
    returns_matrix: np.ndarray,
    *,
    n_bootstrap: int = 2000,
    block_size: int = 10,
    seed: int = 7,
) -> RealityCheckResult:
    """White's Reality Check via the stationary/block bootstrap.

    `returns_matrix`: shape (T, S) — per-period returns of S candidate
    strategies over the SAME T periods. Tests H0: the best strategy has no
    positive expected return once the search over S strategies is accounted
    for. A low p-value means the winner beats what data-snooping alone yields.
    """
    R = np.asarray(returns_matrix, dtype=float)
    if R.ndim != 2 or R.shape[0] < block_size + 1 or R.shape[1] == 0:
        return RealityCheckResult(0, 0.0, 1.0, R.shape[1] if R.ndim == 2 else 0, n_bootstrap)
    T, S = R.shape
    rng = np.random.default_rng(seed)
    means = R.mean(axis=0)
    best = int(np.argmax(means))
    # statistic per strategy: sqrt(T) * mean (demeaned under H0 by subtracting
    # its own mean in the bootstrap world)
    V_obs = np.sqrt(T) * means.max()

    n_blocks = int(np.ceil(T / block_size))
    V_boot = np.empty(n_bootstrap)
    for b in range(n_bootstrap):
        starts = rng.integers(0, T, size=n_blocks)
        idx = np.concatenate([
            np.arange(s, s + block_size) % T for s in starts
        ])[:T]
        sample = R[idx]                            # (T, S)
        boot_means = sample.mean(axis=0) - means   # recenter: H0 of zero skill
        V_boot[b] = np.sqrt(T) * boot_means.max()
    p_value = float((V_boot >= V_obs).mean())
    return RealityCheckResult(
        best_strategy=best, best_mean_return=float(means[best]),
        p_value=p_value, n_strategies=S, n_bootstrap=n_bootstrap,
    )
