"""Tests for the supervised paper supervisor: pre-flight gates, stop rules,
health states and the daily summary (operator mission, Phases 2-4, 8)."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import app.execution.paper_supervisor as ps
from app.core.types import utc_now
from app.execution.paper_supervisor import (
    StopThresholds,
    evaluate_stop_rules,
    health,
    preflight,
    render_daily_summary,
    write_daily_summary,
)
from app.execution.supervised_paper import PaperSession, SupervisedPaperStore


def _settings(tmp_path, *, live=False):
    return SimpleNamespace(live_trading_allowed=live, runtime_dir=tmp_path)


def _store(tmp_path):
    return SupervisedPaperStore(tmp_path, "long_only_t212")


def _today_dates(n: int):
    today = utc_now().replace(tzinfo=None).date()
    return [(today - timedelta(days=n - 1 - i)).isoformat() for i in range(n)]


# --------------------------------------------------------------------------------
# pre-flight gates
# --------------------------------------------------------------------------------

def test_preflight_passes_for_shadow_when_all_good(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (True, "paper_candidate", None))
    pre = preflight(_settings(tmp_path), None, product="long_only_t212", mode="shadow",
                    confirm_demo=False, kill_switch_active=False)
    assert pre.ok is True and pre.terminal is False


def test_preflight_refuses_when_live_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (True, "paper_candidate", None))
    pre = preflight(_settings(tmp_path, live=True), None, product="long_only_t212",
                    mode="shadow", confirm_demo=False, kill_switch_active=False)
    assert pre.ok is False and pre.terminal is True
    assert "live" in pre.refusal_reason.lower()


def test_preflight_refuses_when_not_paper_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (False, "not_yet", None))
    pre = preflight(_settings(tmp_path), None, product="long_only_t212", mode="shadow",
                    confirm_demo=False, kill_switch_active=False)
    assert pre.ok is False and pre.terminal is True
    assert "paper_candidate" in pre.refusal_reason


def test_preflight_refuses_demo_execute_without_confirm(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (True, "paper_candidate", None))
    pre = preflight(_settings(tmp_path), None, product="long_only_t212", mode="demo_execute",
                    confirm_demo=False, kill_switch_active=False)
    assert pre.ok is False and pre.terminal is False     # recoverable, just add --confirm-demo
    assert "confirm-demo" in pre.refusal_reason


# --------------------------------------------------------------------------------
# stop rules
# --------------------------------------------------------------------------------

def _good_day(store, date, **over):
    row = {"date": date, "replay": False, "equity": 10_000.0, "n_orders": 1, "n_rejected": 0,
           "demo_orders_sent": 0, "broker_errors": 0, "top_weight": 0.2, "drawdown_pct": -1.0,
           "n_holdings": 15, "smoothing_ok": True, "n_untradable": 0, "market_hours_ok": True,
           "data_quality_events": 0}
    row.update(over)
    store.append("daily_reports", row)
    store.append("reconciliations", {"date": date, "n_short_positions": 0, "total_abs_drift": 0.01})
    store.append("risk_snapshots", {"date": date, "breach": False})


def test_stop_rules_ok(tmp_path):
    store = _store(tmp_path)
    for d in _today_dates(3):
        _good_day(store, d)
    res = evaluate_stop_rules(store, _settings(tmp_path), kill_switch_active=False,
                              decision_status="paper_candidate")
    assert res.state == "OK" and res.triggered == []


def test_stop_rules_live_enabled_is_failed(tmp_path):
    store = _store(tmp_path)
    _good_day(store, _today_dates(1)[0])
    res = evaluate_stop_rules(store, _settings(tmp_path, live=True), kill_switch_active=False,
                              decision_status="paper_candidate")
    assert res.state == "FAILED"
    assert any(r.rule == "live trading enabled" for r in res.triggered)


def test_stop_rules_kill_switch_pauses(tmp_path):
    store = _store(tmp_path)
    _good_day(store, _today_dates(1)[0])
    res = evaluate_stop_rules(store, _settings(tmp_path), kill_switch_active=True,
                              decision_status="paper_candidate")
    assert res.state == "PAUSED"
    assert any(r.rule == "kill switch engaged" for r in res.triggered)


def test_stop_rules_short_position_is_failed(tmp_path):
    store = _store(tmp_path)
    d = _today_dates(1)[0]
    _good_day(store, d)
    store.append("reconciliations", {"date": d, "n_short_positions": 1, "total_abs_drift": 0.4})
    res = evaluate_stop_rules(store, _settings(tmp_path), kill_switch_active=False,
                              decision_status="paper_candidate")
    assert res.state == "FAILED"
    assert any("short" in r.rule for r in res.triggered)


def test_stop_rules_drawdown_pause_and_fail(tmp_path):
    store = _store(tmp_path)
    d = _today_dates(1)[0]
    _good_day(store, d, drawdown_pct=-22.0)
    res = evaluate_stop_rules(store, _settings(tmp_path), kill_switch_active=False,
                              decision_status="paper_candidate")
    assert res.state == "PAUSED"
    store2 = SupervisedPaperStore(tmp_path / "x", "long_only_t212")
    _good_day(store2, d, drawdown_pct=-40.0)
    res2 = evaluate_stop_rules(store2, _settings(tmp_path), kill_switch_active=False,
                               decision_status="paper_candidate")
    assert res2.state == "FAILED"


def test_stop_rules_concentration_pauses(tmp_path):
    store = _store(tmp_path)
    _good_day(store, _today_dates(1)[0], top_weight=0.30)
    res = evaluate_stop_rules(store, _settings(tmp_path), kill_switch_active=False,
                              decision_status="paper_candidate")
    assert res.state == "PAUSED"
    assert any("concentration" in r.rule for r in res.triggered)


def test_stop_rules_smoothing_failure_is_failed(tmp_path):
    store = _store(tmp_path)
    _good_day(store, _today_dates(1)[0], smoothing_ok=False)
    res = evaluate_stop_rules(store, _settings(tmp_path), kill_switch_active=False,
                              decision_status="paper_candidate")
    assert res.state == "FAILED"
    assert any("smoothing" in r.rule for r in res.triggered)


def test_stop_rules_broker_errors_pause(tmp_path):
    store = _store(tmp_path)
    for i, d in enumerate(_today_dates(2)):
        _good_day(store, d, broker_errors=3 if i == 0 else 2)
    thresholds = StopThresholds()
    res = evaluate_stop_rules(store, _settings(tmp_path), kill_switch_active=False,
                              decision_status="paper_candidate", thresholds=thresholds)
    assert res.state == "PAUSED"
    assert any("broker errors" in r.rule for r in res.triggered)


def test_stop_rules_lost_eligibility_is_failed(tmp_path):
    store = _store(tmp_path)
    _good_day(store, _today_dates(1)[0])
    res = evaluate_stop_rules(store, _settings(tmp_path), kill_switch_active=False,
                              decision_status="not_yet")
    assert res.state == "FAILED"
    assert any("paper_candidate" in r.rule for r in res.triggered)


# --------------------------------------------------------------------------------
# health states
# --------------------------------------------------------------------------------

def test_health_not_started(tmp_path):
    h = health(_store(tmp_path), _settings(tmp_path), kill_switch_active=False,
               decision_status="paper_candidate")
    assert h["state"] == "NOT STARTED"
    assert h["can_generate_final_report"] is False


def test_health_in_progress(tmp_path):
    store = _store(tmp_path)
    store.start_session(PaperSession.new("long_only_t212", "shadow", min_days=30,
                                         starting_cash=10_000.0))
    for d in _today_dates(3):
        _good_day(store, d)
    h = health(store, _settings(tmp_path), kill_switch_active=False,
               decision_status="paper_candidate", min_days=30)
    assert h["state"] == "IN PROGRESS"
    assert h["forward_days_completed"] == 3
    assert h["days_remaining"] == 27
    assert h["live_eligible"] is False


def test_health_ready_for_final_review(tmp_path):
    store = _store(tmp_path)
    store.start_session(PaperSession.new("long_only_t212", "shadow", min_days=30,
                                         starting_cash=10_000.0))
    for i, d in enumerate(_today_dates(30)):
        _good_day(store, d, equity=10_000.0 + 5 * i, drawdown_pct=0.0)
    h = health(store, _settings(tmp_path), kill_switch_active=False,
               decision_status="paper_candidate", min_days=30)
    assert h["state"] == "READY FOR FINAL REVIEW"
    assert h["can_generate_final_report"] is True


def test_health_failed_when_session_stopped(tmp_path):
    store = _store(tmp_path)
    store.start_session(PaperSession.new("long_only_t212", "shadow", min_days=30,
                                         starting_cash=10_000.0))
    _good_day(store, _today_dates(1)[0])
    store.stop_session("operator stopped")
    h = health(store, _settings(tmp_path), kill_switch_active=False,
               decision_status="paper_candidate")
    assert h["state"] == "FAILED"
    assert h["stop_reason"] == "operator stopped"


# --------------------------------------------------------------------------------
# daily summary (Phase 8)
# --------------------------------------------------------------------------------

def test_render_and_write_daily_summary(tmp_path):
    day_info = {
        "product": "long_only_t212", "date": "2026-06-14", "mode": "shadow", "replay": False,
        "equity": 10_010.0, "paper_pnl_day": 10.0, "paper_pnl_pct": 0.1,
        "benchmark_pnl_pct": 0.2, "gross_exposure": 1.0, "top_weight": 0.2,
        "drawdown_pct": -1.0, "risk_status": "OK", "expected_slippage_bps": 4.0,
        "realized_slippage_bps": 5.0, "demo_orders_sent": 0, "broker_errors": 0,
        "target_weights": {"AAA": 0.2, "BBB": 0.2}, "planned_orders": [], "refused_orders": [],
    }
    md = render_daily_summary(day_info, health_state="IN PROGRESS",
                              next_action="run tomorrow", status_line="Shadow day recorded successfully.")
    assert "Shadow day recorded successfully." in md
    assert "NOT LIVE ELIGIBLE" in md
    out = write_daily_summary(tmp_path, md)
    assert out.exists() and out.name == "latest_daily_summary.md"
    assert "long_only_t212" in out.read_text(encoding="utf-8")
