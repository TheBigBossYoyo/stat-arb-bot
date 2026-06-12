"""Binance USDT-perpetual funding-rate history (public REST, research only).

Perpetual futures exchange a funding payment between longs and shorts every
8 hours. A delta-neutral carry position (long spot, short perp of the same
notional) RECEIVES funding while the rate is positive. This provider feeds
research only: no futures account is connected and no orders are placed.
"""

from __future__ import annotations

from datetime import datetime

import httpx
import pandas as pd

from app.core.exceptions import BrokerError
from app.core.logging import get_logger
from app.execution.retry_policy import request_with_retries

log = get_logger(__name__)

FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
PAGE_LIMIT = 1000  # exchange maximum; 8h periods -> one page covers ~333 days


class BinanceFundingRates:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=30.0)

    def fetch_funding(self, symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
        """Funding history -> [ts, funding_rate] (decimal per 8h period)."""
        start_ms = int(pd.Timestamp(start).timestamp() * 1000)
        end_ms = int(pd.Timestamp(end).timestamp() * 1000)
        rows: list[dict] = []
        while start_ms < end_ms:
            params = {"symbol": symbol, "startTime": start_ms, "endTime": end_ms,
                      "limit": PAGE_LIMIT}
            response = request_with_retries(
                lambda: self._client.get(FUNDING_URL, params=params)
            )
            if response.status_code != 200:
                raise BrokerError(
                    f"binance funding {symbol} -> {response.status_code}: {response.text[:200]}"
                )
            page = response.json()
            if not page:
                break
            rows.extend(page)
            if len(page) < PAGE_LIMIT:
                break
            start_ms = int(page[-1]["fundingTime"]) + 1
        if not rows:
            log.warning("no funding history for %s", symbol)
            return pd.DataFrame(columns=["ts", "funding_rate"])
        df = pd.DataFrame({
            "ts": pd.to_datetime([int(r["fundingTime"]) for r in rows], unit="ms"),
            "funding_rate": [float(r["fundingRate"]) for r in rows],
        })
        return df.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
