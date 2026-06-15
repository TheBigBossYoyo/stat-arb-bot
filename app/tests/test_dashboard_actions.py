"""Tests for the dashboard action orchestrator + endpoints (Phase 2/3/16).

Every assertion here defends a safety invariant: live trading is impossible,
demo orders need the full gate, refusals are audited, secrets are never echoed,
and dangerous actions require the exact confirmation phrase.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.dashboard.api import create_app
from app.data.storage import Storage


def make_client(tmp_path, *, controls: bool = False, demo_orders: bool = False,
                api_key: str = "", suffix: str = "") -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / ('dash' + suffix + '.db')}",
        dashboard_controls_enabled=controls,
        trading212_enabled=bool(api_key), trading212_mode="demo",
        trading212_allow_demo_orders=demo_orders, trading212_allow_live_orders=False,
        trading212_api_key=api_key, trading212_api_secret=api_key,
        data_dir=tmp_path / "data", reports_dir=tmp_path / ("reports" + suffix),
        logs_dir=tmp_path / "logs", runtime_dir=tmp_path / ("runtime" + suffix),
    )
    storage = Storage(settings.database_url)
    return TestClient(create_app(settings, storage, start_broadcaster=False))


def _wait(client: TestClient, job_id: str, timeout: float = 8.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/dashboard/jobs/{job_id}").json()
        if body["status"] in ("succeeded", "failed", "refused", "cancelled"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


# -- capability map --------------------------------------------------------------

def test_capabilities_never_live_eligible(tmp_path):
    client = make_client(tmp_path)
    body = client.get("/api/dashboard/capabilities").json()
    assert body["live_eligible"] is False
    assert len(body["actions"]) == 18
    assert all(a["live_eligible"] is False for a in body["actions"])
    # there is no live job type anywhere in the catalogue
    assert not any("live" in a["job_type"] for a in body["actions"])


# -- gate refusals (each becomes an audited, non-running job) ---------------------

def test_action_refused_when_controls_disabled(tmp_path):
    client = make_client(tmp_path, controls=False)
    body = client.post("/api/product-decision/run", json={}).json()
    assert body["status"] == "refused"
    assert "READ-ONLY" in body["refusal_reason"]


def test_demo_execute_refused_without_phrase(tmp_path):
    client = make_client(tmp_path, controls=True)
    body = client.post("/api/paper/daily",
                       json={"params": {"mode": "demo_execute"}, "confirm_phrase": "wrong"}).json()
    assert body["status"] == "refused"
    assert "RUN DEMO PAPER DAY" in body["refusal_reason"]


def test_demo_execute_refused_without_env_gate(tmp_path):
    # correct phrase + admin role, but TRADING212_ALLOW_DEMO_ORDERS is false
    client = make_client(tmp_path, controls=True, demo_orders=False)
    body = client.post("/api/paper/daily",
                       json={"params": {"mode": "demo_execute"},
                             "confirm_phrase": "RUN DEMO PAPER DAY"}).json()
    assert body["status"] == "refused"
    assert "demo orders are blocked" in body["refusal_reason"]


def test_stop_session_requires_phrase(tmp_path):
    client = make_client(tmp_path, controls=True)
    body = client.post("/api/paper/stop", json={"confirm_phrase": "nope"}).json()
    assert body["status"] == "refused"
    assert "STOP PAPER SESSION" in body["refusal_reason"]


def test_invalid_daily_mode_is_400(tmp_path):
    client = make_client(tmp_path, controls=True)
    r = client.post("/api/paper/daily", json={"params": {"mode": "live"}})
    assert r.status_code == 400


# -- kill switch -----------------------------------------------------------------

def test_kill_switch_engage_then_blocks_paper(tmp_path):
    client = make_client(tmp_path, controls=True)
    eng = client.post("/api/risk/kill-switch/engage",
                      json={"confirm_phrase": "ACTIVATE KILL SWITCH",
                            "reason": "test"}).json()
    eng = _wait(client, eng["id"])
    assert eng["status"] == "succeeded"
    assert eng["result"]["kill_switch"]["active"] is True

    blocked = client.post("/api/paper/daily", json={"params": {"mode": "shadow"}}).json()
    assert blocked["status"] == "refused"
    assert "kill switch is ENGAGED" in blocked["refusal_reason"]


def test_kill_switch_disengage_needs_disengage_phrase(tmp_path):
    client = make_client(tmp_path, controls=True)
    body = client.post("/api/risk/kill-switch/disengage",
                       json={"confirm_phrase": "ACTIVATE KILL SWITCH"}).json()
    assert body["status"] == "refused"
    assert "DISENGAGE KILL SWITCH" in body["refusal_reason"]


# -- successful jobs (data-free) -------------------------------------------------

def test_report_generation_job_succeeds_and_audits(tmp_path):
    client = make_client(tmp_path, controls=True)
    started = client.post("/api/dashboard/actions",
                          json={"job_type": "report_generation"}).json()
    assert started["status"] in ("queued", "running")
    assert started["audit_id"] is not None
    done = _wait(client, started["id"])
    assert done["status"] == "succeeded"
    assert "reports" in done["result"]
    # the attempt + the result are both in the audit trail
    audit = client.get("/api/audit").json()
    assert any(e["action"].startswith("job_report_generation") for e in audit)


def test_setup_check_never_returns_secrets(tmp_path):
    secret = "SUPERSECRETKEY_DEADBEEF"
    client = make_client(tmp_path, controls=True, api_key=secret)
    started = client.post("/api/trading212/setup-check",
                          json={"params": {"connect": False}}).json()
    done = _wait(client, started["id"])
    assert done["status"] == "succeeded"
    assert secret not in client.get(f"/api/dashboard/jobs/{started['id']}").text


def test_job_logs_endpoint(tmp_path):
    client = make_client(tmp_path, controls=True)
    started = client.post("/api/dashboard/actions",
                          json={"job_type": "report_generation"}).json()
    _wait(client, started["id"])
    logs = client.get(f"/api/dashboard/jobs/{started['id']}/logs")
    assert logs.status_code == 200
    assert "status" in logs.json()


# -- settings redaction (no secrets over the wire) -------------------------------

def test_settings_endpoint_redacts_secrets(tmp_path):
    secret = "ANOTHER_SECRET_VALUE_1234"
    client = make_client(tmp_path, controls=True, api_key=secret)
    text = client.get("/api/settings").text
    assert secret not in text
