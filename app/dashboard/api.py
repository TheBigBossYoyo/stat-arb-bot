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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config.settings import PROJECT_ROOT, Settings, get_settings
from app.core.logging import audit as audit_log
from app.core.logging import get_logger
from app.dashboard import websocket as ws
from app.dashboard.action_schemas import ActionBody, ActionRequest, JobType
from app.dashboard.actions import list_reports, report_path
from app.dashboard.auth import check_token
from app.dashboard.jobs import ActionOrchestrator
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
    orchestrator = ActionOrchestrator(settings, storage)
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

    # ---- tradability / product dashboard (Phase 7) ---------------------------------

    def _product_dict(p):
        return {"product": p.product_id, "name": p.name, "venue": p.venue,
                "asset_class": p.asset_class, "shorting": p.requires_short,
                "leverage": p.requires_leverage, "venue_wired": p.venue_connected,
                "venue_kind": p.venue_kind, "gates_passed": p.gates_passed,
                "gates_total": p.gates_total, "status": p.status,
                "eligible_label": p.eligible_label, "risk": p.risk_level,
                "missing": p.missing, "notes": p.notes, "live_eligible": False}

    @app.get("/api/product-decision", dependencies=dep)
    def product_decision_view():
        """The operator decision: lead product, action, capital stage. Never live."""
        from app.research.product_decision import evaluate_products

        d = evaluate_products(settings, storage)
        return {"headline": d.headline, "recommended": d.recommended,
                "action": d.action, "capital_stage": d.capital_stage,
                "live_eligible": False, "products": [_product_dict(p) for p in d.products]}

    @app.get("/api/tradability-matrix", dependencies=dep)
    def tradability_matrix_view():
        """Rows = product paths, columns = gate/venue status. live_eligible all False."""
        from app.research.product_decision import evaluate_products

        d = evaluate_products(settings, storage)
        return {"rows": [_product_dict(p) for p in d.products], "live_eligible_any": False}

    @app.get("/api/blockers", dependencies=dep)
    def blockers_view():
        """Current blockers: per-product missing gates + the global blocker list."""
        from app.research.product_decision import evaluate_products

        d = evaluate_products(settings, storage)
        per_product = [{"product": p.product_id, "blocker": m}
                       for p in d.products for m in p.missing]
        return {"per_product": per_product, "global": [
            "no shorting venue connected (market-neutral has no home)",
            "return-concentration gate (long-only & futures just over 25%/month)",
            "survivorship bias (bounded via perturbation, not eliminated)",
            "crisis regime tested synthetically only (no real 2008/2020 crash)",
            "deflated Sharpe FAILS for the market-neutral flagship",
            "no forward supervised paper/testnet period yet",
            "production hardening incomplete"]}

    @app.get("/api/live-readiness", dependencies=dep)
    def live_readiness_view():
        """Live-readiness gate: always NOT LIVE ELIGIBLE, with the per-product standing."""
        from app.research.product_decision import evaluate_products

        d = evaluate_products(settings, storage)
        return {"live_eligible": False, "headline": d.headline,
                "products": [{"product": p.product_id, "status": p.status,
                              "eligible_label": p.eligible_label,
                              "gates": f"{p.gates_passed}/{p.gates_total}"}
                             for p in d.products]}

    @app.get("/api/deflated-sharpe", dependencies=dep)
    def deflated_sharpe_view(group: str = "equity_daily_book_selection"):
        """Trial-family count + Sharpe distribution feeding the deflated Sharpe."""
        from app.research.trial_backfill import backfill_trials, group_stats

        backfill_trials(storage)
        gs = group_stats(storage, group)
        report = settings.reports_dir / f"deflated_sharpe_{group}.md"
        return {"group": group, "n_trials": gs.n_trials, "with_sharpe": len(gs.sharpes),
                "best_sharpe": gs.best_sharpe, "mean_sharpe": gs.mean_sharpe,
                "std_sharpe": gs.std_sharpe,
                "report": report.read_text(encoding="utf-8") if report.exists() else ""}

    @app.get("/api/concentration/{strategy}", dependencies=dep)
    def concentration_view(strategy: str, universe: str = "us_stocks_50"):
        """Latest concentration report for a strategy/universe (markdown)."""
        matches = sorted((settings.reports_dir).glob(f"concentration_*{universe}*.md"))
        if not matches:
            return {"available": False, "report": "not run; execute `statarb concentration-report`"}
        return {"available": True, "file": matches[-1].name,
                "report": matches[-1].read_text(encoding="utf-8")}

    @app.get("/api/crisis/{strategy}", dependencies=dep)
    def crisis_view(strategy: str, universe: str = "us_stocks_50"):
        """Crisis-lab report for a strategy/universe (markdown), if generated."""
        p = settings.reports_dir / f"crisis_long_only_{strategy}_{universe}.md"
        if not p.exists():
            p = settings.reports_dir / f"crisis_{strategy}_{universe}.md"
        return {"available": p.exists(),
                "report": p.read_text(encoding="utf-8") if p.exists()
                else "not run; execute `statarb crisis-test-long-only`"}

    @app.get("/api/trading212-config", dependencies=dep)
    def trading212_config_view():
        """Trading 212 connection config — booleans only, NEVER the secrets, and
        a clear statement that live is hard-blocked."""
        return {
            "enabled": settings.trading212_enabled,
            "mode": settings.trading212_mode,
            "account_type": settings.trading212_account_type,
            "api_key_configured": bool(settings.trading212_api_key),
            "api_secret_configured": bool(settings.trading212_api_secret),
            "allow_demo_orders": settings.trading212_allow_demo_orders,
            "live_orders_supported": False,   # hard-blocked for this product
            "kill_switch_active": _kill_switch_active(),
        }

    def _kill_switch_active() -> bool:
        from app.risk.kill_switch import KillSwitch
        return KillSwitch(settings.runtime_dir / "kill_switch.flag").is_active

    @app.get("/api/long-only-order-preview", dependencies=dep)
    def long_only_order_preview_view(
        strategy: str = "long_only_xsec_momentum", universe: str = "us_stocks_50",
        starting_cash: float = 10_000.0,
    ):
        """SAFE offline (shadow) order preview: target weights -> validated plan.
        Connects to no broker and sends nothing. Read-only."""
        try:
            from app.brokers.trading212.instrument_cache import (
                InstrumentCache,
                synthetic_instruments,
            )
            from app.cli.main import _latest_long_only_weights
            from app.execution.long_only_order_planner import LongOnlyOrderPlanner

            weights, prices_t, symbols, _ = _latest_long_only_weights(
                storage, strategy, universe, "1d")
            planner = LongOnlyOrderPlanner(InstrumentCache(synthetic_instruments(symbols)))
            planned = planner.plan(weights, {}, starting_cash, prices_t, market_open=False)
            return {"available": True, "banner": "SHADOW MODE — SENDS NO ORDERS",
                    "live_eligible": False, "orders": planned.order_rows(),
                    "validation": {"ok": planned.validation.ok,
                                   "checks": planned.validation.checks,
                                   "issues": planned.validation.order_issues},
                    "summary": planned.summary()}
        except Exception as exc:  # noqa: BLE001
            return {"available": False, "error": str(exc), "orders": [], "banner": "SHADOW"}

    @app.get("/api/paper-status/{product}", dependencies=dep)
    def paper_status_view(product: str = "long_only_t212"):
        """Supervised paper session status (read-only)."""
        from app.execution.supervised_paper import SupervisedPaperStore, supervised_status

        return supervised_status(SupervisedPaperStore(settings.runtime_dir, product))

    @app.get("/api/paper-final/{product}", dependencies=dep)
    def paper_final_view(product: str = "long_only_t212", min_days: int = 30):
        """Supervised paper final report (read-only); never claims live-eligible."""
        from app.execution.supervised_paper import SupervisedPaperStore, final_report

        store = SupervisedPaperStore(settings.runtime_dir, product)
        if store.current_session() is None:
            return {"available": False, "message": "no session — run supervised-paper-start"}
        rep = final_report(store, min_days=min_days)
        rep["available"] = True
        equity = [{"date": r.get("date"), "equity": r.get("equity")}
                  for r in store.load("daily_reports")]
        rep["equity_curve"] = equity
        return rep

    # ---- operator paper mode (Phase 7) -------------------------------------------

    @app.get("/api/operator/status", dependencies=dep)
    def operator_status_view(product: str = "long_only_t212", min_days: int = 30):
        """Everything the Operator Paper Mode page needs (read-only). Never live."""
        from app.cli.main import _supervised_next_action
        from app.execution.paper_supervisor import (
            DAILY_SUMMARY_NAME,
            health_for,
            operator_checklist,
            product_status,
        )
        from app.research.product_decision import evaluate_products

        h = health_for(settings, storage, product=product, min_days=min_days)
        _ok, decision_status, _ps = product_status(settings, storage, product)
        d = evaluate_products(settings, storage)
        checklist = operator_checklist(settings, h, decision_status,
                                       kill_switch_active=_kill_switch_active())
        next_action = (h.get("message") if h["state"] == "NOT STARTED" else
                       _supervised_next_action(h["state"], product, h.get("mode", "shadow"),
                                               h.get("days_remaining", 0)))
        summary_path = settings.runtime_dir / "paper" / DAILY_SUMMARY_NAME
        return {
            "product": product,
            "live_eligible": False,
            "controls_enabled": settings.dashboard_controls_enabled,
            "kill_switch_active": _kill_switch_active(),
            "health": h,
            "decision": {"headline": d.headline, "recommended": d.recommended,
                         "action": d.action, "capital_stage": d.capital_stage,
                         "status": decision_status},
            "trading212": {
                "enabled": settings.trading212_enabled,
                "mode": settings.trading212_mode,
                "api_key_configured": bool(settings.trading212_api_key),
                "api_secret_configured": bool(settings.trading212_api_secret),
                "allow_demo_orders": settings.trading212_allow_demo_orders,
                "live_orders_supported": False,
            },
            "checklist": checklist,
            "next_action": next_action,
            "latest_summary": (summary_path.read_text(encoding="utf-8")
                               if summary_path.exists() else ""),
            "confirm_phrase_demo_execute": "RUN DEMO PAPER DAY",
        }

    @app.get("/api/operator/paper-vs-backtest", dependencies=dep)
    def operator_paper_vs_backtest(product: str = "long_only_t212"):
        """Operational paper-vs-backtest comparison (read-only)."""
        from app.execution.paper_vs_backtest import compare
        from app.execution.supervised_paper import SupervisedPaperStore

        return compare(SupervisedPaperStore(settings.runtime_dir, product),
                       product=product).as_dict()

    @app.get("/api/operator/preflight", dependencies=dep)
    def operator_preflight():
        """Final pre-flight check (read-only); also writes PAPER_PREFLIGHT_REPORT.md."""
        from app.config.settings import PROJECT_ROOT
        from app.research.paper_preflight import build_preflight_report

        md, res = build_preflight_report(settings, storage)
        out = PROJECT_ROOT / "PAPER_PREFLIGHT_REPORT.md"
        out.write_text(md, encoding="utf-8")
        return {"ready": res.ready, "live_eligible": False,
                "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail}
                           for c in res.checks],
                "blockers": res.blockers, "report": out.name}

    @app.get("/api/operator/weekly-report", dependencies=dep)
    def operator_weekly_report(product: str = "long_only_t212", as_of: str | None = None):
        """Weekly review report (read-only); writes runtime/paper/weekly_report_*.md."""
        from app.execution.supervised_paper import SupervisedPaperStore
        from app.research.paper_weekly_report import write_weekly_report

        store = SupervisedPaperStore(settings.runtime_dir, product)
        if store.current_session() is None:
            return {"available": False, "message": "no session — run supervised-paper-start"}
        out, rep = write_weekly_report(settings, store, storage=storage, as_of=as_of)
        return {"available": True, "live_eligible": False,
                "report": out.name, **rep.as_dict()}

    # ---- paper monitoring + alerts (Phase 5) -------------------------------------

    @app.get("/api/paper/health", dependencies=dep)
    def paper_health(product: str = "long_only_t212", min_days: int = 30):
        """Full monitoring view (read-only): health score, metrics, alerts, pvb."""
        from app.research.paper_monitor import load_snapshots, run_monitor

        res = run_monitor(settings, storage, product=product, min_days=min_days,
                          persist=False).as_dict()
        res["snapshots"] = load_snapshots(settings.runtime_dir, product)
        return res

    @app.post("/api/paper/health/run", dependencies=dep)
    def paper_health_run(body: ConfirmedAction, product: str = "long_only_t212",
                         min_days: int = 30):
        """Run the monitoring engine and PERSIST (records a snapshot + syncs alerts)."""
        require_role(settings, Role.TRADER)
        from app.research.paper_monitor import run_monitor

        res = run_monitor(settings, storage, product=product, min_days=min_days,
                          persist=True).as_dict()
        record_audit("paper_health_run", True, {"product": product},
                     f"score={res.get('health_score', {}).get('score')}")
        return res

    @app.get("/api/paper/alerts", dependencies=dep)
    def paper_alerts(product: str = "long_only_t212", include_resolved: bool = True):
        """Persisted alerts (active + resolved history) with counts."""
        from app.research.paper_alerts import CRITICAL, WARNING, AlertStore

        store = AlertStore(settings.runtime_dir, product)
        alerts = store.load()
        active = [a for a in alerts if not a.resolved]
        out = alerts if include_resolved else active
        return {
            "live_eligible": False,
            "alerts": [a.as_dict() for a in sorted(out, key=lambda a: a.timestamp, reverse=True)],
            "counts": {
                "critical": sum(1 for a in active if a.severity == CRITICAL),
                "warning": sum(1 for a in active if a.severity == WARNING),
                "info": sum(1 for a in active if a.severity not in (CRITICAL, WARNING)),
                "active_total": len(active),
                "resolved_total": sum(1 for a in alerts if a.resolved),
            },
        }

    @app.post("/api/paper/alerts/{alert_id}/resolve", dependencies=dep)
    def paper_alert_resolve(alert_id: str, body: ConfirmedAction,
                            product: str = "long_only_t212"):
        """Resolve a non-critical alert with a note (audited). A CRITICAL alert
        whose condition is still active cannot be dismissed — fix the cause."""
        require_role(settings, Role.TRADER)
        note = (body.reason or "").strip()
        if not note:
            raise HTTPException(400, "a resolution note (reason) is required")
        from app.core.types import utc_now
        from app.research.paper_alerts import CRITICAL, AlertStore, evaluate_alert_specs
        from app.research.paper_monitor import run_monitor

        # current active critical conditions block manual dismissal
        mon = run_monitor(settings, storage, product=product, persist=False).as_dict()
        specs = evaluate_alert_specs(mon.get("metrics", {}))
        blocked = {s.dedup_key for s in specs if s.severity == CRITICAL}

        store = AlertStore(settings.runtime_dir, product)
        now = utc_now().replace(tzinfo=None).isoformat()
        ok, msg = store.resolve(alert_id, note=note, now=now, blocked_keys=blocked)
        record_audit("paper_alert_resolve", ok,
                     {"alert_id": alert_id, "product": product, "note": note}, msg)
        if not ok:
            raise HTTPException(409 if "still active" in msg or "already" in msg else 404, msg)
        return {"ok": True, "alert_id": alert_id, "result": msg, "live_eligible": False}

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

    @app.post("/api/operator/run/{mode}", dependencies=dep)
    def operator_run(mode: str, body: ConfirmedAction):
        """Run one supervised paper day from the dashboard (audited; controls only).

        shadow / demo_preview need the TRADER role; demo_execute additionally needs
        the ADMIN role AND the exact phrase 'RUN DEMO PAPER DAY'. There is NO live
        path — every mode is paper/demo only and re-validated server-side."""
        if mode not in ("shadow", "demo_preview", "demo_execute"):
            raise HTTPException(400, "mode must be shadow | demo_preview | demo_execute")
        require_role(settings, Role.TRADER)
        confirm_demo = False
        if mode == "demo_execute":
            require_role(settings, Role.ADMIN)
            require_phrase("run_demo_paper_day", body.confirm_phrase)
            confirm_demo = True
        from app.cli.main import run_supervised_paper_daily

        res = run_supervised_paper_daily(settings, storage, product="long_only_t212",
                                         mode=mode, confirm_demo=confirm_demo)
        record_audit(f"operator_run_{mode}", True, {"mode": mode},
                     res.get("status_line", "")[:200])
        return {"ok": not res.get("refused", False), "live_eligible": False, **res}

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

    # ---- action orchestrator (Phase 2/3) -------------------------------------------
    #
    # Every POST below funnels through orchestrator.submit(), which re-validates the
    # role / phrase / env / kill-switch / product gates server-side and returns a job
    # record. A blocked attempt comes back as a REFUSED job (HTTP 200) with a reason —
    # the frontend is never trusted, and NONE of these can place a live order.

    def _submit(job_type: JobType, body: ActionBody) -> dict:
        req = ActionRequest(job_type=job_type, params=body.params,
                            confirm_phrase=body.confirm_phrase,
                            acknowledge=body.acknowledge, reason=body.reason)
        return orchestrator.submit(req).public()

    @app.get("/api/dashboard/capabilities", dependencies=dep)
    def dashboard_capabilities():
        return {"live_eligible": False, "controls_enabled": settings.dashboard_controls_enabled,
                "role": ("admin" if settings.dashboard_controls_enabled else "viewer"),
                "actions": orchestrator.capabilities()}

    @app.get("/api/dashboard/summary", dependencies=dep)
    def dashboard_summary(product: str = "long_only_t212"):
        """One call powering the Command Center: product decision, paper health,
        today's action, broker status, kill switch, latest reports + jobs."""
        from app.cli.main import _supervised_next_action
        from app.execution.paper_supervisor import health_for, product_status
        from app.research.paper_monitor import run_monitor
        from app.research.product_decision import evaluate_products

        h = health_for(settings, storage, product=product)
        _ok, decision_status, _ps = product_status(settings, storage, product)
        d = evaluate_products(settings, storage)
        next_action = (h.get("message") if h["state"] == "NOT STARTED" else
                       _supervised_next_action(h["state"], product,
                                               h.get("mode", "shadow"),
                                               h.get("days_remaining", 0)))
        # compact monitoring summary for the Command Center health card
        monitor_card = None
        if h.get("state") != "NOT STARTED":
            mon = run_monitor(settings, storage, product=product, persist=False).as_dict()
            met = mon.get("metrics", {})
            monitor_card = {
                "health_score": mon["health_score"]["score"],
                "classification": mon["health_score"]["classification"],
                "alert_counts": mon["alert_counts"],
                "next_expected_run": met.get("next_expected_run"),
                "missed_days": met.get("missed_days"),
                "weekly_due": met.get("weekly_due"),
                "final_review_ready": met.get("final_review_ready"),
                "days_remaining_to_min": met.get("days_remaining_to_min"),
                "days_remaining_to_target": met.get("days_remaining_to_target"),
                "ran_today": met.get("ran_today"),
                "suggested_next_action": mon.get("suggested_next_action"),
            }
        return {
            "live_eligible": False,
            "controls_enabled": settings.dashboard_controls_enabled,
            "kill_switch_active": _kill_switch_active(),
            "product": product,
            "decision": {"headline": d.headline, "recommended": d.recommended,
                         "action": d.action, "capital_stage": d.capital_stage,
                         "status": decision_status},
            "health": h,
            "monitor": monitor_card,
            "next_action": next_action,
            "trading212": trading212_config_view(),
            "reports": list_reports(settings)[:8],
            "jobs": orchestrator.list_jobs(8),
        }

    @app.get("/api/dashboard/jobs", dependencies=dep)
    def dashboard_jobs(limit: int = 50):
        return orchestrator.list_jobs(limit)

    @app.get("/api/dashboard/jobs/{job_id}", dependencies=dep)
    def dashboard_job(job_id: str):
        info = orchestrator.get_job(job_id)
        if info is None:
            raise HTTPException(404, f"job {job_id} not found")
        return info

    @app.get("/api/dashboard/jobs/{job_id}/logs", dependencies=dep)
    def dashboard_job_logs(job_id: str):
        info = orchestrator.job_logs(job_id)
        if info is None:
            raise HTTPException(404, f"job {job_id} not found")
        return info

    @app.post("/api/dashboard/jobs/{job_id}/cancel", dependencies=dep)
    def dashboard_job_cancel(job_id: str):
        info = orchestrator.cancel(job_id)
        if info is None:
            raise HTTPException(404, f"job {job_id} not found")
        return info

    @app.post("/api/dashboard/actions", dependencies=dep)
    def dashboard_action(body: ActionRequest):
        return orchestrator.submit(body).public()

    # -- named action endpoints (thin wrappers over the orchestrator) ----------------

    @app.post("/api/product-decision/run", dependencies=dep)
    def product_decision_run(body: ActionBody):
        return _submit(JobType.PRODUCT_DECISION, body)

    @app.post("/api/long-only/readiness/run", dependencies=dep)
    def readiness_run(body: ActionBody):
        return _submit(JobType.LONG_ONLY_READINESS, body)

    @app.post("/api/long-only/concentration/run", dependencies=dep)
    def concentration_run(body: ActionBody):
        return _submit(JobType.CONCENTRATION_ANALYSIS, body)

    @app.post("/api/long-only/concentration/compare-fixes", dependencies=dep)
    def concentration_compare(body: ActionBody):
        return _submit(JobType.COMPARE_CONCENTRATION_FIXES, body)

    @app.post("/api/long-only/survivorship/run", dependencies=dep)
    def survivorship_run(body: ActionBody):
        return _submit(JobType.SURVIVORSHIP_STRESS, body)

    @app.post("/api/long-only/crisis/run", dependencies=dep)
    def crisis_run(body: ActionBody):
        return _submit(JobType.CRISIS_TEST, body)

    @app.post("/api/trading212/setup-check", dependencies=dep)
    def trading212_setup_check(body: ActionBody):
        return _submit(JobType.TRADING212_SETUP_CHECK, body)

    @app.post("/api/trading212/order-preview", dependencies=dep)
    def trading212_order_preview(body: ActionBody):
        return _submit(JobType.ORDER_PREVIEW, body)

    @app.post("/api/paper/start", dependencies=dep)
    def paper_start(body: ActionBody):
        return _submit(JobType.SUPERVISED_PAPER_START, body)

    _DAILY_JOBS = {
        "shadow": JobType.SUPERVISED_PAPER_DAILY_SHADOW,
        "demo_preview": JobType.SUPERVISED_PAPER_DAILY_DEMO_PREVIEW,
        "demo_execute": JobType.SUPERVISED_PAPER_DAILY_DEMO_EXECUTE,
    }

    @app.post("/api/paper/daily", dependencies=dep)
    def paper_daily(body: ActionBody):
        mode = str(body.params.get("mode", "shadow"))
        job_type = _DAILY_JOBS.get(mode)
        if job_type is None:
            raise HTTPException(400, "params.mode must be shadow | demo_preview | demo_execute")
        return _submit(job_type, body)

    @app.post("/api/paper/final-report", dependencies=dep)
    def paper_final_report(body: ActionBody):
        return _submit(JobType.SUPERVISED_PAPER_FINAL_REPORT, body)

    @app.post("/api/paper/stop", dependencies=dep)
    def paper_stop(body: ActionBody):
        return _submit(JobType.SUPERVISED_PAPER_STOP, body)

    # -- kill switch via orchestrator (engage/disengage; audited + phrase-gated) ------

    @app.post("/api/risk/kill-switch/engage", dependencies=dep)
    def kill_switch_engage(body: ActionBody):
        body.params = {**body.params, "operation": "engage"}
        return _submit(JobType.KILL_SWITCH_ACTION, body)

    @app.post("/api/risk/kill-switch/disengage", dependencies=dep)
    def kill_switch_disengage(body: ActionBody):
        body.params = {**body.params, "operation": "disengage"}
        return _submit(JobType.KILL_SWITCH_ACTION, body)

    # -- reports library -------------------------------------------------------------

    @app.get("/api/reports", dependencies=dep)
    def reports_list():
        return {"reports": list_reports(settings), "live_eligible": False}

    @app.get("/api/reports/{report_id}", dependencies=dep)
    def reports_view(report_id: str):
        p = report_path(settings, report_id)
        if p is None or not p.exists():
            raise HTTPException(404, f"report {report_id} not found")
        return {"id": report_id, "name": p.name,
                "content": p.read_text(encoding="utf-8", errors="replace")}

    @app.get("/api/reports/{report_id}/download", dependencies=dep)
    def reports_download(report_id: str):
        p = report_path(settings, report_id)
        if p is None or not p.exists():
            raise HTTPException(404, f"report {report_id} not found")
        return FileResponse(str(p), media_type="text/markdown", filename=p.name)

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
