"""Corporate action adjustment for equity OHLCV data (Phase 5 support).

Back-adjustment: all bars BEFORE the action date are scaled so the series is
continuous afterwards. Splits divide pre-split prices by the ratio (and
multiply volume); dividends apply a proportional factor (1 - div/close).
Run on RAW data at load time — adjusted and raw data are stored separately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd

PRICE_COLUMNS = ("open", "high", "low", "close")


@dataclass(frozen=True)
class Split:
    ex_date: datetime      # bars strictly before this date are adjusted
    ratio: float           # 2.0 = 2-for-1


@dataclass(frozen=True)
class Dividend:
    ex_date: datetime
    amount: float          # cash per share, in price currency


def adjust_for_splits(df: pd.DataFrame, splits: list[Split]) -> pd.DataFrame:
    out = df.copy()
    for split in splits:
        if split.ratio <= 0:
            raise ValueError(f"invalid split ratio {split.ratio}")
        mask = pd.to_datetime(out["ts"]) < pd.Timestamp(split.ex_date)
        out.loc[mask, list(PRICE_COLUMNS)] /= split.ratio
        out.loc[mask, "volume"] *= split.ratio
    return out


def adjust_for_dividends(df: pd.DataFrame, dividends: list[Dividend]) -> pd.DataFrame:
    out = df.copy()
    ts = pd.to_datetime(out["ts"])
    for dividend in dividends:
        ex = pd.Timestamp(dividend.ex_date)
        before = ts < ex
        if not before.any():
            continue
        last_close_before = float(out.loc[before, "close"].iloc[-1])
        if last_close_before <= 0:
            continue
        factor = 1.0 - dividend.amount / last_close_before
        if factor <= 0:
            raise ValueError(f"dividend {dividend.amount} >= price {last_close_before}")
        out.loc[before, list(PRICE_COLUMNS)] *= factor
    return out


def apply_corporate_actions(
    df: pd.DataFrame, splits: list[Split] | None = None, dividends: list[Dividend] | None = None
) -> pd.DataFrame:
    out = adjust_for_splits(df, splits or [])
    return adjust_for_dividends(out, dividends or [])
