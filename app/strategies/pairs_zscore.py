"""Classic rolling z-score pair strategy.

spread_t = log(A_t) - (alpha + beta * log(B_t))
z_t      = (spread_t - mean(spread, lookback)) / std(spread, lookback)

Entries fade extremes; exits close near the mean; stops cut broken
relationships and stale trades.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from pydantic import BaseModel

from app.core.math_utils import zscore_last
from app.core.types import SignalAction
from app.research.pair_selection import SelectedPair
from app.research.regime_detection import any_leg_trending
from app.strategies.base import PairSignal, PairStrategyBase, PositionContext, StrategyInfo


class ZScoreConfig(BaseModel):
    lookback_bars: int = 200
    entry_z: float = 2.0
    exit_z: float = 0.3
    stop_z: float = 3.5
    max_holding_bars: int = 96
    # adaptive time stop: hold up to `mult * half-life` bars (mean reversion is
    # ~88% complete after 3 half-lives), clamped to [min_holding_bars,
    # max_holding_bars]. 0 disables and the fixed max_holding_bars applies —
    # which starves slow pairs (a 96-bar budget on a 180-bar half-life exits
    # most trades before the spread has had time to converge).
    holding_half_life_mult: float = 0.0
    min_holding_bars: int = 24
    # regime filter: skip NEW entries while either leg is strongly trending
    use_regime_filter: bool = False
    regime_window: int = 96
    regime_t_threshold: float = 3.0


class ZScorePairStrategy(PairStrategyBase):
    info = StrategyInfo("pairs_zscore", "1.0")

    def __init__(self, pair: SelectedPair, config: ZScoreConfig | None = None) -> None:
        super().__init__(pair)
        self.config = config or ZScoreConfig()
        self.beta = pair.beta
        self.alpha = pair.alpha
        self.lookback = self.config.lookback_bars
        self.max_holding = self._holding_budget(pair.half_life)

    def _holding_budget(self, half_life: float) -> int:
        cfg = self.config
        if cfg.holding_half_life_mult > 0 and np.isfinite(half_life) and half_life > 0:
            return int(np.clip(round(cfg.holding_half_life_mult * half_life),
                               cfg.min_holding_bars, cfg.max_holding_bars))
        return cfg.max_holding_bars

    @property
    def min_bars(self) -> int:
        return self.lookback + 1

    def _spread_window(self, i: int, log_a: np.ndarray, log_b: np.ndarray) -> np.ndarray:
        start = i + 1 - self.lookback
        return log_a[start : i + 1] - (self.alpha + self.beta * log_b[start : i + 1])

    def _in_trend_regime(self, i: int, log_a: np.ndarray, log_b: np.ndarray) -> bool:
        """t-statistic of the mean log return over the regime window, per leg."""
        cfg = self.config
        return any_leg_trending(i, cfg.regime_window, cfg.regime_t_threshold, log_a, log_b)

    def _signal(self, ts: datetime, action: SignalAction, z: float, spread: np.ndarray,
                mean: float, std: float, reason: str) -> PairSignal:
        return PairSignal(
            ts=ts,
            pair_key=self.pair_key,
            action=action,
            z_score=z,
            hedge_ratio=self.beta,
            alpha=self.alpha,
            spread=float(spread[-1]),
            spread_mean=mean,
            spread_std=std,
            reason=reason,
        )

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

        spread = self._spread_window(i, log_a, log_b)
        z, mean, std = zscore_last(spread)
        if std == 0.0:
            return None
        cfg = self.config

        if ctx.position == 0:
            if cfg.use_regime_filter and self._in_trend_regime(i, log_a, log_b):
                return None  # don't fade a strong trend
            if z >= cfg.entry_z and z <= cfg.stop_z:
                return self._signal(ts, SignalAction.ENTER_SHORT_SPREAD, z, spread, mean, std,
                                    f"z={z:.2f} >= entry {cfg.entry_z}")
            if z <= -cfg.entry_z and z >= -cfg.stop_z:
                return self._signal(ts, SignalAction.ENTER_LONG_SPREAD, z, spread, mean, std,
                                    f"z={z:.2f} <= entry -{cfg.entry_z}")
            return None

        # in a position
        if abs(z) >= cfg.stop_z:
            return self._signal(ts, SignalAction.STOP_LOSS, z, spread, mean, std,
                                f"|z|={abs(z):.2f} >= stop {cfg.stop_z}")
        if ctx.bars_held >= self.max_holding:
            return self._signal(ts, SignalAction.TIME_STOP, z, spread, mean, std,
                                f"held {ctx.bars_held} bars >= {self.max_holding}")
        if abs(z) <= cfg.exit_z:
            return self._signal(ts, SignalAction.EXIT, z, spread, mean, std,
                                f"|z|={abs(z):.2f} <= exit {cfg.exit_z}")
        # convergence through the other side also closes the trade
        if (ctx.position == 1 and z >= cfg.exit_z) or (ctx.position == -1 and z <= -cfg.exit_z):
            return self._signal(ts, SignalAction.EXIT, z, spread, mean, std, "crossed through mean")
        return None
