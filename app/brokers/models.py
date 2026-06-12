"""Broker-facing data models (pydantic)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.types import AssetClass, OrderStatus, OrderType, Side


class Instrument(BaseModel):
    broker: str
    symbol: str
    asset_class: AssetClass
    base_currency: str = ""
    quote_currency: str = ""
    tick_size: float = 0.0       # price increment (0 = unknown/no constraint)
    step_size: float = 0.0       # quantity increment
    min_quantity: float = 0.0
    min_notional: float = 0.0
    shortable: bool = False
    fractional: bool = True


class SignalMetadata(BaseModel):
    """Full signal context attached to every order for the audit trail."""

    strategy: str = ""
    strategy_version: str = ""
    pair_key: str = ""
    action: str = ""
    z_score: float = 0.0
    hedge_ratio: float = 0.0
    spread: float = 0.0
    spread_mean: float = 0.0
    spread_std: float = 0.0
    volatility: float = 0.0
    expected_slippage_bps: float = 0.0


class OrderRequest(BaseModel):
    broker: str
    symbol: str
    side: Side
    order_type: OrderType = OrderType.MARKET
    quantity: float
    limit_price: float | None = None
    stop_price: float | None = None
    time_in_force: str = "GTC"
    ref_price: float = 0.0       # last known price used for sizing/notional checks
    client_order_id: str = ""
    pair_key: str = ""
    metadata: SignalMetadata = Field(default_factory=SignalMetadata)

    @property
    def notional(self) -> float:
        price = self.limit_price or self.ref_price
        return abs(self.quantity) * price


class Fill(BaseModel):
    ts: datetime
    symbol: str
    side: Side
    quantity: float
    price: float
    fee: float = 0.0

    @property
    def notional(self) -> float:
        return abs(self.quantity) * self.price


class Order(BaseModel):
    order_id: str
    request: OrderRequest
    status: OrderStatus = OrderStatus.NEW
    filled_quantity: float = 0.0
    avg_fill_price: float = 0.0
    fee: float = 0.0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    error: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class Position(BaseModel):
    symbol: str
    quantity: float              # signed; negative = short
    avg_entry_price: float = 0.0

    def market_value(self, price: float) -> float:
        return self.quantity * price


class AccountState(BaseModel):
    broker: str
    currency: str = "USDT"
    cash: float = 0.0
    equity: float = 0.0
    positions: list[Position] = Field(default_factory=list)
