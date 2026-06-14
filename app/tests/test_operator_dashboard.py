"""Tests for the Operator Paper Mode dashboard endpoints (operator mission, Phase 7)."""

from __future__ import annotations

from fastapi.testclient import TestClient

import app.cli.main as cli
from app.config.settings import Settings
from app.dashboard.api import create_app
from app.data.storage import Storage


def make_client(tmp_path, controls: bool = False):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'dash.db'}",
        dashboard_controls_enabled=controls,
        data_dir=tmp_path / "data", reports_dir=tmp_path / "reports",
        logs_dir=tmp_path / "logs", runtime_dir=tmp_path / "runtime",
    )
    storage = Storage(settings.database_url)
    return TestClient(create_app(settings, storage, start_broadcaster=False)), settings, storage


def test_operator_status_read_only(tmp_path):
    client, _, _ = make_client(tmp_path)
    r = client.get("/api/operator/status?product=long_only_t212")
    assert r.status_code == 200
    body = r.json()
    assert body["live_eligible"] is False
    assert body["controls_enabled"] is False
    assert body["confirm_phrase_demo_execute"] == "RUN DEMO PAPER DAY"
    assert "state" in body["health"]
    assert "checklist" in body and isinstance(body["checklist"], list)
    assert body["trading212"]["live_orders_supported"] is False


def test_operator_paper_vs_backtest_endpoint(tmp_path):
    client, _, _ = make_client(tmp_path)
    r = client.get("/api/operator/paper-vs-backtest?product=long_only_t212")
    assert r.status_code == 200
    assert r.json()["live_eligible"] is False


def test_run_refused_when_controls_disabled(tmp_path):
    client, _, _ = make_client(tmp_path, controls=False)
    r = client.post("/api/operator/run/shadow", json={"confirm_phrase": "", "reason": "t"})
    assert r.status_code == 403       # read-only: TRADER role required


def test_run_invalid_mode(tmp_path):
    client, _, _ = make_client(tmp_path, controls=True)
    r = client.post("/api/operator/run/live", json={"confirm_phrase": "", "reason": "t"})
    assert r.status_code == 400


def test_demo_execute_requires_exact_phrase(tmp_path):
    client, _, _ = make_client(tmp_path, controls=True)
    r = client.post("/api/operator/run/demo_execute",
                    json={"confirm_phrase": "wrong", "reason": "t"})
    assert r.status_code == 400       # phrase mismatch, before any run


def test_run_shadow_with_controls_invokes_runner(tmp_path, monkeypatch):
    client, _, _ = make_client(tmp_path, controls=True)

    def fake_run(settings, storage, *, product, mode, confirm_demo=False, **kw):
        return {"refused": False, "status_line": "Shadow day recorded successfully.",
                "state": "IN PROGRESS", "next_action": "run tomorrow"}

    monkeypatch.setattr(cli, "run_supervised_paper_daily", fake_run)
    r = client.post("/api/operator/run/shadow", json={"confirm_phrase": "", "reason": "t"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["live_eligible"] is False
    assert body["status_line"] == "Shadow day recorded successfully."
