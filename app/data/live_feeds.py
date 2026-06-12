"""Live data feed helpers: staleness monitoring and REST polling.

The risk layer rejects orders against stale data; this module is the source
of truth for "how old is the latest bar of X". The WebSocket stream
(app.brokers.binance.websocket) and the REST poller both report into a
FreshnessMonitor.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.events import BarEvent
from app.core.logging import get_logger

log = get_logger(__name__)


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class FreshnessMonitor:
    """Tracks the newest data timestamp per symbol (tz-naive UTC)."""

    def __init__(self) -> None:
        self._latest: dict[str, datetime] = {}

    def record(self, symbol: str, ts: datetime) -> None:
        current = self._latest.get(symbol)
        if current is None or ts > current:
            self._latest[symbol] = ts

    def age_seconds(self, symbol: str, now: datetime | None = None) -> float:
        ts = self._latest.get(symbol)
        if ts is None:
            return float("inf")
        return ((now or _utc_now()) - ts).total_seconds()

    def is_fresh(self, symbol: str, max_age_seconds: float, now: datetime | None = None) -> bool:
        return self.age_seconds(symbol, now) <= max_age_seconds

    def stale_symbols(self, symbols: list[str], max_age_seconds: float,
                      now: datetime | None = None) -> list[str]:
        return [s for s in symbols if not self.is_fresh(s, max_age_seconds, now)]


class LatestBarPoller:
    """REST fallback feed: fetch the latest CLOSED bar per symbol."""

    def __init__(self, interval: str, monitor: FreshnessMonitor | None = None) -> None:
        from app.brokers.binance.client import BinancePublicData

        self.client = BinancePublicData()
        self.interval = interval
        self.monitor = monitor or FreshnessMonitor()

    def poll(self, symbol: str) -> BarEvent | None:
        from app.brokers.binance.market_data import klines_to_dataframe

        raw = self.client.get_klines(symbol, self.interval, limit=2)
        df = klines_to_dataframe(raw)
        if len(df) < 2:
            return None
        row = df.iloc[-2]   # last CLOSED bar
        ts = row["ts"].to_pydatetime()
        self.monitor.record(symbol, ts)
        return BarEvent(ts=ts, symbol=symbol, open=float(row["open"]), high=float(row["high"]),
                        low=float(row["low"]), close=float(row["close"]), volume=float(row["volume"]))
