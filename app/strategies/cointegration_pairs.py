"""Cointegration pair strategy with rolling re-estimation.

Extends the z-score strategy with:
  * periodic re-estimation of (beta, alpha) on a trailing window
  * cointegration health checks — the pair is disabled after several
    consecutive refits with a deteriorated p-value
  * dynamic lookback derived from the spread half-life (~5x half-life)
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from pydantic import BaseModel

from app.core.logging import get_logger
from app.core.types import SignalAction
from app.research.cointegration import cointegration_test
from app.research.pair_selection import SelectedPair
from app.strategies.base import PairSignal, PositionContext, StrategyInfo
from app.strategies.pairs_zscore import ZScoreConfig, ZScorePairStrategy

log = get_logger(__name__)


class CointegrationStrategyConfig(BaseModel):
    zscore: ZScoreConfig = ZScoreConfig()
    refit_every_bars: int = 96
    refit_window_bars: int = 2000
    invalid_pvalue: float = 0.10
    max_invalid_refits: int = 3
    lookback_half_life_mult: float = 5.0
    min_lookback_bars: int = 50
    max_lookback_bars: int = 500


class CointegrationPairStrategy(ZScorePairStrategy):
    info = StrategyInfo("cointegration_pairs", "1.0")

    def __init__(self, pair: SelectedPair, config: CointegrationStrategyConfig | None = None) -> None:
        self.cfg = config or CointegrationStrategyConfig()
        super().__init__(pair, self.cfg.zscore)
        self._bars_since_refit = 0
        self._invalid_refits = 0
        self._apply_half_life(pair.half_life)

    def _apply_half_life(self, half_life: float) -> None:
        if np.isfinite(half_life) and half_life > 0:
            dynamic = int(half_life * self.cfg.lookback_half_life_mult)
            self.lookback = int(np.clip(dynamic, self.cfg.min_lookback_bars, self.cfg.max_lookback_bars))
            self.max_holding = self._holding_budget(half_life)

    def _refit(self, i: int, log_a: np.ndarray, log_b: np.ndarray) -> bool:
        """Re-estimate the relationship. Returns False if the pair should be disabled."""
        start = max(0, i + 1 - self.cfg.refit_window_bars)
        window_a, window_b = log_a[start : i + 1], log_b[start : i + 1]
        try:
            result = cointegration_test(window_a, window_b)
        except ValueError:
            return True  # not enough data to judge; keep current params
        if result.eg_pvalue > self.cfg.invalid_pvalue or result.beta <= 0:
            self._invalid_refits += 1
            log.info(
                "pair %s refit unhealthy (eg_p=%.3f, beta=%.3f) strike %d/%d",
                self.pair_key, result.eg_pvalue, result.beta,
                self._invalid_refits, self.cfg.max_invalid_refits,
            )
            return self._invalid_refits < self.cfg.max_invalid_refits
        self._invalid_refits = 0
        self.beta, self.alpha = result.beta, result.alpha
        self._apply_half_life(result.half_life)
        return True

    def on_bar(
        self,
        i: int,
        log_a: np.ndarray,
        log_b: np.ndarray,
        ts: datetime,
        ctx: PositionContext,
    ) -> PairSignal | None:
        if self.disabled or i + 1 < self.min_bars:
            return None

        self._bars_since_refit += 1
        if self._bars_since_refit >= self.cfg.refit_every_bars:
            self._bars_since_refit = 0
            if not self._refit(i, log_a, log_b):
                self.disabled = True
                spread = self._spread_window(i, log_a, log_b)
                from app.core.math_utils import zscore_last

                z, mean, std = zscore_last(spread)
                action = SignalAction.DISABLE_PAIR if ctx.position == 0 else SignalAction.STOP_LOSS
                return self._signal(ts, action, z, spread, mean, std,
                                    "cointegration broke down across refits")

        return super().on_bar(i, log_a, log_b, ts, ctx)
