"""Tests for Path B (crypto futures): engine, strategies, risk."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.futures_engine import (
    FuturesConfig,
    align_funding_to_bars,
    run_futures_backtest,
)
from app.risk.futures_risk import FuturesRiskLimits, FuturesRiskModel
from app.strategies.crypto_tsmom_futures import (
    CryptoTSMOMConfig,
    make_crypto_tsmom_weight_fn,
)
from app.strategies.funding_carry import FundingCarryConfig, make_funding_carry_weight_fn


def _futures_prices(n=400, k=6, seed=3):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    cols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "ADAUSDT", "LINKUSDT", "DOTUSDT"][:k]
    data = {}
    for i, c in enumerate(cols):
        drift = 0.0005 * (1 if i % 2 == 0 else -1)
        data[c] = 100 * np.exp(np.cumsum(rng.normal(drift, 0.02, n)))
    return pd.DataFrame(data, index=idx)


# --- engine --------------------------------------------------------------------

def test_futures_engine_runs_and_caps_leverage():
    close = _futures_prices()
    cfg = FuturesConfig(fit_window=120, leverage=1.0, max_leverage=2.0)
    fn = make_crypto_tsmom_weight_fn(CryptoTSMOMConfig(lookback_bars=[20, 40], vol_window=20))
    res = run_futures_backtest(close, fn, cfg)
    assert len(res.equity.dropna()) > 0
    assert res.weights.abs().sum(axis=1).max() <= cfg.max_leverage + 1e-6


def test_align_funding_sums_into_bars():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    # three 8h prints per day for one symbol
    fidx = pd.date_range("2024-01-01", periods=15, freq="8h")
    panel = pd.DataFrame({"BTCUSDT": np.full(15, 0.0001)}, index=fidx)
    aligned = align_funding_to_bars(panel, idx, ["BTCUSDT"])
    assert aligned is not None
    # each day should sum ~3 prints = 0.0003 (last partial bar may differ)
    assert aligned[0, 0] == pytest.approx(0.0003, abs=1e-9)


def test_funding_applied_costs_longs():
    close = _futures_prices(seed=1)
    # constant positive funding: a persistent long should pay it (lower equity)
    fidx = pd.date_range(close.index[0], periods=len(close) * 3, freq="8h")
    panel = pd.DataFrame({c: np.full(len(fidx), 0.0005) for c in close.columns}, index=fidx)
    cfg = FuturesConfig(fit_window=120, apply_funding=True)
    long_fn = lambda w: pd.Series(1.0 / close.shape[1], index=w.columns)  # noqa: E731
    with_f = run_futures_backtest(close, long_fn, cfg, funding=panel)
    cfg_no = FuturesConfig(fit_window=120, apply_funding=False)
    without = run_futures_backtest(close, long_fn, cfg_no)
    assert with_f.funding_paid > 0                       # longs paid funding
    assert with_f.equity.dropna().iloc[-1] < without.equity.dropna().iloc[-1]


# --- strategies ----------------------------------------------------------------

def test_tsmom_caps_btc_eth_beta():
    close = _futures_prices()
    fn = make_crypto_tsmom_weight_fn(CryptoTSMOMConfig(
        lookback_bars=[20], vol_window=20, max_beta_gross=0.30))
    w = fn(close)
    beta_gross = abs(w.get("BTCUSDT", 0)) + abs(w.get("ETHUSDT", 0))
    assert beta_gross <= 0.30 + 1e-6


def test_funding_carry_shorts_high_funding():
    close = _futures_prices()
    fidx = pd.date_range(close.index[0], periods=len(close), freq="D")
    # SOLUSDT pays the richest funding -> should be shorted
    fund = pd.DataFrame({c: np.full(len(fidx), 0.0001) for c in close.columns}, index=fidx)
    fund["SOLUSDT"] = 0.01
    fn = make_funding_carry_weight_fn(FundingCarryConfig(lookback_bars=5, top_k=2, entry_apr=0.05))
    w = fn(close, aux={"funding": fund})
    assert w.get("SOLUSDT", 0) < 0                       # rich funding -> short


# --- risk ----------------------------------------------------------------------

def test_futures_risk_caps_leverage_and_buffer():
    model = FuturesRiskModel(FuturesRiskLimits(max_leverage=2.0, min_liquidation_distance=0.2))
    w = pd.Series({"BTCUSDT": 2.0, "ETHUSDT": 1.5})      # gross 3.5 > cap
    res = model.screen(w)
    assert res.weights.abs().sum() <= 2.0 + 1e-6


def test_futures_kill_switch_on_abnormal_funding():
    model = FuturesRiskModel(FuturesRiskLimits(abnormal_funding_apr=0.5))
    w = pd.Series({"BTCUSDT": 0.5, "ETHUSDT": 0.5})
    res = model.screen(w, funding_apr=pd.Series({"BTCUSDT": 2.0, "ETHUSDT": 0.1}))
    assert res.kill
    assert res.weights.abs().sum() == 0.0                # fail-closed: flat
