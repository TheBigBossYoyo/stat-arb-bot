"""Yahoo Finance daily-data provider (research data only).

Uses the public chart JSON endpoint (the same one the yfinance library
reads). Suitable for equity and FX RESEARCH history; execution never goes
through Yahoo. FX symbols use Yahoo's '=X' suffix (e.g. 'EURUSD=X') and are
research-only in this system — no connected broker executes spot FX.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from app.core.exceptions import BrokerError
from app.core.logging import get_logger
from app.execution.retry_policy import request_with_retries

log = get_logger(__name__)

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {"User-Agent": "Mozilla/5.0 (research data client)"}


def parse_chart_json(data: dict[str, Any]) -> pd.DataFrame:
    """Yahoo chart JSON -> [ts, open, high, low, close, volume, adj_close].

    The `quote` arrays are SPLIT-adjusted only. `adjclose` is the total-return
    (split + dividend) close — research must use it; ignoring it understates
    high-yield names by their dividend yield and tilts cross-sectional ranks
    (audit finding W-05). Both are kept: raw close for execution realism,
    adj_close for research returns.
    """
    empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "adj_close"])
    result = (data.get("chart", {}).get("result") or [None])[0]
    if not result or not result.get("timestamp"):
        return empty
    quote = result["indicators"]["quote"][0]
    adjclose = (result["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    df = pd.DataFrame({
        "ts": pd.to_datetime(result["timestamp"], unit="s", utc=True).tz_localize(None),
        "open": quote.get("open"),
        "high": quote.get("high"),
        "low": quote.get("low"),
        "close": quote.get("close"),
        "volume": quote.get("volume"),
        "adj_close": adjclose if adjclose is not None else float("nan"),
    })
    # daily bars are stamped at session open — normalize to the date so
    # symbols with different session times align on a common index
    df["ts"] = df["ts"].dt.normalize()
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    df["adj_close"] = pd.to_numeric(df["adj_close"], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)


class YahooDailyData:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30.0, headers=HEADERS,
                                              follow_redirects=True)

    def fetch_daily(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        params = {
            "interval": "1d",
            "period1": int(pd.Timestamp(start).timestamp()),
            "period2": int(pd.Timestamp(end).timestamp()),
            "events": "div,splits",   # adjusted close basis
        }
        url = YAHOO_URL.format(symbol=symbol)
        response = request_with_retries(lambda: self._client.get(url, params=params))
        if response.status_code != 200:
            raise BrokerError(f"yahoo {symbol} -> {response.status_code}: {response.text[:200]}")
        df = parse_chart_json(response.json())
        if df.empty:
            log.warning("yahoo returned no data for %s", symbol)
        return df
