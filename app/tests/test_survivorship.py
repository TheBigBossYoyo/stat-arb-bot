"""Tests for Phase 3 (survivorship bound / point-in-time)."""

from __future__ import annotations

import pytest

from app.backtesting.survivorship import (
    run_survivorship_stress,
    run_universe_bias_report,
)
from app.data.point_in_time import (
    StaticSurvivorProvider,
    UnavailablePITProvider,
    perturbed_universes,
)


def test_perturbed_universes_drop_names_deterministically():
    subs = perturbed_universes("us_stocks_50", n=5, drop_frac=0.2, seed=1)
    assert len(subs) == 5
    full = len(StaticSurvivorProvider("us_stocks_50").members_as_of("x", None))
    for s in subs:
        assert len(s) < full                     # names were dropped
        assert len(set(s)) == len(s)             # no duplicates
    # deterministic for a fixed seed
    assert perturbed_universes("us_stocks_50", 5, 0.2, seed=1) == subs


def test_static_provider_is_flagged_biased():
    assert StaticSurvivorProvider("us_stocks_50").biased


def test_pit_provider_refuses_to_fake_membership():
    with pytest.raises(NotImplementedError):
        UnavailablePITProvider().members_as_of("SP500", None)


def test_survivorship_stress_bounds_a_stable_strategy():
    # a strategy whose metrics barely move across sub-universes is 'bounded'
    def run_on_symbols(symbols):
        return {"sharpe": 1.2 + 0.01 * len(symbols) % 3, "total_return_pct": 30.0}

    res = run_survivorship_stress("us_stocks_50", run_on_symbols, n=6, drop_frac=0.2)
    assert res.n == 6
    assert res.bounded                            # stable -> bounded
    assert res.sharpe_p05 > 0.4


def test_universe_bias_report_bounded_when_winner_drop_survives():
    sectors = {s: "tech" for s in StaticSurvivorProvider("us_stocks_50").members_as_of("x", None)}
    name_returns = {s: 1.0 for s in sectors}

    def run_on_symbols(symbols):
        return {"sharpe": 1.4, "total_return_pct": 50.0, "max_drawdown_pct": -15.0}

    rep = run_universe_bias_report("us_stocks_50", run_on_symbols, sectors=sectors,
                                   name_returns=name_returns, n_random=4)
    assert rep.verdict() == "bounded"             # stable across all drops
    assert not rep.pit_data_used                  # never claims 'eliminated'
    assert any(s.label == "best_5_removed" for s in rep.scenarios)
    assert any(s.label == "sector_balanced_drop_20pct" for s in rep.scenarios)


def test_universe_bias_report_unresolved_when_edge_hinges_on_winners():
    names = StaticSurvivorProvider("us_stocks_50").members_as_of("x", None)
    name_returns = {s: float(i) for i, s in enumerate(names)}  # ranked winners

    def run_on_symbols(symbols):
        # collapses badly whenever names are dropped (edge hinges on the full set)
        return {"sharpe": 1.4 if len(symbols) == len(names) else 0.1,
                "total_return_pct": 50.0, "max_drawdown_pct": -15.0}

    rep = run_universe_bias_report("us_stocks_50", run_on_symbols,
                                   name_returns=name_returns, n_random=4)
    assert rep.verdict() == "unresolved"
    assert rep.verdict() != "eliminated"          # PIT data not used
