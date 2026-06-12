"""Aligned price matrices for research and backtesting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from app.core.exceptions import DataQualityError
from app.core.logging import get_logger
from app.data.storage import Storage

log = get_logger(__name__)


@dataclass
class PriceMatrix:
    """Wide-format aligned OHLC data: index = tz-naive UTC timestamps."""

    close: pd.DataFrame
    open: pd.DataFrame
    interval: str
    high: pd.DataFrame | None = None
    low: pd.DataFrame | None = None
    volume: pd.DataFrame | None = None
    adjusted: bool = False                  # prices on a total-return basis?
    adjustment_coverage: float = 0.0        # fraction of cells with adj data

    @property
    def symbols(self) -> list[str]:
        return list(self.close.columns)

    @property
    def index(self) -> pd.DatetimeIndex:
        return self.close.index

    @property
    def log_close(self) -> pd.DataFrame:
        return np.log(self.close)

    @property
    def aux(self) -> dict[str, pd.DataFrame]:
        """Non-close frames for strategies that consume more than close prices."""
        frames = {"open": self.open, "high": self.high, "low": self.low,
                  "volume": self.volume}
        return {name: df for name, df in frames.items() if df is not None}

    def slice(self, start: int, end: int) -> PriceMatrix:
        """Positional slice [start:end) preserving alignment."""
        def cut(df: pd.DataFrame | None) -> pd.DataFrame | None:
            return None if df is None else df.iloc[start:end]

        return PriceMatrix(self.close.iloc[start:end], self.open.iloc[start:end],
                           self.interval, high=cut(self.high), low=cut(self.low),
                           volume=cut(self.volume), adjusted=self.adjusted,
                           adjustment_coverage=self.adjustment_coverage)


def build_price_matrix(
    storage: Storage,
    symbols: list[str],
    interval: str,
    start: datetime | None = None,
    end: datetime | None = None,
    source: str | None = None,
    max_ffill: int = 3,
    min_rows: int = 100,
    adjusted: bool = False,
) -> PriceMatrix:
    """Load bars and align all symbols onto a common timestamp index.

    Small gaps are forward-filled (up to `max_ffill` bars); symbols whose
    coverage is too short to align are rejected with DataQualityError.

    `adjusted=True` rescales every price frame onto a TOTAL-RETURN basis using
    the stored adj_close (split + dividend adjusted). Research on equities must
    use this — raw closes understate high-yield names and tilt cross-sectional
    ranks (audit W-05). Cells without adjustment data keep raw prices and the
    shortfall is reported in `adjustment_coverage` (re-download fills it in).
    """
    long_df = storage.load_bars(symbols, interval, start=start, end=end, source=source)
    if long_df.empty:
        raise DataQualityError(
            f"no bars found for {symbols} interval={interval}. Run `download-data` first."
        )

    def pivot(values: str) -> pd.DataFrame:
        return long_df.pivot_table(index="ts", columns="symbol", values=values).sort_index()

    close = pivot("close").ffill(limit=max_ffill)
    open_ = pivot("open").ffill(limit=max_ffill)

    missing = [s for s in symbols if s not in close.columns]
    if missing:
        log.warning("symbols missing from storage and skipped: %s", missing)

    aligned = close.dropna(how="any")
    if len(aligned) < min_rows:
        raise DataQualityError(
            f"only {len(aligned)} aligned rows across {list(close.columns)}; "
            f"need >= {min_rows}. Download more history."
        )
    open_ = open_.loc[aligned.index]
    # If an open is still missing after alignment, fall back to that bar's close.
    open_ = open_.fillna(aligned)

    # High/low/volume ride along for strategies that want them (range vol,
    # volume features). They are aligned but NOT backstopped beyond the ffill:
    # consumers must be NaN-safe (e.g. stooq FX has volume 0 -> features NaN).
    high = pivot("high").ffill(limit=max_ffill).reindex(aligned.index)
    low = pivot("low").ffill(limit=max_ffill).reindex(aligned.index)
    volume = pivot("volume").ffill(limit=max_ffill).reindex(aligned.index)

    coverage = 0.0
    if adjusted:
        adj = pd.DataFrame(index=aligned.index, columns=aligned.columns, dtype=float)
        if long_df["adj_close"].notna().any():
            adj = pivot("adj_close").ffill(limit=max_ffill).reindex(
                index=aligned.index, columns=aligned.columns)
        factor = (adj / aligned).where(adj.notna() & (aligned > 0))
        coverage = float(factor.notna().to_numpy().mean())
        if coverage < 1.0:
            log.warning(
                "adjustment coverage %.1f%% — cells without adj_close keep RAW "
                "prices (re-run download-data to backfill dividend adjustment)",
                100 * coverage,
            )
        factor = factor.fillna(1.0)
        aligned = aligned * factor
        open_ = open_ * factor
        high = high * factor
        low = low * factor

    log.info(
        "price matrix: %d bars x %d symbols [%s .. %s]%s",
        len(aligned), aligned.shape[1], aligned.index[0], aligned.index[-1],
        f" (total-return adjusted, coverage {100 * coverage:.1f}%)" if adjusted else "",
    )
    return PriceMatrix(close=aligned, open=open_, interval=interval,
                       high=high, low=low, volume=volume,
                       adjusted=adjusted, adjustment_coverage=coverage)
