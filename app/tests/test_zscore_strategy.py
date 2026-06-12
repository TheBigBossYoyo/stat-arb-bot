"""Rolling z-score machinery and signal state machine."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.core.math_utils import rolling_zscore, zscore_last
from app.core.types import SignalAction
from app.strategies.base import PositionContext
from app.strategies.pairs_zscore import ZScoreConfig, ZScorePairStrategy

TS = datetime(2025, 6, 1, tzinfo=UTC)
LOOKBACK = 50


def _strategy(selected_pair, **overrides) -> ZScorePairStrategy:
    cfg = ZScoreConfig(lookback_bars=LOOKBACK, entry_z=2.0, exit_z=0.3, stop_z=3.5,
                       max_holding_bars=96, **overrides)
    return ZScorePairStrategy(selected_pair, cfg)


def _series_with_final_z(strategy: ZScorePairStrategy, target_z: float, n: int = 120):
    """log_b == 0 so spread == log_a - alpha. Alternate +/-s noise, craft last point."""
    s = 0.01
    base = np.tile([s, -s], n // 2)[:n].astype(float)
    window = base[-(LOOKBACK):].copy()
    mean, std = window[:-1].mean(), window.std(ddof=1)
    # set final spread so that its window z-score is ~ target_z
    spread = base.copy()
    spread[-1] = mean + target_z * std
    log_a = strategy.alpha + spread          # beta * 0 = 0
    log_b = np.zeros(n)
    return log_a, log_b


def test_rolling_zscore_matches_manual_computation():
    series = pd.Series(np.arange(10, dtype=float))
    z = rolling_zscore(series, 5)
    window = series.iloc[3:8]
    expected = (series.iloc[7] - window.mean()) / window.std(ddof=1)
    assert z.iloc[7] == pytest.approx(expected)
    assert z.iloc[:4].isna().all()  # no partial windows


def test_zscore_last_basics():
    z, mean, std = zscore_last(np.array([1.0, 2.0, 3.0, 10.0]))
    assert z > 1.0
    assert mean == pytest.approx(4.0)
    z0, _, std0 = zscore_last(np.ones(10))
    assert z0 == 0.0 and std0 == 0.0


def test_entry_short_signal_when_z_above_threshold(selected_pair):
    strat = _strategy(selected_pair)
    log_a, log_b = _series_with_final_z(strat, +2.5)
    sig = strat.on_bar(len(log_a) - 1, log_a, log_b, TS, PositionContext(0, 0))
    assert sig is not None and sig.action is SignalAction.ENTER_SHORT_SPREAD
    assert sig.z_score == pytest.approx(2.5, abs=0.3)
    assert sig.hedge_ratio == selected_pair.beta


def test_entry_long_signal_when_z_below_threshold(selected_pair):
    strat = _strategy(selected_pair)
    log_a, log_b = _series_with_final_z(strat, -2.5)
    sig = strat.on_bar(len(log_a) - 1, log_a, log_b, TS, PositionContext(0, 0))
    assert sig is not None and sig.action is SignalAction.ENTER_LONG_SPREAD


def test_no_entry_when_z_small(selected_pair):
    strat = _strategy(selected_pair)
    log_a, log_b = _series_with_final_z(strat, 1.0)
    assert strat.on_bar(len(log_a) - 1, log_a, log_b, TS, PositionContext(0, 0)) is None


def test_no_entry_beyond_stop_z(selected_pair):
    """Entering at |z| beyond the stop level would be instantly stopped — skip it."""
    strat = _strategy(selected_pair)
    log_a, log_b = _series_with_final_z(strat, 5.0)
    assert strat.on_bar(len(log_a) - 1, log_a, log_b, TS, PositionContext(0, 0)) is None


def test_exit_when_z_reverts(selected_pair):
    strat = _strategy(selected_pair)
    log_a, log_b = _series_with_final_z(strat, 0.1)
    sig = strat.on_bar(len(log_a) - 1, log_a, log_b, TS, PositionContext(position=-1, bars_held=5))
    assert sig is not None and sig.action is SignalAction.EXIT


def test_stop_loss_when_z_blows_out(selected_pair):
    # note: the crafted outlier itself inflates the window std, so the realized
    # z is lower than the target — 6.0 lands around 4.5, safely past stop_z=3.5
    strat = _strategy(selected_pair)
    log_a, log_b = _series_with_final_z(strat, 6.0)
    sig = strat.on_bar(len(log_a) - 1, log_a, log_b, TS, PositionContext(position=-1, bars_held=5))
    assert sig is not None and sig.action is SignalAction.STOP_LOSS


def test_time_stop_after_max_holding(selected_pair):
    strat = _strategy(selected_pair)
    log_a, log_b = _series_with_final_z(strat, 1.5)  # not at exit/stop levels
    sig = strat.on_bar(len(log_a) - 1, log_a, log_b, TS, PositionContext(position=1, bars_held=96))
    assert sig is not None and sig.action is SignalAction.TIME_STOP


def test_no_signal_before_warmup(selected_pair):
    strat = _strategy(selected_pair)
    log_a, log_b = _series_with_final_z(strat, 3.0)
    short = LOOKBACK - 10
    assert strat.on_bar(short - 1, log_a[:short], log_b[:short], TS, PositionContext(0, 0)) is None
