"""Tests for the paper monitoring + alerting layer (monitoring sprint).

Covers the explainable health score, the alert rule engine, alert persistence
(create / auto-resolve / manual resolve with the critical-still-active block) and
the run_monitor integration. Synthetic settings/stores only — no DB or network.
Live is never in scope; every surface stays not-live-eligible.
"""

from __future__ import annotations

from types import SimpleNamespace

import app.execution.paper_supervisor as ps
from app.execution.supervised_paper import PaperSession, SupervisedPaperStore
from app.research.paper_alerts import CRITICAL, WARNING, AlertStore, evaluate_alert_specs
from app.research.paper_health_score import compute_health_score

# --- health score ---------------------------------------------------------------

def test_health_score_healthy():
    hs = compute_health_score({
        "forward_days_completed": 20, "expected_trading_days": 20, "missed_days": 0,
        "concentration_top_weight": 0.18, "current_drawdown_pct": -3.0,
        "turnover_per_year": 30.0, "excess_return_pct": 1.0,
        "paper_vs_backtest_status": "within", "stop_state": "OK",
    })
    assert hs.classification == "healthy"
    assert hs.score >= 85
    assert any(c.name == "operational_completeness" for c in hs.components)


def test_health_score_failed_override_caps_score():
    hs = compute_health_score({
        "forward_days_completed": 20, "expected_trading_days": 20,
        "concentration_top_weight": 0.18, "current_drawdown_pct": -3.0,
        "stop_state": "FAILED",
    })
    assert hs.classification == "failed"
    assert hs.score <= 30
    assert any("FAILED" in o for o in hs.overrides)


def test_health_score_paused_on_kill_switch():
    hs = compute_health_score({
        "forward_days_completed": 10, "expected_trading_days": 10,
        "kill_switch_active": True, "stop_state": "OK",
    })
    assert hs.classification == "paused"
    assert any("kill switch" in o for o in hs.overrides)


def test_health_score_degraded_on_drawdown_and_concentration():
    hs = compute_health_score({
        "forward_days_completed": 20, "expected_trading_days": 20, "missed_days": 3,
        "concentration_top_weight": 0.31, "current_drawdown_pct": -22.0,
        "stop_state": "OK",
    })
    assert hs.classification in ("degraded", "watch")
    assert hs.score < 85


# --- alert rule engine ----------------------------------------------------------

def _cats(specs):
    return {(s.category, s.severity) for s in specs}


def test_alert_drawdown_critical():
    specs = evaluate_alert_specs({"current_drawdown_pct": -40.0, "fail_drawdown_pct": 35.0})
    assert ("paper_drawdown", CRITICAL) in _cats(specs)


def test_alert_concentration_warning_and_critical():
    assert ("concentration_breach", WARNING) in _cats(
        evaluate_alert_specs({"concentration_top_weight": 0.27}))
    assert ("concentration_breach", CRITICAL) in _cats(
        evaluate_alert_specs({"concentration_top_weight": 0.33}))


def test_alert_live_flag_critical():
    specs = evaluate_alert_specs({"live_trading_allowed": True})
    assert ("live_flag_detected", CRITICAL) in _cats(specs)


def test_alert_product_decision_changed_critical():
    specs = evaluate_alert_specs({"decision_is_candidate": False, "decision_status": "do_not_trade"})
    assert ("product_decision_changed", CRITICAL) in _cats(specs)


def test_alert_missed_day_warning_then_critical():
    assert ("missed_day", WARNING) in _cats(evaluate_alert_specs({"missing_days_gap": 2}))
    assert ("missed_day", CRITICAL) in _cats(evaluate_alert_specs({"missed_days": 2}))


def test_alert_final_review_ready_info():
    specs = evaluate_alert_specs({"can_generate_final_report": True, "forward_days_completed": 30})
    cats = {s.category for s in specs}
    assert "final_review_ready" in cats


# --- alert persistence ----------------------------------------------------------

def test_alert_store_sync_creates_and_autoresolves(tmp_path):
    store = AlertStore(tmp_path, "long_only_t212")
    specs = evaluate_alert_specs({"concentration_top_weight": 0.27})
    alerts = store.sync(specs, session_id="S1", now="2026-06-15T00:00:00")
    active = [a for a in alerts if not a.resolved]
    assert len(active) == 1 and active[0].category == "concentration_breach"
    # condition clears -> the alert auto-resolves (kept in history)
    alerts2 = store.sync([], session_id="S1", now="2026-06-16T00:00:00")
    assert all(a.resolved for a in alerts2)
    assert any(a.resolution_note == "condition cleared automatically" for a in alerts2)


