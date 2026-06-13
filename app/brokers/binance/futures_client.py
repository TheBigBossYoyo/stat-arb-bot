"""Binance USDT-perp futures client (public data + testnet config) — Path B.

Wraps the public futures market data (`BinanceFuturesData`) and carries the
testnet/mainnet base-URL selection and symbol filters. It exposes ONLY public,
keyless market data here; order placement lives in `futures_testnet_execution.py`
and is restricted to testnet/paper. Mainnet live trading is blocked by policy.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger
from app.data.futures import BinanceFuturesData

log = get_logger(__name__)

MAINNET_BASE = "https://fapi.binance.com"
TESTNET_BASE = "https://testnet.binancefuture.com"


@dataclass
class FuturesSymbolFilter:
    symbol: str
    tick_size: float = 0.0
    step_size: float = 0.0
    min_qty: float = 0.0
    min_notional: float = 0.0
    max_leverage: float = 1.0


class BinanceFuturesClient:
    """Public futures data + environment selection. No keys, no live orders."""

    def __init__(self, *, testnet: bool = True, data: BinanceFuturesData | None = None) -> None:
        self.testnet = testnet
        self.base_url = TESTNET_BASE if testnet else MAINNET_BASE
        self.data = data or BinanceFuturesData()

    # -- public market data (keyless) ------------------------------------------
    def klines(self, symbol, interval, start, end):
        return self.data.fetch_klines(symbol, interval, start, end)

    def mark_price(self, symbol: str) -> dict:
        return self.data.fetch_mark_price(symbol)

    def funding_now(self, symbol: str) -> float:
        return self.data.fetch_mark_price(symbol)["last_funding_rate"]

    def open_interest(self, symbol: str, period: str = "1d"):
        return self.data.fetch_open_interest_hist(symbol, period)

    def symbol_filters(self, symbol: str) -> FuturesSymbolFilter:
        """Contract spec / filters. Conservative defaults; the live testnet
        connector would populate these from exchangeInfo."""
        return FuturesSymbolFilter(symbol=symbol, tick_size=0.1, step_size=0.001,
                                   min_qty=0.001, min_notional=5.0, max_leverage=1.0)

    def ping(self) -> bool:
        try:
            self.data.fetch_mark_price("BTCUSDT")
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("futures ping failed: %s", exc)
            return False
