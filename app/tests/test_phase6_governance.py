"""Tests for Phase 6-7: governance gates, governed promotion, automatic
demotion, crash-protected momentum, and the fail-closed kill switch."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# -- governance gates -------------------------------------------------------------


def test_gates_block_on_missing_evidence():
    from app.governance.gates import evaluate_gates

    # empty evidence: every gate that needs data must fail
    report = evaluate_gates("walk_forward", {})
    assert not report.approved
    assert report.blocking_failures


def test_gates_pass_with_good_evidence():
    from app.governance.gates import evaluate_gates

    evidence = {
        "n_years": 6, "n_regimes": 3, "net_sharpe": 1.0, "deflated_sharpe_pass": True,
        "max_month_pct": 18.0, "survives_costs_x2": True, "data_verdict": "research_only",
    }
    report = evaluate_gates("walk_forward", evidence)
    assert report.approved


def test_venue_gate_blocks_short_without_shorting_venue():
    from app.governance.gates import evaluate_gates

    evidence = {
        "executable_venues": ["trading212"], "requires_short": True,
        "venue_supports_short": False, "paper_days": 60, "paper_decisions": 30,
        "paper_slippage_ok": True, "no_unexplained_breaks": True,
        "connectors_exercised": True, "governance_signoff": True,
    }
    report = evaluate_gates("live_tiny", evidence)
    assert not report.approved
    assert any(r.name == "venue_gate" for r in report.blocking_failures)


def test_concentration_gate_blocks_flagship():
    """The real flagship fails the no-month-dominates gate (one month = 30% of
    PnL) — the gate must catch it (matches the validate-ensemble finding)."""
    from app.governance.gates import evaluate_gates

    evidence = {
        "n_years": 5, "n_regimes": 3, "net_sharpe": 1.02, "deflated_sharpe_pass": True,
        "max_month_pct": 30.3, "survives_costs_x2": True, "data_verdict": "research_only",
    }
    report = evaluate_gates("walk_forward", evidence)
    assert not report.approved
    assert any(r.name == "no_month_dominates" for r in report.blocking_failures)


# -- governed promotion -----------------------------------------------------------


@pytest.fixture
def registry(tmp_path):
    from app.research.alpha_registry import Alpha, AlphaRegistry

    reg = AlphaRegistry(path=tmp_path / "reg.yaml")
    reg.add(Alpha(
        alpha_id="cand", name="c", hypothesis="h", asset_class="equity",
        universe="u", horizon="d", rebalance="daily", status="backtest",
        requires_short=True,
    ))
    return reg


def test_attempt_promotion_blocks_then_allows(registry):
    from app.governance.promotion import attempt_promotion

    bad = attempt_promotion(registry, "cand", "walk_forward", {})
    assert not bad.approved
    assert registry.get("cand").status == "backtest"   # unchanged

    good_evidence = {
        "n_years": 6, "n_regimes": 3, "net_sharpe": 1.0, "deflated_sharpe_pass": True,
        "max_month_pct": 15.0, "survives_costs_x2": True, "data_verdict": "ok",
    }
    ok = attempt_promotion(registry, "cand", "walk_forward", good_evidence)
    assert ok.approved
    assert registry.get("cand").status == "walk_forward"


def test_live_promotion_requires_override_even_when_gated(registry):
    from app.governance.promotion import attempt_promotion

    # walk through to paper first
    for stage, ev in [
        ("walk_forward", {"n_years": 6, "n_regimes": 3, "net_sharpe": 1.0,
                          "deflated_sharpe_pass": True, "max_month_pct": 15.0,
                          "survives_costs_x2": True, "data_verdict": "ok"}),
        ("stress", {"oos_sharpe": 0.9, "oos_sharpe_degradation": 0.2,
                    "oos_folds_positive_frac": 0.75, "param_stable": True}),
        ("paper", {"survives_costs_x2": True, "survives_slippage_x2": True,
                   "survives_delay": True, "max_drawdown_pct": -10, "dd_mandate_pct": 15,
                   "capacity_ok": True}),
    ]:
        out = attempt_promotion(registry, "cand", stage, ev)
        assert out.approved, (stage, out.message)
    # now give the cand an executable shorting venue and full live evidence
    registry.get("cand").executable_venues = ["binance_futures"]
    live_ev = {
        "venue_supports_short": True, "paper_days": 90, "paper_decisions": 40,
        "paper_slippage_ok": True, "no_unexplained_breaks": True,
        "connectors_exercised": True, "governance_signoff": True,
    }
    # gates pass but without override the registry's live block holds
    blocked = attempt_promotion(registry, "cand", "shadow_live", live_ev,
                                allow_live_override=False)
    assert not blocked.approved
    assert registry.get("cand").status == "paper"
    # explicit, gated override succeeds
    allowed = attempt_promotion(registry, "cand", "shadow_live", live_ev,
                                allow_live_override=True)
    assert allowed.approved
    assert registry.get("cand").status == "shadow_live"


# -- automatic demotion -----------------------------------------------------------


def test_demotion_decay_demotes():
    from app.governance.retirement import evaluate_demotion

    d = evaluate_demotion({"rolling60_sharpe": -0.2, "oos_sharpe_p5": 0.1})
    assert d.triggered and d.severity == "demote"


def test_demotion_critical_retires():
    from app.governance.retirement import evaluate_demotion

    d = evaluate_demotion({"venue_capability_lost": True})
    assert d.triggered and d.severity == "retire"


def test_demotion_two_triggers_retires():
    from app.governance.retirement import evaluate_demotion

    d = evaluate_demotion({
        "rolling60_sharpe": -0.2, "oos_sharpe_p5": 0.1,
        "tracking_error_unexplained_days": 20,
    })
    assert d.severity == "retire"


def test_no_demotion_when_healthy():
    from app.governance.retirement import evaluate_demotion

    d = evaluate_demotion({"rolling60_sharpe": 1.0, "oos_sharpe_p5": 0.3,
                           "slippage_ratio": 1.1, "data_verdict": "ok"})
    assert not d.triggered


# -- crash-protected momentum -----------------------------------------------------


def test_crash_protection_scales_down_in_high_vol():
    from app.strategies.momentum import XSMOMConfig, make_xsmom_weight_fn

    rng = np.random.default_rng(2)
    n, k = 400, 8
    idx = pd.bdate_range("2023-01-01", periods=n)
    # calm first half, violent second half (a crash regime)
    vol = np.concatenate([np.full(n // 2, 0.008), np.full(n - n // 2, 0.05)])
    close = pd.DataFrame(
        {f"S{i}": 100 * np.exp(np.cumsum(rng.normal(0.0002, 1, n) * vol)) for i in range(k)},
        index=idx)

    plain = make_xsmom_weight_fn(XSMOMConfig(lookback_bars=60, skip_bars=5, top_k=2))
    protected = make_xsmom_weight_fn(XSMOMConfig(
        lookback_bars=60, skip_bars=5, top_k=2,
        crash_protect_vol_window=20, crash_protect_target_vol=0.01))

    calm = close.iloc[:n // 2]
    crash = close
    # in the crash window the protected book must be smaller (lower gross)
    plain_gross = plain(crash).abs().sum()
    prot_gross = protected(crash).abs().sum()
    assert prot_gross < plain_gross
    # in calm conditions protection barely bites
    assert protected(calm).abs().sum() == pytest.approx(plain(calm).abs().sum(), rel=0.05)


# -- fail-closed kill switch ------------------------------------------------------


def test_kill_switch_fails_closed_on_unreadable_flag(tmp_path, monkeypatch):
    from app.risk.kill_switch import KillSwitch

    ks = KillSwitch(tmp_path / "ks.flag")
    assert not ks.is_active           # absent flag = off (normal)

    def boom(self):
        raise OSError("simulated NFS failure")

    monkeypatch.setattr("pathlib.Path.exists", boom)
    assert ks.is_active               # unreadable flag = ENGAGED (fail closed)
