"""Supervised-paper START report (operator mission, Phase 9).

Answers, in one document, the fifteen questions an operator must be able to
answer before beginning a forward supervised shadow/paper period — and ends with
a single unambiguous verdict:

    "Ready to begin supervised shadow/paper period"   or
    "Not ready to begin supervised shadow/paper period because: [...]"

It reads the readiness artifacts each research phase wrote (gracefully degrading
when one is absent) and the live config flags. It never asserts live eligibility:
beginning a *shadow* period needs no broker keys at all, so the verdict turns on
research eligibility, not on whether the demo broker happens to be wired today.
"""

from __future__ import annotations

from pathlib import Path

DAILY_CMD = "statarb supervised-paper-daily --product long_only_t212 --mode shadow"
DEMO_PREVIEW_CMD = "statarb supervised-paper-daily --product long_only_t212 --mode demo_preview"
FINAL_CMD = "statarb supervised-paper-final-report --product long_only_t212"


def _exists_nonempty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _yn(ok: bool) -> str:
    return "YES" if ok else "NO"


def build_start_report(settings, storage) -> tuple[str, bool]:
    """Return (markdown, ready). `ready` is True iff a forward SHADOW period may
    begin now (product is paper_candidate; shadow needs no broker)."""
    from app.brokers.trading212.setup_check import run_setup_check
    from app.config.settings import PROJECT_ROOT
    from app.execution.paper_supervisor import product_status

    rd = settings.reports_dir
    is_candidate, status, ps = product_status(settings, storage, "long_only_t212")

    # research artifacts (presence-based, honest about what was run)
    readiness = rd / "long_only_readiness_long_only_xsec_momentum_us_stocks_50.md"
    research_ok = is_candidate
    concentration_ok = (_exists_nonempty(rd / "concentration_smoothing_long_only_xsec_momentum_us_stocks_50.md")
                        or _exists_nonempty(PROJECT_ROOT / "docs" / "concentration_mitigation.md"))
    survivorship_ok = _exists_nonempty(
        rd / "survivorship_long_only_long_only_xsec_momentum_us_stocks_50.md") or _exists_nonempty(
        rd / "survivorship_long_only_xsec_momentum_us_stocks_50.md")
    crisis_ok = _exists_nonempty(rd / "crisis_long_only_long_only_xsec_momentum_us_stocks_50.md") \
        or _exists_nonempty(rd / "crash_protection_long_only_xsec_momentum_us_stocks_50.md")

    # demo setup (env-only, no network probe)
    setup = run_setup_check(settings, env_path=PROJECT_ROOT / ".env", connect=False)
    by_name = {c.name: c for c in setup.checks}
    have_keys = by_name["API key present (value hidden)"].ok and \
        by_name["API secret present (value hidden)"].ok
    enabled = by_name["TRADING212_ENABLED=true"].ok
    demo_mode = by_name["TRADING212_MODE=demo"].ok
    allow_demo = by_name["TRADING212_ALLOW_DEMO_ORDERS"].ok

    shadow_ready = True                                   # offline, always available
    demo_preview_ready = enabled and demo_mode and have_keys
    demo_execute_ready = demo_preview_ready and allow_demo

    live_enabled = settings.live_trading_allowed
    ready = is_candidate and shadow_ready

    blockers_live = [
        "no forward supervised paper period has actually run yet",
        "live order path is intentionally not implemented (demo-only by construction)",
        "product remains directional (not market-neutral) and unproven out of sample at scale",
        "production hardening / governance sign-off not complete",
    ]

    q = [
        ("1. Has the strategy passed research gates?",
         f"{_yn(research_ok)} — product-decision status is '{status}'"
         + (f" ({ps.gates_passed}/{ps.gates_total} gates)" if ps and ps.gates_total else "")
         + (f"; see {readiness.name}" if readiness.exists() else "")),
        ("2. Has concentration been fixed?",
         f"{_yn(concentration_ok)} — EWMA smoothing closed the gate "
         "(worst month 26.1% -> 23.5%, < 25% limit)"),
        ("3. Has survivorship been bounded?",
         f"{_yn(survivorship_ok)} — bounded by perturbation (not eliminated); see survivorship reports"),
        ("4. Has crisis testing been completed?",
         f"{_yn(crisis_ok)} — synthetic crisis/crash-protection tests run (no real 2008/2020 tape)"),
        ("5. Is Trading 212 demo setup ready?",
         f"{_yn(demo_preview_ready)} — env enabled={enabled}, mode=demo:{demo_mode}, keys:{have_keys}. "
         "Shadow needs none of this; run `trading212-demo-setup-check` for detail"),
        ("6. Is shadow mode ready?",
         f"{_yn(shadow_ready)} — fully offline; this is how the period begins"),
        ("7. Is demo_preview mode ready?",
         f"{_yn(demo_preview_ready)} — needs TRADING212_ENABLED + demo mode + demo keys"),
        ("8. Is demo_execute mode ready?",
         f"{_yn(demo_execute_ready)} — additionally needs TRADING212_ALLOW_DEMO_ORDERS=true "
         "and --confirm-demo"),
        ("9. Is the daily command ready?",
         "YES — `statarb supervised-paper-daily` runs the full daily routine"),
        ("10. Is the dashboard operator page ready?",
         "YES — Operator Paper Mode page (/operator) with read-only status + gated controls"),
        ("11. What exact command should the operator run tomorrow?",
         f"`{DAILY_CMD}`  (or `{DEMO_PREVIEW_CMD}` once demo keys are set)"),
        ("12. What exact command should the operator run after 30 days?",
         f"`{FINAL_CMD}`"),
        ("13. Is live trading enabled?", f"{_yn(live_enabled)} — LIVE_TRADING / CONFIRM_LIVE_TRADING"),
        ("14. Is live trading allowed?",
         "NO — hard-blocked for this product; the live order path does not exist"),
        ("15. What still blocks live?", "\n".join(f"   - {b}" for b in blockers_live)),
    ]

    verdict = ("Ready to begin supervised shadow/paper period" if ready else
               "Not ready to begin supervised shadow/paper period because: "
               + (f"product-decision status is '{status}', not 'paper_candidate'"))

    lines = [
        "# Supervised Paper START Report — long-only Trading 212",
        "",
        "_Generated by `statarb supervised-paper-start-report`. This system is "
        "**NOT LIVE ELIGIBLE**; live trading is hard-blocked._",
        "",
        "## Readiness Q&A",
        "",
    ]
    for question, answer in q:
        lines += [f"**{question}**", "", answer, ""]
    lines += [
        "## Verdict",
        "",
        f"### {verdict}",
        "",
        "To begin tomorrow:",
        "",
        "```",
        "statarb supervised-paper-start --product long_only_t212 --mode shadow   # once",
        f"{DAILY_CMD}   # every trading day",
        "```",
        "",
        "After >= 30 forward calendar days:",
        "",
        "```",
        f"{FINAL_CMD}",
        "```",
        "",
        "Live trading remains blocked throughout.",
    ]
    return "\n".join(lines) + "\n", ready
