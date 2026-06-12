"""Production hardening: order manager, router, compliance, corporate actions,
freshness, hard money stops, accounting, websocket parsing, performance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from app.backtesting.engine import BacktestConfig, BacktestEngine
from app.brokers.base import BrokerBase
from app.brokers.binance.websocket import parse_kline_message
from app.brokers.models import Instrument, Order, OrderRequest, Position
from app.core.exceptions import RiskViolationError
from app.core.types import AssetClass, OrderStatus, OrderType, Side
from app.data.corporate_actions import Dividend, Split, adjust_for_dividends, adjust_for_splits
from app.data.live_feeds import FreshnessMonitor
from app.data.market_data import PriceMatrix
from app.execution.order_manager import OrderManager
from app.execution.pair_executor import Leg
from app.execution.smart_order_router import plan_pair_route
from app.portfolio.accounting import CashLedger, EntryKind, LedgerEntry
from app.risk.compliance import market_is_open, order_compliance_issues
from app.risk.kill_switch import KillSwitch
from app.risk.risk_manager import RiskLimits, RiskManager
from app.risk.stops import pair_loss_stop_triggered, unrealized_pair_pnl
from app.tests.test_backtester import WIDE_LIMITS, make_pair

UTC = UTC


# --- order manager -----------------------------------------------------------------


class FakeBroker(BrokerBase):
    name = "binance_spot"
    asset_class = AssetClass.CRYPTO_SPOT

    def __init__(self) -> None:
        super().__init__()
        self.placed: list[OrderRequest] = []

    def get_account(self): ...
    def get_cash(self) -> float: return 10_000.0
    def get_positions(self) -> list[Position]: return []
    def get_open_orders(self) -> list[Order]: return []
    def get_instruments(self, symbols=None) -> list[Instrument]: return []
    def get_market_data(self, symbol): return {}

    def place_order(self, request: OrderRequest) -> Order:
        self.placed.append(request)
        return Order(order_id="1", request=request, status=OrderStatus.FILLED,
                     filled_quantity=request.quantity, avg_fill_price=request.ref_price)

    def cancel_order(self, order_id, symbol=None) -> Order: ...
    def get_order_status(self, order_id, symbol=None) -> Order: ...


def portfolio_state():
    from app.risk.exposure import PortfolioState

    return PortfolioState(equity=10_000, cash=10_000, daily_start_equity=10_000,
                          peak_equity=10_000)


def test_order_manager_submits_validated_orders():
    broker = FakeBroker()
    manager = OrderManager(broker, RiskManager(kill_switch=KillSwitch()))
    order = manager.submit(
        OrderRequest(broker="binance_spot", symbol="BTCUSDT", side=Side.BUY,
                     quantity=0.0005, ref_price=50_000.0),
        portfolio_state(),
    )
    assert order.status is OrderStatus.FILLED
    assert len(broker.placed) == 1
    assert manager.confirm_filled(order)


def test_order_manager_blocks_risk_rejected_orders():
    broker = FakeBroker()
    risk = RiskManager(limits=RiskLimits(max_order_size_notional=1.0),
                       kill_switch=KillSwitch())
    manager = OrderManager(broker, risk)
    with pytest.raises(RiskViolationError):
        manager.submit(
            OrderRequest(broker="binance_spot", symbol="BTCUSDT", side=Side.BUY,
                         quantity=0.001, ref_price=50_000.0),
            portfolio_state(),
        )
    assert broker.placed == []                      # broker never touched


# --- smart order router ----------------------------------------------------------------


def test_router_orders_most_liquid_leg_first():
    plan = plan_pair_route(
        Leg("ILLIQ", Side.BUY, 1.0), Leg("LIQ", Side.SELL, 2.0),
        quote_volume_24h={"LIQ": 9e9, "ILLIQ": 1e6},
        quoted_spread_bps={"LIQ": 1.0, "ILLIQ": 4.0},
    )
    assert plan.first.symbol == "LIQ"
    assert plan.second.symbol == "ILLIQ"
    assert plan.order_type is OrderType.MARKET      # spreads are tight


def test_router_prefers_limit_on_wide_spread_and_rejects_extremes():
    plan = plan_pair_route(
        Leg("A", Side.BUY, 1.0), Leg("B", Side.SELL, 1.0),
        quoted_spread_bps={"A": 12.0, "B": 2.0},
    )
    assert plan.order_type is OrderType.LIMIT
    with pytest.raises(RiskViolationError):
        plan_pair_route(
            Leg("A", Side.BUY, 1.0), Leg("B", Side.SELL, 1.0),
            quoted_spread_bps={"A": 60.0, "B": 2.0}, max_spread_bps=25.0,
        )


# --- compliance --------------------------------------------------------------------------


def test_market_hours():
    weekday_open = datetime(2026, 6, 10, 15, 0)      # Wednesday 15:00 UTC
    weekday_closed = datetime(2026, 6, 10, 9, 0)
    weekend = datetime(2026, 6, 13, 15, 0)           # Saturday
    assert market_is_open(AssetClass.CRYPTO_SPOT, weekend)
    assert market_is_open(AssetClass.EQUITY, weekday_open)
    assert not market_is_open(AssetClass.EQUITY, weekday_closed)
    assert not market_is_open(AssetClass.EQUITY, weekend)


def test_stale_data_compliance():
    now = datetime(2026, 6, 10, 15, 0)
    fresh = order_compliance_issues(asset_class=AssetClass.CRYPTO_SPOT, ts=now,
                                    last_data_ts=now - timedelta(seconds=30))
    stale = order_compliance_issues(asset_class=AssetClass.CRYPTO_SPOT, ts=now,
                                    last_data_ts=now - timedelta(seconds=600))
    assert fresh == []
    assert any("stale" in issue for issue in stale)


# --- corporate actions ------------------------------------------------------------------


def bars(prices: list[float], start: str = "2026-01-01") -> pd.DataFrame:
    ts = pd.date_range(start, periods=len(prices), freq="1D")
    arr = np.array(prices, dtype=float)
    return pd.DataFrame({"ts": ts, "open": arr, "high": arr * 1.01,
                         "low": arr * 0.99, "close": arr, "volume": 1000.0})


def test_split_back_adjustment():
    df = bars([100, 102, 51, 52])                    # 2:1 split before bar 3
    adjusted = adjust_for_splits(df, [Split(ex_date=datetime(2026, 1, 3), ratio=2.0)])
    assert adjusted["close"].tolist() == [50.0, 51.0, 51.0, 52.0]
    assert adjusted["volume"].iloc[0] == 2000.0      # pre-split volume doubled
    assert adjusted["volume"].iloc[-1] == 1000.0


def test_dividend_back_adjustment():
    df = bars([100, 100, 98, 98])
    adjusted = adjust_for_dividends(df, [Dividend(ex_date=datetime(2026, 1, 3), amount=2.0)])
    assert adjusted["close"].iloc[0] == pytest.approx(98.0)   # factor 0.98 applied
    assert adjusted["close"].iloc[-1] == 98.0                 # post-ex untouched


# --- freshness / stops / ledger ------------------------------------------------------------


def test_freshness_monitor():
    monitor = FreshnessMonitor()
    now = datetime(2026, 6, 10, 12, 0)
    monitor.record("BTCUSDT", now - timedelta(seconds=60))
    assert monitor.is_fresh("BTCUSDT", 120, now=now)
    assert not monitor.is_fresh("BTCUSDT", 30, now=now)
    assert monitor.stale_symbols(["BTCUSDT", "UNKNOWN"], 120, now=now) == ["UNKNOWN"]


def test_unrealized_pair_pnl_and_trigger():
    pnl = unrealized_pair_pnl(direction=-1, qty_a=10, qty_b=20,
                              entry_price_a=100.0, entry_price_b=50.0,
                              mark_a=102.0, mark_b=50.0, entry_fees=1.0)
    assert pnl == pytest.approx(-21.0)               # short A moved against us + fees
    assert pair_loss_stop_triggered(pnl, max_pair_loss=20.0)
    assert not pair_loss_stop_triggered(pnl, max_pair_loss=25.0)


def test_engine_enforces_hard_money_stop():
    """Spread keeps diverging after entry: strategy stops are disabled, so only
    the risk layer's max_pair_loss can close the trade — and it must."""
    n, lookback, spike_i = 200, 50, 100
    t = np.arange(n)
    spread = 0.01 * np.where(t % 2 == 0, 1.0, -1.0)
    ramp = np.arange(n - spike_i) * 0.004
    spread[spike_i:] = 0.025 + ramp                  # enter short, then diverge hard
    log_b = np.full(n, 4.0)
    close = pd.DataFrame({"AAA": np.exp(0.5 + log_b + spread), "BBB": np.exp(log_b)})
    open_ = close.shift(1)
    open_.iloc[0] = close.iloc[0]
    idx = pd.date_range("2025-01-01", periods=n, freq="15min")
    close.index = idx
    open_.index = idx

    from app.strategies.pairs_zscore import ZScoreConfig, ZScorePairStrategy

    def factory(pair):
        return ZScorePairStrategy(pair, ZScoreConfig(
            lookback_bars=lookback, entry_z=2.0, exit_z=0.0,
            stop_z=1e9, max_holding_bars=10_000,
        ))

    limits = RiskLimits(**{**WIDE_LIMITS, "max_pair_loss": 5.0,
                           "max_daily_loss_pct": 100.0, "max_total_drawdown_pct": 100.0})
    risk = RiskManager(limits=limits, kill_switch=KillSwitch())
    engine = BacktestEngine(PriceMatrix(close=close, open=open_, interval="15m"),
                            [make_pair()], factory, risk, BacktestConfig())
    result = engine.run()
    assert len(result.trades) >= 1
    assert result.trades[0].exit_reason == "pair_loss_stop"
    assert result.trades[0].pnl < 0


