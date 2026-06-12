"""Cointegration research stack: ADF wrapper, hedge ratio, half-life, selection."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.math_utils import half_life_of_mean_reversion, ols_hedge_ratio
from app.research.cointegration import cointegration_test
from app.research.pair_selection import PairSelectionConfig, PairSelector
from app.research.stationarity import adf_test
from app.tests.conftest import make_cointegrated_series, make_random_walks


def test_hedge_ratio_recovers_known_beta(cointegrated_pair):
    log_a, log_b = cointegrated_pair
    beta, alpha = ols_hedge_ratio(log_a, log_b)
    assert beta == pytest.approx(1.1, abs=0.05)
    assert alpha == pytest.approx(0.5, abs=0.25)


def test_adf_wrapper_on_stationary_and_nonstationary_series():
    rng = np.random.default_rng(3)
    stationary = rng.normal(0, 1, 500)
    walk = np.cumsum(rng.normal(0, 1, 500))
    res_stat = adf_test(stationary)
    res_walk = adf_test(walk)
    assert res_stat.pvalue < 0.05
    assert res_stat.is_stationary()
    assert res_walk.pvalue > 0.05
    assert "5%" in res_stat.critical_values


def test_adf_requires_enough_observations():
    with pytest.raises(ValueError):
        adf_test(np.ones(10))


def test_cointegrated_pair_is_detected(cointegrated_pair):
    log_a, log_b = cointegrated_pair
    result = cointegration_test(log_a, log_b)
    assert result.eg_pvalue < 0.05
    assert result.adf_pvalue < 0.05
    assert result.beta == pytest.approx(1.1, abs=0.05)
    assert result.is_tradeable()


def test_independent_walks_are_not_cointegrated():
    # average over a few seeds so the test is not hostage to one unlucky path
    pvalues = []
    for seed in (11, 23, 47):
        log_a, log_b = make_random_walks(seed=seed)
        pvalues.append(cointegration_test(log_a, log_b).eg_pvalue)
    assert np.median(pvalues) > 0.05


def test_half_life_estimate_close_to_truth(cointegrated_pair):
    log_a, log_b = cointegrated_pair
    result = cointegration_test(log_a, log_b)
    assert 10 < result.half_life < 90  # true value 30, estimator is noisy


def test_half_life_infinite_for_non_reverting_series():
    # an explosive AR(1) has b > 0 in the half-life regression -> no mean reversion
    rng = np.random.default_rng(5)
    s = np.empty(400)
    s[0] = 1.0
    for t in range(1, 400):
        s[t] = 1.01 * s[t - 1] + rng.normal(0, 0.01)
    assert half_life_of_mean_reversion(s) == float("inf")


def test_pair_selector_finds_planted_pair():
    log_a, log_b = make_cointegrated_series(seed=7)
    log_c, log_d = make_random_walks(seed=13)
    df = pd.DataFrame({"AAA": log_a, "BBB": log_b, "CCC": log_c, "DDD": log_d})
    cfg = PairSelectionConfig(
        min_correlation=0.4, min_observations=500, min_spread_std=0.0,
        max_half_life_bars=150.0,
    )
    pairs = PairSelector(cfg).select(df)
    assert pairs, "planted cointegrated pair was not found"
    keys = {frozenset((p.symbol_a, p.symbol_b)) for p in pairs}
    assert frozenset(("AAA", "BBB")) in keys
    assert frozenset(("CCC", "DDD")) not in keys


def test_pair_selector_respects_min_observations():
    log_a, log_b = make_cointegrated_series(n=200)
    df = pd.DataFrame({"AAA": log_a, "BBB": log_b})
    pairs = PairSelector(PairSelectionConfig(min_observations=500)).select(df)
    assert pairs == []
