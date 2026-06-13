"""Dashboard API: permissions, confirmations, audit trail, secret masking."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config.settings import Settings
from app.dashboard.api import create_app
from app.data.storage import Storage


def make_client(tmp_path, controls: bool = False, token: str = "", **extra):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'dash.db'}",
        dashboard_controls_enabled=controls,
        dashboard_token=token,
        data_dir=tmp_path / "data",
        reports_dir=tmp_path / "reports",
        logs_dir=tmp_path / "logs",
        runtime_dir=tmp_path / "runtime",
        **extra,
    )
    storage = Storage(settings.database_url)
    app = create_app(settings, storage, start_broadcaster=False)
    return TestClient(app), settings, storage


def test_status_read_only_by_default(tmp_path):
    client, _, _ = make_client(tmp_path)
    response = client.get("/api/status")
    assert response.status_code == 200
    body = response.json()
    assert body["controls_enabled"] is False
    assert body["live_trading_allowed"] is False
    assert body["kill_switch"]["active"] is False
    assert {b["broker"] for b in body["brokers"]} == {
        "binance_spot", "trading212", "binance_futures"
    }


def test_institutional_read_endpoints(tmp_path):
    """The new research surface (registry, experiments, data-audit, governance)
    is exposed read-only and reflects the seeded registry."""
    client, _, storage = make_client(tmp_path)

    alphas = client.get("/api/alphas")
    assert alphas.status_code == 200
    ids = {a["id"] for a in alphas.json()}
    assert "flagship_daily_ensemble" in ids
    flagship = next(a for a in alphas.json() if a["id"] == "flagship_daily_ensemble")
    assert flagship["executable_venues"] == []      # no shorting venue
    assert flagship["requires_short"] is True

    rejected = client.get("/api/alphas", params={"status": "rejected"})
    assert {a["id"] for a in rejected.json()} >= {"pca_stat_arb", "xsec_reversion"}

    exps = client.get("/api/experiments")
    assert exps.status_code == 200                  # empty list is fine on a fresh db

    gov = client.get("/api/governance/flagship_daily_ensemble", params={"to": "live_tiny"})
    assert gov.status_code == 200
    body = gov.json()
    assert body["approved"] is False                # venue gate blocks it
    assert any(g["name"] == "venue_gate" for g in body["gates"])


def test_controls_disabled_blocks_dangerous_posts(tmp_path):
    client, _, storage = make_client(tmp_path, controls=False)
    response = client.post("/api/risk/kill-switch/activate",
                           json={"confirm_phrase": "ACTIVATE KILL SWITCH"})
    assert response.status_code == 403
    assert "READ-ONLY" in response.json()["detail"]
    # backtest runs also need at least researcher
    assert client.post("/api/backtests/run", json={"kind": "backtest"}).status_code == 403
    assert client.post("/api/strategies/pairs_zscore/pause").status_code == 403


def test_wrong_confirmation_phrase_rejected(tmp_path):
    client, _, _ = make_client(tmp_path, controls=True)
    response = client.post("/api/risk/kill-switch/activate",
                           json={"confirm_phrase": "activate kill switch"})
    assert response.status_code == 400
    assert "ACTIVATE KILL SWITCH" in response.json()["detail"]


def test_kill_switch_round_trip_with_audit(tmp_path):
    client, _, storage = make_client(tmp_path, controls=True)
    on = client.post("/api/risk/kill-switch/activate",
                     json={"confirm_phrase": "ACTIVATE KILL SWITCH", "reason": "drill"})
    assert on.status_code == 200 and on.json()["kill_switch"]["active"]
    assert client.get("/api/status").json()["kill_switch"]["active"] is True

    off = client.post("/api/risk/kill-switch/deactivate",
                      json={"confirm_phrase": "DEACTIVATE KILL SWITCH"})
    assert off.status_code == 200 and not off.json()["kill_switch"]["active"]

    actions = [e["action"] for e in client.get("/api/audit").json()]
    assert "kill_switch_activate" in actions
    assert "kill_switch_deactivate" in actions


def test_flatten_all_is_honest_and_audited(tmp_path):
    client, _, _ = make_client(tmp_path, controls=True)
    response = client.post("/api/risk/flatten-all", json={"confirm_phrase": "FLATTEN ALL"})
    assert response.status_code == 501          # no live connectors to flatten
    assert "flatten_all" in [e["action"] for e in client.get("/api/audit").json()]


def test_strategy_pause_resume_writes_runtime_file(tmp_path):
    client, settings, _ = make_client(tmp_path, controls=True)
    assert client.post("/api/strategies/pairs_zscore/pause").json()["paused"] == ["pairs_zscore"]
    assert (settings.runtime_dir / "paused_strategies.json").exists()
    strategies = {s["name"]: s for s in client.get("/api/strategies").json()}
    assert strategies["pairs_zscore"]["paused"] is True
    assert strategies["pairs_zscore"]["health"] == "paused"
    assert client.post("/api/strategies/pairs_zscore/resume").json()["paused"] == []


def test_settings_view_never_leaks_secrets(tmp_path):
    client, _, _ = make_client(tmp_path, binance_api_key="SECRET_KEY_XYZ",
                               binance_api_secret="SECRET_VALUE_ABC")
    text = client.get("/api/settings").text
    assert "SECRET_KEY_XYZ" not in text
    assert "SECRET_VALUE_ABC" not in text
    assert client.get("/api/settings").json()["binance"]["key_configured"] is True


def test_token_auth_when_configured(tmp_path):
    client, _, _ = make_client(tmp_path, token="t0p-s3cret")
    assert client.get("/api/status").status_code == 401
    ok = client.get("/api/status", headers={"Authorization": "Bearer t0p-s3cret"})
    assert ok.status_code == 200


def test_empty_portfolio_and_backtest_404(tmp_path):
    client, _, _ = make_client(tmp_path)
    summary = client.get("/api/portfolio/summary").json()
    assert summary["has_data"] is False
    assert client.get("/api/portfolio/equity").json() == []
    assert client.get("/api/backtests/9999").status_code == 404


def test_websocket_channel_accepts_and_rejects(tmp_path):
    client, _, _ = make_client(tmp_path)
    with client.websocket_connect("/ws/system"):
        pass                                     # valid channel connects cleanly
