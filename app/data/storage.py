"""Database access layer (SQLite by default, PostgreSQL via DATABASE_URL)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, delete, desc, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging import get_logger
from app.core.types import utc_now
from app.data.schemas import (
    AuditEventRow,
    BacktestRunRow,
    BarRow,
    Base,
    EquitySnapshotRow,
    OrderRow,
    PairRow,
    SignalRow,
    TradeRow,
)

log = get_logger(__name__)

BAR_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]


def _naive_utc(ts: datetime | pd.Timestamp) -> datetime:
    ts = pd.Timestamp(ts)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.to_pydatetime()


class Storage:
    def __init__(self, database_url: str = "sqlite:///stat_arb.db") -> None:
        self.database_url = database_url
        self.engine = create_engine(database_url, future=True)
        self._session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Session:
        return self._session_factory()

    # -- schema ---------------------------------------------------------------

    def init_db(self) -> None:
        Base.metadata.create_all(self.engine)
        self._ensure_columns("backtest_runs", {"equity_json": "TEXT DEFAULT '[]'",
                                               "trades_json": "TEXT DEFAULT '[]'"})
        log.info("database initialised", extra={"url": self.database_url})

    def _ensure_columns(self, table: str, columns: dict[str, str]) -> None:
        """Additive micro-migration: add missing columns to an existing table."""
        from sqlalchemy import inspect, text

        inspector = inspect(self.engine)
        if table not in inspector.get_table_names():
            return
        existing = {c["name"] for c in inspector.get_columns(table)}
        with self.engine.begin() as conn:
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    log.info("migrated %s: added column %s", table, name)

    # -- bars -----------------------------------------------------------------

    def upsert_bars(self, df: pd.DataFrame, *, source: str, symbol: str, interval: str) -> int:
        """Insert bars, ignoring duplicates on (source, symbol, interval, ts)."""
        if df.empty:
            return 0
        records = [
            {
                "source": source,
                "symbol": symbol,
                "interval": interval,
                "ts": _naive_utc(row.ts),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
            }
            for row in df[BAR_COLUMNS].itertuples(index=False)
        ]
        chunk_size = 500  # keep well under SQLite's bound-parameter limit
        inserted = 0
        with self.session() as s:
            if self.engine.dialect.name == "sqlite":
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert

                for start in range(0, len(records), chunk_size):
                    chunk = records[start : start + chunk_size]
                    stmt = sqlite_insert(BarRow).values(chunk).on_conflict_do_nothing(
                        index_elements=["source", "symbol", "interval", "ts"]
                    )
                    result = s.execute(stmt)
                    inserted += result.rowcount if result.rowcount is not None else len(chunk)
            else:  # generic path: filter out existing timestamps first
                existing = set(
                    s.execute(
                        select(BarRow.ts).where(
                            BarRow.source == source,
                            BarRow.symbol == symbol,
                            BarRow.interval == interval,
                        )
                    ).scalars()
                )
                fresh = [r for r in records if r["ts"] not in existing]
                for start in range(0, len(fresh), chunk_size):
                    s.bulk_insert_mappings(BarRow, fresh[start : start + chunk_size])
                inserted = len(fresh)
            s.commit()
        return inserted

    def load_bars(
        self,
        symbols: Iterable[str],
        interval: str,
        start: datetime | None = None,
        end: datetime | None = None,
        source: str | None = None,
    ) -> pd.DataFrame:
        """Long-format bars: columns [symbol, ts, open, high, low, close, volume]."""
        stmt = select(
            BarRow.symbol, BarRow.ts, BarRow.open, BarRow.high, BarRow.low, BarRow.close, BarRow.volume
        ).where(BarRow.symbol.in_(list(symbols)), BarRow.interval == interval)
        if source:
            stmt = stmt.where(BarRow.source == source)
        if start:
            stmt = stmt.where(BarRow.ts >= _naive_utc(start))
        if end:
            stmt = stmt.where(BarRow.ts <= _naive_utc(end))
        stmt = stmt.order_by(BarRow.symbol, BarRow.ts)
        with self.session() as s:
            rows = s.execute(stmt).all()
        return pd.DataFrame(rows, columns=["symbol", *BAR_COLUMNS])

    def bar_coverage(self, symbol: str, interval: str) -> tuple[datetime | None, datetime | None, int]:
        from sqlalchemy import func

        with self.session() as s:
            row = s.execute(
                select(func.min(BarRow.ts), func.max(BarRow.ts), func.count(BarRow.id)).where(
                    BarRow.symbol == symbol, BarRow.interval == interval
                )
            ).one()
        return row[0], row[1], row[2]

    # -- pairs ----------------------------------------------------------------

    def save_pairs(
        self,
        pairs: list[Any],  # list[SelectedPair]
        *,
        universe: str,
        interval: str,
        window_start: datetime,
        window_end: datetime,
    ) -> int:
        with self.session() as s:
            s.execute(
                update(PairRow)
                .where(PairRow.universe == universe, PairRow.interval == interval)
                .values(is_active=False)
            )
            for p in pairs:
                s.add(
                    PairRow(
                        created_at=_naive_utc(utc_now()),
                        universe=universe,
                        interval=interval,
                        symbol_a=p.symbol_a,
                        symbol_b=p.symbol_b,
                        beta=p.beta,
                        alpha=p.alpha,
                        correlation=p.correlation,
                        eg_pvalue=p.eg_pvalue,
                        adf_pvalue=p.adf_pvalue,
                        half_life_bars=p.half_life,
                        spread_std=p.spread_std,
                        score=p.score,
                        window_start=_naive_utc(window_start),
                        window_end=_naive_utc(window_end),
                        is_active=True,
                    )
                )
            s.commit()
        return len(pairs)

    def load_active_pairs(self, universe: str | None = None, interval: str | None = None) -> list[PairRow]:
        stmt = select(PairRow).where(PairRow.is_active.is_(True))
        if universe:
            stmt = stmt.where(PairRow.universe == universe)
        if interval:
            stmt = stmt.where(PairRow.interval == interval)
        stmt = stmt.order_by(desc(PairRow.score))
        with self.session() as s:
            return list(s.execute(stmt).scalars())

    # -- audit trail ------------------------------------------------------------

    def record_signal(self, **kwargs: Any) -> None:
        with self.session() as s:
            s.add(SignalRow(**kwargs))
            s.commit()

    def record_order(self, **kwargs: Any) -> None:
        for key in ("signal_json", "risk_checks_json"):
            if key in kwargs and not isinstance(kwargs[key], str):
                kwargs[key] = json.dumps(kwargs[key], default=str)
        with self.session() as s:
            s.add(OrderRow(**kwargs))
            s.commit()

    def record_trade(self, **kwargs: Any) -> None:
        with self.session() as s:
            s.add(TradeRow(**kwargs))
            s.commit()

    def record_equity_snapshot(self, *, ts: datetime, mode: str, equity: float, cash: float,
                               gross_exposure: float = 0.0, net_exposure: float = 0.0,
                               open_pairs: int = 0) -> None:
        with self.session() as s:
            s.add(EquitySnapshotRow(
                ts=_naive_utc(ts), mode=mode, equity=equity, cash=cash,
                gross_exposure=gross_exposure, net_exposure=net_exposure,
                open_pairs=open_pairs,
            ))
            s.commit()

    def load_equity_snapshots(self, mode: str | None = None, limit: int = 5000) -> pd.DataFrame:
        stmt = select(
            EquitySnapshotRow.ts, EquitySnapshotRow.mode, EquitySnapshotRow.equity,
            EquitySnapshotRow.cash, EquitySnapshotRow.gross_exposure,
            EquitySnapshotRow.net_exposure, EquitySnapshotRow.open_pairs,
        ).order_by(desc(EquitySnapshotRow.ts)).limit(limit)
        if mode:
            stmt = stmt.where(EquitySnapshotRow.mode == mode)
        with self.session() as s:
            rows = s.execute(stmt).all()
        df = pd.DataFrame(rows, columns=[
            "ts", "mode", "equity", "cash", "gross_exposure", "net_exposure", "open_pairs",
        ])
        return df.sort_values("ts").reset_index(drop=True)

    # -- backtest runs ------------------------------------------------------------

    def save_backtest_run(
        self,
        *,
        strategy: str,
        interval: str,
        start_ts: datetime,
        end_ts: datetime,
        params: dict[str, Any],
        metrics: dict[str, Any],
        report_path: str = "",
        equity_points: list[list] | None = None,
        trades: list[dict] | None = None,
    ) -> int:
        with self.session() as s:
            run = BacktestRunRow(
                created_at=_naive_utc(utc_now()),
                strategy=strategy,
                interval=interval,
                start_ts=_naive_utc(start_ts),
                end_ts=_naive_utc(end_ts),
                params_json=json.dumps(params, default=str),
                metrics_json=json.dumps(metrics, default=str),
                report_path=report_path,
                equity_json=json.dumps(equity_points or [], default=str),
                trades_json=json.dumps(trades or [], default=str),
            )
            s.add(run)
            s.commit()
            return run.id

    def list_backtest_runs(self, limit: int = 100) -> list[BacktestRunRow]:
        with self.session() as s:
            return list(
                s.execute(
                    select(BacktestRunRow).order_by(desc(BacktestRunRow.created_at)).limit(limit)
                ).scalars()
            )

    def get_backtest_run(self, run_id: int) -> BacktestRunRow | None:
        with self.session() as s:
            return s.get(BacktestRunRow, run_id)

    # -- dashboard audit trail ------------------------------------------------------

    def record_audit_event(self, *, actor: str, action: str, mode: str, confirmed: bool,
                           payload: dict[str, Any] | None = None, result: str = "") -> int:
        with self.session() as s:
            row = AuditEventRow(
                ts=_naive_utc(utc_now()), actor=actor, action=action, mode=mode,
                confirmed=confirmed, payload_json=json.dumps(payload or {}, default=str),
                result=result,
            )
            s.add(row)
            s.commit()
            return row.id

    def load_audit_events(self, limit: int = 200) -> list[AuditEventRow]:
        with self.session() as s:
            return list(
                s.execute(
                    select(AuditEventRow).order_by(desc(AuditEventRow.ts)).limit(limit)
                ).scalars()
            )

    def load_orders(self, limit: int = 200, symbol: str | None = None,
                    status: str | None = None) -> list[OrderRow]:
        stmt = select(OrderRow).order_by(desc(OrderRow.ts)).limit(limit)
        if symbol:
            stmt = stmt.where(OrderRow.symbol == symbol)
        if status:
            stmt = stmt.where(OrderRow.status == status)
        with self.session() as s:
            return list(s.execute(stmt).scalars())

    def load_trades(self, limit: int = 200, mode: str | None = None) -> list[TradeRow]:
        stmt = select(TradeRow).order_by(desc(TradeRow.exit_ts)).limit(limit)
        if mode:
            stmt = stmt.where(TradeRow.mode == mode)
        with self.session() as s:
            return list(s.execute(stmt).scalars())

    def load_signals(self, limit: int = 200) -> list[SignalRow]:
        with self.session() as s:
            return list(
                s.execute(select(SignalRow).order_by(desc(SignalRow.ts)).limit(limit)).scalars()
            )

    def last_backtest_run(self) -> BacktestRunRow | None:
        with self.session() as s:
            return s.execute(
                select(BacktestRunRow).order_by(desc(BacktestRunRow.created_at)).limit(1)
            ).scalar_one_or_none()

    def clear_bars(self, source: str | None = None) -> int:
        with self.session() as s:
            stmt = delete(BarRow)
            if source:
                stmt = stmt.where(BarRow.source == source)
            result = s.execute(stmt)
            s.commit()
            return result.rowcount or 0
