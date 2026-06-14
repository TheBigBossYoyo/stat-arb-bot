"""Tests for the Phase 6 supervised paper/shadow PERIOD session state."""

from __future__ import annotations

from app.execution.supervised_paper import (
    PaperSession,
    SupervisedPaperStore,
    final_report,
    supervised_status,
)


def _store(tmp_path):
    return SupervisedPaperStore(tmp_path, "long_only_t212")


def test_session_roundtrip_and_reset(tmp_path):
    store = _store(tmp_path)
    assert store.current_session() is None
    s = PaperSession.new("long_only_t212", "shadow", min_days=30, starting_cash=10_000.0)
    store.start_session(s)
    loaded = store.current_session()
    assert loaded is not None and loaded.session_id == s.session_id
    assert loaded.mode == "shadow" and loaded.min_days == 30
    store.append("daily_reports", {"date": "2026-06-10", "equity": 10_000.0})
    assert len(store.load("daily_reports")) == 1
    store.reset()
    assert store.current_session() is None
    assert store.load("daily_reports") == []


def test_status_counts_forward_vs_replay_days(tmp_path):
    store = _store(tmp_path)
    store.start_session(PaperSession.new("long_only_t212", "shadow",
                                         min_days=30, starting_cash=10_000.0))
    for d in ("2026-06-01", "2026-06-02"):
        store.append("daily_reports", {"date": d, "replay": True, "equity": 10_000.0})
    store.append("daily_reports", {"date": "2026-06-14", "replay": False, "equity": 10_050.0})
    st = supervised_status(store)
    assert st["replay_days_recorded"] == 2
    assert st["forward_days_completed"] == 1
    assert st["cycles"] == 3


def test_final_report_replay_only_cannot_pass(tmp_path):
    store = _store(tmp_path)
    store.start_session(PaperSession.new("long_only_t212", "shadow",
                                         min_days=30, starting_cash=10_000.0))
    for i in range(40):  # 40 REPLAY days — still must not pass (not forward)
        store.append("daily_reports", {"date": f"2025-01-{(i % 28) + 1:02d}",
                                       "replay": True, "equity": 10_000.0 + i})
    rep = final_report(store, min_days=30)
    assert rep["replay_only_not_forward"] is True
    assert rep["recommendation"] == "FAIL"
    assert rep["live_eligible"] is False


def test_final_report_forward_period_can_pass(tmp_path):
    store = _store(tmp_path)
    store.start_session(PaperSession.new("long_only_t212", "shadow",
                                         min_days=30, starting_cash=10_000.0))
    for i in range(31):  # 31 distinct FORWARD days, gentle uptrend, no breaches
        d = f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}"
        eq = 10_000.0 + 10 * i
        store.append("daily_reports", {"date": d, "replay": False, "equity": eq,
                                       "n_rejected": 0, "demo_orders_sent": 0,
                                       "broker_errors": 0, "top_weight": 0.2})
        store.append("reconciliations", {"date": d, "n_short_positions": 0,
                                         "total_abs_drift": 0.01})
        store.append("risk_snapshots", {"date": d, "breach": False})
    rep = final_report(store, min_days=30)
    assert rep["days_completed_forward"] == 31
    assert rep["checks"]["forward calendar days >= 30"] is True
    assert rep["recommendation"] == "PASS"
    assert rep["live_eligible"] is False        # PASS is paper-only, never live


def test_final_report_flags_shorts_and_breaches(tmp_path):
    store = _store(tmp_path)
    store.start_session(PaperSession.new("long_only_t212", "demo_execute",
                                         min_days=1, starting_cash=10_000.0))
    store.append("daily_reports", {"date": "2026-06-14", "replay": False, "equity": 9_000.0,
                                   "n_rejected": 0, "broker_errors": 0, "top_weight": 0.3})
    store.append("reconciliations", {"date": "2026-06-14", "n_short_positions": 1,
                                     "total_abs_drift": 0.4})
    store.append("risk_snapshots", {"date": "2026-06-14", "breach": True})
    rep = final_report(store, min_days=1)
    assert rep["checks"]["no short positions ever"] is False
    assert rep["checks"]["no risk breaches"] is False
    assert rep["recommendation"] == "FAIL"
