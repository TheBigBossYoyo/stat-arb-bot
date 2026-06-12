"""ML alpha basket strategy (Phase 8): learned cross-sectional forecasts.

Gradient-boosted trees on ranked tabular features — the configuration that
actually wins in the asset-pricing ML literature (Gu-Kelly-Xiu 2020) and in
production systematic equity. Deep nets are deliberately NOT used here: a few
thousand daily observations per asset is orders of magnitude short of what
they need, and an overfit net is indistinguishable from alpha in-sample.

Walk-forward by construction: the model is (re)fitted every `retrain_every`
rebalances on the price window the basket engine hands in — which never
extends past the current bar — and training rows only use targets that are
fully realized inside that window. Prediction ranks the latest feature row
and trades the top/bottom fraction, dollar-neutral by default.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.backtesting.basket_engine import WeightFn
from app.core.logging import get_logger
from app.research.ml_features import build_panel

log = get_logger(__name__)


class MLAlphaConfig(BaseModel):
    horizons: list[int] = [12, 48, 96, 336, 672]   # base profile = 15m bars
    vol_windows: list[int] = [48, 96]
    forward_bars: int = 48        # prediction horizon (= rebalance cadence)
    retrain_every: int = 10       # rebalances between refits
    top_frac: float = 0.2         # ENTER the top/bottom quintile of forecasts
    # hold band: a position is kept while its forecast rank stays inside the
    # top/bottom hold_frac. Re-ranking the full book every call churned 3x
    # the turnover for the same signal (-24.6% vs +15% net on us_stocks_50).
    hold_frac: float = 0.35
    gross_target: float = 1.0
    long_only: bool = False
    # tree settings: shallow + regularized; financial signal-to-noise is tiny
    max_iter: int = 200
    max_depth: int = 3
    learning_rate: float = 0.05
    min_train_rows: int = 1000
    random_state: int = 7         # exposed for seed-sensitivity checks
    # extended feature block: beta/idio-vol plus, when the engine provides
    # aux OHLCV frames, volume, overnight/intraday split and range vol —
    # information a close-only momentum signal cannot see. False reproduces
    # the legacy feature set (the documented +28.5% / Sharpe 0.84 baseline).
    orthogonal_features: bool = False
    # train on (and predict) the component of return ORTHOGONAL to the two
    # longest-horizon return ranks: the sleeve's documented failure mode was
    # riding the same 12-1 factor as xsec_momentum (Sharpe 0.84 standalone
    # yet it diluted the ensemble 1.05 -> 0.95)
    momentum_neutral: bool = False


class MLAlphaWeights:
    """Stateful WeightFn: periodic refit, prediction every rebalance."""

    wants_aux = True   # the engine hands us volume/open/high/low windows

    def __init__(self, config: MLAlphaConfig | None = None) -> None:
        self.cfg = config or MLAlphaConfig()
        self._model = None
        self._calls = 0
        self._held: dict[str, int] = {}    # symbol -> +1 long / -1 short
        self._last_update_ts: pd.Timestamp | None = None
        self._fitted_features: list[str] | None = None

    def _neutralize_names(self) -> list[str]:
        """The two longest-horizon return features = where 12-1-style momentum
        lives inside the fit window (the true 252+21-bar characteristic does
        not fit: it would eat the whole 300-bar daily window as warmup)."""
        return [f"ret_{h}" for h in sorted(self.cfg.horizons)[-2:]]

    def _fit(self, X: np.ndarray, y: np.ndarray):
        from sklearn.ensemble import HistGradientBoostingRegressor

        cfg = self.cfg
        model = HistGradientBoostingRegressor(
            max_iter=cfg.max_iter, max_depth=cfg.max_depth,
            learning_rate=cfg.learning_rate, l2_regularization=1.0,
            random_state=cfg.random_state,
        )
        return model.fit(X, y)

    def _book_weights(self, zero: pd.Series) -> pd.Series:
        cfg = self.cfg
        longs = [s for s, side in self._held.items() if side == 1 and s in zero.index]
        shorts = [s for s, side in self._held.items() if side == -1 and s in zero.index]
        weights = zero.copy()
        if longs:
            weights[longs] = cfg.gross_target / 2 / len(longs)
        if shorts:
            weights[shorts] = -cfg.gross_target / 2 / len(shorts)
        return weights

    def __call__(
        self, close_window: pd.DataFrame, aux: dict[str, pd.DataFrame] | None = None
    ) -> pd.Series:
        cfg = self.cfg
        zero = pd.Series(0.0, index=close_window.columns)
        # the book only updates once per forecast horizon, however often the
        # caller rebalances: forecasting 5-day returns and re-trading daily
        # tripled turnover for the same signal (-24.6% vs +28.5% net)
        if self._last_update_ts is not None and self._last_update_ts in close_window.index:
            bars_since = len(close_window.loc[self._last_update_ts:]) - 1
            if bars_since < cfg.forward_bars:
                return self._book_weights(zero)
        panel = build_panel(
            close_window, cfg.horizons, cfg.vol_windows, cfg.forward_bars,
            aux=aux if cfg.orthogonal_features else None,
            neutralize_features=self._neutralize_names() if cfg.momentum_neutral else None,
            extended=cfg.orthogonal_features,
        )
        if panel is None or len(panel.X) < cfg.min_train_rows:
            return zero
        if (self._model is None or self._calls % cfg.retrain_every == 0
                or panel.feature_names != self._fitted_features):
            self._model = self._fit(panel.X, panel.y)
            self._fitted_features = panel.feature_names
        self._calls += 1
        self._last_update_ts = close_window.index[-1]
        raw = self._model.predict(panel.latest)
        if cfg.momentum_neutral and panel.neutralize_idx:
            # belt and braces: the target was residualized at TRAIN time, but
            # the trees can still leak momentum through correlated features —
            # residualize the live scores against the same characteristics
            chars = panel.latest[:, panel.neutralize_idx]
            coef, *_ = np.linalg.lstsq(chars, raw - raw.mean(), rcond=None)
            raw = raw - chars @ coef
        scores = pd.Series(raw, index=panel.assets)
        self._update_book(scores.rank(pct=True))
        return self._book_weights(zero)

    def _update_book(self, ranks: pd.Series) -> None:
        """Entry at top_frac extremes, exit when the rank leaves the hold band."""
        cfg = self.cfg
        for symbol, side in list(self._held.items()):
            r = float(ranks.get(symbol, 0.5))
            if (side == 1 and r < 1.0 - cfg.hold_frac) or (side == -1 and r > cfg.hold_frac):
                del self._held[symbol]
        top_k = max(2, round(cfg.top_frac * len(ranks)))
        longs = sum(1 for side in self._held.values() if side == 1)
        shorts = sum(1 for side in self._held.values() if side == -1)
        candidates = ranks[~ranks.index.isin(self._held)]
        for symbol, r in candidates.sort_values(ascending=False).items():
            if longs >= top_k or r < 1.0 - cfg.top_frac:
                break
            self._held[symbol] = 1
            longs += 1
        if not cfg.long_only:
            for symbol, r in candidates.sort_values().items():
                if shorts >= top_k or r > cfg.top_frac:
                    break
                if symbol not in self._held:
                    self._held[symbol] = -1
                    shorts += 1
        if cfg.long_only:
            self._held = {s: side for s, side in self._held.items() if side == 1}


def make_ml_alpha_weight_fn(config: MLAlphaConfig | None = None) -> WeightFn:
    return MLAlphaWeights(config)
