"""PCA residual statistical arbitrage research (Phase 6).

Avellaneda-Lee style: extract the top principal components of standardized
returns as common risk factors; what they cannot explain is the residual
(idiosyncratic) return. Persistent residual moves tend to revert, so assets
are ranked by an s-score built from trailing cumulative residuals.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.decomposition import PCA


@dataclass
class PCAResidualResult:
    residual_returns: pd.DataFrame      # standardized-return residuals
    explained_variance_ratio: np.ndarray
    n_components: int


def standardize_returns(returns: pd.DataFrame) -> pd.DataFrame:
    std = returns.std(ddof=1).replace(0.0, np.nan)
    return ((returns - returns.mean()) / std).dropna(axis=1, how="all").fillna(0.0)


def pca_residual_returns(
    returns: pd.DataFrame,
    n_components: int = 3,
    var_threshold: float = 0.0,
) -> PCAResidualResult:
    """Residuals of standardized returns after removing the top PCA factors.

    With `var_threshold` > 0 the component count is chosen as the smallest k
    whose cumulative explained variance reaches the threshold (Avellaneda-Lee
    use ~55%), instead of a fixed count. A fixed count does not scale: 5
    components soak up most of a 10-name cross-section but leave a 100-name
    cross-section full of sector factor risk masquerading as "residual".
    """
    z = standardize_returns(returns)
    if var_threshold > 0:
        # cap so the factor model never absorbs the whole cross-section
        max_k = max(1, z.shape[1] // 3)
        probe = PCA(n_components=min(max_k, len(z) - 1)).fit(z.to_numpy())
        cumvar = np.cumsum(probe.explained_variance_ratio_)
        n_components = int(np.searchsorted(cumvar, var_threshold) + 1)
    if returns.shape[1] <= n_components:
        raise ValueError(
            f"need more assets ({returns.shape[1]}) than components ({n_components})"
        )
    pca = PCA(n_components=n_components)
    factors = pca.fit_transform(z.to_numpy())
    common = pca.inverse_transform(factors)
    residuals = pd.DataFrame(z.to_numpy() - common, index=z.index, columns=z.columns)
    return PCAResidualResult(
        residual_returns=residuals,
        explained_variance_ratio=pca.explained_variance_ratio_,
        n_components=n_components,
    )


def sector_residual_returns(
    returns: pd.DataFrame,
    sectors: dict[str, str],
    min_sector_size: int = 3,
) -> PCAResidualResult:
    """Residuals of standardized returns after removing each stock's SECTOR
    factor (Avellaneda-Lee's original design used sector ETFs as factors).

    The factor for stock i is the LEAVE-ONE-OUT equal-weight mean of its
    sector peers' standardized returns — excluding the stock itself, so a
    name is never regressed on a portfolio it sits in (with 5-15 names per
    sector, self-inclusion would mechanically shrink every residual).
    Betas are full-window OLS, matching how the PCA loadings are fitted.

    Stocks in sectors smaller than `min_sector_size` (or absent from the
    map) get all-zero residuals, which the OU kappa filter scores 0 —
    excluded from the book rather than traded against a meaningless factor.
    """
    z = standardize_returns(returns)
    residuals = pd.DataFrame(0.0, index=z.index, columns=z.columns)
    for sector in sorted(set(sectors.values())):
        names = [c for c in z.columns if sectors.get(c) == sector]
        if len(names) < min_sector_size:
            continue
        block = z[names].to_numpy()
        row_sum = block.sum(axis=1, keepdims=True)
        loo = (row_sum - block) / (len(names) - 1)       # T x n peers-mean
        var = loo.var(axis=0, ddof=1)
        cov = ((block - block.mean(axis=0)) * (loo - loo.mean(axis=0))).sum(axis=0) / (
            len(block) - 1)
        beta = np.divide(cov, var, out=np.zeros_like(cov), where=var > 0)
        residuals[names] = block - loo * beta
    return PCAResidualResult(
        residual_returns=residuals,
        explained_variance_ratio=np.array([]),
        n_components=0,
    )


def s_scores(residual_returns: pd.DataFrame, window: int = 60) -> pd.Series:
    """Latest s-score per asset: trailing cumulative residual, standardized.

    Positive s-score => the asset has outperformed its factor exposure
    (candidate short); negative => underperformed (candidate long).
    """
    tail = residual_returns.iloc[-window:]
    cumulative = tail.sum()
    scale = tail.std(ddof=1) * np.sqrt(window)
    return (cumulative / scale.replace(0.0, np.nan)).fillna(0.0)


def ou_s_scores(
    residual_returns: pd.DataFrame,
    window: int = 60,
    max_half_life: float = 40.0,
) -> pd.Series:
    """Avellaneda-Lee (2010) s-scores: fit an OU process to each cumulative
    residual and standardize against its EQUILIBRIUM distribution.

    The cumulative residual X_t is fitted as AR(1): X_{t+1} = a + b·X_t + xi.
    Mean reversion requires 0 < b < 1; the s-score is

        s = (X_T - m) / sigma_eq,   m = a/(1-b),  sigma_eq = std(xi)/sqrt(1-b^2)

    Assets whose residual is NOT mean-reverting (b outside (0,1)) or reverts
    too slowly (half-life -ln2/ln b > max_half_life bars) score 0 — fading a
    residual with no force pulling it back is how stat-arb books bleed. This
    is the kappa filter from the original paper.
    """
    tail = residual_returns.iloc[-window:]
    cumulative = tail.cumsum()
    scores: dict[str, float] = {}
    for col in cumulative.columns:
        x = cumulative[col].to_numpy(dtype=float)
        scores[col] = 0.0
        if len(x) < 10 or not np.all(np.isfinite(x)):
            continue
        x0, x1 = x[:-1], x[1:]
        var0 = float(np.var(x0, ddof=1))
        if var0 <= 0:
            continue
        b = float(np.cov(x0, x1, ddof=1)[0, 1] / var0)
        if not 0.0 < b < 1.0:
            continue
        half_life = float(np.log(2.0) / -np.log(b))
        if max_half_life > 0 and half_life > max_half_life:
            continue
        a = float(x1.mean() - b * x0.mean())
        xi = x1 - a - b * x0
        sigma_eq = float(np.std(xi, ddof=1) / np.sqrt(1.0 - b * b))
        if sigma_eq <= 0 or not np.isfinite(sigma_eq):
            continue
        m = a / (1.0 - b)
        scores[col] = float((x[-1] - m) / sigma_eq)
    return pd.Series(scores).reindex(residual_returns.columns).fillna(0.0)
