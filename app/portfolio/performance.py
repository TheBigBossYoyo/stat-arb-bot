"""Performance attribution from the recorded trade history."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select

from app.data.schemas import TradeRow
from app.data.storage import Storage


def _trades_frame(storage: Storage, mode: str | None = None) -> pd.DataFrame:
    stmt = select(
        TradeRow.strategy, TradeRow.pair_key, TradeRow.mode, TradeRow.direction,
        TradeRow.pnl, TradeRow.fees, TradeRow.holding_bars, TradeRow.exit_reason,
    )
    if mode:
        stmt = stmt.where(TradeRow.mode == mode)
    with storage.session() as s:
        rows = s.execute(stmt).all()
    return pd.DataFrame(rows, columns=[
        "strategy", "pair_key", "mode", "direction", "pnl", "fees",
        "holding_bars", "exit_reason",
    ])


def _aggregate(df: pd.DataFrame, by: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    return (
        df.groupby(by)
        .agg(
            n_trades=("pnl", "size"),
            total_pnl=("pnl", "sum"),
            avg_pnl=("pnl", "mean"),
            win_rate_pct=("pnl", lambda s: round(100.0 * (s > 0).mean(), 2)),
            total_fees=("fees", "sum"),
            avg_holding_bars=("holding_bars", "mean"),
        )
        .round(4)
        .sort_values("total_pnl", ascending=False)
    )


def strategy_performance(storage: Storage, mode: str | None = None) -> pd.DataFrame:
    return _aggregate(_trades_frame(storage, mode), "strategy")


def pair_performance(storage: Storage, mode: str | None = None) -> pd.DataFrame:
    return _aggregate(_trades_frame(storage, mode), "pair_key")
