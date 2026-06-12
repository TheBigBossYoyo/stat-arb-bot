"""Risk manager: limits, kill switch, capability gating."""

from __future__ import annotations

from datetime import UTC, datetime

from app.brokers.base import load_capabilities
from app.brokers.models import OrderRequest, SignalMetadata
from app.core.types import OrderType, Side
from app.risk.exposure import PortfolioState
from app.risk.kill_switch import KillSwitch
from app.risk.risk_manager import RiskLimits, RiskManager, load_risk_limits


def make_state(**overrides) -> PortfolioState:
    defaults = dict(
        equity=10_000.0, cash=10_000.0, daily_start_equity=10_000.0,
        peak_equity=10_000.0, gross_exposure=0.0, net_exposure=0.0,
        open_pairs=0, open_positions=0, trades_today=0,
    )
    defaults.update(overrides)
    return PortfolioState(**defaults)


def make_risk(**limit_overrides) -> RiskManager:
    limits = RiskLimits(**limit_overrides)
    return RiskManager(limits=limits, kill_switch=KillSwitch(), capabilities=load_capabilities())


def test_oversized_trade_is_rejected():
    risk = make_risk(max_notional_per_trade=50.0)
    decision = risk.validate_pair_entry(
        broker="binance_spot", notional_a=500.0, notional_b=500.0, state=make_state(),
    )
    assert not decision.approved
    assert any(c.name == "max_notional_per_trade" for c in decision.failures)


def test_normal_trade_is_approved():
    risk = make_risk()
    decision = risk.validate_pair_entry(
        broker="binance_spot", notional_a=40.0, notional_b=44.0, state=make_state(),
    )
    assert decision.approved, decision.reason()


def test_max_open_pairs_enforced():
    risk = make_risk(max_open_pairs=3)
    decision = risk.validate_pair_entry(
        broker="binance_spot", notional_a=40.0, notional_b=44.0,
        state=make_state(open_pairs=3),
    )
    assert not decision.approved
    assert any(c.name == "max_open_pairs" for c in decision.failures)


def test_gross_exposure_enforced():
    risk = make_risk(max_gross_exposure=100.0)
    decision = risk.validate_pair_entry(
        broker="binance_spot", notional_a=40.0, notional_b=44.0,
        state=make_state(gross_exposure=50.0),
    )
    assert not decision.approved


def test_kill_switch_blocks_everything():
    risk = make_risk()
    risk.kill_switch.engage("test")
    entry = risk.validate_pair_entry(
        broker="binance_spot", notional_a=10.0, notional_b=10.0, state=make_state(),
    )
    assert not entry.approved
    order = OrderRequest(broker="binance_spot", symbol="BTCUSDT", side=Side.BUY,
                         quantity=0.001, ref_price=50_000.0)
    assert not risk.validate_order(order, make_state()).approved


def test_daily_loss_engages_kill_switch():
    risk = make_risk(max_daily_loss_pct=1.0)
    state = make_state(equity=9_850.0)  # -1.5% on the day
    triggered = risk.update_equity(state)
    assert triggered and risk.kill_switch.is_active


def test_drawdown_engages_kill_switch():
    risk = make_risk(max_total_drawdown_pct=5.0)
    state = make_state(equity=9_000.0, daily_start_equity=9_050.0, peak_equity=10_000.0)
    triggered = risk.update_equity(state)
    assert any("drawdown" in t for t in triggered)
    assert risk.kill_switch.is_active


def test_shorting_capability_rejected_outside_paper_mode():
    risk = make_risk()
    decision = risk.validate_pair_entry(
        broker="binance_spot", notional_a=40.0, notional_b=44.0, state=make_state(),
        requires_short=True, paper_mode=False,
    )
    assert not decision.approved
    assert any(c.name == "broker_capability" for c in decision.failures)
    # same trade in paper mode (synthetic shorting) is fine
    assert risk.validate_pair_entry(
        broker="binance_spot", notional_a=40.0, notional_b=44.0, state=make_state(),
        requires_short=True, paper_mode=True,
    ).approved


def test_unsupported_order_type_rejected():
    risk = make_risk()
    order = OrderRequest(broker="binance_spot", symbol="BTCUSDT", side=Side.BUY,
                         order_type=OrderType.STOP, quantity=0.0001, ref_price=50_000.0)
    decision = risk.validate_order(order, make_state())
    assert not decision.approved
    assert any(c.name == "broker_capability" for c in decision.failures)


def test_excess_expected_slippage_rejected():
    risk = make_risk(max_slippage_bps=25.0)
    order = OrderRequest(
        broker="binance_spot", symbol="BTCUSDT", side=Side.BUY, quantity=0.0001,
        ref_price=50_000.0, metadata=SignalMetadata(expected_slippage_bps=80.0),
    )
    assert not risk.validate_order(order, make_state()).approved


def test_trades_per_day_counter_rolls_over():
    risk = make_risk(max_trades_per_day=1)
    risk.roll_day(datetime(2025, 6, 1, tzinfo=UTC))
    risk.register_trade()
    rejected = risk.validate_pair_entry(
        broker="binance_spot", notional_a=10.0, notional_b=11.0, state=make_state(),
    )
    assert not rejected.approved
    assert risk.roll_day(datetime(2025, 6, 2, tzinfo=UTC))
    approved = risk.validate_pair_entry(
        broker="binance_spot", notional_a=10.0, notional_b=11.0, state=make_state(),
    )
    assert approved.approved


def test_load_risk_limits_with_overrides():
    limits = load_risk_limits(overrides={"max_open_pairs": 7})
    assert limits.max_open_pairs == 7
    assert limits.max_daily_loss_pct == 2.0  # from yaml defaults
