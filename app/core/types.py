"""Core shared types and enums."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum


class TradingMode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class AssetClass(str, Enum):
    CRYPTO_SPOT = "crypto_spot"
    CRYPTO_FUTURES = "crypto_futures"
    EQUITY = "equity"
    CFD = "cfd"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1

    @property
    def opposite(self) -> Side:
        return Side.SELL if self is Side.BUY else Side.BUY


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    NEW = "new"
    PENDING = "pending"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    FAILED = "failed"


class SignalAction(str, Enum):
    ENTER_LONG_SPREAD = "enter_long_spread"    # long A, short B
    ENTER_SHORT_SPREAD = "enter_short_spread"  # short A, long B
    EXIT = "exit"
    STOP_LOSS = "stop_loss"
    TIME_STOP = "time_stop"
    PAIR_LOSS_STOP = "pair_loss_stop"   # hard money stop enforced by the risk layer
    DISABLE_PAIR = "disable_pair"

    @property
    def is_entry(self) -> bool:
        return self in (SignalAction.ENTER_LONG_SPREAD, SignalAction.ENTER_SHORT_SPREAD)

    @property
    def is_exit(self) -> bool:
        return self in (
            SignalAction.EXIT,
            SignalAction.STOP_LOSS,
            SignalAction.TIME_STOP,
            SignalAction.PAIR_LOSS_STOP,
        )


@dataclass(frozen=True)
class Pair:
    """An ordered pair of symbols. Convention: spread = log(a) - beta*log(b)."""

    symbol_a: str
    symbol_b: str

    @property
    def key(self) -> str:
        return f"{self.symbol_a}|{self.symbol_b}"

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.key


INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}


def interval_minutes(interval: str) -> int:
    try:
        return INTERVAL_MINUTES[interval]
    except KeyError as exc:
        raise ValueError(f"Unsupported interval {interval!r}; choose from {list(INTERVAL_MINUTES)}") from exc


def utc_now() -> datetime:
    """Timezone-aware UTC now. Internally bars use tz-naive UTC timestamps."""
    return datetime.now(UTC)
