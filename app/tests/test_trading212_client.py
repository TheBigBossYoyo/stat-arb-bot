"""Trading 212 connector behaviour. All HTTP is mocked — no live API calls."""

from __future__ import annotations

import json

import httpx
import pytest

from app.brokers.models import OrderRequest
from app.brokers.trading212.auth import BASE_URLS
from app.brokers.trading212.client import Trading212Client, signed_quantity
from app.core.exceptions import LiveTradingBlockedError, OrderRejectedError
from app.core.types import OrderStatus, OrderType, Side

RATE_HEADERS = {
    "x-ratelimit-limit": "6", "x-ratelimit-period": "60",
    "x-ratelimit-remaining": "5", "x-ratelimit-reset": "1900000000",
    "x-ratelimit-used": "1",
}

PORTFOLIO = [
    {"ticker": "AAPL_US_EQ", "quantity": 5.0, "averagePrice": 100.0, "currentPrice": 110.0},
]
CASH = {"free": 1000.0, "total": 1550.0, "invested": 500.0}
INFO = {"currencyCode": "USD", "id": 123}
INSTRUMENTS = [
    {"ticker": "AAPL_US_EQ", "type": "STOCK", "currencyCode": "USD", "minTradeQuantity": 0.01},
    {"ticker": "VUSA_EQ", "type": "ETF", "currencyCode": "GBP", "minTradeQuantity": 0.1},
    {"ticker": "WEIRD_CFD", "type": "CFD", "currencyCode": "USD"},
]


def make_client(captured: dict | None = None) -> Trading212Client:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/equity/portfolio"):
            return httpx.Response(200, json=PORTFOLIO, headers=RATE_HEADERS)
        if path.endswith("/equity/account/cash"):
            return httpx.Response(200, json=CASH, headers=RATE_HEADERS)
        if path.endswith("/equity/account/info"):
            return httpx.Response(200, json=INFO, headers=RATE_HEADERS)
        if path.endswith("/equity/metadata/instruments"):
            return httpx.Response(200, json=INSTRUMENTS, headers=RATE_HEADERS)
        if path.endswith("/equity/orders/market") and request.method == "POST":
            body = json.loads(request.content)
            if captured is not None:
                captured.update(body)
            return httpx.Response(200, json={
                "id": 777, "ticker": body["ticker"], "quantity": body["quantity"],
                "status": "FILLED", "filledQuantity": body["quantity"],
                "filledValue": abs(body["quantity"]) * 110.0,
            }, headers=RATE_HEADERS)
        if "/equity/orders/" in path and request.method == "DELETE":
            return httpx.Response(200, json={}, headers=RATE_HEADERS)
        if "/equity/orders/" in path and request.method == "GET":
            return httpx.Response(200, json={
                "id": 777, "ticker": "AAPL_US_EQ", "quantity": -3.0,
                "status": "FILLED", "filledQuantity": -3.0, "filledValue": 330.0,
            }, headers=RATE_HEADERS)
        return httpx.Response(404, json={"msg": f"not mocked: {path}"})

    http = httpx.Client(base_url=BASE_URLS["demo"], transport=httpx.MockTransport(handler))
    return Trading212Client(api_key="k", api_secret="s", mode="demo", enabled=True, client=http)


def test_live_mode_requires_gate():
    with pytest.raises(LiveTradingBlockedError):
        Trading212Client(api_key="k", api_secret="s", mode="live", enabled=True)


def test_account_and_rate_limit_parsing():
    client = make_client()
    account = client.get_account()
    assert account.cash == 1000.0
    assert account.currency == "USD"
    assert account.positions[0].symbol == "AAPL_US_EQ"
    assert client.last_rate_limit["remaining"] == 5
    assert client.last_rate_limit["limit"] == 6


def test_instruments_filter_out_non_equity():
    client = make_client()
    instruments = client.get_instruments()
    tickers = {i.symbol for i in instruments}
    assert tickers == {"AAPL_US_EQ", "VUSA_EQ"}      # the CFD-typed product is excluded
    assert all(not i.shortable for i in instruments)


def test_sell_uses_negative_quantity_convention():
    assert signed_quantity(Side.BUY, 3.0) == 3.0
    assert signed_quantity(Side.SELL, 3.0) == -3.0

    captured: dict = {}
    client = make_client(captured=captured)
    order = client.place_order(OrderRequest(
        broker="trading212", symbol="AAPL_US_EQ", side=Side.SELL,
        order_type=OrderType.MARKET, quantity=3.0, ref_price=110.0,
    ))
    assert captured["quantity"] == -3.0
    assert order.status is OrderStatus.FILLED
    assert order.filled_quantity == 3.0
    assert order.avg_fill_price == pytest.approx(110.0)


def test_short_sell_rejected_before_http():
    captured: dict = {}
    client = make_client(captured=captured)
    with pytest.raises(OrderRejectedError, match="short selling"):
        client.place_order(OrderRequest(
            broker="trading212", symbol="AAPL_US_EQ", side=Side.SELL,
            order_type=OrderType.MARKET, quantity=10.0, ref_price=110.0,  # held: 5
        ))
    assert captured == {}                            # nothing was sent


def test_limit_order_requires_price():
    client = make_client()
    with pytest.raises(OrderRejectedError):
        client.place_order(OrderRequest(
            broker="trading212", symbol="AAPL_US_EQ", side=Side.BUY,
            order_type=OrderType.LIMIT, quantity=1.0, ref_price=110.0,
        ))


def test_cancel_and_status():
    client = make_client()
    canceled = client.cancel_order("777", symbol="AAPL_US_EQ")
    assert canceled.status is OrderStatus.CANCELED
    status = client.get_order_status("777")
    assert status.status is OrderStatus.FILLED
    assert status.request.side is Side.SELL          # negative qty decoded as sell
    assert status.avg_fill_price == pytest.approx(110.0)
