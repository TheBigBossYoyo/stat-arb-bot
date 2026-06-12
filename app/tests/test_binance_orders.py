"""Binance order construction and signed submission. All HTTP is mocked."""

from __future__ import annotations

import json

import httpx
import pytest

from app.brokers.binance.client import BASE_URLS, BinanceClient
from app.brokers.binance.execution import build_order_params, format_decimal
from app.brokers.models import OrderRequest
from app.core.exceptions import LiveTradingBlockedError, OrderRejectedError
from app.core.types import OrderStatus, OrderType, Side

EXCHANGE_INFO = {
    "symbols": [{
        "symbol": "ETHUSDT", "baseAsset": "ETH", "quoteAsset": "USDT",
        "filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
            {"filterType": "NOTIONAL", "minNotional": "5"},
        ],
    }]
}

ORDER_RESPONSE = {
    "orderId": 12345, "status": "FILLED", "executedQty": "0.123",
    "cummulativeQuoteQty": "369.00",
    "fills": [{"price": "3000.00", "qty": "0.123", "commission": "0.369"}],
}


def make_client(mode: str = "testnet", allow_live_orders: bool = False,
                captured: dict | None = None) -> BinanceClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v3/exchangeInfo":
            return httpx.Response(200, json=EXCHANGE_INFO)
        if request.url.path == "/api/v3/order" and request.method == "POST":
            if captured is not None:
                captured.update(dict(request.url.params))
            return httpx.Response(200, json=ORDER_RESPONSE)
        if request.url.path == "/api/v3/order" and request.method == "GET":
            return httpx.Response(200, json={**ORDER_RESPONSE, "side": "BUY", "origQty": "0.123"})
        return httpx.Response(404, json={"msg": "not mocked"})

    http = httpx.Client(base_url=BASE_URLS[mode], transport=httpx.MockTransport(handler),
                        headers={"X-MBX-APIKEY": "key"})
    return BinanceClient(api_key="key", api_secret="secret", mode=mode, enabled=True,
                         allow_live_orders=allow_live_orders, client=http)


def order_request(qty: float = 0.1234567) -> OrderRequest:
    return OrderRequest(broker="binance_spot", symbol="ETHUSDT", side=Side.BUY,
                        order_type=OrderType.MARKET, quantity=qty, ref_price=3000.0)


# --- pure payload construction --------------------------------------------------


def test_format_decimal_strips_noise():
    assert format_decimal(0.000500) == "0.0005"
    assert format_decimal(1.0) == "1"
    assert format_decimal(50000.10) == "50000.1"


def test_build_market_order_params():
    params = build_order_params(order_request(0.123))
    assert params == {"symbol": "ETHUSDT", "side": "BUY", "type": "MARKET", "quantity": "0.123"}


def test_build_limit_order_requires_price():
    request = order_request().model_copy(update={"order_type": OrderType.LIMIT})
    with pytest.raises(OrderRejectedError):
        build_order_params(request)
    with_price = request.model_copy(update={"limit_price": 2999.5})
    params = build_order_params(with_price)
    assert params["price"] == "2999.5"
    assert params["timeInForce"] == "GTC"


def test_plain_stop_rejected_on_spot():
    request = order_request().model_copy(update={"order_type": OrderType.STOP})
    with pytest.raises(OrderRejectedError):
        build_order_params(request)


# --- signed submission (mocked transport) ------------------------------------------


def test_place_order_normalizes_signs_and_parses():
    captured: dict = {}
    client = make_client(captured=captured)
    order = client.place_order(order_request(0.1234567))

    assert captured["quantity"] == "0.123"          # rounded DOWN to step 0.001
    assert "signature" in captured and len(captured["signature"]) == 64
    assert "timestamp" in captured
    assert order.status is OrderStatus.FILLED
    assert order.order_id == "12345"
    assert order.avg_fill_price == pytest.approx(3000.0)
    assert order.fee == pytest.approx(0.369)


def test_order_below_min_notional_rejected_before_http():
    client = make_client()
    with pytest.raises(OrderRejectedError):
        client.place_order(order_request(0.001))    # 3 USDT < min 5


def test_live_orders_blocked_without_gate():
    client = make_client(mode="live", allow_live_orders=False)
    with pytest.raises(LiveTradingBlockedError):
        client.place_order(order_request())


def test_get_order_status_maps_terminal_state():
    client = make_client()
    order = client.get_order_status("12345", symbol="ETHUSDT")
    assert order.status is OrderStatus.FILLED
    assert json.loads(json.dumps(order.raw))["orderId"] == 12345
