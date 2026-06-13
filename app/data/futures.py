"""Binance USDT-perpetual futures market data (public REST, research only).

Feeds the Path B crypto-futures research path: futures klines, mark price and
open interest from the public futures API (fapi.binance.com). No key required,
no account connected, no orders. Testnet/live execution is the broker layer's
concern and stays blocked.

Klines are stored through the same `Storage` as spot bars, under a distinct
`source="binance_futures"`, so a futures backtest never silently mixes in spot
bars.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pandas as pd

from app.core.exceptions import BrokerError
from app.core.logging import get_logger
from app.execution.retry_policy import request_with_retries

log = get_logger(__name__)

FUTURES_BASE = "https://fapi.binance.com"
KLINES_URL = f"{FUTURES_BASE}/fapi/v1/klines"
MARK_URL = f"{FUTURES_BASE}/fapi/v1/premiumIndex"          # mark + index + last funding
OI_URL = f"{FUTURES_BASE}/futures/data/openInterestHist"
EXCHANGE_INFO_URL = f"{FUTURES_BASE}/fapi/v1/exchangeInfo"
PAGE_LIMIT = 1500

_INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000,
                "4h": 14_400_000, "8h": 28_800_000, "1d": 86_400_000}


class BinanceFuturesData:
    """Public USDT-perp market data. Research only."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_klines(self, symbol: str, interval: str, start: datetime,
                     end: datetime) -> pd.DataFrame:
        """OHLCV futures klines -> [ts, open, high, low, close, volume]."""
        step = _INTERVAL_MS.get(interval)
        if step is None:
            raise BrokerError(f"unsupported futures interval {interval!r}")
        start_ms = int(pd.Timestamp(start).timestamp() * 1000)
        end_ms = int(pd.Timestamp(end).timestamp() * 1000)
        rows: list[list] = []
        while start_ms < end_ms:
            params = {"symbol": symbol, "interval": interval, "startTime": start_ms,
                      "endTime": end_ms, "limit": PAGE_LIMIT}
            resp = request_with_retries(lambda p=params: self._client.get(KLINES_URL, params=p))
            if resp.status_code != 200:
                raise BrokerError(f"futures klines {symbol} -> {resp.status_code}: {resp.text[:200]}")
            page = resp.json()
            if not page:
                break
            rows.extend(page)
            last_open = int(page[-1][0])
            start_ms = last_open + step
            if len(page) < PAGE_LIMIT:
                break
        if not rows:
            log.warning("no futures klines for %s %s", symbol, interval)
            return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame({
            "ts": pd.to_datetime([int(r[0]) for r in rows], unit="ms"),
            "open": [float(r[1]) for r in rows], "high": [float(r[2]) for r in rows],
            "low": [float(r[3]) for r in rows], "close": [float(r[4]) for r in rows],
            "volume": [float(r[5]) for r in rows],
        })
        return df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)

    def fetch_mark_price(self, symbol: str) -> dict:
        """Current mark price, index price and last funding rate for a perp."""
        resp = request_with_retries(
            lambda: self._client.get(MARK_URL, params={"symbol": symbol}))
        if resp.status_code != 200:
            raise BrokerError(f"mark price {symbol} -> {resp.status_code}")
        d = resp.json()
        return {"symbol": symbol, "mark_price": float(d["markPrice"]),
                "index_price": float(d["indexPrice"]),
                "last_funding_rate": float(d["lastFundingRate"])}

    def fetch_open_interest_hist(self, symbol: str, period: str = "1d",
                                 limit: int = 200) -> pd.DataFrame:
        """Open-interest history (a crowding signal). May be empty if unavailable."""
        params = {"symbol": symbol, "period": period, "limit": min(limit, 500)}
        resp = request_with_retries(lambda: self._client.get(OI_URL, params=params))
        if resp.status_code != 200:
            log.warning("open interest %s -> %s", symbol, resp.status_code)
            return pd.DataFrame(columns=["ts", "open_interest"])
        page = resp.json()
        if not page:
            return pd.DataFrame(columns=["ts", "open_interest"])
        return pd.DataFrame({
            "ts": pd.to_datetime([int(r["timestamp"]) for r in page], unit="ms"),
            "open_interest": [float(r["sumOpenInterest"]) for r in page],
        }).sort_values("ts").reset_index(drop=True)

    def download(self, storage, symbols: list[str], interval: str, days: int) -> dict:
        """Download futures klines into storage under source='binance_futures'."""
        end = pd.Timestamp.utcnow().tz_localize(None)
        start = end - pd.Timedelta(days=days)
        counts: dict[str, int] = {}
        for sym in symbols:
            df = self.fetch_klines(sym, interval, start.to_pydatetime(), end.to_pydatetime())
            if df.empty:
                counts[sym] = 0
                continue
            n = storage.upsert_bars(df, source="binance_futures", symbol=sym, interval=interval)
            counts[sym] = n
            log.info("downloaded futures %s %s: %d rows", sym, interval, len(df))
        return counts
