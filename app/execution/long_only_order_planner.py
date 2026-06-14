"""Long-only order planner (Phase 5).

One entry point that turns a target long-only weight vector into a CONCRETE,
VALIDATED Trading 212 Invest/ISA order plan — the same plan used by shadow,
demo-preview and demo-execute. It composes:

* `Trading212Rebalancer` — builds the orders (no short, no margin, fractional /
  whole-share rounding, minimum order value, market-hours awareness, marketable
  limit to bound slippage),
* `order_validation.validate_plan` — checks the plan against the demo execution
  gate's order-/plan-level conditions.

It places nothing. The caller decides whether to send (demo only) based on the
validation result and the demo execution gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.brokers.trading212.instrument_cache import InstrumentCache
from app.brokers.trading212.order_validation import (
    OrderValidationConfig,
    ValidationResult,
    validate_plan,
)
from app.core.types import Side
from app.execution.trading212_rebalancer import (
    RebalanceConfig,
    RebalancePlan,
    Trading212Rebalancer,
)


@dataclass
class PlannedLongOnlyOrders:
    plan: RebalancePlan
    validation: ValidationResult
    target_weights: dict[str, float]

    @property
    def ok(self) -> bool:
        return self.validation.ok

    def order_rows(self) -> list[dict]:
        rows = []
        for o in self.plan.orders:
            r = o.request
            rows.append({
                "symbol": r.symbol, "side": r.side.value, "type": r.order_type.value,
                "quantity": round(r.quantity, 6),
                "limit_price": round(r.limit_price, 4) if r.limit_price else None,
                "ref_price": round(r.ref_price, 4),
                "notional": round(r.notional, 2),
                "target_weight": o.weight_after,
                "queued_for_open": o.queued_for_open,
            })
        return rows

    def summary(self) -> dict:
        s = self.plan.summary()
        s.update({"validated": self.validation.ok,
                  "market_open": self.validation.market_open,
                  "queued": self.validation.queued,
                  "n_skipped": len(self.plan.skipped)})
        return s


class LongOnlyOrderPlanner:
    def __init__(self, cache: InstrumentCache,
                 rebalance_config: RebalanceConfig | None = None,
                 validation_config: OrderValidationConfig | None = None) -> None:
        self.cache = cache
        self.rebalancer = Trading212Rebalancer(cache.as_dict(),
                                               rebalance_config or RebalanceConfig())
        self.validation_config = validation_config or OrderValidationConfig()

    def plan(
        self,
        target_weights: dict[str, float],
        positions: dict[str, float],
        cash: float,
        prices: dict[str, float],
        *,
        market_open: bool = True,
        now=None,
    ) -> PlannedLongOnlyOrders:
        # long-only by construction: clip any negative target to zero before planning
        tw = {s: max(0.0, float(w)) for s, w in target_weights.items()}
        plan = self.rebalancer.plan(tw, positions, cash, prices, market_open=market_open)
        validation = validate_plan(plan, self.cache, target_weights=tw, cash=cash,
                                   config=self.validation_config, now=now)
        return PlannedLongOnlyOrders(plan=plan, validation=validation, target_weights=tw)


def expected_slippage_bps(plan: RebalancePlan) -> float:
    """Mean limit-offset slippage (bps) across the plan's orders — the slippage
    the validation budget caps."""
    bps = []
    for o in plan.orders:
        r = o.request
        if r.limit_price and r.ref_price:
            bps.append(1e4 * abs(r.limit_price - r.ref_price) / r.ref_price)
    return round(sum(bps) / len(bps), 2) if bps else 0.0


def buy_sell_notional(plan: RebalancePlan) -> tuple[float, float]:
    buys = sum(o.request.notional for o in plan.orders if o.request.side is Side.BUY)
    sells = sum(o.request.notional for o in plan.orders if o.request.side is Side.SELL)
    return round(buys, 2), round(sells, 2)
