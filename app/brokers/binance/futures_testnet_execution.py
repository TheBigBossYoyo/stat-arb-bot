"""Binance futures TESTNET / paper execution (Path B) — live is blocked.

Order placement for the crypto-futures path is restricted to:

* **paper** — fully simulated fills at the mark price + modeled slippage/fees,
  no network, no keys; and
* **testnet** — would route to testnet.binancefuture.com with TESTNET keys only.

**Mainnet live trading is refused unconditionally here**, regardless of config —
the futures path is research/paper/testnet until a supervised period and an
explicit, separate live-enablement step exist. There is no code path in this
module that can send an order to mainnet.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.core.exceptions import CapabilityError
from app.core.logging import get_logger
from app.core.types import OrderStatus, Side

log = get_logger(__name__)

ALLOWED_MODES = ("paper", "testnet")


@dataclass
class FuturesFill:
    order_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    fee: float
    status: OrderStatus = OrderStatus.FILLED
    simulated: bool = True


@dataclass
class FuturesExecutionConfig:
    mode: str = "paper"               # paper | testnet  (never live)
    taker_fee_bps: float = 4.0
    slippage_bps: float = 3.0


@dataclass
class FuturesExecutionReport:
    fills: list[FuturesFill] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)
    mode: str = "paper"


class FuturesTestnetExecutor:
    """Simulated/testnet executor. Refuses mainnet live by construction."""

    def __init__(self, config: FuturesExecutionConfig | None = None) -> None:
        self.cfg = config or FuturesExecutionConfig()
        if self.cfg.mode not in ALLOWED_MODES:
            raise CapabilityError(
                f"futures execution mode {self.cfg.mode!r} not allowed — only "
                f"{ALLOWED_MODES}. Mainnet live trading is blocked.")

    def execute_target(
        self,
        target_weights: dict[str, float],
        positions: dict[str, float],
        equity: float,
        mark_prices: dict[str, float],
    ) -> FuturesExecutionReport:
        """Turn target weights into simulated futures fills (paper mode).

        Futures CAN short, so target quantities may be negative. No margin check
        beyond the engine/risk leverage cap (the risk model runs before this)."""
        report = FuturesExecutionReport(mode=self.cfg.mode)
        if self.cfg.mode == "testnet":
            # A real testnet connector would sign + POST to testnet here using
            # TESTNET keys. Not wired; we never fall through to mainnet.
            log.info("testnet mode requested — connector not wired; simulating fills")
        fee_rate = (self.cfg.taker_fee_bps + self.cfg.slippage_bps) / 10_000.0
        for sym, w in target_weights.items():
            price = mark_prices.get(sym, 0.0)
            if price <= 0:
                report.rejected.append((sym, "no mark price"))
                continue
            target_qty = w * equity / price
            delta = target_qty - positions.get(sym, 0.0)
            if abs(delta) * price < 5.0:        # min notional
                continue
            side = Side.BUY if delta > 0 else Side.SELL
            fill_price = price * (1 + fee_rate if side is Side.BUY else 1 - fee_rate)
            report.fills.append(FuturesFill(
                order_id=f"PAPER-{uuid.uuid4().hex[:8]}", symbol=sym, side=side,
                quantity=abs(delta), price=fill_price,
                fee=abs(delta) * price * fee_rate, simulated=True))
        return report

    @staticmethod
    def refuse_live() -> None:
        raise CapabilityError(
            "Binance futures MAINNET live trading is blocked. Use mode=paper or "
            "mode=testnet; live enablement is a separate, supervised step that "
            "does not exist yet.")
