"""Trading 212 connector (Phase 5) — official Public API only.

Verified against https://docs.trading212.com/api (June 2026):
  * HTTP Basic auth: API key as username, API secret as password.
  * Demo first: https://demo.trading212.com/api/v0; the LIVE base URL is only
    used when the live-trading gate explicitly grants allow_live=True.
  * Equity (Invest / Stocks ISA) only. CFDs, shorting, margin: UNSUPPORTED.
  * Rate limits arrive in x-ratelimit-* headers and are respected.

Endpoints used:
  GET    /equity/account/cash          GET    /equity/account/info
  GET    /equity/metadata/instruments  GET    /equity/portfolio
  GET    /equity/orders                GET    /equity/orders/{id}
  POST   /equity/orders/market|limit|stop|stop_limit
  DELETE /equity/orders/{id}           GET    /equity/history/orders

Sell convention: this client sends sells as NEGATIVE quantity, per the docs'
order schema. VERIFY against the demo environment before first real use —
the assertion lives in one place (`signed_quantity`).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.brokers.base import BrokerBase
from app.brokers.models import AccountState, Instrument, Order, OrderRequest, Position
from app.brokers.trading212.auth import BASE_URLS, basic_auth_header, rate_limit_state
from app.core.exceptions import (
    BrokerError,
    BrokerNotEnabledError,
    CapabilityError,
    LiveTradingBlockedError,
    OrderRejectedError,
)
from app.core.logging import audit, get_logger
from app.core.types import AssetClass, OrderStatus, OrderType, Side, utc_now
from app.execution.retry_policy import request_with_retries

log = get_logger(__name__)

EQUITY_INSTRUMENT_TYPES = {"STOCK", "ETF"}

ORDER_STATUS_MAP: dict[str, OrderStatus] = {
    "LOCAL": OrderStatus.PENDING,
    "UNCONFIRMED": OrderStatus.PENDING,
    "CONFIRMED": OrderStatus.NEW,
    "NEW": OrderStatus.NEW,
    "PROCESSING": OrderStatus.PENDING,
    "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED,
    "FILLED": OrderStatus.FILLED,
    "CANCELLING": OrderStatus.CANCELED,
    "CANCELLED": OrderStatus.CANCELED,
    "REJECTED": OrderStatus.REJECTED,
}

ORDER_PATHS: dict[OrderType, str] = {
    OrderType.MARKET: "/equity/orders/market",
    OrderType.LIMIT: "/equity/orders/limit",
    OrderType.STOP: "/equity/orders/stop",
    OrderType.STOP_LIMIT: "/equity/orders/stop_limit",
}


def signed_quantity(side: Side, quantity: float) -> float:
    """Trading 212 sell convention: negative quantity = sell. (VERIFY on demo.)"""
    return quantity if side is Side.BUY else -quantity


class Trading212Client(BrokerBase):
    name = "trading212"
    asset_class = AssetClass.EQUITY

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        mode: str = "demo",
        enabled: bool = False,
        allow_live: bool = False,
        account_type: str = "invest",
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__()
        if not enabled:
            raise BrokerNotEnabledError(
                "Trading 212 connector is disabled. Set TRADING212_ENABLED=true (demo first)."
            )
        if account_type not in ("invest", "isa"):
            raise CapabilityError(
                f"Trading 212 account type '{account_type}' is not supported by the official "
                "Public API (Invest / Stocks ISA only — CFDs are unsupported)."
            )
        if not api_key or not api_secret:
            raise BrokerNotEnabledError("TRADING212_API_KEY / TRADING212_API_SECRET not configured.")
        if mode == "live" and not allow_live:
            raise LiveTradingBlockedError(
                "Trading 212 LIVE mode requires the live-trading gate (allow_live). Use demo."
            )
        self.mode = mode
        self.last_rate_limit: dict[str, int | None] = {}
        self._client = client or httpx.Client(
            base_url=BASE_URLS[mode],
            timeout=30.0,
            headers=basic_auth_header(api_key, api_secret),
        )

    # -- plumbing ---------------------------------------------------------------

    def _respect_rate_limit(self) -> None:
        remaining = self.last_rate_limit.get("remaining")
        reset = self.last_rate_limit.get("reset")
        if remaining == 0 and reset:
            wait = max(0.0, reset - time.time()) + 0.25
            if wait > 0:
                log.warning("trading212 rate limit reached; sleeping %.1fs", wait)
                time.sleep(min(wait, 60.0))

    def _request(self, method: str, path: str, json_body: dict | None = None,
                 params: dict | None = None) -> Any:
        self._respect_rate_limit()
        response = request_with_retries(
            lambda: self._client.request(method, path, json=json_body, params=params)
        )
        self.last_rate_limit = rate_limit_state(dict(response.headers))
        if response.status_code in (200, 201):
            return response.json()
        if response.status_code == 204:
            return {}
        raise BrokerError(
            f"trading212 {method} {path} -> {response.status_code}: {response.text[:300]}"
        )

    # -- account ----------------------------------------------------------------

    def get_account(self) -> AccountState:
        cash = self._request("GET", "/equity/account/cash")
        info = self._request("GET", "/equity/account/info")
        return AccountState(
            broker=self.name,
            currency=str(info.get("currencyCode", "USD")),
            cash=float(cash.get("free", 0) or 0),
            equity=float(cash.get("total", 0) or 0),
            positions=self.get_positions(),
        )

    def get_cash(self) -> float:
        return float(self._request("GET", "/equity/account/cash").get("free", 0) or 0)

    def get_positions(self) -> list[Position]:
        data = self._request("GET", "/equity/portfolio")
        return [
            Position(
                symbol=item["ticker"],
                quantity=float(item.get("quantity", 0) or 0),
                avg_entry_price=float(item.get("averagePrice", 0) or 0),
            )
            for item in data
        ]

    def position_quantity(self, ticker: str) -> float:
        return next((p.quantity for p in self.get_positions() if p.symbol == ticker), 0.0)

    # -- market structure ----------------------------------------------------------

    def get_instruments(self, symbols: list[str] | None = None) -> list[Instrument]:
        """Equity instruments only (tickers look like 'AAPL_US_EQ')."""
        data = self._request("GET", "/equity/metadata/instruments")
        instruments = []
        for item in data:
            if str(item.get("type", "")).upper() not in EQUITY_INSTRUMENT_TYPES:
                continue  # anything else (incl. CFD-like products) is filtered out
            ticker = item["ticker"]
            if symbols and ticker not in symbols:
                continue
            instruments.append(
                Instrument(
                    broker=self.name,
                    symbol=ticker,
                    asset_class=AssetClass.EQUITY,
                    base_currency="",
                    quote_currency=str(item.get("currencyCode", "")),
                    min_quantity=float(item.get("minTradeQuantity", 0) or 0),
                    shortable=False,
                    fractional=True,
                )
            )
        return instruments

    def get_market_data(self, symbol: str) -> dict[str, Any]:
        raise CapabilityError(
            "The Trading 212 Public API does not expose quotes/candles. Use the "
            "configured research data provider for prices; execution stays here."
        )

    # -- orders ------------------------------------------------------------------------

    def place_order(self, request: OrderRequest) -> Order:
        self.capabilities.require(asset_class=self.asset_class, order_type=request.order_type)
        if request.order_type not in ORDER_PATHS:
            raise OrderRejectedError(f"unsupported order type {request.order_type.value}")

        # Long-only enforcement: a sell may never exceed the held quantity.
        if request.side is Side.SELL:
            held = self.position_quantity(request.symbol)
            if request.quantity > held + 1e-9:
                raise OrderRejectedError(
                    f"{request.symbol}: sell {request.quantity} exceeds held {held} — "
                    "short selling is not supported on Trading 212 Invest/ISA."
                )

        payload: dict[str, Any] = {
            "ticker": request.symbol,
            "quantity": signed_quantity(request.side, request.quantity),
        }
        if request.order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
            if request.limit_price is None:
                raise OrderRejectedError("limit/stop-limit order requires limit_price")
            payload["limitPrice"] = request.limit_price
        if request.order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            if request.stop_price is None:
                raise OrderRejectedError("stop/stop-limit order requires stop_price")
            payload["stopPrice"] = request.stop_price
        if request.order_type is not OrderType.MARKET:
            payload["timeValidity"] = "DAY" if request.time_in_force == "DAY" else "GOOD_TILL_CANCEL"

        audit("trading212_order_submit", mode=self.mode, **payload)
        data = self._request("POST", ORDER_PATHS[request.order_type], json_body=payload)
        order = self._parse_order(data, request)
        audit("trading212_order_result", order_id=order.order_id, status=order.status.value)
        return order

    def cancel_order(self, order_id: str, symbol: str | None = None) -> Order:
        self._request("DELETE", f"/equity/orders/{order_id}")
        return Order(
            order_id=str(order_id),
            request=OrderRequest(broker=self.name, symbol=symbol or "", side=Side.BUY, quantity=0.0),
            status=OrderStatus.CANCELED,
            updated_at=utc_now(),
        )

    def get_order_status(self, order_id: str, symbol: str | None = None) -> Order:
        data = self._request("GET", f"/equity/orders/{order_id}")
        return self._parse_order(data)

    def get_open_orders(self) -> list[Order]:
        data = self._request("GET", "/equity/orders")
        return [self._parse_order(item) for item in data]

    def get_order_history(self, limit: int = 50) -> list[dict]:
        data = self._request("GET", "/equity/history/orders", params={"limit": limit})
        return data.get("items", data) if isinstance(data, dict) else data

    # -- helpers -----------------------------------------------------------------------

    def _parse_order(self, data: dict[str, Any], request: OrderRequest | None = None) -> Order:
        qty = float(data.get("quantity", 0) or 0)
        if request is None:
            request = OrderRequest(
                broker=self.name,
                symbol=str(data.get("ticker", "")),
                side=Side.BUY if qty >= 0 else Side.SELL,
                quantity=abs(qty),
                limit_price=data.get("limitPrice"),
                stop_price=data.get("stopPrice"),
            )
        filled = abs(float(data.get("filledQuantity", 0) or 0))
        return Order(
            order_id=str(data.get("id", "")),
            request=request,
            status=ORDER_STATUS_MAP.get(str(data.get("status", "")).upper(), OrderStatus.PENDING),
            filled_quantity=filled,
            avg_fill_price=float(data.get("filledValue", 0) or 0) / filled if filled else 0.0,
            created_at=utc_now(),
            updated_at=utc_now(),
            raw=data,
        )
