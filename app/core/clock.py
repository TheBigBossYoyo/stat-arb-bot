"""Clock abstraction so backtests and live trading share the same code paths."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""


class RealClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)


class SimClock(Clock):
    """Deterministic clock driven by the backtest engine."""

    def __init__(self, start: datetime | None = None) -> None:
        self._now = start or datetime(2020, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def set(self, ts: datetime) -> None:
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        self._now = ts
