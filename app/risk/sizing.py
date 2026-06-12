"""Position sizing for pair trades.

Sizing convention (log-price hedge): if spread = log(A) - beta*log(B), then a
return-neutral hedge holds notional_B = beta * notional_A. Quantities are
rounded down to instrument step sizes; orders that round to zero or breach
minimum notional are rejected upstream.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.brokers.base import round_step
from app.core.exceptions import RiskViolationError


@dataclass
class PairSizing:
    qty_a: float
    qty_b: float
    notional_a: float
    notional_b: float
    target_notional: float


def size_pair(
    *,
    equity: float,
    target_pct: float,
    beta: float,
    price_a: float,
    price_b: float,
    max_notional_per_trade: float,
    spread_std: float | None = None,
    target_spread_vol: float | None = None,
    step_a: float = 0.0,
    step_b: float = 0.0,
) -> PairSizing:
    """Volatility-aware dollar sizing for one pair trade.

    Base notional = min(equity * target_pct, max_notional_per_trade), optionally
    scaled down when the spread is more volatile than the target (never scaled
    above 1x — volatility targeting only de-risks here).
    """
    if beta <= 0:
        raise RiskViolationError(f"refusing to size pair with non-positive hedge ratio beta={beta:.4f}")
    if price_a <= 0 or price_b <= 0:
        raise RiskViolationError("refusing to size with non-positive prices")
    if equity <= 0:
        raise RiskViolationError("no equity available")

    base = min(equity * target_pct, max_notional_per_trade)
    if spread_std and target_spread_vol and spread_std > 0:
        base *= min(1.0, target_spread_vol / spread_std)

    notional_a = base
    notional_b = beta * base

    qty_a = round_step(notional_a / price_a, step_a) if step_a else notional_a / price_a
    qty_b = round_step(notional_b / price_b, step_b) if step_b else notional_b / price_b
    if qty_a <= 0 or qty_b <= 0:
        raise RiskViolationError(
            f"pair size rounds to zero (notional_a={notional_a:.2f}, notional_b={notional_b:.2f})"
        )

    return PairSizing(
        qty_a=qty_a,
        qty_b=qty_b,
        notional_a=qty_a * price_a,
        notional_b=qty_b * price_b,
        target_notional=base,
    )
