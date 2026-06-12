"""Capability matrix enforcement and order normalization. No live API calls."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from app.brokers.base import (
    BrokerCapabilities,
    load_capabilities,
    normalize_quantity,
    round_step,
    round_tick,
)
from app.brokers.binance.signing import sign_query
from app.brokers.models import Instrument
from app.brokers.trading212.auth import basic_auth_header
from app.brokers.trading212.client import Trading212Client
from app.core.exceptions import (
    BrokerNotEnabledError,
    CapabilityError,
    OrderRejectedError,
)
from app.core.types import AssetClass


def caps(name: str) -> BrokerCapabilities:
    return load_capabilities()[name]


# --- capability matrix --------------------------------------------------------


def test_trading212_cfds_are_unsupported():
    t212 = caps("trading212")
    ok, reason = t212.supports(asset_class="cfd")
    assert not ok and "cfd" in reason.lower()
    with pytest.raises(CapabilityError):
        t212.require(asset_class="cfd")


def test_trading212_shorting_and_margin_unsupported():
    t212 = caps("trading212")
    assert not t212.supports(shorting=True)[0]
    assert not t212.supports(margin=True)[0]
    assert t212.supports(asset_class="equity", order_type="limit")[0]


def test_binance_spot_capabilities():
    spot = caps("binance_spot")
    assert spot.supports(asset_class=AssetClass.CRYPTO_SPOT, order_type="market")[0]
    assert not spot.supports(shorting=True)[0]
    assert not spot.supports(order_type="stop")[0]  # plain stop not in spot matrix


def test_trading212_client_rejects_cfd_account_type():
    with pytest.raises(CapabilityError):
        Trading212Client(api_key="k", api_secret="s", enabled=True, account_type="cfd")


def test_disabled_connectors_refuse_to_construct():
    from app.brokers.binance.client import BinanceClient

    with pytest.raises(BrokerNotEnabledError):
        BinanceClient(api_key="k", api_secret="s", enabled=False)
    with pytest.raises(BrokerNotEnabledError):
        Trading212Client(api_key="k", api_secret="s", enabled=False)


# --- precision normalization -----------------------------------------------------


def test_round_step_is_decimal_safe():
    assert round_step(0.123456, 0.001) == 0.123
    assert round_step(2.6, 0.1) == 2.6          # no 2.5999999 float dust
    assert round_step(1.0, 0.0) == 1.0          # zero step = unconstrained
    assert round_tick(50000.37, 0.01) == 50000.37


def instrument(**overrides) -> Instrument:
    base = dict(
        broker="binance_spot", symbol="ETHUSDT", asset_class=AssetClass.CRYPTO_SPOT,
        step_size=0.001, min_quantity=0.001, min_notional=5.0, tick_size=0.01,
    )
    base.update(overrides)
    return Instrument(**base)


def test_normalize_quantity_rounds_down_to_step():
    qty = normalize_quantity(0.123456, instrument(), ref_price=3000.0)
    assert qty == 0.123


def test_normalize_quantity_rejects_below_min_notional():
    with pytest.raises(OrderRejectedError):
        normalize_quantity(0.001, instrument(), ref_price=3000.0)  # 3 USDT < 5


def test_normalize_quantity_rejects_zero_after_rounding():
    with pytest.raises(OrderRejectedError):
        normalize_quantity(0.0004, instrument(), ref_price=3000.0)


# --- auth helpers -------------------------------------------------------------------


def test_binance_hmac_signature_matches_reference():
    params = {"symbol": "BTCUSDT", "side": "BUY", "timestamp": 1700000000000}
    expected = hmac.new(
        b"secret", b"symbol=BTCUSDT&side=BUY&timestamp=1700000000000", hashlib.sha256
    ).hexdigest()
    assert sign_query(params, "secret") == expected


def test_trading212_basic_auth_header():
    header = basic_auth_header("mykey", "mysecret")
    assert header["Authorization"] == "Basic bXlrZXk6bXlzZWNyZXQ="