def test_cash_ledger():
    ledger = CashLedger()
    ts = datetime(2026, 6, 10, tzinfo=UTC)
    ledger.record(LedgerEntry(ts, EntryKind.DEPOSIT, 1000.0))
    ledger.record_fill(ts, "BTCUSDT", cash_delta=-500.0, fee=0.5)
    assert ledger.balance() == pytest.approx(499.5)
    assert ledger.total_fees() == pytest.approx(0.5)


# --- websocket parsing -------------------------------------------------------------------


def kline_msg(closed: bool) -> dict:
    return {"data": {"e": "kline", "k": {
        "t": 1750000000000, "s": "BTCUSDT", "x": closed,
        "o": "100", "h": "101", "l": "99", "c": "100.5", "v": "12.5",
    }}}


def test_websocket_parser_only_emits_closed_bars():
    bar = parse_kline_message(kline_msg(closed=True))
    assert bar is not None and bar.symbol == "BTCUSDT" and bar.close == 100.5
    assert parse_kline_message(kline_msg(closed=False)) is None
    assert parse_kline_message({"data": {"e": "trade"}}) is None


# --- performance & equity snapshots ---------------------------------------------------------


def test_performance_aggregation_and_equity_snapshots(tmp_path):
    from app.data.storage import Storage
    from app.portfolio.performance import pair_performance, strategy_performance

    storage = Storage(f"sqlite:///{tmp_path / 'perf.db'}")
    storage.init_db()
    base = dict(mode="paper", direction="long_spread",
                entry_ts=datetime(2026, 6, 1), exit_ts=datetime(2026, 6, 2),
                holding_bars=10, entry_z=2.1, exit_z=0.2, beta=1.0,
                qty_a=1.0, qty_b=1.0, exit_reason="exit")
    storage.record_trade(strategy="s1", pair_key="A|B", pnl=10.0, fees=1.0, **base)
    storage.record_trade(strategy="s1", pair_key="A|B", pnl=-4.0, fees=1.0, **base)
    storage.record_trade(strategy="s2", pair_key="C|D", pnl=2.0, fees=0.5, **base)

    by_strategy = strategy_performance(storage)
    assert by_strategy.loc["s1", "n_trades"] == 2
    assert by_strategy.loc["s1", "total_pnl"] == pytest.approx(6.0)
    assert by_strategy.loc["s1", "win_rate_pct"] == pytest.approx(50.0)
    assert pair_performance(storage).loc["A|B", "total_fees"] == pytest.approx(2.0)

    storage.record_equity_snapshot(ts=datetime(2026, 6, 1), mode="paper",
                                   equity=10_000.0, cash=9_000.0, open_pairs=1)
    snaps = storage.load_equity_snapshots(mode="paper")
    assert len(snaps) == 1 and snaps["equity"].iloc[0] == 10_000.0
