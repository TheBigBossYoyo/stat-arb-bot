"""Kalman hedge-ratio filter."""

from __future__ import annotations

import numpy as np
import pytest

from app.research.kalman import KalmanHedgeFilter


def test_filter_series_output_dimensions():
    rng = np.random.default_rng(1)
    x = np.cumsum(rng.normal(0, 0.01, 300)) + 4.0
    y = 1.2 * x + 0.1 + rng.normal(0, 0.005, 300)
    result = KalmanHedgeFilter().filter_series(y, x)
    for arr in (result.betas, result.alphas, result.residuals, result.residual_vars):
        assert arr.shape == (300,)
    assert np.all(np.isfinite(result.betas))
    assert np.all(result.residual_vars > 0)


def test_beta_converges_to_true_value():
    rng = np.random.default_rng(2)
    x = np.cumsum(rng.normal(0, 0.01, 2000)) + 5.0
    y = 1.5 * x + 0.3 + rng.normal(0, 0.002, 2000)
    result = KalmanHedgeFilter(delta=1e-4, r=1e-4).filter_series(y, x)
    assert result.betas[-1] == pytest.approx(1.5, abs=0.1)


def test_beta_tracks_a_regime_change():
    rng = np.random.default_rng(3)
    x = np.cumsum(rng.normal(0, 0.01, 3000)) + 5.0
    beta_true = np.where(np.arange(3000) < 1500, 1.0, 1.6)
    y = beta_true * x + rng.normal(0, 0.002, 3000)
    result = KalmanHedgeFilter(delta=1e-3, r=1e-4).filter_series(y, x)
    assert result.betas[1400] == pytest.approx(1.0, abs=0.15)
    assert result.betas[-1] == pytest.approx(1.6, abs=0.15)


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        KalmanHedgeFilter().filter_series(np.ones(10), np.ones(9))
