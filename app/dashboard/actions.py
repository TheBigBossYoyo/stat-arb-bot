"""Action handlers for the dashboard orchestrator (Phase 2).

Each handler runs ONE job and returns a JSON-serialisable dict. Handlers reuse
the exact same engine / CLI helper functions the terminal uses — they never
re-implement the strategy or weaken a gate, and there is no handler that can
reach a live order. Heavy research handlers import the same private helpers from
`app.cli.main` that the read endpoints already use.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.settings import Settings
from app.core.logging import get_logger
from app.dashboard.action_schemas import JobRecord, JobType
from app.dashboard.job_store import JobStore
from app.data.storage import Storage

log = get_logger(__name__)


class HandlerError(Exception):
    """A handler could not complete (turns the job FAILED, not REFUSED)."""


@dataclass
class ActionContext:
    settings: Settings
    storage: Storage
    params: dict[str, Any]
    confirm_demo: bool
    job: JobRecord
    store: JobStore

    def log(self, line: str) -> None:
        self.store.append_log(self.job.id, line)

    def progress(self, pct: float, step: str = "") -> None:
        self.store.set_progress(self.job.id, pct, step)

    @property
    def cancelled(self) -> bool:
        return self.job.cancel_requested

    # common params
    def product(self) -> str:
        return str(self.params.get("product", "long_only_t212"))

    def strategy(self) -> str:
        return str(self.params.get("strategy", "long_only_xsec_momentum"))

    def universe(self) -> str:
        return str(self.params.get("universe", "us_stocks_50"))

    def interval(self) -> str:
        return str(self.params.get("interval", "1d"))


def _product_dict(p) -> dict[str, Any]:
    return {"product": p.product_id, "name": p.name, "venue": p.venue,
            "asset_class": p.asset_class, "gates_passed": p.gates_passed,
            "gates_total": p.gates_total, "status": p.status,
            "eligible_label": p.eligible_label, "risk": p.risk_level,
            "missing": p.missing, "notes": p.notes, "live_eligible": False}


# -- handlers -------------------------------------------------------------------

def _h_product_decision(ctx: ActionContext) -> dict[str, Any]:
    from app.research.product_decision import evaluate_products

    ctx.progress(0.3, "evaluating product paths")
    d = evaluate_products(ctx.settings, ctx.storage)
    ctx.progress(1.0, "done")
    return {"headline": d.headline, "recommended": d.recommended, "action": d.action,
            "capital_stage": d.capital_stage, "live_eligible": False,
            "products": [_product_dict(p) for p in d.products]}


def _h_trading212_setup_check(ctx: ActionContext) -> dict[str, Any]:
    from app.brokers.trading212.setup_check import run_setup_check

    connect = bool(ctx.params.get("connect", True))
    ctx.progress(0.4, "probing DEMO endpoints" if connect else "checking config")
    res = run_setup_check(ctx.settings, connect=connect).as_dict()
    ctx.progress(1.0, "done")
    return res


def _h_order_preview(ctx: ActionContext) -> dict[str, Any]:
    """Order PREVIEW — builds the validated long-only plan but connects to no
    broker and sends NOTHING. Both `shadow` and `demo_preview` here are offline
    previews: real demo execution only ever happens inside the gated supervised
    paper daily run. This is the operator's "what would happen today" view."""
    from app.brokers.trading212.instrument_cache import (
        InstrumentCache,
        synthetic_instruments,
    )
    from app.cli.main import _latest_long_only_weights
    from app.execution.long_only_order_planner import (
        LongOnlyOrderPlanner,
        expected_slippage_bps,
    )

    mode = str(ctx.params.get("mode", "shadow"))
    strategy, universe = ctx.strategy(), ctx.universe()
    starting_cash = float(ctx.params.get("starting_cash", 10_000.0))
    ctx.progress(0.4, "loading latest target weights")
    weights, prices_t, symbols, _ = _latest_long_only_weights(
        ctx.storage, strategy, universe, ctx.interval())
    planner = LongOnlyOrderPlanner(InstrumentCache(synthetic_instruments(symbols)))
    planned = planner.plan(weights, {}, starting_cash, prices_t, market_open=False)
    demo_ready = bool(ctx.settings.trading212_enabled
                      and ctx.settings.trading212_mode == "demo"
                      and ctx.settings.trading212_allow_demo_orders)
    ctx.progress(1.0, "done")
    return {
        "banner": ("SHADOW MODE — SENDS NO ORDERS" if mode == "shadow"
                   else "DEMO PREVIEW (offline) — validates the plan, contacts no broker, sends nothing"),
        "mode": mode, "live_eligible": False,
        "orders": planned.order_rows(),
        "skipped": [list(s) for s in planned.plan.skipped],
        "target_weights": [{"symbol": s, "weight": round(w, 4)}
                           for s, w in sorted(planned.target_weights.items(),
                                              key=lambda kv: -kv[1]) if w > 0],
        "summary": {**planned.summary(),
                    "expected_slippage_bps": round(expected_slippage_bps(planned.plan), 2)},
        "validation": {"ok": planned.validation.ok,
                       "checks": planned.validation.checks,
                       "issues": planned.validation.order_issues},
        "demo_eligible": demo_ready,
        "demo_note": ("demo orders are configured — but are only ever sent inside the gated "
                      "supervised paper daily run" if demo_ready
                      else "demo orders are not enabled — this is preview only"),
    }


