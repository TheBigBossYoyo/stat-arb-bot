"""Long-only ML alpha sleeve for Trading 212 Invest/ISA (Path A).

The flagship's ML sleeve is the momentum-neutral gradient-boosted forecaster
(`ml_alpha` with `momentum_neutral=True`). For a long-only book we keep the same
learned cross-sectional forecast but trade only the LONG leg: buy the names the
model ranks highest, hold cash instead of shorting the lowest. A regime trend
filter can scale the whole sleeve toward cash in a downtrend.

This is a thin, honest wrapper over the existing `ml_alpha` machinery — no new
model, no new claim. The only change is direction (long-only) and the optional
risk-off cash scalar.
"""

from __future__ import annotations

import pandas as pd

from app.strategies.long_only_momentum import RegimeFilterConfig, regime_scalar
from app.strategies.ml_alpha import MLAlphaConfig, make_ml_alpha_weight_fn


class LongOnlyMLAlpha:
    """Stateful long-only ML sleeve. Wraps the long-only ml_alpha weight fn and
    applies an optional book-level regime scalar. Re-exposes `wants_aux` so the
    basket engine keeps feeding OHLCV windows to the underlying model."""

    wants_aux = True

    def __init__(self, config: MLAlphaConfig | None = None,
                 regime: RegimeFilterConfig | None = None) -> None:
        cfg = config or MLAlphaConfig()
        # force the directional, momentum-neutral long-only configuration
        cfg = cfg.model_copy(update={"long_only": True, "momentum_neutral": True})
        self._inner = make_ml_alpha_weight_fn(cfg)
        self.regime = regime or RegimeFilterConfig(enabled=False)

    def __call__(self, close_window: pd.DataFrame, aux: dict | None = None) -> pd.Series:
        weights = self._inner(close_window, aux=aux)
        # long-only guard: the underlying is already long-only, but never let a
        # negative weight through to a no-shorting venue.
        weights = weights.clip(lower=0.0)
        return weights * regime_scalar(close_window, self.regime)


def make_long_only_ml_alpha(config: MLAlphaConfig | None = None,
                            regime: RegimeFilterConfig | None = None) -> LongOnlyMLAlpha:
    return LongOnlyMLAlpha(config, regime)
