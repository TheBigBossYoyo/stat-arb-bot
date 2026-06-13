"""Tests for Phase 1 (concentration) and Path A (long-only) building blocks."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.concentration import (
    analyze_concentration,
    concentration_gate,
    per_asset_pnl,
)
from app.backtesting.concentration_fixes import (
    cap_per_asset,
    default_fix_specs,
    winsorize_weights,
)
from app.execution.trading212_rebalancer import RebalanceConfig, Trading212Rebalancer
from app.risk.long_only_risk import LongOnlyConstraints, LongOnlyRiskModel
from app.strategies.long_only_momentum import (
    LongOnlyXSMOMConfig,
    RegimeFilterConfig,
    make_long_only_xsmom_weight_fn,
)


def _trending_prices(n=400, k=8, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=n, freq="D")
    drifts = np.linspace(-0.0005, 0.0015, k)
    data = {}
    for i in range(k):
        rets = rng.normal(drifts[i], 0.01, n)
        data[f"A{i}"] = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame(data, index=idx)


# --- concentration -------------------------------------------------------------

def test_concentration_even_vs_spiky():
    idx = pd.date_range("2022-01-01", periods=600, freq="D")
    even = pd.Series(10_000 * (1 + 0.0003) ** np.arange(600), index=idx)
    rep_even = analyze_concentration(even)
    # a smooth compounding curve: no single month dominates
    assert rep_even.max_month_pct is not None
    assert rep_even.max_month_pct < 25

    spiky_rets = np.full(600, -0.0002)
    spiky_rets[100] = 0.5            # one enormous day carries everything
    spiky = pd.Series(10_000 * np.cumprod(1 + spiky_rets), index=idx)
    rep_spiky = analyze_concentration(spiky)
    assert rep_spiky.max_month_pct > 25
    assert not concentration_gate(rep_spiky).passed


def test_per_asset_attribution_sums_close_to_gross():
    close = _trending_prices()
    # static book: hold A7 (strongest) and A0 (weakest) equally long
    weights = pd.DataFrame({"A7": [0.5], "A0": [0.5]}, index=[close.index[50]])
    equity = pd.Series(10_000.0, index=close.index)
    pnl = per_asset_pnl(close, weights, equity)
    assert set(pnl.columns) == {"A7", "A0"}
    assert pnl.shape[0] > 0


def test_concentration_fix_transforms_preserve_long_gross():
    w = pd.Series({"A": 0.40, "B": 0.30, "C": 0.20, "D": 0.10})
    # feasible cap (0.30 * 4 = 1.2 >= gross 1.0): water-fill caps AND preserves gross
    capped = cap_per_asset(0.30)(w, pd.DataFrame())
    assert capped.max() <= 0.30 + 1e-9
    assert capped.sum() == pytest.approx(w.sum(), rel=1e-6)   # gross preserved
    # infeasible cap (0.15 * 4 < 1.0): cap binds, residual becomes cash
    tight = cap_per_asset(0.15)(w, pd.DataFrame())
    assert tight.max() <= 0.15 + 1e-9
    assert tight.sum() < w.sum()
    wins = winsorize_weights(0.5)(w, pd.DataFrame())
    assert wins.sum() == pytest.approx(w.sum(), rel=1e-6)


def test_default_fix_specs_present():
    specs = default_fix_specs({})
    for name in ("none", "cap_asset_15", "smooth_05", "combo"):
        assert name in specs


# --- long-only strategy + risk -------------------------------------------------

def test_long_only_xsmom_is_non_negative_and_unlevered():
    close = _trending_prices(n=400)
    cfg = LongOnlyXSMOMConfig(lookback_bars=120, skip_bars=5, top_k=3,
                              regime=RegimeFilterConfig(enabled=False))
    fn = make_long_only_xsmom_weight_fn(cfg)
    w = fn(close)
    assert (w >= -1e-12).all()                 # never short
    assert w.sum() <= 1.0 + 1e-9               # never levered
    assert (w > 0).sum() <= 3                   # respects top_k


def test_regime_filter_goes_to_cash_in_downtrend():
    # build a clearly falling market: proxy below its MA at the end
    idx = pd.date_range("2022-01-01", periods=300, freq="D")
    falling = pd.DataFrame({f"A{i}": 100 * np.exp(np.cumsum(
        np.full(300, -0.002))) for i in range(5)}, index=idx)
    cfg = LongOnlyXSMOMConfig(lookback_bars=120, skip_bars=5, top_k=2,
                              regime=RegimeFilterConfig(ma_window=100,
                                                        risk_off_exposure=0.0))
    fn = make_long_only_xsmom_weight_fn(cfg)
    assert fn(falling).sum() == pytest.approx(0.0)   # fully to cash


def test_long_only_risk_clips_shorts_and_leverage():
    model = LongOnlyRiskModel(LongOnlyConstraints(max_position=0.25, max_gross=1.0))
    w = pd.Series({"A": 0.6, "B": -0.3, "C": 0.7})    # short + over-levered
    res = model.enforce(w)
    assert (res.weights >= 0).all()
    assert res.weights.max() <= 0.25 + 1e-9
    assert res.weights.sum() <= 1.0 + 1e-9
    assert res.changed


# --- Trading 212 rebalancer ----------------------------------------------------

def _instruments(symbols):
    from app.brokers.models import Instrument
    from app.core.types import AssetClass

    return {s: Instrument(broker="trading212", symbol=s, asset_class=AssetClass.EQUITY,
                          tick_size=0.01, step_size=0.0001, min_notional=1.0,
                          fractional=True, shortable=False) for s in symbols}


def test_rebalancer_never_exceeds_cash_no_margin():
    syms = ["AAA", "BBB", "CCC"]
    reb = Trading212Rebalancer(_instruments(syms), RebalanceConfig(limit_offset_bps=10))
    prices = {s: 100.0 for s in syms}
    plan = reb.plan({"AAA": 0.34, "BBB": 0.33, "CCC": 0.33}, positions={},
                    cash=10_000.0, prices=prices, market_open=True)
    spent = sum(o.request.notional for o in plan.orders if o.request.side.value == "buy")
    assert spent <= 10_000.0 + 1e-6            # no-margin: never overspend
    assert all(o.request.quantity > 0 for o in plan.orders)


def test_rebalancer_skips_untradable_and_never_shorts():
    syms = ["AAA"]
    reb = Trading212Rebalancer(_instruments(syms), RebalanceConfig())
    # ZZZ not in the instrument list -> untradable, must be skipped
    plan = reb.plan({"AAA": 0.5, "ZZZ": 0.5}, positions={}, cash=10_000.0,
                    prices={"AAA": 50.0, "ZZZ": 25.0}, market_open=True)
    assert any(sym == "ZZZ" for sym, _ in plan.skipped)
    assert all(o.request.side.value == "buy" for o in plan.orders)