def _h_supervised_paper_start(ctx: ActionContext) -> dict[str, Any]:
    from app.execution.supervised_paper import (
        PaperSession,
        SupervisedPaperStore,
        supervised_status,
    )

    product, mode = ctx.product(), str(ctx.params.get("mode", "shadow"))
    if mode not in ("shadow", "demo_preview", "demo_execute"):
        raise HandlerError("mode must be shadow | demo_preview | demo_execute")
    min_days = int(ctx.params.get("min_days", 30))
    starting_cash = float(ctx.params.get("starting_cash", 10_000.0))
    store = SupervisedPaperStore(ctx.settings.runtime_dir, product)
    if bool(ctx.params.get("reset", False)):
        store.reset()
    session = store.current_session()
    started = False
    if session is None:
        session = PaperSession.new(product, mode, min_days=min_days,
                                   starting_cash=starting_cash)
        store.start_session(session)
        started = True
    elif session.status != "active":
        raise HandlerError("a stopped session exists — pass reset=true to start a new one")
    ctx.progress(1.0, "session ready")
    return {"product": product, "mode": session.mode, "session_id": session.session_id,
            "started": started, "min_days": session.min_days, "live_eligible": False,
            "status": supervised_status(store)}


def _make_daily_handler(mode: str) -> Callable[[ActionContext], dict[str, Any]]:
    def handler(ctx: ActionContext) -> dict[str, Any]:
        from app.cli.main import run_supervised_paper_daily

        ctx.progress(0.2, f"running supervised paper day ({mode})")
        res = run_supervised_paper_daily(
            ctx.settings, ctx.storage, product=ctx.product(), mode=mode,
            confirm_demo=ctx.confirm_demo)
        ctx.progress(1.0, res.get("status_line", "done"))
        out = {"live_eligible": False, **res}
        if res.get("summary_path"):
            out["report_path"] = res["summary_path"]
        return out
    return handler


def _h_supervised_paper_health(ctx: ActionContext) -> dict[str, Any]:
    from app.execution.paper_supervisor import health_for

    return health_for(ctx.settings, ctx.storage, product=ctx.product(),
                      min_days=int(ctx.params.get("min_days", 30)))


def _h_supervised_paper_final_report(ctx: ActionContext) -> dict[str, Any]:
    from app.execution.supervised_paper import SupervisedPaperStore, final_report

    product = ctx.product()
    min_days = int(ctx.params.get("min_days", 30))
    store = SupervisedPaperStore(ctx.settings.runtime_dir, product)
    if store.current_session() is None:
        raise HandlerError("no session — start a supervised paper session first")
    ctx.progress(0.5, "building final report")
    rep = final_report(store, min_days=min_days)
    out = ctx.settings.reports_dir / f"supervised_paper_final_{product}.md"
    lines = [f"# Supervised paper final report — {product}", "",
             f"Verdict: **{rep.get('verdict')}**", "",
             *(f"- {k}: {v}" for k, v in rep.items() if k != "checks"), "",
             "## Checks", "",
             *(f"- {'PASS' if ok else 'FAIL'} — {n}"
               for n, ok in rep.get("checks", {}).items())]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ctx.progress(1.0, "done")
    rep["report_path"] = str(out)
    rep["live_eligible"] = False
    return rep


