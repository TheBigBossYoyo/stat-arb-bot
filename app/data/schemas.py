"""SQLAlchemy ORM schema.

Raw market data, research artifacts (pairs), and the full audit trail
(signals, orders, trades, backtest runs) live in separate tables. SQLite for
local mode; PostgreSQL/TimescaleDB works unchanged via DATABASE_URL.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BarRow(Base):
    """Raw OHLCV bars. Timestamps are tz-naive UTC (bar open time)."""

    __tablename__ = "bars"
    __table_args__ = (
        UniqueConstraint("source", "symbol", "interval", "ts", name="uq_bar"),
        Index("ix_bars_lookup", "symbol", "interval", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32))           # binance | synthetic | ...
    symbol: Mapped[str] = mapped_column(String(32))
    interval: Mapped[str] = mapped_column(String(8))
    ts: Mapped[datetime] = mapped_column(DateTime)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float] = mapped_column(Float)


class PairRow(Base):
    """A selected tradeable pair with its research statistics."""

    __tablename__ = "pairs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    universe: Mapped[str] = mapped_column(String(64))
    interval: Mapped[str] = mapped_column(String(8))
    symbol_a: Mapped[str] = mapped_column(String(32))
    symbol_b: Mapped[str] = mapped_column(String(32))
    beta: Mapped[float] = mapped_column(Float)
    alpha: Mapped[float] = mapped_column(Float)
    correlation: Mapped[float] = mapped_column(Float)
    eg_pvalue: Mapped[float] = mapped_column(Float)
    adf_pvalue: Mapped[float] = mapped_column(Float)
    half_life_bars: Mapped[float] = mapped_column(Float)
    spread_std: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    window_start: Mapped[datetime] = mapped_column(DateTime)
    window_end: Mapped[datetime] = mapped_column(DateTime)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class SignalRow(Base):
    """Every signal a strategy emitted, accepted or not."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    mode: Mapped[str] = mapped_column(String(16))              # backtest | paper | live
    strategy: Mapped[str] = mapped_column(String(64))
    strategy_version: Mapped[str] = mapped_column(String(16))
    pair_key: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(32))
    z_score: Mapped[float] = mapped_column(Float)
    hedge_ratio: Mapped[float] = mapped_column(Float)
    spread: Mapped[float] = mapped_column(Float)
    spread_mean: Mapped[float] = mapped_column(Float)
    spread_std: Mapped[float] = mapped_column(Float)
    accepted: Mapped[bool] = mapped_column(Boolean)
    reject_reason: Mapped[str] = mapped_column(Text, default="")


class OrderRow(Base):
    """Every order attempt, with full signal context and risk-check outcome."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    mode: Mapped[str] = mapped_column(String(16))
    broker: Mapped[str] = mapped_column(String(32))
    strategy: Mapped[str] = mapped_column(String(64))
    pair_key: Mapped[str] = mapped_column(String(80), default="")
    symbol: Mapped[str] = mapped_column(String(32))
    side: Mapped[str] = mapped_column(String(8))
    order_type: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[float] = mapped_column(Float)
    ref_price: Mapped[float] = mapped_column(Float)
    notional: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(24))
    fill_price: Mapped[float] = mapped_column(Float, default=0.0)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    signal_json: Mapped[str] = mapped_column(Text, default="{}")
    risk_checks_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str] = mapped_column(Text, default="")


class TradeRow(Base):
    """A completed round-trip pair trade."""

    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mode: Mapped[str] = mapped_column(String(16))
    strategy: Mapped[str] = mapped_column(String(64))
    pair_key: Mapped[str] = mapped_column(String(80))
    direction: Mapped[str] = mapped_column(String(16))         # long_spread | short_spread
    entry_ts: Mapped[datetime] = mapped_column(DateTime)
    exit_ts: Mapped[datetime] = mapped_column(DateTime)
    holding_bars: Mapped[int] = mapped_column(Integer)
    entry_z: Mapped[float] = mapped_column(Float)
    exit_z: Mapped[float] = mapped_column(Float)
    beta: Mapped[float] = mapped_column(Float)
    qty_a: Mapped[float] = mapped_column(Float)
    qty_b: Mapped[float] = mapped_column(Float)
    pnl: Mapped[float] = mapped_column(Float)
    fees: Mapped[float] = mapped_column(Float)
    exit_reason: Mapped[str] = mapped_column(String(32))


class EquitySnapshotRow(Base):
    """Per-bar equity snapshots from paper/live trading (drives the dashboard)."""

    __tablename__ = "equity_snapshots"
    __table_args__ = (Index("ix_equity_mode_ts", "mode", "ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    mode: Mapped[str] = mapped_column(String(16))
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    gross_exposure: Mapped[float] = mapped_column(Float, default=0.0)
    net_exposure: Mapped[float] = mapped_column(Float, default=0.0)
    open_pairs: Mapped[int] = mapped_column(Integer, default=0)


class BacktestRunRow(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    strategy: Mapped[str] = mapped_column(String(64))
    interval: Mapped[str] = mapped_column(String(8))
    start_ts: Mapped[datetime] = mapped_column(DateTime)
    end_ts: Mapped[datetime] = mapped_column(DateTime)
    params_json: Mapped[str] = mapped_column(Text, default="{}")
    metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    report_path: Mapped[str] = mapped_column(Text, default="")
    equity_json: Mapped[str] = mapped_column(Text, default="[]")   # downsampled [ts, value]
    trades_json: Mapped[str] = mapped_column(Text, default="[]")


class AuditEventRow(Base):
    """Every dashboard control action, successful or refused."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    actor: Mapped[str] = mapped_column(String(64), default="local")
    action: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16), default="paper")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result: Mapped[str] = mapped_column(Text, default="")
