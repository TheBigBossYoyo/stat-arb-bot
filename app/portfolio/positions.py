"""Local position book (the system's own view, reconciled against the broker)."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.types import Side


@dataclass
class PositionLot:
    symbol: str
    quantity: float = 0.0          # signed
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return self.quantity * (price - self.avg_entry_price)


@dataclass
class PositionBook:
    lots: dict[str, PositionLot] = field(default_factory=dict)

    def get(self, symbol: str) -> PositionLot:
        return self.lots.setdefault(symbol, PositionLot(symbol))

    def apply_fill(self, symbol: str, side: Side, quantity: float, price: float) -> float:
        """Update the book with a fill; returns realized PnL from any reduction."""
        lot = self.get(symbol)
        signed = side.sign * quantity
        realized = 0.0

        if lot.quantity * signed >= 0:  # increasing (or opening) position
            total = lot.quantity + signed
            if total != 0:
                lot.avg_entry_price = (
                    lot.avg_entry_price * abs(lot.quantity) + price * abs(signed)
                ) / abs(total)
            lot.quantity = total
        else:  # reducing / flipping
            closing = min(abs(signed), abs(lot.quantity))
            direction = 1.0 if lot.quantity > 0 else -1.0
            realized = direction * closing * (price - lot.avg_entry_price)
            lot.realized_pnl += realized
            lot.quantity += signed
            if lot.quantity * direction < 0:  # flipped through zero
                lot.avg_entry_price = price
        if abs(lot.quantity) < 1e-12:
            lot.quantity = 0.0
        return realized

    def as_dict(self) -> dict[str, float]:
        return {s: lot.quantity for s, lot in self.lots.items() if lot.quantity != 0.0}
