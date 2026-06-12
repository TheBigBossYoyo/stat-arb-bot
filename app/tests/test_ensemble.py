"""Risk-parity ensemble and percent-of-equity risk limits."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.risk.exposure import PortfolioState
from app.risk.risk_manager import RiskLimits, RiskManager
from app.strategies.ensemble import EnsembleConfig, RiskParityEnsemble


def _window(n: int, start: int = 0) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=start + n, freq="15min")[start:]
    rng = np.random.default_rng(start)            # different draws per window
    quiet = 100 * np.exp(np.cumsum(rng.normal(0, 0.0001, n)))
    wild = 100 * np.exp(np.cumsum(rng.normal(0, 0.05, n)))
    return pd.DataFrame({"QUIET": quiet, "WILD": wild}, index=idx)


def test_ensemble_equal_weights_during_warmup():
    sleeves = {
        "a": lambda w: pd.Series({"QUIET": 1.0, "WILD": 0.0}),
        "b": lambda w: pd.Series({"QUIET": 0.0, "WILD": 1.0}),
    }
    ens = RiskParityEnsemble(sleeves, EnsembleConfig(min_observations=5))
    combined = ens(_window(50))
    assert ens.sleeve_allocations() == {"a": 0.5, "b": 0.5}
    assert combined["QUIET"] == pytest.approx(0.5)
    assert combined["WILD"] == pytest.approx(0.5)


def test_ensemble_shifts_risk_to_the_quiet_sleeve():
    """Sleeve holding the wild asset realizes higher vol -> smaller allocation."""
    sleeves = {
        "quiet": lambda w: pd.Series({"QUIET": 1.0, "WILD": 0.0}),
        "wild": lambda w: pd.Series({"QUIET": 0.0, "WILD": 1.0}),
    }
    ens = RiskParityEnsemble(
        sleeves, EnsembleConfig(min_observations=3, vol_window=20, max_sleeve_share=1.0)
    )
    n, step = 200, 24
    full = _window(800)
    for t in range(n, 800, step):                  # sliding windows, time order
        ens(full.iloc[t - n: t])
    alloc = ens.sleeve_allocations()
    assert alloc["quiet"] > alloc["wild"]
    assert sum(alloc.values()) == pytest.approx(1.0)


def test_ensemble_caps_gross_exposure():
    sleeves = {  # both sleeves pile into the same asset
        "a": lambda w: pd.Series({"QUIET": 1.0, "WILD": 1.0}),
        "b": lambda w: pd.Series({"QUIET": 1.0, "WILD": 1.0}),
    }
    ens = RiskParityEnsemble(sleeves, EnsembleConfig(gross_target=1.0))
    combined = ens(_window(50))
    assert combined.abs().sum() <= 1.0 + 1e-12


def test_vol_target_derisks_but_never_levers_up():
    sleeves = {"wild": lambda w: pd.Series({"QUIET": 0.0, "WILD": 1.0})}
    cfg = EnsembleConfig(min_observations=3, vol_window=20, max_sleeve_share=1.0,
                         target_vol_pct=10.0, rebalances_per_year=365.0, cost_bps=0.0)
    ens = RiskParityEnsemble(sleeves, cfg)
    n, step = 200, 24
    full = _window(800)
    for t in range(n, 800, step):
        combined = ens(full.iloc[t - n: t])
    # WILD's 5% per-bar vol is far above a 10% annual target -> scaled down hard
    assert 0.0 < combined.abs().sum() < 0.25
    # a quiet book must NOT be levered above its natural gross
    calm = RiskParityEnsemble(
        {"quiet": lambda w: pd.Series({"QUIET": 0.5, "WILD": 0.0})}, cfg)
    for t in range(n, 800, step):
        combined = calm(full.iloc[t - n: t])
    assert combined.abs().sum() <= 0.5 + 1e-12


def _state(equity: float = 10_000.0) -> PortfolioState:
    return PortfolioState(equity=equity, cash=equity, daily_start_equity=equity,
                          peak_equity=equity, gross_exposure=0.0, net_exposure=0.0,
                          open_pairs=0, open_positions=0, trades_today=0,
                          notional_by_symbol={})


def test_pct_limits_scale_with_equity():
    limits = RiskLimits(max_notional_per_trade=1e9, max_notional_per_trade_pct=15.0,
                        max_pair_loss=1e9, max_pair_loss_pct=1.5)
    assert limits.eff_max_notional_per_trade(10_000) == pytest.approx(1_500.0)
    assert limits.eff_max_notional_per_trade(100_000) == pytest.approx(15_000.0)
    assert limits.eff_max_pair_loss(10_000) == pytest.approx(150.0)
    # absolute value stays a hard backstop
    tight = RiskLimits(max_notional_per_trade=100.0, max_notional_per_trade_pct=15.0)
    assert tight.eff_max_notional_per_trade(10_000) == pytest.approx(100.0)
    # pct = 0 disables the percent leg entirely
    off = RiskLimits(max_notional_per_trade=50.0)
    assert off.eff_max_notional_per_trade(10_000) == pytest.approx(50.0)


def test_validate_pair_entry_uses_pct_limits():
    limits = RiskLimits(
        max_notional_per_trade=1e9, max_notional_per_trade_pct=15.0,
        max_pair_notional=1e9, max_pair_notional_pct=30.0,
        max_notional_per_asset=1e9, max_notional_per_asset_pct=45.0,
        max_gross_exposure=1e9, max_gross_exposure_pct=150.0,
        max_net_exposure=1e9, max_net_exposure_pct=25.0,
    )
    risk = RiskManager(limits=limits)
    ok = risk.validate_pair_entry(broker="binance_spot", notional_a=1_000.0,
                                  notional_b=900.0, state=_state())
    assert ok.approved, ok.reason()
    too_big = risk.validate_pair_entry(broker="binance_spot", notional_a=2_000.0,
                                       notional_b=1_800.0, state=_state())
    assert not too_big.approved
    assert any(c.name == "max_notional_per_trade" for c in too_big.failures)