def _h_supervised_paper_stop(ctx: ActionContext) -> dict[str, Any]:
    from app.execution.supervised_paper import SupervisedPaperStore

    product = ctx.product()
    reason = str(ctx.params.get("reason") or "stopped from dashboard")
    store = SupervisedPaperStore(ctx.settings.runtime_dir, product)
    s = store.stop_session(reason)
    if s is None:
        raise HandlerError("no active session to stop")
    return {"stopped": s.session_id, "reason": reason, "live_eligible": False}


def _h_paper_vs_backtest(ctx: ActionContext) -> dict[str, Any]:
    from app.execution.paper_vs_backtest import compare
    from app.execution.supervised_paper import SupervisedPaperStore

    return compare(SupervisedPaperStore(ctx.settings.runtime_dir, ctx.product()),
                   product=ctx.product()).as_dict()


def _h_concentration(ctx: ActionContext) -> dict[str, Any]:
    from app.cli.main import (
        _long_only_smoothing_eval,
        _smoothing_config,
        _strategy_defaults,
    )

    strategy, universe, interval = ctx.strategy(), ctx.universe(), ctx.interval()
    method = str(ctx.params.get("method", "ewma"))
    n_folds = int(ctx.params.get("n_folds", 3))
    defaults = _strategy_defaults(interval)
    baseline = _smoothing_config(defaults, method="none")
    smoothed = _smoothing_config(defaults, method=method)
    ctx.progress(0.3, "evaluating baseline vs smoothed concentration")
    rows, names, base_oos = _long_only_smoothing_eval(
        ctx.storage, strategy, universe, interval, [baseline, smoothed], n_folds=n_folds)
    ctx.progress(1.0, "done")
    return {"strategy": strategy, "universe": universe, "smoothing": smoothed.label(),
            "baseline_oos_sharpe": base_oos, "gate_pass": bool(rows[-1].get("gate_pass")),
            "rows": rows, "sleeves": names, "live_eligible": False}


def _h_survivorship(ctx: ActionContext) -> dict[str, Any]:
    from app.cli.main import _run_universe_bias

    strategy, universe, interval = ctx.strategy(), ctx.universe(), ctx.interval()
    ctx.progress(0.3, "running survivorship perturbation bound")
    rep = _run_universe_bias(ctx.storage, ctx.settings, strategy, universe, interval)
    out = ctx.settings.reports_dir / f"survivorship_long_only_{strategy}_{universe}.md"
    ctx.progress(1.0, "done")
    return {"strategy": strategy, "universe": universe, "verdict": rep.verdict(),
            "median_sharpe": rep.median_sharpe, "sharpe_p05": rep.sharpe_p05,
            "worst_case_dd_pct": rep.worst_case_dd_pct, "summary": rep.summary(),
            "rows": rep.rows(), "report_path": str(out), "live_eligible": False,
            "note": "Only a point-in-time constituent backtest can ELIMINATE the bias."}


def _h_crisis(ctx: ActionContext) -> dict[str, Any]:
    from app.backtesting.crisis import long_only_scenarios, run_crisis_suite
    from app.cli.main import _crisis_equity_runner, _smoothing_config, _strategy_defaults
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_sectors, get_universe

    strategy, universe, interval = ctx.strategy(), ctx.universe(), ctx.interval()
    defaults = _strategy_defaults(interval)
    sm = _smoothing_config(defaults)
    ctx.progress(0.2, "building price panel")
    prices = build_price_matrix(ctx.storage, get_universe(universe), interval, adjusted=True)
    scen = long_only_scenarios(get_sectors(universe))
    run_fn, _ = _crisis_equity_runner(strategy, universe, interval, regime=True, smoothing=sm)
    ctx.progress(0.5, "running synthetic crisis suite (certified book)")
    table = run_crisis_suite(prices.close, run_fn, aux=prices.aux, scenarios=scen)
    base_full_dd = float(table.loc["base", "full_max_dd_pct"])
    worst = float(table["crisis_max_dd_pct"].astype(float).min())
    worst_scen = str(table["crisis_max_dd_pct"].astype(float).idxmin())
    bounded = worst > -45.0
    catastrophic = worst <= -60.0
    out = ctx.settings.reports_dir / f"crisis_long_only_{strategy}_{universe}.md"
    out.write_text(
        f"# Long-only crisis test (SYNTHETIC) — {strategy} ({universe}, {interval})\n\n"
        f"Smoothing: **{sm.label()}** | worst synthetic crisis DD: **{worst}%** "
        f"({worst_scen}) | base full DD {base_full_dd}%\n\n"
        "> All crisis scenarios are SYNTHETIC/proxy injections — the live window has no "
        "real 2008/2020 tail.\n\n" + table.to_markdown() + "\n\n"
        f"Acceptance: bounded (> -45%): **{bounded}**; catastrophic (<= -60%): "
        f"**{catastrophic}**.\n", encoding="utf-8")
    ctx.progress(1.0, "done")
    return {"strategy": strategy, "universe": universe, "worst_crisis_dd_pct": worst,
            "worst_scenario": worst_scen, "base_full_dd_pct": base_full_dd,
            "bounded": bounded, "catastrophic": catastrophic,
            "verdict": "BOUNDED" if bounded else ("CATASTROPHIC" if catastrophic
                                                  else "DEEP BUT SURVIVABLE"),
            "scenarios": table.reset_index().to_dict("records"),
            "report_path": str(out), "live_eligible": False,
            "note": "Synthetic/proxy crisis injections — stress bounds, not history."}


