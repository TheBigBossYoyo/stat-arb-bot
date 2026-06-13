"""Dashboard API (FastAPI).

READ-ONLY by default. Control endpoints require DASHBOARD_CONTROLS_ENABLED,
a typed confirmation phrase, and every attempt — allowed or refused — is
written to the audit trail. Secrets never leave the server.

Serves the built frontend from frontend/dist when present:
    cd frontend && npm install && npm run build
    statarb dashboard
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config.settings import PROJECT_ROOT, Settings, get_settings
from app.core.logging import audit as audit_log
from app.core.logging import get_logger
from app.dashboard import websocket as ws
from app.dashboard.auth import check_token
from app.dashboard.permissions import Role, require_phrase, require_role
from app.dashboard.schemas import ConfirmedAction, JobRequest
from app.dashboard.service import DashboardService
from app.data.storage import Storage

log = get_logger(__name__)

FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"


def create_app(settings: Settings | None = None, storage: Storage | None = None,
               start_broadcaster: bool = True) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    storage = storage or Storage(settings.database_url)
    storage.init_db()
    service = DashboardService(settings, storage)
    manager = ws.ConnectionManager()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        task = None
        if start_broadcaster:
            task = asyncio.create_task(ws.snapshot_broadcaster(manager, service))
        yield
        if task:
            task.cancel()

    app = FastAPI(title="stat-arb control panel", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"], allow_headers=["*"],
    )

    def guard(request: Request) -> None:
        check_token(settings, request)

    dep = [Depends(guard)]

    def record_audit(action: str, confirmed: bool, payload: dict, result: str) -> None:
        mode = "live" if settings.live_trading_allowed else "paper"
        storage.record_audit_event(actor="local", action=action, mode=mode,
                                   confirmed=confirmed, payload=payload, result=result)
        audit_log(f"dashboard_{action}", confirmed=confirmed, result=result, **payload)

    # ---- read endpoints ---------------------------------------------------------

    @app.get("/api/status", dependencies=dep)
    def status(probe: bool = False):
        return service.system_status(probe=probe)

    @app.get("/api/portfolio/summary", dependencies=dep)
    def portfolio_summary(mode: str = "paper"):
        return service.portfolio_summary(mode)

    @app.get("/api/portfolio/equity", dependencies=dep)
    def portfolio_equity(mode: str = "paper", limit: int = 2000):
        return service.equity_curve(mode, limit)

    @app.get("/api/risk/status", dependencies=dep)
    def risk_status():
        return service.risk_status()

    @app.get("/api/risk/limits", dependencies=dep)
    def risk_limits():
        return service.risk_status().limits

    @app.get("/api/strategies", dependencies=dep)
    def strategies():
        return service.strategies()

    @app.get("/api/pairs", dependencies=dep)
    def pairs():
        return service.pairs()

    @app.get("/api/backtests", dependencies=dep)
    def backtests(limit: int = 100):
        return service.backtests(limit)

    @app.get("/api/backtests/{run_id}", dependencies=dep)
    def backtest_detail(run_id: int):
        detail = service.backtest_detail(run_id)
        if detail is None:
            raise HTTPException(404, f"backtest {run_id} not found")
        return detail

    @app.get("/api/orders", dependencies=dep)
    def orders(limit: int = 200, symbol: str | None = None, status: str | None = None):
        return service.orders(limit, symbol, status)

    @app.get("/api/trades", dependencies=dep)
    def trades(limit: int = 200, mode: str | None = None):
        return service.trades(limit, mode)

    @app.get("/api/signals", dependencies=dep)
    def signals(limit: int = 200):
        return service.signals(limit)

    @app.get("/api/performance", dependencies=dep)
    def performance(mode: str | None = None):
        from app.portfolio.performance import pair_performance, strategy_performance

        return {
            "by_strategy": strategy_performance(storage, mode).reset_index().to_dict("records"),
            "by_pair": pair_performance(storage, mode).reset_index().to_dict("records"),
        }

    @app.get("/api/brokers", dependencies=dep)
    def brokers(probe: bool = False):
        return service.broker_statuses(probe=probe)

    @app.get("/api/logs", dependencies=dep)
    def logs(limit: int = 300, level: str | None = None):
        return service.logs(limit, level)

    @app.get("/api/audit", dependencies=dep)
    def audit_trail(limit: int = 200):
        return service.audit_events(limit)

    @app.get("/api/settings", dependencies=dep)
    def settings_view():
        return service.settings_view()

    # ---- institutional research surface (read-only) --------------------------------

    @app.get("/api/alphas", dependencies=dep)
    def alphas(status: str | None = None):
        """Alpha registry: status, venues, hypothesis, last transition."""
        from app.research.alpha_registry import AlphaRegistry

        return [
            {"id": a.alpha_id, "name": a.name, "status": a.status,
             "asset_class": a.asset_class, "universe": a.universe,
             "requires_short": a.requires_short, "requires_leverage": a.requires_leverage,
             "executable_venues": a.executable_venues, "hypothesis": a.hypothesis,
             "known_risks": a.known_risks,
             "last_transition": a.history[-1] if a.history else None}
            for a in AlphaRegistry().list(status=status)
        ]

    @app.get("/api/experiments", dependencies=dep)
    def experiments(family: str | None = None, limit: int = 100):
        """Experiment tracker: every research run with its trial family count."""
        import json as _json

        rows = storage.list_experiments(family=family, limit=limit)
        out = []
        for r in rows:
            metrics = _json.loads(r.metrics_json or "{}")
            out.append({
                "experiment_id": r.experiment_id, "created_at": str(r.created_at),
                "kind": r.kind, "strategy": r.strategy, "family": r.family,
                "sample": r.sample, "git_commit": r.git_commit, "git_dirty": r.git_dirty,
                "sharpe": metrics.get("sharpe", metrics.get("oos_sharpe_mean")),
                "total_return_pct": metrics.get("total_return_pct",
                                                metrics.get("oos_total_return_pct")),
                "family_trials": storage.count_experiment_trials(r.family) if r.family else 0,
            })
        return out

    @app.get("/api/data-audit/{universe}", dependencies=dep)
    def data_audit_view(universe: str, interval: str = "1d", source: str | None = None):
        """Data-quality verdict for a universe (survivorship/adjustment/coverage)."""
        from app.data.data_audit import audit_universe

        rep = audit_universe(storage, universe, interval, source=source)
        return {
            "universe": rep.universe, "interval": rep.interval,
            "survivorship": rep.survivorship, "survivorship_note": rep.survivorship_note,
            "verdict": rep.verdict, "verdict_reasons": rep.verdict_reasons,
            "adj_coverage_pct": rep.adj_coverage_pct,
            "alignment_loss_pct": rep.alignment_loss_pct,
            "missing_symbols": rep.missing_symbols,
            "symbols_with_issues": [
                {"symbol": s.symbol, "issues": s.issues} for s in rep.symbols if s.issues],
        }

    @app.get("/api/governance/{alpha_id}", dependencies=dep)
    def governance_view(alpha_id: str, to: str = "walk_forward"):
        """Promotion-gate report for an alpha entering stage `to`."""
        from app.governance.gates import evaluate_gates
        from app.research.alpha_registry import AlphaRegistry, RegistryError

        try:
            alpha = AlphaRegistry().get(alpha_id)
        except RegistryError as exc:
            raise HTTPException(404, str(exc)) from exc
        evidence = {"executable_venues": alpha.executable_venues,
                    "requires_short": alpha.requires_short,
                    "requires_leverage": alpha.requires_leverage}
        report = evaluate_gates(to, evidence, stage_from=alpha.status)
        return {"alpha_id": alpha_id, "stage_from": alpha.status, "stage_to": to,
                "approved": report.approved,
                "gates": [{"name": r.name, "status": r.status, "detail": r.detail,
                           "blocking": r.blocking} for r in report.results]}

    @app.get("/api/jobs", dependencies=dep)
    def jobs():
        return service.list_jobs()

    @app.get("/api/jobs/{job_id}", dependencies=dep)
    def job(job_id: str):
        info = service.get_job(job_id)
        if info is None:
            raise HTTPException(404, f"job {job_id} not found")
        return info

    # ---- control endpoints (audited; refused unless controls are enabled) -----------

    @app.post("/api/risk/kill-switch/activate", dependencies=dep)
    def kill_switch_activate(body: ConfirmedAction):
        require_role(settings, Role.TRADER)
        require_phrase("kill_switch_activate", body.confirm_phrase)
        service.kill_switch.engage(body.reason or "dashboard")
        record_audit("kill_switch_activate", True, {"reason": body.reason}, "engaged")
        return {"ok": True, "kill_switch": service.kill_switch.status()}

    @app.post("/api/risk/kill-switch/deactivate", dependencies=dep)
    def kill_switch_deactivate(body: ConfirmedAction):
        require_role(settings, Role.ADMIN)
        require_phrase("kill_switch_deactivate", body.confirm_phrase)
        service.kill_switch.disengage()
        record_audit("kill_switch_deactivate", True, {"reason": body.reason}, "disengaged")
        return {"ok": True, "kill_switch": service.kill_switch.status()}

    @app.post("/api/risk/flatten-all", dependencies=dep)
    def flatten_all(body: ConfirmedAction):
        require_role(settings, Role.ADMIN)
        require_phrase("flatten_all", body.confirm_phrase)
        result = ("not available: live order connectors are gated off in this deployment. "
                  "The kill switch (engaged via this panel) is the effective halt; paper "
                  "positions are simulated inside the paper-trader process.")
        record_audit("flatten_all", True, {"reason": body.reason}, result)
        raise HTTPException(status_code=501, detail=result)

    @app.post("/api/risk/cancel-all-orders", dependencies=dep)
    def cancel_all_orders(body: ConfirmedAction):
        require_role(settings, Role.ADMIN)
        require_phrase("cancel_all_orders", body.confirm_phrase)
        result = "not available: no live order connectors are enabled in this deployment."
        record_audit("cancel_all_orders", True, {"reason": body.reason}, result)
        raise HTTPException(status_code=501, detail=result)

    @app.post("/api/strategies/{name}/pause", dependencies=dep)
    def pause_strategy(name: str):
        require_role(settings, Role.TRADER)
        paused = service.set_strategy_paused(name, True)
        record_audit("strategy_pause", True, {"strategy": name}, "paused")
        return {"ok": True, "paused": sorted(paused)}

    @app.post("/api/strategies/{name}/resume", dependencies=dep)
    def resume_strategy(name: str):
        require_role(settings, Role.TRADER)
        paused = service.set_strategy_paused(name, False)
        record_audit("strategy_resume", True, {"strategy": name}, "resumed")
        return {"ok": True, "paused": sorted(paused)}

    @app.post("/api/backtests/run", dependencies=dep)
    def run_backtest(body: JobRequest):
        require_role(settings, Role.RESEARCHER)
        body.kind = "backtest"
        info = service.start_job(body)
        record_audit("backtest_run", True, body.model_dump(), f"job {info.id} started")
        return info

    @app.post("/api/pairs/discover", dependencies=dep)
    def discover(body: JobRequest):
        require_role(settings, Role.RESEARCHER)
        body.kind = "discover_pairs"
        info = service.start_job(body)
        record_audit("pair_discovery", True, body.model_dump(), f"job {info.id} started")
        return info

    @app.post("/api/brokers/{broker}/reconnect", dependencies=dep)
    def broker_reconnect(broker: str):
        require_role(settings, Role.TRADER)
        statuses = {b.broker: b for b in service.broker_statuses(probe=True)}
        if broker not in statuses:
            raise HTTPException(404, f"unknown broker {broker}")
        record_audit("broker_probe", True, {"broker": broker},
                     f"connected={statuses[broker].connected}")
        return statuses[broker]

    # ---- websocket -----------------------------------------------------------------

    @app.websocket("/ws/{channel}")
    async def websocket_channel(websocket: WebSocket, channel: str):
        await ws.channel_endpoint(manager, channel, websocket)

    # ---- static frontend (built bundle) ------------------------------------------------

    if FRONTEND_DIST.exists():
        app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
    else:
        @app.get("/")
        def index_placeholder():
            return {
                "name": "stat-arb control panel API",
                "frontend": "not built — run: cd frontend && npm install && npm run build",
                "docs": "/docs",
            }

    return app


api = create_app()
