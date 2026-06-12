"""Simulated broker used by both the backtester and the paper trader.

Synthetic shorting is allowed by default (paper mode) so market-neutral
strategies can be evaluated; set allow_short=False to simulate a true spot
account. `fail_symbols` injects execution failures for pair-leg tests.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.backtesting.commissions import CommissionModel, PercentCommission
from app.backtesting.slippage import FixedBpsSlippage, SlippageModel
from app.brokers.models import Fill
from app.core.exceptions import ExecutionError, OrderRejectedError
from app.core.types import Side


class SimulatedBroker:
    name = "simulated"

    def __init__(
        self,
        starting_cash: float = 10_000.0,
        slippage: SlippageModel | None = None,
        commission: CommissionModel | None = None,
        allow_short: bool = True,
        fail_symbols: set[str] | None = None,
    ) -> None:
        self.cash = starting_cash
        self.starting_cash = starting_cash
        self.slippage = slippage or FixedBpsSlippage(5.0)
        self.commission = commission or PercentCommission(10.0)
        self.allow_short = allow_short
        self.fail_symbols = fail_symbols or set()
        self.positions: dict[str, float] = {}
        self.fees_paid = 0.0
        self.fills: list[Fill] = []
        self._prices: dict[str, float] = {}
        self._ts: datetime = datetime(2020, 1, 1, tzinfo=UTC)

    # -- market state ------------------------------------------------------------

    def set_market(self, prices: dict[str, float], ts: datetime) -> None:
        self._prices.update(prices)
        self._ts = ts

    def price(self, symbol: str) -> float:
        try:
            return self._prices[symbol]
        except KeyError as exc:
            raise ExecutionError(f"no market price for {symbol}") from exc

    # -- account ---------------------------------------------------------------------

    def position(self, symbol: str) -> float:
        return self.positions.get(symbol, 0.0)

    def equity(self, prices: dict[str, float] | None = None) -> float:
        marks = prices or self._prices
        value = self.cash
        for symbol, qty in self.positions.items():
            value += qty * marks.get(symbol, 0.0)
        return value

    def exposures(self) -> tuple[float, float]:
        gross = net = 0.0
        for symbol, qty in self.positions.items():
            value = qty * self._prices.get(symbol, 0.0)
            gross += abs(value)
            net += value
        return gross, net

    # -- execution ----------------------------------------------------------------------

    def execute_market(
        self,
        symbol: str,
        side: Side,
        quantity: float,
        ref_price: float | None = None,
    ) -> Fill:
        """Immediate market fill at ref price +/- slippage. Raises on failure."""
        if quantity <= 0:
            raise OrderRejectedError(f"{symbol}: quantity must be positive, got {quantity}")
        if symbol in self.fail_symbols:
            raise ExecutionError(f"injected execution failure for {symbol}")

        price = self.slippage.fill_price(side, ref_price if ref_price is not None else self.price(symbol))
        new_qty = self.position(symbol) + side.sign * quantity
        if not self.allow_short and new_qty < -1e-12:
            raise OrderRejectedError(
                f"{symbol}: shorting not allowed on this account "
                f"(position {self.position(symbol)}, sell {quantity})"
            )

        notional = quantity * price
        fee = self.commission.fee(notional)
        self.cash -= side.sign * notional
        self.cash -= fee
        self.fees_paid += fee
        self.positions[symbol] = new_qty
        if abs(self.positions[symbol]) < 1e-12:
            del self.positions[symbol]

        fill = Fill(ts=self._ts, symbol=symbol, side=side, quantity=quantity, price=price, fee=fee)
        self.fills.append(fill)
        return fill

    def flatten(self, symbol: str) -> Fill | None:
        qty = self.position(symbol)
        if qty == 0:
            return None
        side = Side.SELL if qty > 0 else Side.BUY
        return self.execute_market(symbol, side, abs(qty))
