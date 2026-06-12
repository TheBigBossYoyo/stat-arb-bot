"""Binance REST clients.

* BinancePublicData — unauthenticated market data (klines, exchangeInfo,
  server time). Used by research, backtesting and paper trading. No API key.
* BinanceClient    — signed endpoints (account, orders). TESTNET FIRST:
  orders against the live endpoint additionally require allow_live_orders=True,
  which only the live-trading gate may set.

Rate limits: requests go through retry/backoff and respect Retry-After on
429/418 responses.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from app.brokers.base import BrokerBase
from app.brokers.binance.execution import build_order_params, parse_order_response
from app.brokers.binance.market_data import BINANCE_INTERVALS, klines_to_dataframe
from app.brokers.binance.signing import signed_params
from app.brokers.models import AccountState, Instrument, Order, OrderRequest, Position
from app.core.exceptions import (
    BrokerError,
    BrokerNotEnabledError,
    LiveTradingBlockedError,
)
from app.core.logging import audit, get_logger
from app.core.types import AssetClass
from app.execution.retry_policy import request_with_retries

log = get_logger(__name__)

BASE_URLS = {
    "live": "https://api.binance.com",
    "testnet": "https://testnet.binance.vision",
}
KLINES_MAX_LIMIT = 1000


class BinancePublicData:
    """Public (unsigned) Binance Spot market data.

    Historical data is always pulled from the live endpoint by default —
    testnet has very little history. This involves no account access.
    """

    def __init__(self, mode: str = "live", client: httpx.Client | None = None) -> None:
        self.base_url = BASE_URLS[mode]
        self._client = client or httpx.Client(base_url=self.base_url, timeout=30.0)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        def call() -> httpx.Response:
            return self._client.get(path, params=params)

        response = request_with_retries(call)
        if response.status_code != 200:
            raise BrokerError(f"binance GET {path} -> {response.status_code}: {response.text[:300]}")
        return response.json()

    def ping(self) -> bool:
        self._get("/api/v3/ping")
        return True

    def server_time_ms(self) -> int:
        return int(self._get("/api/v3/time")["serverTime"])

    def clock_offset_ms(self) -> float:
        """Local clock minus exchange clock, in milliseconds."""
        import time

        local = time.time() * 1000
        return local - self.server_time_ms()

    def get_exchange_info(self, symbols: list[str] | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if symbols:
            params["symbols"] = "[" + ",".join(f'"{s}"' for s in symbols) + "]"
        return self._get("/api/v3/exchangeInfo", params or None)

    def get_instruments(self, symbols: list[str] | None = None) -> list[Instrument]:
        info = self.get_exchange_info(symbols)
        instruments = []
        for sym in info.get("symbols", []):
            filters = {f["filterType"]: f for f in sym.get("filters", [])}
            lot = filters.get("LOT_SIZE", {})
            price = filters.get("PRICE_FILTER", {})
            notional = filters.get("NOTIONAL", filters.get("MIN_NOTIONAL", {}))
            instruments.append(
                Instrument(
                    broker="binance_spot",
                    symbol=sym["symbol"],
                    asset_class=AssetClass.CRYPTO_SPOT,
                    base_currency=sym.get("baseAsset", ""),
                    quote_currency=sym.get("quoteAsset", ""),
                    tick_size=float(price.get("tickSize", 0) or 0),
                    step_size=float(lot.get("stepSize", 0) or 0),
                    min_quantity=float(lot.get("minQty", 0) or 0),
                    min_notional=float(notional.get("minNotional", 0) or 0),
                    shortable=False,
                    fractional=True,
                )
            )
        return instruments

    def get_klines(
        self,
        symbol: str,
        interval: str,
        start_ms: int | None = None,
        end_ms: int | None = None,
        limit: int = KLINES_MAX_LIMIT,
    ) -> list[list]:
        if interval not in BINANCE_INTERVALS:
            raise BrokerError(f"unsupported Binance interval {interval!r}")
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        return self._get("/api/v3/klines", params)

    def fetch_klines_range(
        self, symbol: str, interval: str, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """Paginate forward through [start, end] in 1000-bar chunks."""
        start_ms = int(pd.Timestamp(start).timestamp() * 1000)
        end_ms = int(pd.Timestamp(end).timestamp() * 1000)
        chunks: list[pd.DataFrame] = []
        cursor = start_ms
        while cursor < end_ms:
            raw = self.get_klines(symbol, interval, start_ms=cursor, end_ms=end_ms)
            if not raw:
                break
            df = klines_to_dataframe(raw)
            chunks.append(df)
            last_open_ms = int(raw[-1][0])
            next_cursor = last_open_ms + 1
            if next_cursor <= cursor:
                break
            cursor = next_cursor
            if len(raw) < KLINES_MAX_LIMIT:
                break
        if not chunks:
            return klines_to_dataframe([])
        return pd.concat(chunks, ignore_index=True).drop_duplicates(subset="ts", keep="last")


class BinanceClient(BrokerBase):
    """Signed Binance Spot client (account + order endpoints).

    Safety model:
      * `enabled=True` (BINANCE_ENABLED) is required to construct at all;
      * order endpoints work freely against the TESTNET;
      * against the LIVE endpoint they additionally require
        `allow_live_orders=True`, which only the live-trading gate sets.
    """

    name = "binance_spot"
    asset_class = AssetClass.CRYPTO_SPOT

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        mode: str = "testnet",
        enabled: bool = False,
        allow_live_orders: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__()
        if not enabled:
            raise BrokerNotEnabledError(
                "Binance connector is disabled. Set BINANCE_ENABLED=true (testnet first)."
            )
        if not api_key or not api_secret:
            raise BrokerNotEnabledError("BINANCE_API_KEY / BINANCE_API_SECRET not configured.")
        self.mode = mode
        self.allow_live_orders = allow_live_orders
        self.api_secret = api_secret
        self._instruments: dict[str, Instrument] = {}
        self._client = client or httpx.Client(
            base_url=BASE_URLS[mode],
            timeout=30.0,
            headers={"X-MBX-APIKEY": api_key},
        )

    # -- plumbing ---------------------------------------------------------------

    def _signed_request(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        response = request_with_retries(
            lambda: self._client.request(
                method, path, params=signed_params(params or {}, self.api_secret)
            )
        )
        if response.status_code != 200:
            raise BrokerError(
                f"binance {method} {path} -> {response.status_code}: {response.text[:300]}"
            )
        return response.json()

    def _guard_orders(self) -> None:
        if self.mode == "live" and not self.allow_live_orders:
            raise LiveTradingBlockedError(
                "Refusing live Binance order: the live-trading gate has not granted "
                "allow_live_orders. Use testnet or paper trading."
            )

    def _instrument(self, symbol: str) -> Instrument:
        if symbol not in self._instruments:
            found = self.get_instruments([symbol])
            if not found:
                raise BrokerError(f"unknown Binance symbol {symbol!r}")
            self._instruments[symbol] = found[0]
        return self._instruments[symbol]

    # -- account ----------------------------------------------------------------

    def get_account(self) -> AccountState:
        data = self._signed_request("GET", "/api/v3/account")
        positions = [
            Position(symbol=b["asset"], quantity=float(b["free"]) + float(b["locked"]))
            for b in data.get("balances", [])
            if float(b["free"]) + float(b["locked"]) != 0.0
        ]
        usdt = next((p.quantity for p in positions if p.symbol == "USDT"), 0.0)
        return AccountState(broker=self.name, currency="USDT", cash=usdt, equity=usdt, positions=positions)

    def get_cash(self) -> float:
        return self.get_account().cash

    def get_positions(self) -> list[Position]:
        return self.get_account().positions

    # -- market structure ----------------------------------------------------------

    def get_instruments(self, symbols: list[str] | None = None) -> list[Instrument]:
        # exchangeInfo is public but must come from the SAME environment as
        # orders (testnet filters differ from live) — reuse this client.
        return BinancePublicData(client=self._client).get_instruments(symbols)

    def get_market_data(self, symbol: str) -> dict[str, Any]:
        raw = BinancePublicData().get_klines(symbol, "1m", limit=1)
        df = klines_to_dataframe(raw)
        if df.empty:
            raise BrokerError(f"no market data for {symbol}")
        row = df.iloc[-1]
        return {"symbol": symbol, "ts": row["ts"], "close": float(row["close"])}

    # -- orders ------------------------------------------------------------------------

    def place_order(self, request: OrderRequest) -> Order:
        self._guard_orders()
        instrument = self._instrument(request.symbol)
        self.validate_order(request, instrument)            # capabilities + precision
        normalized = self.normalize_order(request, instrument)
        params = build_order_params(normalized)
        audit("binance_order_submit", mode=self.mode, **{k: str(v) for k, v in params.items()})
        data = self._signed_request("POST", "/api/v3/order", params)
        order = parse_order_response(data, normalized)
        audit("binance_order_result", order_id=order.order_id, status=order.status.value,
              filled=order.filled_quantity, avg_price=order.avg_fill_price)
        return order

    def cancel_order(self, order_id: str, symbol: str | None = None) -> Order:
        self._guard_orders()
        if not symbol:
            raise BrokerError("Binance cancel requires the symbol")
        data = self._signed_request(
            "DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}
        )
        echo = OrderRequest(
            broker=self.name, symbol=symbol,
            side=str(data.get("side", "BUY")).lower(), quantity=float(data.get("origQty", 0) or 0),
        )
        return parse_order_response(data, echo)

    def get_order_status(self, order_id: str, symbol: str | None = None) -> Order:
        if not symbol:
            raise BrokerError("Binance order query requires the symbol")
        data = self._signed_request("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id})
        echo = OrderRequest(
            broker=self.name, symbol=symbol,
            side=str(data.get("side", "BUY")).lower(), quantity=float(data.get("origQty", 0) or 0),
        )
        return parse_order_response(data, echo)

    def get_open_orders(self) -> list[Order]:
        data = self._signed_request("GET", "/api/v3/openOrders")
        orders = []
        for item in data:
            echo = OrderRequest(
                broker=self.name, symbol=item.get("symbol", ""),
                side=str(item.get("side", "BUY")).lower(),
                quantity=float(item.get("origQty", 0) or 0),
            )
            orders.append(parse_order_response(item, echo))
        return orders
