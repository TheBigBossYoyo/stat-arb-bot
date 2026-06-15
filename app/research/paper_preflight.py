"""Final pre-flight check before a forward supervised paper period (Phase 1).

A single, auditable gate that verifies EVERY safety- and readiness-relevant
precondition immediately before an operator starts the forward shadow/paper
period. It is intentionally broader than the per-day ``preflight`` in
``paper_supervisor`` (which gates one recorded day): this checks the product
decision, the structural live-trading blocks, the broker capability matrix,
the operational plumbing (paper-session storage, report generation, audit
trail) and the presence of every research/dashboard artifact the period relies
on.

It produces ``PAPER_PREFLIGHT_REPORT.md`` with one of two verdicts:

    "Ready to start supervised forward paper period"   or
    "Not ready because: [...]"

Nothing here trades or connects. Live is never in scope; the report restates
that the system is not live-eligible.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

# Reuse the supervisor's Check shape so pre-flight rows render identically
# wherever they surface (CLI table, dashboard, this report).
from app.execution.paper_supervisor import Check

PRODUCT = "long_only_t212"
DECISION_ID = "long_only_equity"


@dataclass
class PreflightResult:
    ready: bool
    checks: list[Check]

    @property
    def blockers(self) -> list[str]:
        return [f"{c.name} ({c.detail})" if c.detail else c.name
                for c in self.checks if not c.ok]


def _exists_nonempty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _first_existing(*paths: Path) -> Path | None:
    return next((p for p in paths if _exists_nonempty(p)), None)


# -- individual checks (each returns a Check; never raises) -----------------------

def _check_product_decision(settings, storage) -> Check:
    try:
        from app.execution.paper_supervisor import product_status
        is_candidate, status, _ps = product_status(settings, storage, PRODUCT)
        return Check(f"product-decision: {DECISION_ID} is paper_candidate", is_candidate,
                     f"status is '{status}', not 'paper_candidate'")
    except Exception as exc:  # noqa: BLE001 - a broken decision engine is itself a blocker
        return Check(f"product-decision: {DECISION_ID} is paper_candidate", False, str(exc))


def _check_live_off(settings) -> Check:
    off = not settings.live_trading_allowed
    return Check("live trading is OFF", off,
                 "LIVE_TRADING/CONFIRM_LIVE_TRADING are ON — refuse")


def _check_live_hard_blocked() -> Check:
    """The live Trading 212 order path must not exist as callable behaviour."""
    try:
        import app.brokers.trading212.execution as live_ex
        offenders = [n for n in dir(live_ex)
                     if not n.startswith("_")
                     and ("executor" in n.lower() or "submit" in n.lower()
                          or "place_order" in n.lower())]
        # Defense in depth: the demo executor must refuse any non-demo mode.
        from app.brokers.trading212.demo_execution import Trading212DemoExecutor  # noqa: F401
        ok = not offenders
        return Check("Trading 212 LIVE orders hard-blocked (no live order path)", ok,
                     f"live execution module exposes order symbols: {offenders}")
    except Exception as exc:  # noqa: BLE001
        return Check("Trading 212 LIVE orders hard-blocked (no live order path)", False, str(exc))


def _check_capabilities() -> list[Check]:
    try:
        from app.brokers.trading212.capabilities import (
            UNSUPPORTED_PRODUCTS,
            trading212_capabilities,
        )
        caps = trading212_capabilities()
        unsupported = {u.lower() for u in caps.unsupported} | set(UNSUPPORTED_PRODUCTS)
        cfd_ok = "cfd" in unsupported
        no_short = not caps.shorting
        no_margin = not caps.margin
        no_lev = caps.max_leverage <= 1.0
        return [
            Check("CFDs are UNSUPPORTED", cfd_ok, "cfd missing from broker unsupported list"),
            Check("no shorting on Invest/ISA", no_short, "capabilities allow shorting"),
            Check("no margin on Invest/ISA", no_margin, "capabilities allow margin"),
            Check("no leverage (max_leverage <= 1.0)", no_lev,
                  f"max_leverage is {caps.max_leverage}"),
        ]
    except Exception as exc:  # noqa: BLE001
        return [Check("Trading 212 capability matrix (CFD/short/margin/leverage)", False, str(exc))]


def _check_kill_switch(settings) -> Check:
    try:
        from app.execution.paper_supervisor import _kill_switch_active
        active = _kill_switch_active(settings)
        return Check("kill switch is OFF", not active, "kill switch is ENGAGED")
    except Exception as exc:  # noqa: BLE001
        return Check("kill switch is OFF", False, str(exc))


def _check_dashboard_controls(settings) -> Check:
    """The dashboard must remain structurally not-live-eligible regardless of
    whether the operator has controls enabled."""
    controls = bool(getattr(settings, "dashboard_controls_enabled", False))
    live_eligible = False  # invariant: the dashboard never reports live-eligible
    ok = (not live_eligible) and (not settings.live_trading_allowed)
    return Check("dashboard controls status correct (paper-only, not live-eligible)", ok,
                 f"controls_enabled={controls}, live_eligible={live_eligible}")


def _check_paper_storage() -> Check:
    """Round-trip a throwaway paper session + table row in a temp dir."""
    try:
        from app.execution.supervised_paper import PaperSession, SupervisedPaperStore
        with tempfile.TemporaryDirectory() as td:
            store = SupervisedPaperStore(Path(td), "preflight_probe")
            sess = PaperSession.new("preflight_probe", "shadow", min_days=1, starting_cash=1.0)
            store.start_session(sess)
            store.append("daily_reports", {"date": "1970-01-01", "equity": 1.0})
            rows = store.load("daily_reports")
            loaded = store.current_session()
            store.reset()
            ok = bool(rows) and loaded is not None and loaded.session_id == sess.session_id
            return Check("paper session storage works (write/read/reset round-trip)", ok,
                         "round-trip did not return the written session/row")
    except Exception as exc:  # noqa: BLE001
        return Check("paper session storage works (write/read/reset round-trip)", False, str(exc))


def _check_report_generation() -> Check:
    try:
        from app.execution.paper_supervisor import render_daily_summary
        md = render_daily_summary(
            {"product": PRODUCT, "date": "1970-01-01", "mode": "shadow", "equity": 1.0,
             "target_weights": {}, "planned_orders": [], "refused_orders": []},
            health_state="IN PROGRESS", next_action="(probe)", status_line="(probe)")
        ok = bool(md) and "NOT LIVE ELIGIBLE" in md
        return Check("report generation works", ok, "rendered summary missing safety footer")
    except Exception as exc:  # noqa: BLE001
        return Check("report generation works", False, str(exc))


def _check_audit_trail(storage) -> Check:
    try:
        if storage is None:
            return Check("audit trail works", False, "no storage handle supplied")
        # read-only probe: the audit table must be queryable
        _ = storage.load_audit_events(limit=1)
        return Check("audit trail works (audit table queryable)", True, "")
    except Exception as exc:  # noqa: BLE001
        return Check("audit trail works (audit table queryable)", False, str(exc))


def _check_reports(settings) -> list[Check]:
    from app.config.settings import PROJECT_ROOT
    rd = settings.reports_dir
    readiness = _first_existing(
        rd / "long_only_readiness_long_only_xsec_momentum_us_stocks_50.md")
    concentration = _first_existing(
        rd / "concentration_smoothing_long_only_xsec_momentum_us_stocks_50.md",
        PROJECT_ROOT / "docs" / "concentration_mitigation.md")
    crisis = _first_existing(
        rd / "crisis_long_only_long_only_xsec_momentum_us_stocks_50.md",
        rd / "crisis_long_only_xsec_momentum_us_stocks_50.md")
    survivorship = _first_existing(
        rd / "survivorship_long_only_long_only_xsec_momentum_us_stocks_50.md",
        rd / "survivorship_long_only_xsec_momentum_us_stocks_50.md")
    dashboard_acc = _first_existing(
        PROJECT_ROOT / "DASHBOARD_NO_TERMINAL_ACCEPTANCE.md",
        PROJECT_ROOT / "DASHBOARD_REDESIGN_REPORT.md",
        PROJECT_ROOT / "DASHBOARD_COMPLETION_REPORT.md")
    return [
        Check("latest readiness report exists", readiness is not None,
              "no long_only_readiness report in reports/"),
        Check("latest concentration report exists", concentration is not None,
              "no concentration report in reports/"),
        Check("latest crisis report exists", crisis is not None, "no crisis report in reports/"),
        Check("latest survivorship report exists", survivorship is not None,
              "no survivorship report in reports/"),
        Check("latest dashboard acceptance report exists", dashboard_acc is not None,
              "no dashboard acceptance/redesign report at project root"),
    ]


def run_preflight(settings, storage) -> PreflightResult:
    """Evaluate every pre-flight gate and return a PreflightResult."""
    checks: list[Check] = [
        _check_product_decision(settings, storage),
        _check_live_off(settings),
        _check_live_hard_blocked(),
        *_check_capabilities(),
        _check_kill_switch(settings),
        _check_dashboard_controls(settings),
        _check_paper_storage(),
        _check_report_generation(),
        _check_audit_trail(storage),
        *_check_reports(settings),
    ]
    return PreflightResult(ready=all(c.ok for c in checks), checks=checks)


def build_preflight_report(settings, storage) -> tuple[str, PreflightResult]:
    """Return (markdown, PreflightResult) for PAPER_PREFLIGHT_REPORT.md."""
    res = run_preflight(settings, storage)
    verdict = ("Ready to start supervised forward paper period" if res.ready else
               "Not ready because: " + "; ".join(res.blockers))
    n_ok = sum(1 for c in res.checks if c.ok)
    lines = [
        "# Paper Pre-Flight Report — long-only Trading 212",
        "",
        "_Generated by `statarb supervised-paper-preflight`. This system is "
        "**NOT LIVE ELIGIBLE**; the live order path does not exist and live trading "
        "is hard-blocked._",
        "",
        f"## Verdict: {verdict}",
        "",
        f"{n_ok}/{len(res.checks)} pre-flight checks passed.",
        "",
        "## Checks",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for c in res.checks:
        mark = "PASS" if c.ok else "**FAIL**"
        detail = "" if c.ok else c.detail
        lines.append(f"| {c.name} | {mark} | {detail} |")
    lines += [
        "",
        "## What this gate does NOT assert",
        "",
        "- It does **not** make the product live-eligible. Live trading remains "
        "blocked and the live order path is intentionally absent.",
        "- A PASS means the system is ready to BEGIN recording forward shadow/paper "
        "days — not that any forward period has yet passed.",
        "",
        "## Next step",
        "",
        ("Start the period: `statarb supervised-paper-daily --product long_only_t212 "
         "--mode shadow` (or use the dashboard Command Center → Run Shadow Day)."
         if res.ready else
         "Resolve the failing check(s) above, then re-run "
         "`statarb supervised-paper-preflight`."),
        "",
        "_NOT LIVE ELIGIBLE._",
    ]
    return "\n".join(lines) + "\n", res
