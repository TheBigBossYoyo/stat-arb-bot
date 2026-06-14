"""Tests for the Phase 5 Trading 212 DEMO order path (validation + gate + executor).

Everything here is offline (a fake client). The point is to prove the SAFETY
properties: no shorting, no margin, no CFDs, minimum order value, correct
share rounding, market-hours behaviour, the full demo execution gate, and that
demo orders are refused without explicit confirmation — and live is never reachable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.brokers.models import AccountState, Instrument, Order, OrderRequest, Position
from app.brokers.trading212.demo_execution import (
    Trading212DemoExecutor,
    evaluate_demo_gate,
)
from app.brokers.trading212.instrument_cache import (
    InstrumentCache,
    load_instrument_cache,
    synthetic_instruments,
)
from app.brokers.trading212.order_validation import (
    is_us_market_open,
    validate_target_weights,
)
from app.core.exceptions import LiveTradingBlockedError
from app.core.types import AssetClass, OrderStatus, Side
from app.execution.long_only_demo_executor import LongOnlyDemoExecutor
from app.execution.long_only_order_planner import LongOnlyOrderPlanner
from app.execution.long_only_reconciliation import reconcile_long_only

UNIVERSE = ["AAA", "BBB", "CCC", "DDD", "EEE"]
PRICES = {s: 100.0 for s in UNIVERSE}


# --- fakes --------------------------------------------------------------------

class FakeClient:
    def __init__(self, cash=10_000.0, positions=None, instruments=None):
        self.cash = cash
        self._positions = positions or {}
        self._instruments = instruments
        self.placed: list[OrderRequest] = []

    def get_account(self):
        return AccountState(
            broker="trading212", currency="USD", cash=self.cash, equity=self.cash,
            positions=[Position(symbol=s, quantity=q) for s, q in self._positions.items()])

    def get_instruments(self, symbols=None):
        return list(self._instruments or [])

    def place_order(self, request: OrderRequest) -> Order:
        self.placed.append(request)
        return Order(order_id=f"DEMO-{len(self.placed)}", request=request, status=OrderStatus.NEW)


def make_settings(tmp_path, **over):
    base = dict(trading212_enabled=True, trading212_mode="demo",
                trading212_allow_demo_orders=True, trading212_api_key="k",
                trading212_api_secret="s", trading212_account_type="invest",
                live_trading_allowed=False, runtime_dir=tmp_path)
    base.update(over)
    return SimpleNamespace(**base)


def make_planner(cache=None):
    cache = cache or InstrumentCache(synthetic_instruments(UNIVERSE))
    return LongOnlyOrderPlanner(cache)


# --- target-weight constraints ------------------------------------------------

def test_validate_target_weights_rejects_shorts_and_leverage():
    ok, reasons = validate_target_weights({"A": 0.5, "B": -0.2})
    assert not ok and any("negative" in r for r in reasons)
    ok2, reasons2 = validate_target_weights({"A": 0.7, "B": 0.6})
    assert not ok2 and any("gross" in r for r in reasons2)
    ok3, _ = validate_target_weights({"A": 0.5, "B": 0.4})
    assert ok3


# --- instrument cache / CFD + tradability -------------------------------------

def test_synthetic_instruments_are_tradable_equities():
    cache = InstrumentCache(synthetic_instruments(UNIVERSE))
    ok, _ = cache.is_tradable("AAA")
    assert ok and cache.is_fractional("AAA")


def test_non_equity_and_missing_instruments_are_not_tradable():
    cache = InstrumentCache({
        "CFDX": Instrument(broker="trading212", symbol="CFDX",
                           asset_class=AssetClass.CFD, fractional=True),
    })
    assert cache.is_tradable("CFDX")[0] is False     # CFDs are never Invest/ISA-eligible
    assert cache.is_tradable("NOPE")[0] is False      # not offered


def test_load_instrument_cache_falls_back_to_synthetic(tmp_path):
    cache = load_instrument_cache(UNIVERSE, client=None, runtime_dir=tmp_path)
    assert cache.source == "synthetic"
    assert cache.is_tradable("AAA")[0]


# --- plan validation: min value, rounding, slippage, cash ---------------------

def test_plan_validation_passes_for_clean_long_only_plan():
    planner = make_planner()
    weights = {s: 0.2 for s in UNIVERSE}
    planned = planner.plan(weights, positions={}, cash=10_000.0, prices=PRICES,
                           market_open=True)
    assert planned.ok
    assert planned.validation.checks["no negative target weights"]
    assert planned.validation.checks["gross exposure <= 1.0"]
    assert planned.validation.checks["account cash sufficient (no margin)"]


def test_plan_validation_blocks_untradable_instrument():
    cache = InstrumentCache(synthetic_instruments(["AAA", "BBB"]))  # CCC missing
    planner = LongOnlyOrderPlanner(cache)
    planned = planner.plan({"AAA": 0.3, "CCC": 0.3}, positions={}, cash=10_000.0,
                           prices={"AAA": 100.0, "CCC": 100.0}, market_open=True)
    # CCC is not in the cache -> the rebalancer skips it; plan stays valid + long-only
    assert all(o.request.symbol != "CCC" for o in planned.plan.orders)
    assert any(sym == "CCC" for sym, _ in planned.plan.skipped)


def test_plan_validation_enforces_whole_share_rounding():
    insts = synthetic_instruments(UNIVERSE)
    insts["AAA"] = Instrument(broker="trading212", symbol="AAA", asset_class=AssetClass.EQUITY,
                              fractional=False, step_size=0.0, min_notional=1.0)
    planner = LongOnlyOrderPlanner(InstrumentCache(insts))
    planned = planner.plan({"AAA": 0.5}, positions={}, cash=10_000.0, prices=PRICES,
                           market_open=True)
    aaa = [o for o in planned.plan.orders if o.request.symbol == "AAA"]
    assert aaa and aaa[0].request.quantity == float(int(aaa[0].request.quantity))  # whole shares


def test_plan_validation_blocks_when_buy_exceeds_cash_no_margin():
    planner = make_planner()
    # only tiny cash but full-weight targets -> the planner scales buys to cash,
    # so the validated plan never spends more than settled cash (no margin).
    planned = planner.plan({s: 0.2 for s in UNIVERSE}, positions={}, cash=50.0,
                           prices=PRICES, market_open=True)
    buys = sum(o.request.notional for o in planned.plan.orders if o.request.side is Side.BUY)
    assert buys <= 50.0 + 1e-6
    assert planned.validation.checks["account cash sufficient (no margin)"]


def test_market_hours_open_and_closed():
    open_dt = datetime(2026, 6, 10, 15, 0, tzinfo=UTC)   # Wed ~11:00 ET
    closed_dt = datetime(2026, 6, 13, 15, 0, tzinfo=UTC)  # Sat
    assert is_us_market_open(open_dt) is True
    assert is_us_market_open(closed_dt) is False


# --- demo execution gate ------------------------------------------------------

def _good_validation():
    return make_planner().plan({s: 0.2 for s in UNIVERSE}, positions={}, cash=10_000.0,
                               prices=PRICES, market_open=True).validation


def test_demo_gate_all_conditions_pass(tmp_path):
    gate = evaluate_demo_gate(make_settings(tmp_path), confirm_demo=True,
                              kill_switch_active=False, validation=_good_validation(),
                              paper_eligible=True, market_data_fresh=True)
    assert gate.ok


def test_demo_gate_refuses_without_confirmation(tmp_path):
    gate = evaluate_demo_gate(make_settings(tmp_path), confirm_demo=False,
                              kill_switch_active=False, validation=_good_validation(),
                              paper_eligible=True, market_data_fresh=True)
    assert not gate.ok
    assert any("confirm" in r.lower() for r in gate.reasons)


def test_demo_gate_refuses_when_demo_orders_not_allowed(tmp_path):
    s = make_settings(tmp_path, trading212_allow_demo_orders=False)
    gate = evaluate_demo_gate(s, confirm_demo=True, kill_switch_active=False,
                              validation=_good_validation(), paper_eligible=True,
                              market_data_fresh=True)
    assert not gate.ok


def test_demo_gate_refuses_when_kill_switch_active_or_not_paper_eligible(tmp_path):
    s = make_settings(tmp_path)
    assert not evaluate_demo_gate(s, confirm_demo=True, kill_switch_active=True,
                                  validation=_good_validation(), paper_eligible=True,
                                  market_data_fresh=True).ok
    assert not evaluate_demo_gate(s, confirm_demo=True, kill_switch_active=False,
                                  validation=_good_validation(), paper_eligible=False,
                                  market_data_fresh=True).ok


def test_demo_gate_refuses_when_global_live_trading_on(tmp_path):
    s = make_settings(tmp_path, live_trading_allowed=True)
    gate = evaluate_demo_gate(s, confirm_demo=True, kill_switch_active=False,
                              validation=_good_validation(), paper_eligible=True,
                              market_data_fresh=True)
    assert not gate.ok
    assert any("live" in r.lower() for r in gate.reasons)


# --- executor: live hard-block, shadow, preview, execute ----------------------

def test_executor_refuses_live_mode(tmp_path):
    s = make_settings(tmp_path, trading212_mode="live")
    with pytest.raises(LiveTradingBlockedError):
        Trading212DemoExecutor(s).connect()


def test_shadow_mode_sends_nothing(tmp_path):
    fake = FakeClient()
    demo = Trading212DemoExecutor(make_settings(tmp_path), client=fake)
    execu = LongOnlyDemoExecutor(make_settings(tmp_path),
                                 InstrumentCache(synthetic_instruments(UNIVERSE)),
                                 demo_executor=demo)
    res = execu.run("shadow", {s: 0.2 for s in UNIVERSE}, positions={}, cash=10_000.0,
                    prices=PRICES, market_open=True)
    assert res.sent_orders is False
    assert fake.placed == []                          # never connected/sent


def test_demo_preview_connects_but_sends_nothing(tmp_path):
    fake = FakeClient(cash=10_000.0)
    demo = Trading212DemoExecutor(make_settings(tmp_path), client=fake)
    execu = LongOnlyDemoExecutor(make_settings(tmp_path),
                                 InstrumentCache(synthetic_instruments(UNIVERSE)),
                                 demo_executor=demo)
    res = execu.run("demo_preview", {s: 0.2 for s in UNIVERSE}, positions={}, cash=0.0,
                    prices=PRICES, market_open=True)
    assert res.account is not None                    # connected + read account
    assert res.sent_orders is False
    assert fake.placed == []                          # preview sends nothing


def test_demo_execute_submits_only_when_gate_passes(tmp_path):
    fake = FakeClient(cash=10_000.0)
    demo = Trading212DemoExecutor(make_settings(tmp_path), client=fake)
    execu = LongOnlyDemoExecutor(make_settings(tmp_path),
                                 InstrumentCache(synthetic_instruments(UNIVERSE)),
                                 demo_executor=demo)
    res = execu.run("demo_execute", {s: 0.2 for s in UNIVERSE}, positions={}, cash=0.0,
                    prices=PRICES, confirm_demo=True, paper_eligible=True,
                    market_data_fresh=True, market_open=True)
    assert res.gate.ok
    assert res.sent_orders is True
    assert len(fake.placed) == len(res.planned.plan.orders) > 0
    assert all(o.side is Side.BUY for o in fake.placed)   # long-only: buys only


def test_demo_execute_refused_without_confirm_submits_nothing(tmp_path):
    fake = FakeClient(cash=10_000.0)
    demo = Trading212DemoExecutor(make_settings(tmp_path), client=fake)
    execu = LongOnlyDemoExecutor(make_settings(tmp_path),
                                 InstrumentCache(synthetic_instruments(UNIVERSE)),
                                 demo_executor=demo)
    res = execu.run("demo_execute", {s: 0.2 for s in UNIVERSE}, positions={}, cash=0.0,
                    prices=PRICES, confirm_demo=False, paper_eligible=True,
                    market_data_fresh=True, market_open=True)
    assert res.gate.ok is False
    assert res.sent_orders is False
    assert fake.placed == []                          # nothing sent


# --- reconciliation -----------------------------------------------------------

def test_reconcile_flags_short_positions():
    rep = reconcile_long_only({"AAA": 0.5}, {"AAA": -3.0}, {"AAA": 100.0}, cash=1000.0)
    assert rep.n_short_positions == 1
    assert not rep.in_sync                              # a short can never be in sync


def test_reconcile_in_sync_when_matching():
    # equity 10000, target AAA 50% -> 50 shares @100; hold exactly that
    rep = reconcile_long_only({"AAA": 0.5}, {"AAA": 50.0}, {"AAA": 100.0}, cash=5000.0)
    assert rep.n_short_positions == 0
    assert rep.in_sync
