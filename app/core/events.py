"""Event types flowing through the backtest engine and paper trader.

The pipeline is: BarEvent -> (strategy) -> SignalEvent -> (risk manager)
-> OrderEvent -> (broker/simulator) -> FillEvent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.types import OrderType, Side, SignalAction


@dataclass(frozen=True)
class BarEvent:
    ts: datetime
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class SignalEvent:
    ts: datetime
    strategy: str
    strategy_version: str
    pair_key: str
    action: SignalAction
    z_score: float
    hedge_ratio: float
    spread: float
    spread_mean: float
    spread_std: float
    reason: str = ""


@dataclass(frozen=True)
class OrderEvent:
    ts: datetime
    broker: str
    symbol: str
    side: Side
    order_type: OrderType
    quantity: float
    ref_price: float
    pair_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FillEvent:
    ts: datetime
    symbol: str
    side: Side
    quantity: float
    price: float
    fee: float
    pair_key: str = ""
