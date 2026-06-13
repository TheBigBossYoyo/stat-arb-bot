"""Concentration fixes — composable weight transforms (Phase 1).

The goal is NOT to delete the winning month (that just cuts return and proves
nothing). It is to make the *same* edge arrive more evenly: spread risk across
names, damp single-bar spikes, and de-risk when the market is turbulent. Each
fix is a transform on a weight function (or an ensemble config tweak), so it can
be layered onto any basket/ensemble book and re-validated through the existing
walk-forward + concentration gate.

A fix is kept only if it lowers concentration *without* breaking OOS Sharpe — the
acceptance criterion the comparison command enforces (see compare-concentration
-fixes). Fixes are deliberately small, transparent and reversible.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

WeightTransform = Callable[[pd.Series, pd.DataFrame], pd.Series]


def _renorm(weights: pd.Series, target_gross: float) -> pd.Series:
    gross = float(weights.abs().sum())
    if gross > 0 and target_gross > 0:
        return weights * (target_gross / gross)
    return weights


def cap_per_asset(max_weight: float, max_iter: int = 100) -> WeightTransform:
    """Water-fill every |weight| down to `max_weight`, redistributing the excess
    across the under-cap names so gross is preserved *where feasible*.

    Directly attacks single-name concentration: a book that loaded 30% into one
    winner is forced to spread it. A plain clip-then-renormalize would re-inflate
    the capped names back over the cap; iterating cap+redistribute makes the cap
    actually bind. If the cap is infeasible (max_weight * n_names < gross), every
    name ends at the cap and the residual gross simply becomes cash."""
    def transform(weights: pd.Series, _close: pd.DataFrame) -> pd.Series:
        signs = np.sign(weights)
        mag = weights.abs().astype(float)
        for _ in range(max_iter):
            over = mag > max_weight + 1e-12
            if not over.any():
                break
            excess = float((mag[over] - max_weight).sum())
            mag[over] = max_weight
            room = (max_weight - mag).clip(lower=0.0)
            room[over] = 0.0
            total_room = float(room.sum())
            if excess <= 1e-12 or total_room <= 1e-12:
                break                              # infeasible: cap binds, rest is cash
            mag = mag + room / total_room * excess
        return signs * mag
    return transform


def winsorize_weights(quantile: float = 0.9) -> WeightTransform:
    """Winsorize the weight magnitudes at `quantile` (pull extreme bets in to
    the cap implied by the distribution), preserving gross. Softer than a hard
    per-asset cap — the cap floats with how concentrated the book already is."""
    def transform(weights: pd.Series, _close: pd.DataFrame) -> pd.Series:
        nz = weights[weights != 0].abs()
        if len(nz) < 3:
            return weights
        cap = float(np.quantile(nz, quantile))
        gross = float(weights.abs().sum())
        return _renorm(weights.clip(-cap, cap), gross)
    return transform


def cap_per_sector(sectors: dict[str, str], max_sector_gross: float) -> WeightTransform:
    """Scale down any sector whose aggregate gross exposure exceeds
    `max_sector_gross` (fraction of book). Stops a single sector carrying the
    whole book even when no single name does."""
    def transform(weights: pd.Series, _close: pd.DataFrame) -> pd.Series:
        out = weights.copy()
        by_sector: dict[str, list[str]] = {}
        for sym in weights.index:
            by_sector.setdefault(sectors.get(sym, "other"), []).append(sym)
        for names in by_sector.values():
            sec_gross = float(weights[names].abs().sum())
            if sec_gross > max_sector_gross > 0:
                out[names] = weights[names] * (max_sector_gross / sec_gross)
        return out
    return transform


def market_vol_scalar(vol_window: int, target_vol: float) -> WeightTransform:
    """De-risk the whole book when recent equal-weight market volatility exceeds
    `target_vol` (Daniel-Moskowitz crash-protection logic, applied at the book
    level). Stateless — reads the close window the engine already passes. <=1x:
    de-risking only, never levers up."""
    def transform(weights: pd.Series, close: pd.DataFrame) -> pd.Series:
        if vol_window <= 0 or target_vol <= 0 or len(close) <= vol_window:
            return weights
        mkt = np.log(close).diff().mean(axis=1).iloc[-vol_window:]
        vol = float(mkt.std(ddof=1)) if len(mkt) > 1 else 0.0
        if vol <= 1e-12:
            return weights
        return weights * float(min(1.0, target_vol / vol))
    return transform


@dataclass
class EwmaSmoother:
    """Stateful: blend each new target with the previous one,
    `w = alpha*new + (1-alpha)*prev`. Smoother rebalancing spreads turnover —
    and therefore PnL — across more bars, which is exactly what shrinks the
    best-5%-of-days share. alpha=1 is a no-op; lower = smoother."""

    alpha: float = 0.5
    _prev: pd.Series | None = field(default=None, repr=False)

    def __call__(self, weights: pd.Series, _close: pd.DataFrame) -> pd.Series:
        if self._prev is None:
            self._prev = weights.copy()
            return weights
        prev = self._prev.reindex(weights.index).fillna(0.0)
        blended = self.alpha * weights + (1.0 - self.alpha) * prev
        self._prev = blended.copy()
        return blended


class WrappedWeightFn:
    """Wrap a (possibly aux-consuming, possibly stateful) weight fn with an
    ordered list of transforms. Forwards `aux` when the inner fn wants it and
    re-exposes `wants_aux` so the basket engine keeps feeding aux frames."""

    def __init__(self, inner: object, transforms: list[WeightTransform]):
        self.inner = inner
        self.transforms = transforms
        self.wants_aux = bool(getattr(inner, "wants_aux", False))

    def __call__(self, close_window: pd.DataFrame, aux: dict | None = None) -> pd.Series:
        if getattr(self.inner, "wants_aux", False):
            weights = self.inner(close_window, aux=aux)
        else:
            weights = self.inner(close_window)
        for transform in self.transforms:
            weights = transform(weights, close_window)
        return weights

    def sleeve_allocations(self):  # pragma: no cover - passthrough for ensembles
        return self.inner.sleeve_allocations()


@dataclass(frozen=True)
class FixSpec:
    """A named concentration fix: ensemble-config overrides plus a factory that
    builds the (fresh, possibly stateful) transform list for one run."""

    name: str
    description: str
    config_overrides: dict = field(default_factory=dict)
    transforms: Callable[[dict], list[WeightTransform]] = field(
        default=lambda ctx: [], repr=False)


def default_fix_specs(sectors: dict[str, str] | None = None) -> dict[str, FixSpec]:
    """The catalogue tested by compare-concentration-fixes. `ctx` passed to each
    transform factory carries {"sectors": ...} so sector-aware fixes can build."""
    sectors = sectors or {}
    specs = [
        FixSpec("none", "baseline ensemble (no fix)"),
        FixSpec("cap_asset_15", "cap any single name at 15% gross",
                transforms=lambda ctx: [cap_per_asset(0.15)]),
        FixSpec("winsorize_85", "winsorize weight magnitudes at the 85th pct",
                transforms=lambda ctx: [winsorize_weights(0.85)]),
        FixSpec("smooth_05", "EWMA-smooth target weights (alpha=0.5)",
                transforms=lambda ctx: [EwmaSmoother(0.5)]),
        FixSpec("vol_target_10", "portfolio vol target 10%/yr (de-risk only)",
                config_overrides={"target_vol_pct": 10.0}),
        FixSpec("crash_protect", "book-level market-vol de-risking",
                transforms=lambda ctx: [market_vol_scalar(20, 0.012)]),
        FixSpec("cap_sector_40", "cap any sector at 40% gross",
                transforms=lambda ctx: [cap_per_sector(ctx.get("sectors", {}), 0.40)]),
        FixSpec("combo", "cap_asset 15% + EWMA smooth 0.5 + vol target 10%",
                config_overrides={"target_vol_pct": 10.0},
                transforms=lambda ctx: [cap_per_asset(0.15), EwmaSmoother(0.5)]),
    ]
    return {s.name: s for s in specs}
