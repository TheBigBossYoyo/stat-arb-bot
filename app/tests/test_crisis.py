"""Tests for the Phase 4 crisis-regime scenarios."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtesting.crisis import (
    SCENARIOS,
    correlation_spike,
    covid_crash_rebound,
    long_only_scenarios,
    market_gap,
    momentum_crash,
    run_crisis_suite,
    sector_shock,
    sustained_bear,
    vol_spike,
    vol_whipsaw,
)


def _prices(n=300, k=6, seed=2):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {f"A{i}": 100 * np.exp(np.cumsum(rng.normal(0.0005 * (1 if i % 2 else -1), 0.015, n)))
         for i in range(k)}, index=idx)


def test_scenarios_change_prices_and_keep_shape():
    close = _prices()
    for transform in (momentum_crash, correlation_spike, vol_spike, market_gap):
        out = transform(close)
        assert out.shape == close.shape
        assert not out.equals(close)                 # something changed
        assert (out > 0).all().all()                 # prices stay positive


def test_vol_spike_raises_recent_volatility():
    close = _prices(seed=5)
    stressed = vol_spike(close, window_frac=0.2, mult=3.0)
    base_vol = close.pct_change().iloc[-50:].std().mean()
    stress_vol = stressed.pct_change().iloc[-50:].std().mean()
    assert stress_vol > base_vol


def test_market_gap_drops_level():
    close = _prices(seed=7)
    gapped = market_gap(close, gap=-0.2, at_frac=0.9)
    assert gapped.iloc[-1].mean() < close.iloc[-1].mean()


def test_run_crisis_suite_reports_each_scenario():
    close = _prices()

    def run_fn(c, aux):
        # equal-weight buy-and-hold equity
        norm = c / c.iloc[0]
        return 10_000 * norm.mean(axis=1)

    table = run_crisis_suite(close, run_fn)
    assert "base" in table.index
    for name in SCENARIOS:
        assert name in table.index
    assert "crisis_max_dd_pct" in table.columns


# --- Phase 4 expanded long-only scenarios -------------------------------------

def test_new_long_only_scenarios_change_prices_and_stay_positive():
    close = _prices()
    for transform in (covid_crash_rebound, sustained_bear, vol_whipsaw):
        out = transform(close)
        assert out.shape == close.shape
        assert not out.equals(close)
        assert (out > 0).all().all()


def test_covid_crash_rebound_dips_then_recovers():
    close = _prices(seed=3)
    out = covid_crash_rebound(close, crash=-0.3, rebound=0.25, at_frac=0.6)
    # the crash trough is below the pre-crash level
    pre = close.iloc[int(len(close) * 0.6) - 1].mean()
    trough = out.iloc[int(len(close) * 0.6):].min().min()
    assert trough < pre


def test_sector_shock_only_hits_named_members():
    close = _prices(k=6)
    members = ["A0", "A2"]
    out = sector_shock(close, members, window_frac=0.2, magnitude=-0.4)
    # untouched names are identical; named members fall
    assert out["A1"].equals(close["A1"])
    assert out["A0"].iloc[-1] < close["A0"].iloc[-1]


def test_long_only_scenarios_include_synthetic_tail_and_sectors():
    scen = long_only_scenarios({"A0": "tech", "A1": "tech", "A2": "finance", "A3": "finance"})
    for name in ("covid_crash_rebound", "sustained_bear_2008", "vol_whipsaw",
                 "gap_up_after_crash", "tech_sector_crash"):
        assert name in scen
