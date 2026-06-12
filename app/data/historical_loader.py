"""Historical data download into local storage.

Sources:
  * binance   — public REST klines (no API key required)
  * synthetic — offline generator with known cointegrated pairs

Equity history providers (yahoo/stooq/polygon/...) plug in here later via the
same interface; execution remains broker-side regardless of data source.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.core.types import utc_now
from app.data.data_quality import DataQualityReport, check_bars, clean_bars
from app.data.storage import Storage
from app.data.synthetic import generate_synthetic_bars

log = get_logger(__name__)


@dataclass
class DownloadSummary:
    source: str
    interval: str
    symbols: dict[str, int]          # symbol -> rows inserted
    reports: list[DataQualityReport]

    def total_rows(self) -> int:
        return sum(self.symbols.values())


class HistoricalDataLoader:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def download(
        self,
        symbols: list[str],
        interval: str,
        days: int,
        source: str = "binance",
    ) -> DownloadSummary:
        if source == "binance":
            return self._download_binance(symbols, interval, days)
        if source == "yahoo":
            return self._download_daily_provider(symbols, interval, days, source="yahoo")
        if source == "stooq":
            return self._download_daily_provider(symbols, interval, days, source="stooq")
        if source == "synthetic":
            return self._generate_synthetic(symbols, interval, days)
        raise ConfigurationError(
            f"unknown data source {source!r} (use 'binance', 'yahoo', 'stooq' or 'synthetic')"
        )

    def _download_binance(self, symbols: list[str], interval: str, days: int) -> DownloadSummary:
        from app.brokers.binance.client import BinancePublicData

        client = BinancePublicData()
        end = utc_now()
        start = end - timedelta(days=days)
        inserted: dict[str, int] = {}
        reports: list[DataQualityReport] = []
        for symbol in symbols:
            df = client.fetch_klines_range(symbol, interval, start, end)
            df = clean_bars(df)
            report = check_bars(df, symbol=symbol, interval=interval)
            reports.append(report)
            if not report.passed:
                log.warning("data quality failed for %s — storing anyway, flagged: %s",
                            symbol, "; ".join(report.issues))
            n = self.storage.upsert_bars(df, source="binance", symbol=symbol, interval=interval)
            inserted[symbol] = n
            log.info("downloaded %s %s: %d rows (%d new)", symbol, interval, len(df), n)
        return DownloadSummary("binance", interval, inserted, reports)

    def _download_daily_provider(
        self, symbols: list[str], interval: str, days: int, source: str
    ) -> DownloadSummary:
        """Daily equity/FX research data from a configurable provider.

        Note: stooq currently gates downloads behind a JS challenge, so yahoo
        is the working default; the stooq parser remains for when that lifts.
        """
        if interval != "1d":
            raise ConfigurationError(f"{source} provides DAILY data only — use --interval 1d")
        if source == "yahoo":
            from app.data.providers_yahoo import YahooDailyData

            client = YahooDailyData()
        else:
            from app.data.providers_stooq import StooqDailyData

            client = StooqDailyData()
        end = utc_now()
        start = end - timedelta(days=days)
        inserted: dict[str, int] = {}
        reports: list[DataQualityReport] = []
        for symbol in symbols:
            df = client.fetch_daily(symbol, start=start, end=end)
            df = clean_bars(df)
            # weekends/holidays are normal gaps on an exchange calendar
            report = check_bars(df, symbol=symbol, interval=interval, max_missing_pct=40.0)
            reports.append(report)
            n = self.storage.upsert_bars(df, source=source, symbol=symbol, interval=interval)
            inserted[symbol] = n
            log.info("downloaded %s 1d from %s: %d rows (%d new)", symbol, source, len(df), n)
        return DownloadSummary(source, interval, inserted, reports)

    def _generate_synthetic(self, symbols: list[str], interval: str, days: int) -> DownloadSummary:
        from app.core.types import interval_minutes

        n_bars = int(days * 24 * 60 / interval_minutes(interval))
        long_df = generate_synthetic_bars(symbols, n_bars=n_bars, interval=interval)
        inserted: dict[str, int] = {}
        reports: list[DataQualityReport] = []
        for symbol, group in long_df.groupby("symbol"):
            df = clean_bars(group.drop(columns="symbol"))
            reports.append(check_bars(df, symbol=str(symbol), interval=interval))
            inserted[str(symbol)] = self.storage.upsert_bars(
                df, source="synthetic", symbol=str(symbol), interval=interval
            )
        log.info("generated synthetic data: %d symbols x %d bars", len(symbols), n_bars)
        return DownloadSummary("synthetic", interval, inserted, reports)
