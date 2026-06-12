"""Binance kline parsing helpers."""

from __future__ import annotations

import pandas as pd

# Map app intervals to Binance interval strings (identical for those we use).
BINANCE_INTERVALS = {"1m", "5m", "15m", "30m", "1h", "4h", "1d"}


def klines_to_dataframe(raw: list[list]) -> pd.DataFrame:
    """Convert raw /api/v3/klines rows to [ts, open, high, low, close, volume].

    Binance kline layout: [openTime, open, high, low, close, volume,
    closeTime, quoteVolume, trades, takerBase, takerQuote, ignore].
    `ts` is the bar OPEN time as tz-naive UTC.
    """
    if not raw:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(raw).iloc[:, :6]
    df.columns = ["ts", "open", "high", "low", "close", "volume"]
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.tz_localize(None)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)
    return df
