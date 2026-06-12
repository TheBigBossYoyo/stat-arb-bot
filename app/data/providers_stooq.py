"""Stooq daily-data provider (free, no API key).

Used for EQUITY and FX research history — Trading 212's official API exposes
no candles, so research data comes from here while execution (equities only)
stays broker-side. FX is RESEARCH-ONLY in this system: no connected broker
executes spot FX, and FX CFDs are out of scope by policy.

Symbols: stocks use Stooq's exchange suffix ("AAPL.US"); FX crosses are bare
("EURUSD"). Response is CSV: Date,Open,High,Low,Close[,Volume] — FX rows have
no volume.
"""

from __future__ import annotations

import io
from datetime import datetime

import httpx
import pandas as pd

from app.core.exceptions import BrokerError
from app.core.logging import get_logger
from app.execution.retry_policy import request_with_retries

log = get_logger(__name__)

STOOQ_URL = "https://stooq.com/q/d/l/"


def parse_stooq_csv(text: str) -> pd.DataFrame:
    """CSV -> [ts, open, high, low, close, volume]; empty frame if no data."""
    if not text or text.strip().lower().startswith(("no data", "<html")):
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip().lower() for c in df.columns]
    if "date" not in df.columns or "close" not in df.columns:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.rename(columns={"date": "ts"})
    df["ts"] = pd.to_datetime(df["ts"])
    if "volume" not in df.columns:
        df["volume"] = 0.0
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["ts", "open", "high", "low", "close", "volume"]].dropna(
        subset=["open", "high", "low", "close"]
    )


class StooqDailyData:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30.0, follow_redirects=True)

    def fetch_daily(
        self, symbol: str, start: datetime | None = None, end: datetime | None = None
    ) -> pd.DataFrame:
        params = {"s": symbol.lower(), "i": "d"}
        if start is not None:
            params["d1"] = pd.Timestamp(start).strftime("%Y%m%d")
        if end is not None:
            params["d2"] = pd.Timestamp(end).strftime("%Y%m%d")
        response = request_with_retries(lambda: self._client.get(STOOQ_URL, params=params))
        if response.status_code != 200:
            raise BrokerError(f"stooq {symbol} -> {response.status_code}: {response.text[:200]}")
        df = parse_stooq_csv(response.text)
        if df.empty:
            log.warning("stooq returned no data for %s (check the symbol suffix, e.g. AAPL.US)",
                        symbol)
        return df
