"""Order routing policy for pair legs.

Decides leg ordering (most liquid first — the harder fill should not be the
one left naked) and order type (limit preferred when the quoted spread is
wide). Rejects routes whose quoted spread already exceeds the slippage
budget: if crossing costs more than the modeled edge, don't trade.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.exceptions import RiskViolationError
from app.core.types import OrderType
from app.execution.pair_executor import Leg


@dataclass
class RoutePlan:
    first: Leg
    second: Leg
    order_type: OrderType
    reason: str = ""


def plan_pair_route(
    leg_a: Leg,
    leg_b: Leg,
    *,
    quote_volume_24h: dict[str, float] | None = None,
    quoted_spread_bps: dict[str, float] | None = None,
    max_spread_bps: float = 25.0,
    prefer_limit: bool = True,
    wide_spread_bps: float = 8.0,
) -> RoutePlan:
    spreads = quoted_spread_bps or {}
    volumes = quote_volume_24h or {}

    worst_spread = max(
        (spreads.get(leg.symbol, 0.0) for leg in (leg_a, leg_b)), default=0.0
    )
    if worst_spread > max_spread_bps:
        raise RiskViolationError(
            f"quoted spread {worst_spread:.1f}bps exceeds budget {max_spread_bps}bps — "
            "crossing would destroy the edge"
        )

    # liquidity ranking: higher 24h volume = rank 0 = execute first
    ranked = sorted((leg_a, leg_b), key=lambda leg: -volumes.get(leg.symbol, 0.0))
    ranked[0].liquidity_rank = 0
    ranked[1].liquidity_rank = 1

    order_type = (
        OrderType.LIMIT if prefer_limit and worst_spread >= wide_spread_bps else OrderType.MARKET
    )
    return RoutePlan(
        first=ranked[0],
        second=ranked[1],
        order_type=order_type,
        reason=f"worst spread {worst_spread:.1f}bps; "
               f"{'limit (wide spread)' if order_type is OrderType.LIMIT else 'market'}",
    )
