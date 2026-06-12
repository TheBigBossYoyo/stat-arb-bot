"""Semi-atomic pair execution.

A pair trade is two child orders that must both fill. The executor:
  1. places leg 1 (configurable ordering — more liquid leg first),
  2. places leg 2,
  3. if leg 2 fails: retries it up to `max_repair_attempts` (hedge repair),
  4. if repair fails: flattens leg 1 (rollback), logs the incident and
     optionally engages the kill switch.

An order is never assumed filled until the broker confirms the fill.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.backtesting.broker_simulator import SimulatedBroker
from app.brokers.models import Fill
from app.core.exceptions import ExecutionError, OrderRejectedError
from app.core.logging import audit, get_logger
from app.core.types import Side
from app.risk.kill_switch import KillSwitch

log = get_logger(__name__)


class PairExecutionStatus(str, Enum):
    FILLED = "filled"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"          # leg 2 failed; leg 1 flattened
    ROLLBACK_FAILED = "rollback_failed"  # manual intervention required


@dataclass
class Leg:
    symbol: str
    side: Side
    quantity: float
    liquidity_rank: int = 0   # lower = more liquid = execute first


@dataclass
class PairExecutionResult:
    status: PairExecutionStatus
    fill_a: Fill | None = None
    fill_b: Fill | None = None
    incident: str = ""

    @property
    def ok(self) -> bool:
        return self.status is PairExecutionStatus.FILLED


class PairExecutor:
    def __init__(
        self,
        broker: SimulatedBroker,
        kill_switch: KillSwitch | None = None,
        max_repair_attempts: int = 2,
        engage_kill_on_rollback_failure: bool = True,
    ) -> None:
        self.broker = broker
        self.kill_switch = kill_switch
        self.max_repair_attempts = max_repair_attempts
        self.engage_kill_on_rollback_failure = engage_kill_on_rollback_failure

    def execute_pair(self, pair_key: str, leg_a: Leg, leg_b: Leg) -> PairExecutionResult:
        first, second = sorted((leg_a, leg_b), key=lambda leg: leg.liquidity_rank)

        # --- leg 1 -----------------------------------------------------------
        try:
            fill_1 = self.broker.execute_market(first.symbol, first.side, first.quantity)
        except (ExecutionError, OrderRejectedError) as exc:
            audit("pair_leg1_rejected", pair=pair_key, symbol=first.symbol, error=str(exc))
            return PairExecutionResult(PairExecutionStatus.REJECTED, incident=f"leg1: {exc}")

        # --- leg 2 with hedge repair -------------------------------------------
        fill_2: Fill | None = None
        last_error = ""
        for attempt in range(1 + self.max_repair_attempts):
            try:
                fill_2 = self.broker.execute_market(second.symbol, second.side, second.quantity)
                break
            except (ExecutionError, OrderRejectedError) as exc:
                last_error = str(exc)
                log.warning(
                    "pair %s leg2 %s failed (attempt %d/%d): %s",
                    pair_key, second.symbol, attempt + 1, 1 + self.max_repair_attempts, exc,
                )

        if fill_2 is not None:
            fills = {leg_a.symbol: None, leg_b.symbol: None}
            fills[first.symbol] = fill_1
            fills[second.symbol] = fill_2
            return PairExecutionResult(
                PairExecutionStatus.FILLED,
                fill_a=fills[leg_a.symbol], fill_b=fills[leg_b.symbol],
            )

        # --- rollback leg 1 -------------------------------------------------------
        audit("pair_leg2_failed", pair=pair_key, symbol=second.symbol, error=last_error)
        try:
            self.broker.execute_market(first.symbol, first.side.opposite, first.quantity)
            incident = (
                f"leg2 ({second.symbol}) failed after {self.max_repair_attempts} repair "
                f"attempts: {last_error}; leg1 ({first.symbol}) rolled back"
            )
            audit("pair_rolled_back", pair=pair_key, incident=incident)
            log.error("pair %s rolled back: %s", pair_key, incident)
            return PairExecutionResult(PairExecutionStatus.ROLLED_BACK, incident=incident)
        except (ExecutionError, OrderRejectedError) as exc:
            incident = (
                f"leg2 failed AND rollback of leg1 ({first.symbol}) failed: {exc}. "
                "UNHEDGED POSITION — manual intervention required."
            )
            audit("pair_rollback_failed", pair=pair_key, incident=incident)
            log.critical("pair %s: %s", pair_key, incident)
            if self.kill_switch and self.engage_kill_on_rollback_failure:
                self.kill_switch.engage(f"pair {pair_key}: {incident}")
            return PairExecutionResult(PairExecutionStatus.ROLLBACK_FAILED, incident=incident)
