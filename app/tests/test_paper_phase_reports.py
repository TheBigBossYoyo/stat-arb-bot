"""Tests for the forward-paper sprint additions: the pre-flight gate (Phase 1),
the weekly review report (Phase 7) and the forward-start report (Phase 11).

These exercise the REAL report builders against synthetic settings/stores so no
network, DB or live config is touched. Live is never in scope; every report must
remain not-live-eligible."""

from __future__ import annotations

from types import SimpleNamespace

import app.execution.paper_supervisor as ps
from app.execution.supervised_paper import PaperSession, SupervisedPaperStore
from app.research.paper_preflight import build_preflight_report, run_preflight
from app.research.paper_weekly_report import compute_weekly_report, render_weekly_report

REPORTS = [
    "long_only_readiness_long_only_xsec_momentum_us_stocks_50.md",
    "concentration_smoothing_long_only_xsec_momentum_us_stocks_50.md",
    "crisis_long_only_long_only_xsec_momentum_us_stocks_50.md",
    "survivorship_long_only_long_only_xsec_momentum_us_stocks_50.md",
]


def _settings(tmp_path, **over):
    base = dict(runtime_dir=tmp_path, reports_dir=tmp_path / "reports",
                live_trading_allowed=False, dashboard_controls_enabled=True)
    base.update(over)
    s = SimpleNamespace(**base)
    s.reports_dir.mkdir(parents=True, exist_ok=True)
    for name in REPORTS:
        (s.reports_dir / name).write_text("# report\nbody\n", encoding="utf-8")
    return s


class _FakeStorage:
    def load_audit_events(self, limit: int = 200):
        return []


# --- Phase 1: pre-flight --------------------------------------------------------

def test_preflight_ready_when_all_gates_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (True, "paper_candidate", None))
    settings = _settings(tmp_path)
    res = run_preflight(settings, _FakeStorage())
    assert res.ready is True
    assert all(c.ok for c in res.checks)
    # the safety-critical checks must be present
    names = {c.name for c in res.checks}
    assert any("CFDs" in n for n in names)
    assert any("hard-blocked" in n for n in names)
    assert any("leverage" in n for n in names)


def test_preflight_not_ready_when_not_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (False, "not_yet", None))
    settings = _settings(tmp_path)
    res = run_preflight(settings, _FakeStorage())
    assert res.ready is False
    assert any("paper_candidate" in b for b in res.blockers)


def test_preflight_not_ready_when_live_enabled(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (True, "paper_candidate", None))
    settings = _settings(tmp_path, live_trading_allowed=True)
    res = run_preflight(settings, _FakeStorage())
    assert res.ready is False
    assert any("live trading is OFF" in c.name for c in res.checks if not c.ok)


def test_preflight_report_markdown_has_verdict_and_not_live(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (True, "paper_candidate", None))
    md, res = build_preflight_report(_settings(tmp_path), _FakeStorage())
    assert "Ready to start supervised forward paper period" in md
    assert "NOT LIVE ELIGIBLE" in md
    assert res.ready is True


# --- Phase 7: weekly review -----------------------------------------------------

def _seed_week(store: SupervisedPaperStore, equities, start="2026-06-08"):
    import datetime as dt
    store.start_session(PaperSession.new("long_only_t212", "shadow",
                                         min_days=30, starting_cash=10_000.0))
    d0 = dt.date.fromisoformat(start)
    for i, eq in enumerate(equities):
        d = (d0 + dt.timedelta(days=i)).isoformat()
        store.append("daily_reports", {"date": d, "replay": False, "equity": eq,
                                       "drawdown_pct": 0.0, "top_weight": 0.2,
                                       "n_orders": 1, "n_rejected": 0, "broker_errors": 0,
                                       "data_quality_events": 0, "n_untradable": 0})
        store.append("benchmark_snapshots", {"date": d, "spy_equity": 100.0 + i})
        store.append("orders", {"date": d, "notional": 100.0})
        store.append("tca", {"date": d, "realized_slippage_bps": 5.0, "fees": 0.0})


def test_weekly_report_continue(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (True, "paper_candidate", None))
    settings = _settings(tmp_path)
    store = SupervisedPaperStore(tmp_path, "long_only_t212")
    _seed_week(store, [10_000, 10_050, 10_100, 10_120, 10_140], start="2026-06-09")
    rep = compute_weekly_report(store, settings, as_of="2026-06-15",
                                decision_status="paper_candidate")
    assert rep.days_completed == 5
    assert rep.paper_return_pct is not None
    assert rep.recommendation in ("continue", "investigate")
    md = render_weekly_report(rep)
    assert "NOT LIVE ELIGIBLE" in md
    assert rep.recommendation.upper() in md


def test_weekly_report_pauses_on_stop_rule(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "product_status", lambda s, st, p: (True, "paper_candidate", None))
    settings = _settings(tmp_path)
    store = SupervisedPaperStore(tmp_path, "long_only_t212")
    _seed_week(store, [10_000, 10_050], start="2026-06-12")
    # inject a short position via reconciliations -> FAILED stop rule
    store.append("reconciliations", {"date": "2026-06-12", "n_short_positions": 1,
                                     "total_abs_drift": 0.0})
    rep = compute_weekly_report(store, settings, as_of="2026-06-15",
                                decision_status="paper_candidate")
    assert rep.recommendation == "fail session"
    assert rep.stop_state == "FAILED"


# --- Phase 11: forward-start theme detection ------------------------------------

def test_forward_start_theme_detection_truthful():
    from app.research.forward_paper_start_report import _theme_support

    theme = _theme_support()
    assert theme["dark"] is True
    assert set(theme) == {"dark", "light", "system"}
