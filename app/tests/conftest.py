"""Shared test fixtures. No live API calls anywhere in the test suite."""

from __future__ import annotations

import numpy as np
import pytest

from app.research.pair_selection import SelectedPair


def make_cointegrated_series(
    n: int = 1500,
    beta: float = 1.1,
    alpha: float = 0.5,
    half_life: float = 30.0,
    bar_vol: float = 0.004,
    spread_vol: float = 0.0025,
    seed: int = 7,
) -> tuple[np.ndarray, np.ndarray]:
    """(log_a, log_b) where log_a = alpha + beta*log_b + OU(half_life)."""
    rng = np.random.default_rng(seed)
    log_b = 4.0 + np.cumsum(rng.normal(0.0, bar_vol, n))
    phi = np.exp(-np.log(2.0) / half_life)
    noise = rng.normal(0.0, spread_vol, n)
    spread = np.empty(n)
    spread[0] = noise[0]
    for t in range(1, n):
        spread[t] = phi * spread[t - 1] + noise[t]
    log_a = alpha + beta * log_b + spread
    return log_a, log_b


def make_random_walks(n: int = 1500, seed: int = 11) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    a = 4.0 + np.cumsum(rng.normal(0.0, 0.004, n))
    b = 5.0 + np.cumsum(rng.normal(0.0, 0.004, n))
    return a, b


@pytest.fixture
def cointegrated_pair() -> tuple[np.ndarray, np.ndarray]:
    return make_cointegrated_series()


@pytest.fixture
def selected_pair() -> SelectedPair:
    return SelectedPair(
        symbol_a="AAAUSDT", symbol_b="BBBUSDT", beta=1.1, alpha=0.5,
        correlation=0.9, eg_pvalue=0.01, adf_pvalue=0.01, half_life=30.0,
        spread_std=0.01, score=10.0,
    )
