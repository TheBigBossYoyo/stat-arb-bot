"""Cross-sectional basket engine, PCA/x-sec strategies, and the allocator."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.backtesting.basket_engine import BasketConfig, rank_weights, run_basket_backtest
from app.research.pair_selection import SelectedPair
from app.research.pca_residuals import pca_residual_returns, s_scores
from app.strategies.cross_sectional_mean_reversion import XSecReversalConfig, make_xsec_weight_fn
from app.strategies.pca_stat_arb import PCAStatArbConfig, make_pca_weight_fn
from app.strategies.portfolio_allocator import AllocationConfig, inverse_vol_pair_weights


def test_rank_weights_dollar_neutral():
    scores = pd.Series({"A": 2.0, "B": 1.0, "C": -1.0, "D": -2.0})
    weights = rank_weights(scores, top_k=1, gross_target=1.0)
    assert weights["D"] == pytest.approx(0.5)        # most negative -> long
    assert weights["A"] == pytest.approx(-0.5)       # most positive -> short
    assert weights.sum() == pytest.approx(0.0)
    assert weights.abs().sum() == pytest.approx(1.0)


def test_rank_weights_long_only_never_shorts():
    scores = pd.Series({"A": 2.0, "B": 1.0, "C": -1.0, "D": -2.0})
    weights = rank_weights(scores, top_k=2, gross_target=1.0, long_only=True)
    assert (weights >= 0).all()
    assert weights.sum() == pytest.approx(1.0)


def test_basket_engine_no_lookahead_and_costs():
    """Constant +1 weight on one asset must reproduce that asset's returns,
    shifted by one bar, minus the initial turnover cost."""
    n, fit = 60, 10
    idx = pd.date_range("2025-01-01", periods=n, freq="15min")
    up = 100 * np.cumprod(1 + np.full(n, 0.01))          # +1% per bar
    flat = np.full(n, 50.0)
    close = pd.DataFrame({"UP": up, "FLAT": flat}, index=idx)

    weight_fn = lambda window: pd.Series({"UP": 1.0, "FLAT": 0.0})  # noqa: E731
    cfg = BasketConfig(interval="15m", starting_cash=10_000, fit_window=fit,
                       rebalance_every=1, cost_bps=10.0)
    result = run_basket_backtest(close, weight_fn, cfg)

    bars_invested = (n - 1) - fit
    expected = 10_000 * (1 - 10.0 / 10_000) * (1.01 ** bars_invested)
    assert float(result.equity.iloc[-1]) == pytest.approx(expected, rel=1e-9)
    # weights decided at t earn t->t+1: equity only starts moving AFTER fit_window
    assert (result.equity.iloc[: fit + 1] == 10_000).all()


def test_basket_engine_passes_aligned_aux_windows():
    """A wants_aux weight fn must receive aux frames sliced to exactly the
    same rows as the close window; plain fns keep the single-arg contract."""
    n, fit = 40, 10
    idx = pd.date_range("2025-01-01", periods=n, freq="D")
    close = pd.DataFrame({"A": np.linspace(100, 110, n), "B": np.linspace(50, 55, n)},
                         index=idx)
    volume = pd.DataFrame({"A": np.arange(n, dtype=float), "B": np.arange(n, dtype=float)},
                          index=idx)
    seen: list[tuple[pd.Timestamp, pd.Timestamp]] = []

    class AuxFn:
        wants_aux = True

        def __call__(self, window, aux=None):
            assert aux is not None and "volume" in aux
            assert aux["volume"].index.equals(window.index)
            seen.append((window.index[0], window.index[-1]))
            return pd.Series(0.0, index=window.columns)

    cfg = BasketConfig(interval="1d", fit_window=fit, rebalance_every=5, cost_bps=0.0)
    run_basket_backtest(close, AuxFn(), cfg, aux={"volume": volume})
    assert seen, "aux weight fn was never called"
    # a plain single-arg fn still works with aux supplied to the engine
    plain = lambda window: pd.Series(0.0, index=window.columns)  # noqa: E731
    run_basket_backtest(close, plain, cfg, aux={"volume": volume})


def test_ensemble_t_stat_taper_scales_funding_with_evidence():
    """With t_stat_scale on, a sleeve barely above t=0 gets a fraction of its
    inverse-vol share; a sleeve above the scale gets the full share."""
    from app.strategies.ensemble import EnsembleConfig, RiskParityEnsemble

    flat = lambda window: pd.Series(0.0, index=window.columns)  # noqa: E731
    ens = RiskParityEnsemble(
        {"strong": flat, "weak": flat},
        EnsembleConfig(vol_window=30, min_observations=5, min_sleeve_t=0.0,
                       t_stat_scale=1.0, cost_bps=0.0),
    )
    # strong: steady positive returns (t >> scale -> full inverse-vol share);
    # weak: noisy, mean barely above zero (t ~ 0.05 -> heavily tapered)
    for i in range(30):
        ens._returns["strong"].append(0.009 if i % 2 else 0.011)
        ens._returns["weak"].append(0.01 if i % 2 else -0.0098)
    alloc = ens.sleeve_allocations()
    assert alloc["strong"] > 0.0 and alloc["weak"] > 0.0
    assert sum(alloc.values()) == pytest.approx(1.0)
    # same realized vol ordering as binary gate would give, but the weak
    # sleeve's share must be tapered below its pure inverse-vol share
    binary = RiskParityEnsemble(
        {"strong": flat, "weak": flat},
        EnsembleConfig(vol_window=30, min_observations=5, min_sleeve_t=0.0,
                       t_stat_scale=0.0, cost_bps=0.0),
    )
    binary._returns = ens._returns
    assert alloc["weak"] < binary.sleeve_allocations()["weak"]


def test_pca_residuals_shapes_and_neutrality():
    rng = np.random.default_rng(4)
    market = rng.normal(0, 0.01, 800)
    returns = pd.DataFrame({
        f"A{i}": 1.0 * market + rng.normal(0, 0.004, 800) for i in range(6)
    })
    result = pca_residual_returns(returns, n_components=2)
    assert result.residual_returns.shape == returns.shape
    scores = s_scores(result.residual_returns, window=60)
    assert set(scores.index) == set(returns.columns)
    assert np.isfinite(scores.to_numpy()).all()


def test_pca_weight_fn_is_dollar_neutral_on_synthetic():
    rng = np.random.default_rng(5)
    market = np.cumsum(rng.normal(0, 0.01, 600))
    close = pd.DataFrame({
        f"A{i}": np.exp(3 + market + np.cumsum(rng.normal(0, 0.003, 600)))
        for i in range(6)
    })
    # legacy scoring forces a full book every rebalance; OU mode may stand aside
    weights = make_pca_weight_fn(PCAStatArbConfig(top_k=2, use_ou_scores=False))(close)
    assert weights.sum() == pytest.approx(0.0, abs=1e-12)
    assert weights.abs().sum() == pytest.approx(1.0, abs=1e-12)


def test_pca_ou_mode_stays_flat_when_nothing_qualifies():
    """Random-walk residuals have no mean reversion — the OU kappa filter must
    refuse to trade them rather than force a book."""
    rng = np.random.default_rng(6)
    market = np.cumsum(rng.normal(0, 0.01, 600))
    close = pd.DataFrame({
        f"A{i}": np.exp(3 + market + np.cumsum(rng.normal(0, 0.01, 600)))
        for i in range(6)
    })
    weights = make_pca_weight_fn(PCAStatArbConfig(top_k=2, use_ou_scores=True,
                                                  s_entry=10.0))(close)
    assert weights.abs().sum() == pytest.approx(0.0)


def _two_sector_world(n: int = 600, seed: int = 11) -> tuple[pd.DataFrame, dict[str, str]]:
    """Two sectors with strong, distinct factors plus idiosyncratic noise."""
    rng = np.random.default_rng(seed)
    fac_a = rng.normal(0, 0.012, n)
    fac_b = rng.normal(0, 0.012, n)

    def mean_reverting_idio() -> np.ndarray:
        """Idio LEVEL is AR(1): its cumulative residual is OU, so the kappa
        filter accepts it (white-noise idio cumulates to a random walk,
        which the filter rejects by design)."""
        level = np.zeros(n)
        shocks = rng.normal(0, 0.004, n)
        for t in range(1, n):
            level[t] = 0.8 * level[t - 1] + shocks[t]
        return np.diff(level, prepend=0.0)

    rets = {}
    sectors = {}
    for i in range(5):
        rets[f"A{i}"] = fac_a + mean_reverting_idio()
        sectors[f"A{i}"] = "alpha"
        rets[f"B{i}"] = fac_b + mean_reverting_idio()
        sectors[f"B{i}"] = "beta"
    rets["LONER"] = rng.normal(0, 0.01, n)         # sector below min size
    sectors["LONER"] = "solo"
    returns = pd.DataFrame(rets)
    return returns, sectors


def test_sector_residuals_strip_the_sector_factor():
    from app.research.pca_residuals import sector_residual_returns, standardize_returns

    returns, sectors = _two_sector_world()
    result = sector_residual_returns(returns, sectors, min_sector_size=3)
    z = standardize_returns(returns)
    loo = (z[[f"A{i}" for i in range(1, 5)]]).mean(axis=1)   # A0's peers
    raw_corr = float(np.corrcoef(z["A0"], loo)[0, 1])
    resid_corr = float(np.corrcoef(result.residual_returns["A0"], loo)[0, 1])
    assert raw_corr > 0.8                       # factor dominates raw returns
    assert abs(resid_corr) < 0.1                # ...and is gone from residuals
    # a name whose sector is too small must be excluded, not traded
    assert float(result.residual_returns["LONER"].abs().sum()) == 0.0


def test_sector_weight_fn_trades_dollar_neutral():
    returns, sectors = _two_sector_world()
    close = pd.DataFrame(100 * np.exp(returns.cumsum()).to_numpy(),
                         columns=returns.columns,
                         index=pd.date_range("2024-01-01", periods=len(returns), freq="D"))
    weights = make_pca_weight_fn(PCAStatArbConfig(
        sectors=sectors, min_sector_size=3, top_k=2, score_window=60,
        s_entry=0.5, s_exit=0.1, max_residual_half_life=40))(close)
    assert weights.sum() == pytest.approx(0.0, abs=1e-12)
    assert float(weights.abs().sum()) > 0.0     # low entry bar -> book trades
    assert weights["LONER"] == 0.0


def test_every_us_stock_symbol_has_a_sector():
    from app.data.universe import get_sectors, get_universe

    for universe in ("us_stocks_50", "us_stocks_100"):
        symbols = get_universe(universe)
        sectors = get_sectors(universe)
        assert set(sectors) == set(symbols), (
            f"{universe}: missing sectors for {set(symbols) - set(sectors)}")


def test_xsec_weight_fn_buys_recent_losers():
    n = 50
    idx = pd.date_range("2025-01-01", periods=n, freq="15min")
    base = np.full(n, 100.0)
    crashed = base.copy()
    crashed[-12:] *= np.linspace(1.0, 0.80, 12)      # -20% over the lookback
    pumped = base.copy()
    pumped[-12:] *= np.linspace(1.0, 1.25, 12)
    close = pd.DataFrame({"CRASH": crashed, "PUMP": pumped, "FLAT1": base, "FLAT2": base},
                         index=idx)
    weights = make_xsec_weight_fn(XSecReversalConfig(lookback_bars=12, top_k=1))(close)
    assert weights["CRASH"] > 0                       # buy the loser
    assert weights["PUMP"] < 0                        # short the winner


def test_allocator_inverse_vol_with_caps():
    def pair(key_a: str, spread_std: float) -> SelectedPair:
        return SelectedPair(symbol_a=key_a, symbol_b="X", beta=1.0, alpha=0.0,
                            correlation=0.9, eg_pvalue=0.01, adf_pvalue=0.01,
                            half_life=30.0, spread_std=spread_std, score=1.0)

    pairs = [pair("QUIET", 0.001), pair("NOISY", 0.10)]
    weights = inverse_vol_pair_weights(
        pairs, AllocationConfig(total_target_pct=0.30, max_per_pair_pct=0.10,
                                min_per_pair_pct=0.02)
    )
    assert weights["QUIET|X"] == pytest.approx(0.10)   # capped at max
    assert weights["NOISY|X"] == pytest.approx(0.02)   # floored at min
    assert sum(weights.values()) <= 0.30 + 1e-9        # caps only ever reduce the total
