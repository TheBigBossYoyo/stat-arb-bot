"""ML alpha sleeve: feature-panel hygiene and learnability of a planted signal."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
from app.research.ml_features import build_panel
from app.strategies.ml_alpha import MLAlphaConfig, MLAlphaWeights

HORIZONS = [5, 10, 21]
VOLS = [10, 21]
FORWARD = 5


def _momentum_world(n_assets: int = 12, n_bars: int = 700, seed: int = 3) -> pd.DataFrame:
    """Universe with a planted cross-sectional momentum effect: assets that
    outperformed over the past 21 bars keep outperforming, plus noise."""
    rng = np.random.default_rng(seed)
    rets = np.zeros((n_bars, n_assets))
    for t in range(1, n_bars):
        past = rets[max(0, t - 21): t].sum(axis=0)
        rank = past.argsort().argsort() / (n_assets - 1) - 0.5    # [-0.5, 0.5]
        rets[t] = 0.004 * rank + rng.normal(0, 0.004, n_assets)
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="D")
    cols = [f"A{i}" for i in range(n_assets)]
    return pd.DataFrame(100 * np.exp(rets.cumsum(axis=0)), index=idx, columns=cols)


def test_panel_features_are_ranked_and_targets_complete():
    close = _momentum_world()
    panel = build_panel(close, HORIZONS, VOLS, FORWARD)
    assert panel is not None
    assert np.all(np.abs(panel.X) <= 0.5 + 1e-9)        # rank transform range
    assert panel.latest.shape == (close.shape[1], len(panel.feature_names))
    # training rows: dates after warmup, stopping FORWARD bars before the end
    warmup = max(max(HORIZONS), max(VOLS))
    expected_rows = (len(close) - warmup - FORWARD) * close.shape[1]
    assert len(panel.X) == expected_rows


def test_panel_refuses_insufficient_data():
    close = _momentum_world(n_bars=30)
    assert build_panel(close, HORIZONS, VOLS, FORWARD) is None


def test_ml_alpha_learns_a_planted_momentum_signal():
    close = _momentum_world()
    cfg = MLAlphaConfig(horizons=HORIZONS, vol_windows=VOLS, forward_bars=FORWARD,
                        retrain_every=10, top_frac=0.25, min_train_rows=500)
    result = run_basket_backtest(
        close, MLAlphaWeights(cfg),
        BasketConfig(interval="1d", fit_window=300, rebalance_every=FORWARD,
                     cost_bps=0.0, bars_per_year=252.0),
    )
    # the effect is strong by construction; a working learner must print money
    assert result.metrics["total_return_pct"] > 10.0


def test_ml_alpha_returns_flat_weights_when_data_is_short():
    cfg = MLAlphaConfig(horizons=HORIZONS, vol_windows=VOLS, forward_bars=FORWARD)
    weights = MLAlphaWeights(cfg)(_momentum_world(n_bars=40))
    assert float(weights.abs().sum()) == 0.0


def _aux_for(close: pd.DataFrame, seed: int = 9) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    spread = 1.0 + np.abs(rng.normal(0, 0.01, close.shape))
    return {
        "open": close.shift(1).fillna(close) * (1 + rng.normal(0, 0.002, close.shape)),
        "high": close * spread,
        "low": close / spread,
        "volume": pd.DataFrame(rng.lognormal(10, 0.5, close.shape),
                               index=close.index, columns=close.columns),
    }


def test_panel_default_features_match_legacy_exactly():
    """Reproducibility guard: without `extended`, the feature set must stay
    byte-identical to the one behind the documented baseline results."""
    panel = build_panel(_momentum_world(), HORIZONS, VOLS, FORWARD)
    assert panel is not None
    assert panel.feature_names == ["ret_5", "ret_10", "ret_21", "vol_10",
                                   "vol_21", "price_z_10", "drawdown_21"]


def test_panel_aux_features_present_without_extra_warmup():
    close = _momentum_world()
    plain = build_panel(close, HORIZONS, VOLS, FORWARD)
    rich = build_panel(close, HORIZONS, VOLS, FORWARD, aux=_aux_for(close))
    assert rich is not None and plain is not None
    extra = set(rich.feature_names) - set(plain.feature_names)
    assert {"beta_21", "idio_vol_21", "volume_z_21", "volume_trend", "amihud_21",
            "overnight_10", "intraday_10", "park_vol_10", "range_ratio_10"} <= extra
    # aux features must not shrink the training panel (same warmup)
    assert len(rich.X) == len(plain.X)


def test_panel_drops_feature_frames_that_never_have_data():
    close = _momentum_world()
    aux = {"volume": pd.DataFrame(0.0, index=close.index, columns=close.columns)}
    panel = build_panel(close, HORIZONS, VOLS, FORWARD, aux=aux)
    assert panel is not None
    assert not any(name.startswith(("volume", "amihud")) for name in panel.feature_names)


def test_neutralized_target_is_orthogonal_to_momentum_ranks():
    close = _momentum_world()
    chars = [f"ret_{h}" for h in sorted(HORIZONS)[-2:]]
    panel = build_panel(close, HORIZONS, VOLS, FORWARD, neutralize_features=chars)
    assert panel is not None
    assert len(panel.neutralize_idx) == 2
    # per-construction: residualized target has ~zero projection on the chars
    M = panel.X[:, panel.neutralize_idx]
    proj = np.abs(M.T @ panel.y) / len(panel.y)
    assert np.all(proj < 1e-4)


def test_ml_alpha_neutral_book_is_dollar_neutral_and_trades():
    close = _momentum_world()
    cfg = MLAlphaConfig(horizons=HORIZONS, vol_windows=VOLS, forward_bars=FORWARD,
                        retrain_every=10, top_frac=0.25, min_train_rows=500,
                        orthogonal_features=True, momentum_neutral=True)
    weights = MLAlphaWeights(cfg)(close, aux=_aux_for(close))
    assert float(weights.sum()) == pytest.approx(0.0, abs=1e-9)
    assert float(weights.abs().sum()) == pytest.approx(1.0, abs=1e-9)
