"""Portfolio state snapshot used by the risk manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PortfolioState:
    equity: float
    cash: float
    daily_start_equity: float
    peak_equity: float
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    open_pairs: int = 0
    open_positions: int = 0
    trades_today: int = 0
    notional_by_symbol: dict[str, float] = field(default_factory=dict)
    ts: datetime | None = None

    @property
    def daily_pnl(self) -> float:
        return self.equity - self.daily_start_equity

    @property
    def daily_loss_pct(self) -> float:
        if self.daily_start_equity <= 0:
            return 0.0
        return max(0.0, -self.daily_pnl / self.daily_start_equity * 100.0)

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity * 100.0)


def compute_exposures(positions: dict[str, float], prices: dict[str, float]) -> tuple[float, float]:
    """(gross, net) exposure from signed quantities and current prices."""
    gross = 0.0
    net = 0.0
    for symbol, qty in positions.items():
        value = qty * prices.get(symbol, 0.0)
        gross += abs(value)
        net += value
    return gross, net
