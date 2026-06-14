"""Long-only ensemble for Trading 212 Invest/ISA (Path A).

Combines the three long-only sleeves — cross-sectional momentum, time-series
momentum and the momentum-neutral ML alpha — into one cash-aware book. The
combination uses the same risk-parity ensemble as the flagship (inverse-vol
sleeve weighting with a trailing-performance gate), but every sleeve is
LONG-ONLY: the combined book is always >= 0 per name and its gross never
exceeds 1.0, so it holds cash, never borrows, never shorts.

The market-regime trend filter is applied ONCE at the book level here (sleeves
are built with their own regime filter disabled) so the whole book de-risks to
cash together in a downtrend, rather than each sleeve de-risking independently.

`build_long_only_ensemble` returns a stateful weight fn the basket / long-only
engine can run directly.
"""

from __future__ import annotations

import pandas as pd

from app.strategies.ensemble import EnsembleConfig, RiskParityEnsemble
from app.strategies.long_only_ml_alpha import make_long_only_ml_alpha
from app.strategies.long_only_momentum import (
    LongOnlyTSMOMConfig,
    LongOnlyXSMOMConfig,
    RegimeFilterConfig,
    make_long_only_tsmom_weight_fn,
    make_long_only_xsmom_weight_fn,
    regime_scalar,
)
from app.strategies.ml_alpha import MLAlphaConfig
from app.strategies.weight_smoothing import SmoothingConfig, WeightSmoother

LONG_ONLY_SLEEVES = ("long_only_xsec_momentum", "long_only_tsmom", "long_only_ml_alpha")


class LongOnlyEnsemble:
    """Risk-parity long-only ensemble with a single book-level regime filter and
    a hard long-only / gross-cap guard on the combined book.

    Target-weight smoothing (Phase 1) is applied ONCE at the book level — the
    sleeves are built with smoothing OFF (like the regime filter) so the combined
    book is smoothed coherently rather than each sleeve damping independently."""

    wants_aux = True

    def __init__(self, ensemble: RiskParityEnsemble, regime: RegimeFilterConfig,
                 gross_cap: float = 1.0, max_position: float = 0.20,
                 smoothing: SmoothingConfig | None = None) -> None:
        self.ensemble = ensemble
        self.regime = regime
        self.gross_cap = gross_cap
        self.max_position = max_position
        self.smoother = WeightSmoother(smoothing, max_weight=max_position,
                                       gross_target=gross_cap)

    def __call__(self, close_window: pd.DataFrame, aux: dict | None = None) -> pd.Series:
        weights = self.ensemble(close_window, aux=aux)
        weights = weights.clip(lower=0.0, upper=self.max_position)  # no shorts, per-name cap
        gross = float(weights.sum())
        if gross > self.gross_cap > 0:           # never lever; cash absorbs the rest
            weights = weights * (self.gross_cap / gross)
        weights = weights * regime_scalar(close_window, self.regime)
        return self.smoother.smooth(weights)

    def sleeve_allocations(self) -> dict[str, float]:
        return self.ensemble.sleeve_allocations()

    @property
    def history(self):
        return self.ensemble.history


def build_long_only_ensemble(
    *,
    sleeves: list[str] | None = None,
    xsmom: LongOnlyXSMOMConfig | None = None,
    tsmom: LongOnlyTSMOMConfig | None = None,
    ml: MLAlphaConfig | None = None,
    ensemble_config: EnsembleConfig | None = None,
    regime: RegimeFilterConfig | None = None,
    gross_cap: float = 1.0,
    max_position: float = 0.20,
    smoothing: SmoothingConfig | None = None,
    record_history: bool = False,
) -> LongOnlyEnsemble:
    """Assemble the long-only ensemble. Sleeves are built with their own regime
    filter AND smoothing OFF; the book-level regime filter and smoother (passed
    here) govern de-risking and rebalance damping for the combined book."""
    names = sleeves or list(LONG_ONLY_SLEEVES)
    off = RegimeFilterConfig(enabled=False)
    no_smooth = SmoothingConfig()   # sleeves never smooth; the book does (once)
    builders = {
        "long_only_xsec_momentum": lambda: make_long_only_xsmom_weight_fn(
            (xsmom or LongOnlyXSMOMConfig()).model_copy(
                update={"regime": off, "smoothing": no_smooth})),
        "long_only_tsmom": lambda: make_long_only_tsmom_weight_fn(
            (tsmom or LongOnlyTSMOMConfig()).model_copy(
                update={"regime": off, "smoothing": no_smooth})),
        "long_only_ml_alpha": lambda: make_long_only_ml_alpha(
            ml or MLAlphaConfig(), regime=off),
    }
    unknown = [n for n in names if n not in builders]
    if unknown:
        raise ValueError(f"unknown long-only sleeve(s) {unknown}; choose from {list(builders)}")
    sleeve_fns = {n: builders[n]() for n in names}
    ens = RiskParityEnsemble(sleeve_fns, ensemble_config or EnsembleConfig(),
                             record_history=record_history)
    return LongOnlyEnsemble(ens, regime or RegimeFilterConfig(),
                            gross_cap=gross_cap, max_position=max_position,
                            smoothing=smoothing)
