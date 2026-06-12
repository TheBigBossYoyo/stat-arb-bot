"""Backtest engine: no lookahead, slippage, fees, risk integration."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.engine import BacktestConfig, BacktestEngine
from app.data.market_data import PriceMatrix
from app.research.pair_selection import SelectedPair
from app.risk.kill_switch import KillSwitch
from app.risk.risk_manager import RiskLimits, RiskManager
from app.strategies.pairs_zscore import ZScoreConfig, ZScorePairStrategy

LOOKBACK = 50
SPIKE_I = 100          # spread spike bar -> entry signal here, fill at SPIKE_I+1
N = 200
NOISE = 0.01


def deterministic_prices() -> PriceMatrix:
    """Pair with a flat alternating spread, one +2.5-sigma spike at SPIKE_I,
    then pinned near the post-spike rolling mean so the trade exits immediately."""
    t = np.arange(N)
    spread = NOISE * np.where(t % 2 == 0, 1.0, -1.0)
    spread[SPIKE_I] = 2.5 * NOISE
    spread[SPIKE_I + 1 :] = 2.5 * NOISE / LOOKBACK  # ~ rolling mean incl. spike -> z ~ 0

    log_b = np.full(N, 4.0)
    log_a = 0.5 + 1.0 * log_b + spread
    close = pd.DataFrame({"AAA": np.exp(log_a), "BBB": np.exp(log_b)})
    open_ = close.shift(1)
    open_.iloc[0] = close.iloc[0]
    idx = pd.date_range("2025-01-01", periods=N, freq="15min")
    close.index = idx
    open_.index = idx
    return PriceMatrix(close=close, open=open_, interval="15m")


def make_pair() -> SelectedPair:
    return SelectedPair(
        symbol_a="AAA", symbol_b="BBB", beta=1.0, alpha=0.5, correlation=0.9,
        eg_pvalue=0.01, adf_pvalue=0.01, half_life=20.0, spread_std=NOISE, score=5.0,
    )


def strategy_factory(pair: SelectedPair) -> ZScorePairStrategy:
    cfg = ZScoreConfig(lookback_bars=LOOKBACK, entry_z=2.0, exit_z=0.3,
                       stop_z=5.0, max_holding_bars=96)
    return ZScorePairStrategy(pair, cfg)


WIDE_LIMITS = dict(
    max_notional_per_trade=1000.0, max_pair_notional=2500.0,
    max_notional_per_asset=5000.0, max_gross_exposure=10_000.0,
    max_net_exposure=10_000.0,
)


def run_engine(config: BacktestConfig, limits: RiskLimits | None = None):
    risk = RiskManager(limits=limits or RiskLimits(**WIDE_LIMITS),
                       kill_switch=KillSwitch())
    engine = BacktestEngine(deterministic_prices(), [make_pair()], strategy_factory, risk, config)
    return engine.run()


def test_signal_fills_on_next_bar_open_with_slippage():
    slippage_bps = 5.0
    result = run_engine(BacktestConfig(slippage_bps=slippage_bps, commission_bps=0.0))
    assert len(result.trades) == 1
    trade = result.trades[0]
    prices = deterministic_prices()

    assert trade.direction == "short_spread"  # spike up -> short the spread
    # the signal was generated on the spike bar...
    entries = [s for s in result.signals if s["accepted"] and s["action"].startswith("enter")]
    assert entries, "entry signal missing"
    assert entries[0]["ts"] == prices.index[SPIKE_I].to_pydatetime()
    # ...but filled at the NEXT bar's open (no lookahead), slippage against us
    assert trade.entry_ts == prices.index[SPIKE_I + 1]
    expected_fill_a = prices.open.iloc[SPIKE_I + 1]["AAA"] * (1 - slippage_bps / 10_000)
    expected_fill_b = prices.open.iloc[SPIKE_I + 1]["BBB"] * (1 + slippage_bps / 10_000)
    assert trade.entry_price_a == pytest.approx(expected_fill_a, rel=1e-12)
    assert trade.entry_price_b == pytest.approx(expected_fill_b, rel=1e-12)


def test_no_lookahead_entry_delay_shifts_fill():
    base = run_engine(BacktestConfig(slippage_bps=0.0, commission_bps=0.0))
    delayed = run_engine(BacktestConfig(slippage_bps=0.0, commission_bps=0.0, entry_delay_bars=1))
    prices = deterministic_prices()
    assert base.trades[0].entry_ts == prices.index[SPIKE_I + 1]
    assert delayed.trades[0].entry_ts == prices.index[SPIKE_I + 2]


def test_fees_are_charged_per_leg():
    no_fees = run_engine(BacktestConfig(slippage_bps=0.0, commission_bps=0.0))
    with_fees = run_engine(BacktestConfig(slippage_bps=0.0, commission_bps=100.0))  # 1%
    assert no_fees.metrics["total_fees"] == 0.0
    assert with_fees.metrics["total_fees"] > 0.0
    assert with_fees.trades[0].fees > 0.0
    assert with_fees.trades[0].pnl < no_fees.trades[0].pnl


def test_equity_curve_is_complete_and_finite():
    result = run_engine(BacktestConfig())
    assert len(result.equity) == N
    assert result.equity.notna().all()
    assert np.isfinite(result.equity.to_numpy()).all()


def test_risk_manager_blocks_all_trades_when_limit_zero():
    result = run_engine(BacktestConfig(), limits=RiskLimits(max_notional_per_trade=0.0))
    assert result.trades == []
    rejected = [s for s in result.signals if s["action"].startswith("enter") and not s["accepted"]]
    assert rejected, "entry should have been generated and rejected"


def test_open_position_is_closed_at_end_of_data():
    """Spike near the very end leaves no room to exit -> forced end_of_data close."""
    t = np.arange(N)
    spread = NOISE * np.where(t % 2 == 0, 1.0, -1.0)
    spread[N - 3 :] = 2.5 * NOISE  # spike persists to the end
    log_b = np.full(N, 4.0)
    close = pd.DataFrame({"AAA": np.exp(0.5 + log_b + spread), "BBB": np.exp(log_b)})
    open_ = close.shift(1)
    open_.iloc[0] = close.iloc[0]
    idx = pd.date_range("2025-01-01", periods=N, freq="15min")
    close.index = idx
    open_.index = idx
    prices = PriceMatrix(close=close, open=open_, interval="15m")

    risk = RiskManager(limits=RiskLimits(**WIDE_LIMITS), kill_switch=KillSwitch())
    result = BacktestEngine(prices, [make_pair()], strategy_factory, risk, BacktestConfig()).run()
    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "end_of_data"