def test_alert_store_resolve_info_alert(tmp_path):
    store = AlertStore(tmp_path, "long_only_t212")
    specs = evaluate_alert_specs({"can_generate_final_report": True})
    alerts = store.sync(specs, session_id="S1", now="2026-06-15T00:00:00")
    aid = alerts[0].alert_id
    ok, msg = store.resolve(aid, note="seen it", now="2026-06-15T01:00:00")
    assert ok and msg == "resolved"
    assert store.get(aid).resolution_note == "seen it"


def test_alert_store_resolve_blocks_active_critical(tmp_path):
    store = AlertStore(tmp_path, "long_only_t212")
    specs = evaluate_alert_specs({"live_trading_allowed": True})
    alerts = store.sync(specs, session_id="S1", now="2026-06-15T00:00:00")
    crit = next(a for a in alerts if a.severity == CRITICAL)
    blocked = {crit.dedup_key}
    ok, msg = store.resolve(crit.alert_id, note="ignore", now="t", blocked_keys=blocked)
    assert not ok and "still active" in msg
    # once the condition clears it is no longer blocked
    ok2, _ = store.resolve(crit.alert_id, note="fixed", now="t2", blocked_keys=set())
    assert ok2


# --- run_monitor integration ----------------------------------------------------

def _settings(tmp_path, **over):
    base = dict(runtime_dir=tmp_path, live_trading_allowed=False)
    base.update(over)
    return SimpleNamespace(**base)


def _seed(tmp_path, equities, *, start="2026-06-01", top=0.20, dd=-2.0):
    import datetime as dt
    store = SupervisedPaperStore(tmp_path, "long_only_t212")
    store.start_session(PaperSession.new("long_only_t212", "shadow",
                                         min_days=30, starting_cash=10_000.0))
    d0 = dt.date.fromisoformat(start)
    for i, eq in enumerate(equities):
        d = (d0 + dt.timedelta(days=i)).isoformat()
        store.append("daily_reports", {"date": d, "replay": False, "equity": eq,
                                       "drawdown_pct": dd, "top_weight": top, "n_orders": 1,
                                       "n_rejected": 0, "broker_errors": 0, "n_holdings": 12,
                                       "data_quality_events": 0})
        store.append("benchmark_snapshots", {"date": d, "spy_equity": 100.0 + i})
    return store


def test_run_monitor_persists_score_and_alerts(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (True, "paper_candidate", None))
    _seed(tmp_path, [10_000, 10_010, 10_020])
    from app.research.paper_monitor import load_snapshots, run_monitor

    res = run_monitor(_settings(tmp_path), None).as_dict()
    assert res["active"] is True
    assert res["live_eligible"] is False
    assert 0 <= res["health_score"]["score"] <= 100
    assert res["health_score"]["classification"] in (
        "healthy", "watch", "degraded", "failed", "paused")
    # a snapshot was persisted
    assert len(load_snapshots(tmp_path, "long_only_t212")) == 1
    # alerts file exists and is loadable
    assert AlertStore(tmp_path, "long_only_t212").load() is not None


def test_run_monitor_raises_concentration_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (True, "paper_candidate", None))
    _seed(tmp_path, [10_000, 9_900, 9_800], top=0.32)
    from app.research.paper_monitor import run_monitor

    res = run_monitor(_settings(tmp_path), None).as_dict()
    cats = {(a["category"], a["severity"]) for a in res["alerts"] if not a["resolved"]}
    assert ("concentration_breach", CRITICAL) in cats


def test_run_monitor_product_lost_is_failed_and_critical(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (False, "do_not_trade", None))
    _seed(tmp_path, [10_000, 10_010])
    from app.research.paper_monitor import run_monitor

    res = run_monitor(_settings(tmp_path), None).as_dict()
    assert res["health_score"]["classification"] == "failed"
    cats = {a["category"] for a in res["alerts"] if not a["resolved"]}
    assert "product_decision_changed" in cats
