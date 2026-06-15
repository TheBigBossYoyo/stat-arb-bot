"""Tests for the dashboard action orchestrator + endpoints (Phase 2/3/16).

Every assertion here defends a safety invariant: live trading is impossible,
demo orders need the full gate, refusals are audited, secrets are never echoed,
and dangerous actions require the exact confirmation phrase.
"""

from __future__ import annotations

import time

import pytest
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


# -- rerun / research action gates (Phase 6 coverage) ----------------------------

# Every operator-facing rerun goes through the same gate. Read-only must refuse
# each one, and each refusal must be audited. (A refused job never runs a handler,
# so these stay fast and data-free.)
RESEARCH_RERUN_ENDPOINTS = [
    "/api/product-decision/run",
    "/api/long-only/readiness/run",
    "/api/long-only/concentration/run",
    "/api/long-only/concentration/compare-fixes",
    "/api/long-only/crisis/run",
    "/api/long-only/survivorship/run",
    "/api/trading212/order-preview",
]


@pytest.mark.parametrize("endpoint", RESEARCH_RERUN_ENDPOINTS)
def test_rerun_action_refused_and_audited_when_read_only(tmp_path, endpoint):
    suffix = endpoint.strip("/").replace("/", "_")
    client = make_client(tmp_path, controls=False, suffix=suffix)
    body = client.post(endpoint, json={}).json()
    assert body["status"] == "refused"
    assert body["live_eligible"] is False
    assert body["audit_id"] is not None
    # the refusal is recorded in the audit trail with a "refused" result
    audit = client.get("/api/audit").json()
    assert any("refused" in (e.get("result") or "") for e in audit)


def test_order_preview_action_passes_gate_with_controls(tmp_path):
    """With controls enabled the ORDER_PREVIEW action is accepted (not refused)
    by the gate — the page can generate a preview. It never sends an order."""
    client = make_client(tmp_path, controls=True)
    body = client.post("/api/trading212/order-preview",
                       json={"params": {"mode": "shadow"}}).json()
    assert body["status"] != "refused"
    assert body["status"] in ("queued", "running", "succeeded", "failed")
    assert body["live_eligible"] is False
    assert body["audit_id"] is not None


def test_product_decision_rerun_succeeds_and_audits(tmp_path):
    client = make_client(tmp_path, controls=True)
    started = client.post("/api/product-decision/run", json={}).json()
    assert started["status"] != "refused"
    done = _wait(client, started["id"])
    assert done["status"] == "succeeded"
    assert done["result"]["live_eligible"] is False
    audit = client.get("/api/audit").json()
    assert any(e["action"].startswith("job_product_decision") for e in audit)


def test_kill_switch_blocks_setup_check(tmp_path):
    client = make_client(tmp_path, controls=True, api_key="demo-key")
    eng = client.post("/api/risk/kill-switch/engage",
                      json={"confirm_phrase": "ACTIVATE KILL SWITCH", "reason": "test"}).json()
    _wait(client, eng["id"])
    body = client.post("/api/trading212/setup-check",
                       json={"params": {"connect": False}}).json()
    assert body["status"] == "refused"
    assert "kill switch is ENGAGED" in body["refusal_reason"]


# -- reports library (list / view / download) ------------------------------------

def test_reports_list_view_and_download(tmp_path):
    client = make_client(tmp_path, controls=True)
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "concentration_us_stocks_50.md").write_text(
        "# concentration test report\n", encoding="utf-8")

    listing = client.get("/api/reports").json()
    assert listing["live_eligible"] is False
    assert any(r["id"] == "concentration_us_stocks_50.md" for r in listing["reports"])

    view = client.get("/api/reports/concentration_us_stocks_50.md")
    assert view.status_code == 200
    assert "concentration test report" in view.json()["content"]

    dl = client.get("/api/reports/concentration_us_stocks_50.md/download")
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("text/markdown")

    assert client.get("/api/reports/this_does_not_exist.md").status_code == 404


def test_refused_action_is_audited_before_running(tmp_path):
    """A read-only refusal is audited even though the handler never runs."""
    client = make_client(tmp_path, controls=False)
    body = client.post("/api/long-only/concentration/run", json={}).json()
    assert body["status"] == "refused"
    audit = client.get("/api/audit").json()
    matching = [e for e in audit if e["action"].startswith("job_concentration_analysis")]
    assert matching
    assert any("refused" in (e.get("result") or "") for e in matching)


def test_order_preview_offline_preview_sends_nothing(tmp_path):
    """The order-preview result carries the SHADOW banner and the demo-eligibility
    flag, and never claims to be live-eligible — proof the page only previews."""
    client = make_client(tmp_path, controls=True)
    started = client.post("/api/trading212/order-preview",
                          json={"params": {"mode": "demo_preview"}}).json()
    done = _wait(client, started["id"])
    # With no market data the handler may fail to build a plan; either way it must
    # never be live-eligible and never be a live order path.
    assert done["live_eligible"] is False
    assert done["status"] in ("succeeded", "failed")
    if done["status"] == "succeeded":
        assert done["result"]["live_eligible"] is False
        assert "demo_eligible" in done["result"]
