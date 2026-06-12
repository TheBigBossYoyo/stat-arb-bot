"""Kalman-filter dynamic hedge ratio pair strategy (Phase 6).

The hedge ratio is tracked online by app.research.kalman.KalmanHedgeFilter.
The tradeable signal is the one-step-ahead innovation, standardized against
the EMPIRICAL std of recent innovations (not the model's assumed variance —
that would make the signal hostage to a mis-specified observation noise r):

    z_t = residual_t / std(residuals over the last `zscore_window` bars)

Safeguards against overreacting to noise:
  * a warmup period before any signal,
  * entries are blocked while beta is outside [beta_min, beta_max] or <= 0
    (an unstable relationship must not be sized off a garbage hedge ratio),
  * the usual stop-z / time-stop machinery.

NOTE: this strategy keeps internal filter state indexed by bar position, so
it requires a GROWING history (backtest engine, accumulating paper trader) —
not a sliding window.
"""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime

import numpy as np
from pydantic import BaseModel

from app.core.types import SignalAction
from app.research.kalman import KalmanHedgeFilter
from app.research.pair_selection import SelectedPair
from app.research.regime_detection import any_leg_trending
from app.strategies.base import PairSignal, PairStrategyBase, PositionContext, StrategyInfo


class KalmanPairConfig(BaseModel):
    # delta must be SMALL: it is the speed at which the filter re-explains the
    # spread as a change in (beta, alpha). Too fast (1e-5) and every dislocation
    # is absorbed into the state within a few bars — the innovation degenerates
    # to one-step noise, every "reversion" trade is a coin flip, and round-trip
    # costs turn the strategy into a fee donation (observed: 8.7% win rate).
    delta: float = 1e-7
    r: float = 1e-3
    warmup_bars: int = 200
    zscore_window: int = 200       # empirical std window for the innovation z-score
    entry_z: float = 2.0
    exit_z: float = 0.5
    stop_z: float = 4.0
    max_holding_bars: int = 288
    min_holding_bars: int = 4      # don't churn out on next-bar noise
    beta_min: float = 0.05
    beta_max: float = 20.0
    # regime filter: skip NEW entries while either leg is strongly trending —
    # fading dislocations during breakouts is where mean reversion bleeds most
    use_regime_filter: bool = False
    regime_window: int = 96
    regime_t_threshold: float = 3.0
    # drift gate: innovations of a healthy spread are mean-zero. When their
    # trailing mean is statistically nonzero the "spread" is going somewhere —
    # fading it is a directional bet against a drift, not mean reversion.
    max_drift_t: float = 3.0       # 0 disables


class KalmanPairStrategy(PairStrategyBase):
    info = StrategyInfo("kalman_pairs", "1.0")

    def __init__(self, pair: SelectedPair, config: KalmanPairConfig | None = None) -> None:
        super().__init__(pair)
        self.cfg = config or KalmanPairConfig()
        beta0 = pair.beta if pair.beta > 0 else 1.0
        self.filter = KalmanHedgeFilter(
            delta=self.cfg.delta, r=self.cfg.r, beta0=beta0, alpha0=pair.alpha
        )
        self.beta = beta0
        self.alpha = pair.alpha
        self._next_i = 0
        self._residual = 0.0
        self._recent: deque[float] = deque(maxlen=self.cfg.zscore_window)

    @property
    def min_bars(self) -> int:
        return self.cfg.warmup_bars + 1

    def _advance(self, i: int, log_a: np.ndarray, log_b: np.ndarray) -> None:
        """Feed any unprocessed bars into the filter (idempotent per index)."""
        while self._next_i <= i:
            self.beta, self.alpha, self._residual, _ = self.filter.update(
                float(log_a[self._next_i]), float(log_b[self._next_i])
            )
            self._recent.append(self._residual)
            self._next_i += 1

    def _beta_is_sane(self) -> bool:
        return self.cfg.beta_min <= self.beta <= self.cfg.beta_max

    def _signal(self, ts: datetime, action: SignalAction, z: float, std: float, reason: str) -> PairSignal:
        return PairSignal(
            ts=ts, pair_key=self.pair_key, action=action, z_score=z,
            hedge_ratio=self.beta, alpha=self.alpha, spread=self._residual,
            spread_mean=0.0, spread_std=std, reason=reason,
        )

    def on_bar(
        self,
        i: int,
        log_a: np.ndarray,
        log_b: np.ndarray,
        ts: datetime,
        ctx: PositionContext,
    ) -> PairSignal | None:
        if self.disabled:
            return None
        self._advance(i, log_a, log_b)
        if i + 1 < self.min_bars or len(self._recent) < 20:
            return None

        recent = np.fromiter(self._recent, dtype=float)
        std = float(np.std(recent, ddof=1))
        if std <= 0.0 or not math.isfinite(std):
            return None
        z = self._residual / std
        cfg = self.cfg

        if ctx.position == 0:
            if not self._beta_is_sane():
                return None  # never size a trade off an unstable hedge ratio
            if cfg.use_regime_filter and any_leg_trending(
                i, cfg.regime_window, cfg.regime_t_threshold, log_a, log_b
            ):
                return None  # don't fade a strong trend
            if cfg.max_drift_t > 0:
                drift_t = abs(float(recent.mean()) / (std / math.sqrt(len(recent))))
                if drift_t > cfg.max_drift_t:
                    return None  # spread is drifting, not oscillating
            if cfg.entry_z <= z <= cfg.stop_z:
                return self._signal(ts, SignalAction.ENTER_SHORT_SPREAD, z, std,
                                    f"innovation z={z:.2f} >= {cfg.entry_z} (beta={self.beta:.3f})")
            if -cfg.stop_z <= z <= -cfg.entry_z:
                return self._signal(ts, SignalAction.ENTER_LONG_SPREAD, z, std,
                                    f"innovation z={z:.2f} <= -{cfg.entry_z} (beta={self.beta:.3f})")
            return None

        if abs(z) >= cfg.stop_z:
            return self._signal(ts, SignalAction.STOP_LOSS, z, std,
                                f"|z|={abs(z):.2f} >= stop {cfg.stop_z}")
        if ctx.bars_held >= cfg.max_holding_bars:
            return self._signal(ts, SignalAction.TIME_STOP, z, std,
                                f"held {ctx.bars_held} bars")
        if ctx.bars_held >= cfg.min_holding_bars and abs(z) <= cfg.exit_z:
            return self._signal(ts, SignalAction.EXIT, z, std,
                                f"|z|={abs(z):.2f} <= exit {cfg.exit_z}")
        return None
