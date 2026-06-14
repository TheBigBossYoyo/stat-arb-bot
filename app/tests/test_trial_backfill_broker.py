"""Tests for Phase 2 (trial backfill) and Path C (margin broker abstraction)."""

from __future__ import annotations

import pandas as pd

from app.brokers.margin_equity.capabilities import (
    CANDIDATES,
    evaluate_candidate,
)
from app.brokers.margin_equity.models import BorrowQuote, ShortabilityStatus
from app.research.trial_backfill import load_trial_manifest
from app.risk.borrow_risk import (
    borrow_cost_for_book,
    momentum_loser_tiers,
    per_asset_cost_bps,
)
from app.risk.shorting_risk import ShortingConstraints, screen_short_book

# --- Phase 2: trial manifest ---------------------------------------------------

def test_manifest_has_real_search_breadth():
    groups, trials = load_trial_manifest()
    assert "equity_daily_book_selection" in groups
    equity = [t for t in trials if t.group == "equity_daily_book_selection"]
    # the documented search was ~40-60 configs; we must back-fill far more than 1
    assert len(equity) >= 40
    with_sharpe = [t for t in equity if t.sharpe is not None]
    assert len(with_sharpe) >= 20
    # the flagship's pre-audit Sharpe is in the record
    assert any(abs((t.sharpe or 0) - 1.34) < 1e-6 for t in equity)


def test_manifest_count_expands():
    _groups, trials = load_trial_manifest()
    # the xsec_reversion sweep entry has count: 24
    crypto = [t for t in trials if t.strategy == "xsec_reversion"]
    assert len(crypto) == 24


# --- Path C: capability survey -------------------------------------------------

def test_trading212_disqualified_binance_disqualified():
    by_name = {c.name: evaluate_candidate(c) for c in CANDIDATES}
    assert "shorting" in by_name["trading212"].missing
    assert "shorting" in by_name["binance_spot"].missing
    assert not by_name["trading212"].ready
    # IBKR / Alpaca clear the hard requirements (still not connected)
    assert by_name["interactive_brokers"].ready
    assert by_name["alpaca"].ready


# --- Path C: shorting screen ---------------------------------------------------

def test_short_screen_cuts_unshortable_and_caps_htb():
    weights = pd.Series({"GC1": -0.10, "HTB1": -0.10, "NOLOC": -0.10, "LONG1": 0.30})
    borrow = {
        "GC1": BorrowQuote(symbol="GC1", available_shares=1e6, borrow_rate_bps_annual=30),
        "HTB1": BorrowQuote(symbol="HTB1", available_shares=1e4,
                            borrow_rate_bps_annual=600, is_hard_to_borrow=True),
        "NOLOC": BorrowQuote(symbol="NOLOC", available_shares=0, locate_required=True),
    }
    short = {
        "GC1": ShortabilityStatus(symbol="GC1", shortable=True),
        "HTB1": ShortabilityStatus(symbol="HTB1", shortable=True),
        "NOLOC": ShortabilityStatus(symbol="NOLOC", shortable=False, reason="no inventory"),
    }
    res = screen_short_book(weights, borrow, short,
                            ShortingConstraints(max_short_per_name=0.08, max_htb_gross=0.05))
    assert res.weights["NOLOC"] == 0.0                 # cut: not shortable
    assert abs(res.weights["GC1"]) <= 0.08 + 1e-9      # per-name cap
    assert res.weights["LONG1"] == 0.30                # long untouched
    assert res.htb_gross <= 0.05 + 1e-9                # HTB bucket capped


# --- Path C: per-name borrow cost ---------------------------------------------

def test_borrow_cost_skewed_by_tier():
    weights = pd.Series({"A": -0.5, "B": -0.5})
    tiers = {"A": "gc", "B": "special"}
    res = borrow_cost_for_book(weights, tiers)
    assert res.worst_name == "B"
    assert res.blended_bps_annual > 30          # special name drags blended up hard
    # per-asset cost folds borrow into shorts only
    vec = per_asset_cost_bps(weights, tiers, base_trade_bps=5.0, bars_per_year=252)
    assert vec["A"] > 5.0 and vec["B"] > vec["A"]


def test_momentum_loser_tiers_are_conservative():
    tiers = momentum_loser_tiers(["s1", "s2", "s3", "s4", "s5"], hard_fraction=0.4)
    assert "special" in tiers.values() or "hard" in tiers.values()
