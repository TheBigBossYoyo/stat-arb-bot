"""Commission models."""

from __future__ import annotations

from abc import ABC, abstractmethod


class CommissionModel(ABC):
    @abstractmethod
    def fee(self, notional: float) -> float: ...


class PercentCommission(CommissionModel):
    """Fee as a percentage of traded notional (Binance spot taker ~10bps)."""

    def __init__(self, bps: float = 10.0, minimum: float = 0.0) -> None:
        self.bps = bps
        self.minimum = minimum

    def fee(self, notional: float) -> float:
        return max(abs(notional) * self.bps / 10_000.0, self.minimum)


class ZeroCommission(CommissionModel):
    """Trading 212 equities are commission-free (FX/stamp costs modeled separately)."""

    def fee(self, notional: float) -> float:
        return 0.0


def for_broker(broker: str) -> CommissionModel:
    return {
        "binance_spot": PercentCommission(10.0),
        "trading212": ZeroCommission(),
    }.get(broker, PercentCommission(10.0))
