"""Kalman pair strategy and its engine integration."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from app.backtesting.engine import BacktestConfig, BacktestEngine
from app.data.market_data import PriceMatrix
from app.research.pair_selection import SelectedPair
from app.risk.kill_switch import KillSwitch
from app.risk.risk_manager import RiskLimits, RiskManager
from app.strategies.base import PositionContext
from app.strategies.kalman_pairs import KalmanPairConfig, KalmanPairStrategy
from app.tests.conftest import make_cointegrated_series

TS = datetime(2025, 6, 1, tzinfo=UTC)


def make_pair(beta: float = 1.1) -> SelectedPair:
    return SelectedPair(
        symbol_a="AAA", symbol_b="BBB", beta=beta, alpha=0.5, correlation=0.9,
        eg_pvalue=0.01, adf_pvalue=0.01, half_life=30.0, spread_std=0.01, score=5.0,
    )


def run_through(strategy: KalmanPairStrategy, log_a: np.ndarray, log_b: np.ndarray) -> list:
    """Drive the strategy bar by bar with engine-like position tracking."""
    signals = []
    position, held = 0, 0
    for i in range(len(log_a)):
        sig = strategy.on_bar(i, log_a, log_b, TS, PositionContext(position, held))
        if sig is None:
            held += 1 if position else 0
            continue
        signals.append(sig)
        if sig.action.is_entry:
            position = 1 if sig.action.value == "enter_long_spread" else -1
            held = 0
        elif sig.action.is_exit:
            position, held = 0, 0
    return signals


def test_kalman_strategy_trades_a_cointegrated_pair():
    log_a, log_b = make_cointegrated_series(n=2000, seed=21)
    strategy = KalmanPairStrategy(make_pair(), KalmanPairConfig(warmup_bars=150))
    signals = run_through(strategy, log_a, log_b)
    entries = [s for s in signals if s.action.is_entry]
    exits = [s for s in signals if s.action.is_exit]
    assert entries, "no entries on a genuinely cointegrated pair"
    assert exits, "entries must eventually exit"
    assert all(s.hedge_ratio > 0 for s in entries)
    assert all(abs(s.z_score) >= 2.0 for s in entries)


def test_no_entries_while_beta_is_insane():
    # x trends strongly so beta is identifiable; y = -x + noise drags the
    # filtered beta below beta_min. While beta was still transitioning through
    # the sane band entries are legitimately possible — the safeguard under
    # test is: once beta is OUTSIDE the band, a flat book gets no new entries.
    rng = np.random.default_rng(9)
    x = 4.0 + 0.005 * np.arange(1500) + rng.normal(0, 0.0005, 1500)
    y = -1.0 * x + rng.normal(0, 0.002, 1500) + 10.0
    strategy = KalmanPairStrategy(make_pair(beta=1.0),
                                  KalmanPairConfig(warmup_bars=150, delta=1e-2))
    run_through(strategy, y, x)
    assert strategy.beta < strategy.cfg.beta_min      # outside the sane band now
    sig = strategy.on_bar(len(y) - 1, y, x, TS, PositionContext(0, 0))
    assert sig is None or not sig.action.is_entry


def test_engine_smoke_with_kalman_factory():
    log_a, log_b = make_cointegrated_series(n=1500, seed=33)
    idx = pd.date_range("2025-01-01", periods=1500, freq="15min")
    close = pd.DataFrame({"AAA": np.exp(log_a), "BBB": np.exp(log_b)}, index=idx)
    open_ = close.shift(1)
    open_.iloc[0] = close.iloc[0]
    prices = PriceMatrix(close=close, open=open_, interval="15m")

    # leg B notional is beta * target (~1.1 * 1000): keep limits clear of it
    risk = RiskManager(
        limits=RiskLimits(max_notional_per_trade=2000.0, max_pair_notional=5000.0,
                          max_notional_per_asset=8000.0, max_gross_exposure=20_000.0,
                          max_net_exposure=20_000.0, max_pair_loss=1e9),
        kill_switch=KillSwitch(),
    )
    engine = BacktestEngine(
        prices, [make_pair()],
        lambda pair: KalmanPairStrategy(pair, KalmanPairConfig(warmup_bars=150)),
        risk, BacktestConfig(),
    )
    result = engine.run()
    assert result.equity.notna().all()
    assert np.isfinite(result.equity.to_numpy()).all()
    assert len(result.trades) >= 1
