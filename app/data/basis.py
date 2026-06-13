"""Perp-vs-spot basis for a crypto-futures universe (Path B).

Basis = (perp_price - spot_price) / spot_price. A persistently positive basis
(perp rich to spot) is the cash-and-carry signal: short the perp, long spot,
collect the convergence as the perp pulls back to index at funding/expiry. This
module computes basis from aligned futures and spot close panels and annualizes
it. Research only.
"""

from __future__ import annotations

import pandas as pd


def compute_basis(futures_close: pd.DataFrame, spot_close: pd.DataFrame) -> pd.DataFrame:
    """Per-bar fractional basis (perp - spot)/spot, aligned on common index/cols."""
    common_cols = [c for c in futures_close.columns if c in spot_close.columns]
    if not common_cols:
        return pd.DataFrame()
    idx = futures_close.index.intersection(spot_close.index)
    fut = futures_close.loc[idx, common_cols]
    spot = spot_close.loc[idx, common_cols].replace(0.0, pd.NA)
    return ((fut - spot) / spot).astype(float)


def annualized_basis(basis: pd.DataFrame, bars_per_year: float = 365.0) -> pd.Series:
    """Latest basis per symbol, annualized as a simple carry APR.

    For perps there is no fixed expiry, so we report the *spot* basis level
    annualized over the holding cadence as an indicative carry, not a true
    yield-to-expiry."""
    if basis.empty:
        return pd.Series(dtype=float)
    latest = basis.iloc[-1]
    return (latest * bars_per_year).sort_values(ascending=False)


def basis_summary(basis: pd.DataFrame) -> pd.DataFrame:
    """Per-symbol basis stats: latest, mean, vol (all in bps of spot)."""
    if basis.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "latest_bps": (basis.iloc[-1] * 1e4).round(1),
        "mean_bps": (basis.mean() * 1e4).round(1),
        "vol_bps": (basis.std() * 1e4).round(1),
    }).sort_values("mean_bps", ascending=False)