def _h_long_only_readiness(ctx: ActionContext) -> dict[str, Any]:
    """Run the long-only paper-readiness battery via the project's own CLI in a
    controlled, allow-listed subprocess (the readiness command is a large Typer
    command with no headless entry point). Live is never in scope."""
    strategy = str(ctx.params.get("strategy", "long_only_ensemble"))
    universe, interval = ctx.universe(), ctx.interval()
    full = bool(ctx.params.get("full", True))
    args = ["long-only-readiness", "--strategy", strategy, "--universe", universe,
            "--interval", interval]
    if full:
        args.append("--full")
    ctx.progress(0.2, "running readiness battery")
    rc, tail = _run_cli(ctx, args)
    report = ctx.settings.reports_dir.parent / "PAPER_ELIGIBILITY_REPORT.md"
    ctx.progress(1.0, "done")
    return {"strategy": strategy, "universe": universe, "exit_code": rc,
            "passed": rc == 0, "log_tail": tail, "live_eligible": False,
            "report_path": str(report) if report.exists() else None}


def _h_compare_concentration_fixes(ctx: ActionContext) -> dict[str, Any]:
    strategy, universe, interval = ctx.strategy(), ctx.universe(), ctx.interval()
    args = ["compare-concentration-fixes", "--strategy", strategy,
            "--universe", universe, "--interval", interval]
    ctx.progress(0.2, "comparing concentration fixes")
    rc, tail = _run_cli(ctx, args)
    ctx.progress(1.0, "done")
    return {"strategy": strategy, "universe": universe, "exit_code": rc,
            "log_tail": tail, "live_eligible": False}


def _h_report_generation(ctx: ActionContext) -> dict[str, Any]:
    return {"reports": list_reports(ctx.settings), "live_eligible": False}


def _h_kill_switch(ctx: ActionContext) -> dict[str, Any]:
    from app.risk.kill_switch import KillSwitch

    op = str(ctx.params.get("operation", "")).lower()
    ks = KillSwitch(ctx.settings.runtime_dir / "kill_switch.flag")
    if op in ("engage", "activate", "on"):
        ks.engage(str(ctx.params.get("reason") or "dashboard"))
        return {"operation": "engage", "kill_switch": ks.status(), "live_eligible": False}
    if op in ("disengage", "deactivate", "off", "release"):
        ks.disengage()
        return {"operation": "disengage", "kill_switch": ks.status(), "live_eligible": False}
    raise HandlerError("operation must be 'engage' or 'disengage'")


# -- controlled CLI subprocess (allow-listed) -----------------------------------

_ALLOWED_CLI: frozenset[str] = frozenset({
    "long-only-readiness", "compare-concentration-fixes",
})


def _run_cli(ctx: ActionContext, args: list[str], timeout: int = 1800) -> tuple[int, str]:
    """Run `python -m app.cli.main <sub> <args>` for an ALLOW-LISTED research
    subcommand. This is not a shell: argv is a fixed list, the subcommand is
    checked against an allow-list, and no operator string is interpolated into a
    shell. Output is streamed into the job log."""
    import subprocess
    import sys

    from app.config.settings import PROJECT_ROOT

    if not args or args[0] not in _ALLOWED_CLI:
        raise HandlerError(f"refusing: '{args[0] if args else ''}' is not an allow-listed action")
    cmd = [sys.executable, "-m", "app.cli.main", *args]
    ctx.log(f"$ {' '.join(args)}")
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True,
                          text=True, timeout=timeout, check=False)
    tail = (proc.stdout or "")[-4000:] + (proc.stderr or "")[-2000:]
    for line in tail.splitlines()[-60:]:
        ctx.log(line)
    return proc.returncode, tail


