"""Broker abstraction: capability matrix, precision normalization, base class.

Capability checks are enforced *before* every order. A broker connector can
only execute what its entry in config/broker_capabilities.yaml allows.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import ROUND_DOWN, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from app.brokers.models import AccountState, Instrument, Order, OrderRequest, Position
from app.core.exceptions import CapabilityError, OrderRejectedError
from app.core.types import AssetClass, OrderType, Side

CAPABILITIES_PATH = Path(__file__).resolve().parent.parent / "config" / "broker_capabilities.yaml"


class BrokerCapabilities(BaseModel):
    broker: str
    display_name: str = ""
    asset_classes: list[str] = Field(default_factory=list)
    order_types: list[str] = Field(default_factory=list)
    shorting: bool = False
    margin: bool = False
    max_leverage: float = 1.0
    fractional: bool = True
    quote_currencies: list[str] = Field(default_factory=list)
    market_hours: str = "24/7"
    sell_convention: str = "positive_quantity_with_side"
    unsupported: list[str] = Field(default_factory=list)
    enabled_by_default: bool = True
    notes: str = ""

    def supports(
        self,
        *,
        asset_class: AssetClass | str | None = None,
        order_type: OrderType | str | None = None,
        side: Side | str | None = None,
        shorting: bool | None = None,
        margin: bool | None = None,
    ) -> tuple[bool, str]:
        """Return (supported, reason_if_not)."""
        if asset_class is not None:
            ac = asset_class.value if isinstance(asset_class, AssetClass) else asset_class
            if ac in self.unsupported or ac not in self.asset_classes:
                return False, f"asset class '{ac}' not supported by {self.broker}"
        if order_type is not None:
            ot = order_type.value if isinstance(order_type, OrderType) else order_type
            if ot not in self.order_types:
                return False, f"order type '{ot}' not supported by {self.broker}"
        if shorting and not self.shorting:
            return False, f"shorting not supported by {self.broker}"
        if margin and not self.margin:
            return False, f"margin not supported by {self.broker}"
        # side alone is always valid if shorting constraints pass; selling more
        # than held is enforced by position checks, not capabilities.
        _ = side
        return True, ""

    def require(self, **kwargs: Any) -> None:
        ok, reason = self.supports(**kwargs)
        if not ok:
            raise CapabilityError(reason)


@lru_cache(maxsize=1)
def load_capabilities(path: str | None = None) -> dict[str, BrokerCapabilities]:
    file = Path(path) if path else CAPABILITIES_PATH
    raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    return {name: BrokerCapabilities(broker=name, **cfg) for name, cfg in raw.items()}


# --- precision helpers -------------------------------------------------------


def round_step(value: float, step: float) -> float:
    """Floor `value` to a multiple of `step`, decimal-safe (no float dust)."""
    if step <= 0:
        return value
    d_value, d_step = Decimal(str(value)), Decimal(str(step))
    return float((d_value / d_step).to_integral_value(rounding=ROUND_DOWN) * d_step)


def round_tick(price: float, tick: float) -> float:
    return round_step(price, tick)


def normalize_quantity(quantity: float, instrument: Instrument, ref_price: float) -> float:
    """Round quantity to the instrument's step size and enforce minimums.

    Raises OrderRejectedError if the rounded quantity violates min_quantity or
    min_notional — an order that small must not be sent at all.
    """
    qty = round_step(abs(quantity), instrument.step_size)
    if qty <= 0:
        raise OrderRejectedError(
            f"{instrument.symbol}: quantity {quantity} rounds to 0 at step {instrument.step_size}"
        )
    if instrument.min_quantity and qty < instrument.min_quantity:
        raise OrderRejectedError(
            f"{instrument.symbol}: quantity {qty} < min_quantity {instrument.min_quantity}"
        )
    notional = qty * ref_price
    if instrument.min_notional and notional < instrument.min_notional:
        raise OrderRejectedError(
            f"{instrument.symbol}: notional {notional:.2f} < min_notional {instrument.min_notional}"
        )
    return qty


# --- base class ---------------------------------------------------------------


class BrokerBase(ABC):
    """Interface every broker connector implements."""

    name: str = "base"
    asset_class: AssetClass = AssetClass.CRYPTO_SPOT

    def __init__(self, capabilities: BrokerCapabilities | None = None) -> None:
        self.capabilities = capabilities or load_capabilities()[self.name]

    # -- account ---------------------------------------------------------------
    @abstractmethod
    def get_account(self) -> AccountState: ...

    @abstractmethod
    def get_cash(self) -> float: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_open_orders(self) -> list[Order]: ...

    # -- market structure --------------------------------------------------------
    @abstractmethod
    def get_instruments(self, symbols: list[str] | None = None) -> list[Instrument]: ...

    @abstractmethod
    def get_market_data(self, symbol: str) -> dict[str, Any]: ...

    # -- orders -------------------------------------------------------------------
    @abstractmethod
    def place_order(self, request: OrderRequest) -> Order: ...

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str | None = None) -> Order: ...

    @abstractmethod
    def get_order_status(self, order_id: str, symbol: str | None = None) -> Order: ...

    # -- shared validation -----------------------------------------------------------
    def supports(self, **kwargs: Any) -> tuple[bool, str]:
        return self.capabilities.supports(**kwargs)

    def normalize_order(self, request: OrderRequest, instrument: Instrument) -> OrderRequest:
        qty = normalize_quantity(request.quantity, instrument, request.ref_price or 1.0)
        update: dict[str, Any] = {"quantity": qty}
        if request.limit_price is not None and instrument.tick_size:
            update["limit_price"] = round_tick(request.limit_price, instrument.tick_size)
        return request.model_copy(update=update)

    def validate_order(self, request: OrderRequest, instrument: Instrument) -> None:
        """Capability + precision validation. Raises on violation."""
        self.capabilities.require(asset_class=instrument.asset_class, order_type=request.order_type)
        if request.side is Side.SELL and not self.capabilities.shorting:
            # spot/long-only: selling is only allowed against an existing position;
            # connectors check held quantity at execution time.
            pass
        normalize_quantity(request.quantity, instrument, request.ref_price or 1.0)
