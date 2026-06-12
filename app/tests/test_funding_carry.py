"""Funding-rate carry backtest: selection, costs, no lookahead."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.research.funding_carry import CarryConfig, run_carry_backtest


def _panel(n: int = 100, **rates: float) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="8h")
    return pd.DataFrame({sym: np.full(n, r) for sym, r in rates.items()}, index=idx)


def test_carry_concentrates_in_the_richest_funding():
    funding = _panel(100, RICH=0.0002, FLAT=0.0, NEG=-0.0002)
    cfg = CarryConfig(lookback_periods=10, top_k=1, cost_bps=0.0)
    result = run_carry_backtest(funding, cfg)
    held = result.weights.iloc[-1]
    assert held["RICH"] == pytest.approx(1.0)
    assert held["FLAT"] == held["NEG"] == 0.0
    # 90 periods x 2bp, compounded, no costs
    expected = 10_000.0 * (1.0 + 0.0002) ** 90
    assert result.metrics["final_equity"] == pytest.approx(expected, rel=1e-6)


def test_carry_stays_in_cash_when_no_positive_funding():
    funding = _panel(100, A=-0.0001, B=-0.0003)
    result = run_carry_backtest(funding, CarryConfig(lookback_periods=10, top_k=2))
    assert result.metrics["final_equity"] == pytest.approx(10_000.0)
    assert float(result.weights.abs().sum().sum()) == 0.0


def test_carry_charges_entry_costs():
    funding = _panel(100, RICH=0.0002, FLAT=0.0)
    cfg = CarryConfig(lookback_periods=10, top_k=1, cost_bps=30.0)
    result = run_carry_backtest(funding, cfg)
    # one entry of weight 1.0 -> 30bps charged exactly once (book never changes)
    expected = 10_000.0 * (1.0 - 0.0030) * (1.0 + 0.0002) ** 90
    assert result.metrics["final_equity"] == pytest.approx(expected, rel=1e-6)


def test_carry_has_no_lookahead():
    """A funding spike in the final period of an UNHELD symbol cannot
    change the result — weights for t are decided strictly from t-1 back."""
    base = _panel(100, RICH=0.0002, DEAD=0.0)
    spiked = base.copy()
    spiked.iloc[-1, spiked.columns.get_loc("DEAD")] = 0.10
    cfg = CarryConfig(lookback_periods=10, top_k=1, cost_bps=0.0)
    assert (run_carry_backtest(base, cfg).metrics["final_equity"]
            == pytest.approx(run_carry_backtest(spiked, cfg).metrics["final_equity"]))