# -- reports library ------------------------------------------------------------

_ROOT_REPORTS = (
    "PAPER_ELIGIBILITY_REPORT.md", "SUPERVISED_PAPER_START_REPORT.md",
    "TRADABLE_PRODUCT_REPORT.md", "FINAL_RESEARCH_REPORT.md", "AUDIT_REPORT.md",
    "RESEARCH_WEAKNESSES.md", "PRODUCTION_RISK_REGISTER.md",
    "STRATEGY_ACCEPTANCE_CRITERIA.md", "DASHBOARD_COMPLETION_REPORT.md",
)


def _categorise(name: str) -> str:
    low = name.lower()
    if low.startswith("crisis"):
        return "crisis"
    if low.startswith("concentration"):
        return "concentration"
    if low.startswith("survivorship"):
        return "survivorship"
    if "paper_final" in low or "paper_start" in low or "paper_elig" in low:
        return "paper"
    if "deflated" in low or "multiple_testing" in low:
        return "research"
    return "report"


def list_reports(settings: Settings) -> list[dict[str, Any]]:
    """All operator-facing reports (root + reports_dir), newest first, with a
    staleness flag (older than 14 days)."""
    import time

    from app.config.settings import PROJECT_ROOT

    seen: dict[str, Path] = {}
    for name in _ROOT_REPORTS:
        p = PROJECT_ROOT / name
        if p.exists():
            seen[name] = p
    reports_dir = Path(settings.reports_dir)
    if reports_dir.exists():
        for p in sorted(reports_dir.glob("*.md")):
            seen[p.name] = p
    out: list[dict[str, Any]] = []
    now = time.time()
    for name, p in seen.items():
        st = p.stat()
        out.append({"id": name, "name": name, "category": _categorise(name),
                    "size": st.st_size, "modified": int(st.st_mtime),
                    "stale": (now - st.st_mtime) > 14 * 86400,
                    "path": str(p)})
    out.sort(key=lambda r: r["modified"], reverse=True)
    return out


def report_path(settings: Settings, report_id: str) -> Path | None:
    """Resolve a report id to a path, guarding against traversal."""
    for r in list_reports(settings):
        if r["id"] == report_id:
            return Path(r["path"])
    return None


# -- registry -------------------------------------------------------------------

HANDLERS: dict[JobType, Callable[[ActionContext], dict[str, Any]]] = {
    JobType.PRODUCT_DECISION: _h_product_decision,
    JobType.LONG_ONLY_READINESS: _h_long_only_readiness,
    JobType.CONCENTRATION_ANALYSIS: _h_concentration,
    JobType.COMPARE_CONCENTRATION_FIXES: _h_compare_concentration_fixes,
    JobType.SURVIVORSHIP_STRESS: _h_survivorship,
    JobType.CRISIS_TEST: _h_crisis,
    JobType.TRADING212_SETUP_CHECK: _h_trading212_setup_check,
    JobType.ORDER_PREVIEW: _h_order_preview,
    JobType.SUPERVISED_PAPER_START: _h_supervised_paper_start,
    JobType.SUPERVISED_PAPER_DAILY_SHADOW: _make_daily_handler("shadow"),
    JobType.SUPERVISED_PAPER_DAILY_DEMO_PREVIEW: _make_daily_handler("demo_preview"),
    JobType.SUPERVISED_PAPER_DAILY_DEMO_EXECUTE: _make_daily_handler("demo_execute"),
    JobType.SUPERVISED_PAPER_HEALTH: _h_supervised_paper_health,
    JobType.SUPERVISED_PAPER_FINAL_REPORT: _h_supervised_paper_final_report,
    JobType.SUPERVISED_PAPER_STOP: _h_supervised_paper_stop,
    JobType.PAPER_VS_BACKTEST: _h_paper_vs_backtest,
    JobType.REPORT_GENERATION: _h_report_generation,
    JobType.KILL_SWITCH_ACTION: _h_kill_switch,
}
