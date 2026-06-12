"""Strategy base classes.

A pair strategy is a pure signal generator: at bar i it sees log prices up to
and including i (never beyond — lookahead is structurally impossible) plus its
current position state, and may emit one PairSignal. Execution, sizing and
risk are the engine's job, not the strategy's.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.core.types import SignalAction
from app.research.pair_selection import SelectedPair


@dataclass(frozen=True)
class StrategyInfo:
    name: str
    version: str


@dataclass
class PairSignal:
    ts: datetime
    pair_key: str
    action: SignalAction
    z_score: float
    hedge_ratio: float
    alpha: float
    spread: float
    spread_mean: float
    spread_std: float
    reason: str = ""


@dataclass
class PositionContext:
    """Engine-owned position state passed to the strategy each bar."""

    position: int = 0        # +1 long spread, -1 short spread, 0 flat
    bars_held: int = 0


class PairStrategyBase(ABC):
    info: StrategyInfo = StrategyInfo("base", "0.0")

    def __init__(self, pair: SelectedPair) -> None:
        self.pair = pair
        self.disabled = False

    @property
    def pair_key(self) -> str:
        return self.pair.key

    @property
    @abstractmethod
    def min_bars(self) -> int:
        """Bars of history required before the first signal."""

    @abstractmethod
    def on_bar(
        self,
        i: int,
        log_a: np.ndarray,
        log_b: np.ndarray,
        ts: datetime,
        ctx: PositionContext,
    ) -> PairSignal | None:
        """Called once per bar with history[0..i] inclusive."""
