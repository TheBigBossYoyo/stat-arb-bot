"""Momentum basket strategies (TSMOM / XSMOM) and OU s-scores."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.research.pca_residuals import ou_s_scores
from app.strategies.momentum import (
    TSMOMConfig,
    XSMOMConfig,
    make_tsmom_weight_fn,
    make_xsmom_weight_fn,
)


def _trend_universe(n: int = 300) -> pd.DataFrame:
    """Deterministic up/down/flat universe with tiny noise for vol estimates."""
    idx = pd.date_range("2025-01-01", periods=n, freq="15min")
    wiggle = 0.001 * np.sin(np.arange(n))                 # nonzero vol, no drift
    up = 100 * np.exp(np.linspace(0, 0.5, n) + wiggle)
    down = 100 * np.exp(np.linspace(0, -0.5, n) + wiggle)
    flat = 100 * np.exp(wiggle)
    return pd.DataFrame({"UP": up, "DOWN": down, "FLAT": flat}, index=idx)


def test_tsmom_goes_with_the_trend():
    close = _trend_universe()
    cfg = TSMOMConfig(lookback_bars=200, skip_bars=5, vol_window=50)
    weights = make_tsmom_weight_fn(cfg)(close)
    assert weights["UP"] > 0
    assert weights["DOWN"] < 0
    assert weights.abs().sum() == pytest.approx(1.0)


def test_tsmom_long_only_drops_shorts():
    close = _trend_universe()
    cfg = TSMOMConfig(lookback_bars=200, skip_bars=5, vol_window=50, long_only=True)
    weights = make_tsmom_weight_fn(cfg)(close)
    assert (weights >= 0).all()
    assert weights["DOWN"] == 0.0


def test_tsmom_insufficient_history_returns_zeros():
    close = _trend_universe(50)
    weights = make_tsmom_weight_fn(TSMOMConfig(lookback_bars=200, skip_bars=5))(close)
    assert weights.abs().sum() == 0.0


def test_xsmom_longs_winners_shorts_losers_dollar_neutral():
    close = _trend_universe()
    cfg = XSMOMConfig(lookback_bars=200, skip_bars=5, top_k=1)
    weights = make_xsmom_weight_fn(cfg)(close)
    assert weights["UP"] > 0                 # winner -> long (opposite of reversal)
    assert weights["DOWN"] < 0               # loser -> short
    assert weights.sum() == pytest.approx(0.0)
    assert weights.abs().sum() == pytest.approx(1.0)


def test_ou_s_scores_sign_and_kappa_filter():
    rng = np.random.default_rng(7)
    n = 400
    # OU process pinned well above its long-run mean at the end
    ou = np.zeros(n)
    for t in range(1, n):
        ou[t] = 0.9 * ou[t - 1] + rng.normal(0, 0.1)
    ou[-1] = 3.0 * np.std(ou)                # force a stretched residual
    walk = np.cumsum(rng.normal(0, 0.1, n))  # no mean reversion
    residual_returns = pd.DataFrame({"OU": np.diff(ou, prepend=0.0),
                                     "WALK": np.diff(walk, prepend=0.0)})
    # max_half_life=10: the OU series (true half-life ~6.6 bars) passes, while
    # the walk's finite-sample AR(1) estimate (b ~0.97, downward-biased) does not
    scores = ou_s_scores(residual_returns, window=200, max_half_life=10)
    assert scores["OU"] > 1.0                # stretched above equilibrium
    assert scores["WALK"] == 0.0             # excluded by the kappa filter
