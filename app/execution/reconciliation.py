"""Position reconciliation.

After every execution cycle the locally tracked book is compared with the
broker's reported positions. Any mismatch beyond tolerance is an incident:
trading should halt until the difference is explained.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import audit, get_logger

log = get_logger(__name__)


@dataclass
class PositionMismatch:
    symbol: str
    local_qty: float
    broker_qty: float

    @property
    def difference(self) -> float:
        return self.broker_qty - self.local_qty


def reconcile_positions(
    local: dict[str, float],
    broker: dict[str, float],
    tolerance: float = 1e-9,
) -> list[PositionMismatch]:
    """Compare signed position quantities. Returns all mismatches (empty = clean)."""
    mismatches: list[PositionMismatch] = []
    for symbol in sorted(set(local) | set(broker)):
        local_qty = local.get(symbol, 0.0)
        broker_qty = broker.get(symbol, 0.0)
        if abs(local_qty - broker_qty) > tolerance:
            mismatches.append(PositionMismatch(symbol, local_qty, broker_qty))
    if mismatches:
        for m in mismatches:
            log.error("position mismatch %s: local=%s broker=%s", m.symbol, m.local_qty, m.broker_qty)
        audit("reconciliation_mismatch",
              mismatches=[{"symbol": m.symbol, "local": m.local_qty, "broker": m.broker_qty}
                          for m in mismatches])
    return mismatches
