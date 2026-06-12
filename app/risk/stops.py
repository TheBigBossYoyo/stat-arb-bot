"""Hard stop policies enforced by the risk layer.

Z-stops and time-stops live inside strategies (they are signal logic); the
hard MONEY stop lives here because it must fire even if a strategy
misbehaves: an open pair whose unrealized loss breaches max_pair_loss is
force-closed by the engine/paper trader regardless of what the model thinks.
"""

from __future__ import annotations


def unrealized_pair_pnl(
    *,
    direction: int,            # +1 long spread, -1 short spread
    qty_a: float,
    qty_b: float,
    entry_price_a: float,
    entry_price_b: float,
    mark_a: float,
    mark_b: float,
    entry_fees: float = 0.0,
) -> float:
    """Mark-to-market PnL of an open pair (entry fees included, exit fees not)."""
    signed_a = direction * qty_a
    signed_b = -direction * qty_b
    return (
        signed_a * (mark_a - entry_price_a)
        + signed_b * (mark_b - entry_price_b)
        - entry_fees
    )


def pair_loss_stop_triggered(unrealized: float, max_pair_loss: float) -> bool:
    """True when the pair must be force-closed."""
    return max_pair_loss > 0 and unrealized < -abs(max_pair_loss)
