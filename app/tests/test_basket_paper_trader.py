"""Basket paper trader: rebalancing, persistence, risk gating, idempotence."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.config.settings import get_settings
from app.data.storage import Storage
from app.execution.basket_paper_trader import BasketPaperConfig, BasketPaperTrader
from app.risk.kill_switch import KillSwitch
from app.risk.risk_manager import RiskManager, load_risk_limits

SYMBOLS = ["AAA", "BBB", "CCC", "DDD"]


def _seed_bars(storage: Storage, n_days: int, start: str = "2026-01-01") -> None:
    rng = np.random.default_rng(2)
    ts = pd.date_range(start, periods=n_days, freq="D")
    for i, symbol in enumerate(SYMBOLS):
        close = 100.0 * (i + 1) * np.exp(np.cumsum(rng.normal(0, 0.01, n_days)))
        df = pd.DataFrame({
            "ts": ts, "open": close, "high": close * 1.01, "low": close * 0.99,
            "close": close, "volume": 1e6,
        })
        storage.upsert_bars(df, source="yahoo", symbol=symbol, interval="1d")


def _trader(tmp_path, weight_fn, fit_window: int = 20, n_days: int = 30,
            min_trade_notional_pct: float = 0.0005,
            seed: bool = True) -> BasketPaperTrader:
    storage = Storage(f"sqlite:///{tmp_path / 'paper.db'}")
    storage.init_db()
    if seed:
        _seed_bars(storage, n_days)
    risk = RiskManager(limits=load_risk_limits(), kill_switch=KillSwitch())
    config = BasketPaperConfig(symbols=SYMBOLS, fit_window=fit_window,
                               starting_cash=10_000.0, label="test_basket",
                               min_trade_notional_pct=min_trade_notional_pct)
    return BasketPaperTrader(get_settings(), storage, weight_fn, risk, config,
                             refresh_data=False)


def static_weights(window: pd.DataFrame) -> pd.Series:
    # per-leg weights must clear max_order_size_notional_pct (16%): a real
    # ensemble book is this diversified or more
    return pd.Series({"AAA": 0.15, "BBB": 0.10, "CCC": -0.12, "DDD": -0.13})


def test_step_rebalances_to_target_weights(tmp_path):
    trader = _trader(tmp_path, static_weights)
    assert trader.step() is True
    equity = trader.broker.equity()
    marks = trader.broker._prices
    for symbol, want in static_weights(None).items():
        held = trader.broker.position(symbol) * marks[symbol] / equity
        assert held == pytest.approx(want, abs=0.01), symbol
    orders = trader.storage.load_orders(limit=10)
    assert len(orders) == 4
    assert all(o.status == "filled" for o in orders)
    snaps = trader.storage.load_equity_snapshots(mode="paper")
    assert len(snaps) == 1


def test_same_bar_is_not_processed_twice(tmp_path):
    trader = _trader(tmp_path, static_weights)
    assert trader.step() is True
    assert trader.step() is False                     # no new bar
    assert len(trader.storage.load_orders(limit=20)) == 4


def test_dust_rebalances_are_skipped(tmp_path):
    # 5% dust threshold: day-to-day price drift (~1%) must NOT trigger trades
    trader = _trader(tmp_path, static_weights, min_trade_notional_pct=0.05)
    trader.step()
    n_orders = len(trader.storage.load_orders(limit=20))
    assert n_orders == 4                              # initial book build
    _seed_bars(trader.storage, 31)                    # one more day, same targets
    assert trader.step() is True
    assert len(trader.storage.load_orders(limit=40)) == n_orders

def test_kill_switch_blocks_all_orders(tmp_path):
    trader = _trader(tmp_path, static_weights)
    trader.risk.kill_switch.engage("test")
    assert trader.step() is True                      # bar processed...
    assert trader.storage.load_orders(limit=10) == [] # ...but nothing traded
    assert trader.broker.positions == {}
    # equity snapshot still recorded for monitoring
    assert len(trader.storage.load_equity_snapshots(mode="paper")) == 1


def test_short_history_refuses_to_trade(tmp_path):
    trader = _trader(tmp_path, static_weights, fit_window=300, n_days=30)
    assert trader.step() is False
    assert trader.storage.load_orders(limit=10) == []


def test_empty_database_triggers_one_deep_backfill(tmp_path):
    """A fresh DB must not refuse forever: the trader backfills enough
    calendar days to cover the fit window, once, then trades."""
    trader = _trader(tmp_path, static_weights, seed=False)
    trader.refresh_data = True
    calls: list[int] = []

    def fake_refresh(days: int) -> None:
        calls.append(days)
        if days > trader.cfg.refresh_days:        # the deep backfill call
            _seed_bars(trader.storage, 30)

    trader._refresh = fake_refresh
    assert trader.step() is True
    assert calls == [trader.cfg.refresh_days, trader._backfill_days()]
    assert len(trader.storage.load_orders(limit=10)) == 4
    # the backfill is attempted at most once per process
    assert trader.step() is False
    assert calls[2:] == [trader.cfg.refresh_days]


def test_relative_sqlite_url_is_anchored_to_project_root():
    from app.config.settings import PROJECT_ROOT, Settings

    anchored = Settings(database_url="sqlite:///stat_arb.db").database_url
    assert anchored == f"sqlite:///{(PROJECT_ROOT / 'stat_arb.db').as_posix()}"
    # absolute and non-sqlite URLs pass through unchanged
    absolute = "sqlite:///C:/tmp/x.db"
    assert Settings(database_url=absolute).database_url == absolute
    postgres = "postgresql://user:pw@host/db"
    assert Settings(database_url=postgres).database_url == postgres


def test_wants_aux_weight_fn_receives_aux(tmp_path):
    seen: dict = {}

    class AuxFn:
        wants_aux = True

        def __call__(self, window, aux=None):
            seen["aux"] = aux
            return pd.Series(0.0, index=window.columns)

    trader = _trader(tmp_path, AuxFn())
    assert trader.step() is True
    assert seen["aux"] is not None and "volume" in seen["aux"]
