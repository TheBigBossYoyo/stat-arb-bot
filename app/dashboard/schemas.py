"""Pydantic schemas for the dashboard API (never expose secrets here)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KillSwitchState(BaseModel):
    active: bool
    reason: str = ""


class BrokerStatus(BaseModel):
    broker: str
    display_name: str
    enabled: bool
    mode: str
    asset_class: str
    key_configured: bool
    connected: bool | None = None      # None = not probed
    latency_ms: float | None = None
    detail: str = ""
    capabilities: dict[str, Any] = Field(default_factory=dict)


class SystemStatus(BaseModel):
    mode: str                          # research | paper | live
    bot_status: str                    # running | idle | halted
    app_env: str
    live_trading_env: bool
    confirm_live_env: bool
    live_trading_allowed: bool
    controls_enabled: bool
    kill_switch: KillSwitchState
    brokers: list[BrokerStatus]
    last_equity_ts: datetime | None = None
    last_order_ts: datetime | None = None
    server_time: datetime


class PortfolioSummary(BaseModel):
    as_of: datetime | None = None
    equity: float = 0.0
    cash: float = 0.0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    gross_exposure: float = 0.0
    net_exposure: float = 0.0
    open_pairs: int = 0
    current_drawdown_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    n_trades: int = 0
    has_data: bool = False


class RiskLimitStatus(BaseModel):
    name: str
    current: float
    limit: float
    pct_used: float
    status: str                        # safe | warning | breached


class RiskStatus(BaseModel):
    kill_switch: KillSwitchState
    limits: list[RiskLimitStatus]
    as_of: datetime


class StrategyStatus(BaseModel):
    name: str
    version: str
    kind: str                          # pair | basket
    paused: bool = False
    health: str = "idle"               # healthy | degraded | paused | idle
    n_trades: int = 0
    total_pnl: float = 0.0
    win_rate_pct: float | None = None
    total_fees: float = 0.0
    last_signal_ts: datetime | None = None


class PairInfo(BaseModel):
    id: int
    universe: str
    interval: str
    symbol_a: str
    symbol_b: str
    beta: float
    alpha: float
    correlation: float
    eg_pvalue: float
    adf_pvalue: float
    half_life_bars: float
    spread_std: float
    score: float
    is_active: bool
    window_start: datetime
    window_end: datetime


class BacktestSummary(BaseModel):
    id: int
    strategy: str
    interval: str
    start_ts: datetime
    end_ts: datetime
    created_at: datetime
    metrics: dict[str, Any]
    report_path: str = ""


class BacktestDetail(BacktestSummary):
    params: dict[str, Any] = Field(default_factory=dict)
    equity: list[list[Any]] = Field(default_factory=list)   # [iso_ts, value]
    trades: list[dict[str, Any]] = Field(default_factory=list)


class OrderInfo(BaseModel):
    id: int
    ts: datetime
    mode: str
    broker: str
    strategy: str
    pair_key: str
    symbol: str
    side: str
    order_type: str
    quantity: float
    ref_price: float
    notional: float
    status: str
    fill_price: float
    fee: float
    error: str = ""


class TradeInfo(BaseModel):
    id: int
    mode: str
    strategy: str
    pair_key: str
    direction: str
    entry_ts: datetime
    exit_ts: datetime
    holding_bars: int
    entry_z: float
    exit_z: float
    pnl: float
    fees: float
    exit_reason: str


class SignalInfo(BaseModel):
    id: int
    ts: datetime
    mode: str
    strategy: str
    pair_key: str
    action: str
    z_score: float
    hedge_ratio: float
    accepted: bool
    reject_reason: str = ""


class AuditEventOut(BaseModel):
    id: int
    ts: datetime
    actor: str
    action: str
    mode: str
    confirmed: bool
    payload: dict[str, Any]
    result: str


class LogEvent(BaseModel):
    ts: str
    level: str
    logger: str
    message: str


class ConfirmedAction(BaseModel):
    """Body required by every dangerous POST endpoint."""

    confirm_phrase: str
    reason: str = ""


class JobRequest(BaseModel):
    kind: str                          # backtest | discover_pairs
    strategy: str = "pairs_zscore"
    universe: str = "crypto_top_10"
    interval: str = "15m"
    days: int | None = None
    lookback_days: int = 90
    bars_per_year: float | None = None
    max_half_life: float | None = None
    max_eg_pvalue: float | None = None


class JobInfo(BaseModel):
    id: str
    kind: str
    status: str                        # running | done | failed
    started_at: datetime
    finished_at: datetime | None = None
    error: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
