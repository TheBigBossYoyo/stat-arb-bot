"""Data quality checks for OHLCV bars.

Every dataset is cleaned and checked before it reaches research or trading.
Failing data raises DataQualityError at load time rather than producing a
quietly wrong backtest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.core.types import interval_minutes

log = get_logger(__name__)


@dataclass
class DataQualityReport:
    symbol: str
    interval: str
    n_rows: int
    n_duplicates: int
    n_nonpositive: int
    n_missing: int
    missing_pct: float
    max_abs_return: float
    issues: list[str] = field(default_factory=list)
    passed: bool = True

    def summary(self) -> str:
        status = "OK" if self.passed else "FAILED"
        return (
            f"[{status}] {self.symbol} {self.interval}: rows={self.n_rows} "
            f"dups={self.n_duplicates} nonpos={self.n_nonpositive} "
            f"missing={self.n_missing} ({self.missing_pct:.2f}%) "
            f"max|ret|={self.max_abs_return:.4f}"
        )


def clean_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Sort, deduplicate timestamps (keep last) and drop non-positive prices."""
    if df.empty:
        return df
    out = df.sort_values("ts").drop_duplicates(subset="ts", keep="last")
    price_cols = ["open", "high", "low", "close"]
    out = out[(out[price_cols] > 0).all(axis=1)]
    return out.reset_index(drop=True)


def check_bars(
    df: pd.DataFrame,
    *,
    symbol: str,
    interval: str,
    max_missing_pct: float = 5.0,
    max_abs_return: float = 0.5,
) -> DataQualityReport:
    """Validate a single-symbol bar frame (columns: ts, open, high, low, close, volume)."""
    issues: list[str] = []
    n_rows = len(df)
    if n_rows == 0:
        return DataQualityReport(symbol, interval, 0, 0, 0, 0, 100.0, 0.0, ["empty dataset"], passed=False)

    n_duplicates = int(df["ts"].duplicated().sum())
    n_nonpositive = int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())

    ts = pd.to_datetime(df["ts"]).sort_values()
    step = pd.Timedelta(minutes=interval_minutes(interval))
    expected = int((ts.iloc[-1] - ts.iloc[0]) / step) + 1
    n_missing = max(expected - n_rows, 0)
    missing_pct = 100.0 * n_missing / expected if expected else 0.0

    returns = np.log(df["close"]).diff().abs()
    max_ret = float(returns.max()) if n_rows > 1 else 0.0

    if n_duplicates:
        issues.append(f"{n_duplicates} duplicate timestamps")
    if n_nonpositive:
        issues.append(f"{n_nonpositive} non-positive prices")
    if missing_pct > max_missing_pct:
        issues.append(f"missing bars {missing_pct:.2f}% > {max_missing_pct}%")
    if max_ret > max_abs_return:
        issues.append(f"outlier bar return {max_ret:.3f} > {max_abs_return} (check for bad ticks)")

    hard_fail = missing_pct > max_missing_pct or n_nonpositive > 0
    report = DataQualityReport(
        symbol=symbol,
        interval=interval,
        n_rows=n_rows,
        n_duplicates=n_duplicates,
        n_nonpositive=n_nonpositive,
        n_missing=n_missing,
        missing_pct=missing_pct,
        max_abs_return=max_ret,
        issues=issues,
        passed=not hard_fail,
    )
    log.info(report.summary())
    return report
