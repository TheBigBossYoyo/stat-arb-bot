"""Semi-atomic pair execution and position reconciliation."""

from __future__ import annotations

from datetime import UTC, datetime

from app.backtesting.broker_simulator import SimulatedBroker
from app.backtesting.commissions import ZeroCommission
from app.backtesting.slippage import FixedBpsSlippage
from app.core.exceptions import ExecutionError
from app.core.types import Side
from app.execution.pair_executor import Leg, PairExecutionStatus, PairExecutor
from app.execution.reconciliation import reconcile_positions
from app.risk.kill_switch import KillSwitch

TS = datetime(2025, 6, 1, tzinfo=UTC)
PRICES = {"AAA": 100.0, "BBB": 50.0}


def make_broker(**kwargs) -> SimulatedBroker:
    broker = SimulatedBroker(
        starting_cash=10_000.0,
        slippage=FixedBpsSlippage(0.0),
        commission=ZeroCommission(),
        **kwargs,
    )
    broker.set_market(PRICES, TS)
    return broker


class FlakyBroker(SimulatedBroker):
    """Fails the first `fail_plan[symbol]` executions of a symbol, then succeeds."""

    def __init__(self, fail_plan: dict[str, int], **kwargs) -> None:
        super().__init__(**kwargs)
        self.fail_plan = dict(fail_plan)

    def execute_market(self, symbol, side, quantity, ref_price=None):
        if self.fail_plan.get(symbol, 0) > 0:
            self.fail_plan[symbol] -= 1
            raise ExecutionError(f"injected failure for {symbol}")
        return super().execute_market(symbol, side, quantity, ref_price)


def legs() -> tuple[Leg, Leg]:
    return (
        Leg("AAA", Side.BUY, 1.0, liquidity_rank=0),
        Leg("BBB", Side.SELL, 2.0, liquidity_rank=1),
    )


def test_both_legs_fill():
    broker = make_broker()
    result = PairExecutor(broker).execute_pair("AAA|BBB", *legs())
    assert result.status is PairExecutionStatus.FILLED
    assert result.fill_a is not None and result.fill_a.symbol == "AAA"
    assert result.fill_b is not None and result.fill_b.symbol == "BBB"
    assert broker.position("AAA") == 1.0
    assert broker.position("BBB") == -2.0


def test_leg2_failure_rolls_back_leg1():
    broker = make_broker(fail_symbols={"BBB"})
    result = PairExecutor(broker, max_repair_attempts=2).execute_pair("AAA|BBB", *legs())
    assert result.status is PairExecutionStatus.ROLLED_BACK
    assert broker.position("AAA") == 0.0          # leg 1 flattened
    assert broker.position("BBB") == 0.0
    assert "rolled back" in result.incident


def test_leg2_recovers_via_hedge_repair():
    broker = FlakyBroker(
        {"BBB": 1},  # first attempt fails, retry succeeds
        starting_cash=10_000.0, slippage=FixedBpsSlippage(0.0), commission=ZeroCommission(),
    )
    broker.set_market(PRICES, TS)
    result = PairExecutor(broker, max_repair_attempts=2).execute_pair("AAA|BBB", *legs())
    assert result.status is PairExecutionStatus.FILLED
    assert broker.position("BBB") == -2.0


def test_rollback_failure_engages_kill_switch():
    # BBB always fails; AAA succeeds once (the entry) then fails (the rollback)
    broker = FlakyBroker(
        {"BBB": 99},
        starting_cash=10_000.0, slippage=FixedBpsSlippage(0.0), commission=ZeroCommission(),
    )
    broker.set_market(PRICES, TS)

    original = FlakyBroker.execute_market
    calls = {"AAA": 0}

    def wrapped(self, symbol, side, quantity, ref_price=None):
        if symbol == "AAA":
            calls["AAA"] += 1
            if calls["AAA"] > 1:
                raise ExecutionError("AAA down for rollback")
        return original(self, symbol, side, quantity, ref_price)

    broker.execute_market = wrapped.__get__(broker)

    switch = KillSwitch()
    result = PairExecutor(broker, kill_switch=switch, max_repair_attempts=1).execute_pair(
        "AAA|BBB", *legs()
    )
    assert result.status is PairExecutionStatus.ROLLBACK_FAILED
    assert switch.is_active
    assert "manual intervention" in result.incident.lower()


def test_leg1_rejection_means_no_position():
    broker = make_broker(fail_symbols={"AAA"})
    result = PairExecutor(broker).execute_pair("AAA|BBB", *legs())
    assert result.status is PairExecutionStatus.REJECTED
    assert broker.positions == {}


def test_liquidity_rank_orders_legs():
    broker = make_broker()
    leg_a, leg_b = legs()
    leg_a.liquidity_rank, leg_b.liquidity_rank = 1, 0  # BBB should go first now
    PairExecutor(broker).execute_pair("AAA|BBB", leg_a, leg_b)
    assert broker.fills[0].symbol == "BBB"


# --- reconciliation ---------------------------------------------------------------


def test_reconciliation_detects_mismatch():
    mismatches = reconcile_positions(
        local={"BTCUSDT": 1.0, "ETHUSDT": -2.0},
        broker={"BTCUSDT": 0.9, "ETHUSDT": -2.0},
    )
    assert len(mismatches) == 1
    assert mismatches[0].symbol == "BTCUSDT"
    assert mismatches[0].difference == -0.10000000000000009 or abs(
        mismatches[0].difference + 0.1
    ) < 1e-9


def test_reconciliation_clean_book():
    assert reconcile_positions(
        local={"BTCUSDT": 1.0}, broker={"BTCUSDT": 1.0}
    ) == []
    # symbol present on one side only with zero qty is clean too
    assert reconcile_positions(local={"X": 0.0}, broker={}) == []
