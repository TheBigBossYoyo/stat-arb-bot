"""Binance Spot order payload construction and response parsing (Phase 4).

Pure functions — no network — so the exact bytes we would send are unit
tested. The signed HTTP call itself lives in BinanceClient.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.brokers.models import Order, OrderRequest
from app.core.exceptions import OrderRejectedError
from app.core.types import OrderStatus, OrderType, utc_now

ORDER_TYPE_MAP: dict[OrderType, str] = {
    OrderType.MARKET: "MARKET",
    OrderType.LIMIT: "LIMIT",
    OrderType.STOP_LIMIT: "STOP_LOSS_LIMIT",
}

ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "NEW": OrderStatus.NEW,
    "PENDING_NEW": OrderStatus.PENDING,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELED": OrderStatus.CANCELED,
    "PENDING_CANCEL": OrderStatus.CANCELED,
    "REJECTED": OrderStatus.REJECTED,
    "EXPIRED": OrderStatus.CANCELED,
    "EXPIRED_IN_MATCH": OrderStatus.CANCELED,
}


def format_decimal(value: float) -> str:
    """Plain decimal string (no scientific notation, no trailing zeros)."""
    text = format(Decimal(str(value)), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def build_order_params(request: OrderRequest) -> dict[str, Any]:
    """Translate an OrderRequest into /api/v3/order parameters."""
    binance_type = ORDER_TYPE_MAP.get(request.order_type)
    if binance_type is None:
        raise OrderRejectedError(
            f"order type {request.order_type.value!r} not supported on Binance spot"
        )
    params: dict[str, Any] = {
        "symbol": request.symbol,
        "side": request.side.value.upper(),
        "type": binance_type,
        "quantity": format_decimal(request.quantity),
    }
    if request.client_order_id:
        params["newClientOrderId"] = request.client_order_id
    if request.order_type is OrderType.LIMIT:
        if request.limit_price is None:
            raise OrderRejectedError("limit order requires limit_price")
        params["price"] = format_decimal(request.limit_price)
        params["timeInForce"] = request.time_in_force
    elif request.order_type is OrderType.STOP_LIMIT:
        if request.limit_price is None or request.stop_price is None:
            raise OrderRejectedError("stop-limit order requires limit_price and stop_price")
        params["price"] = format_decimal(request.limit_price)
        params["stopPrice"] = format_decimal(request.stop_price)
        params["timeInForce"] = request.time_in_force
    return params


def parse_order_response(data: dict[str, Any], request: OrderRequest) -> Order:
    executed = float(data.get("executedQty", 0) or 0)
    quote = float(data.get("cummulativeQuoteQty", 0) or 0)
    fills = data.get("fills") or []
    fee = sum(float(f.get("commission", 0) or 0) for f in fills)
    if fills:
        notional = sum(float(f["price"]) * float(f["qty"]) for f in fills)
        qty = sum(float(f["qty"]) for f in fills)
        avg_price = notional / qty if qty else 0.0
    else:
        avg_price = quote / executed if executed else 0.0
    return Order(
        order_id=str(data.get("orderId", "")),
        request=request,
        status=ORDER_STATUS_MAP.get(str(data.get("status", "")).upper(), OrderStatus.PENDING),
        filled_quantity=executed,
        avg_fill_price=avg_price,
        fee=fee,
        created_at=utc_now(),
        updated_at=utc_now(),
        raw=data,
    )
