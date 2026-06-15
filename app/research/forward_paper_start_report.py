"""FORWARD_PAPER_START_REPORT.md — the final deliverable (Phase 11).

Confirms whether the forward supervised paper period is actually running, reads
the live session state, restates exactly what the operator does next, and ends
with one of two verdicts:

    A. "Forward supervised paper period started successfully."
    B. "Forward supervised paper period not started because: [...]"

Dashboard theme support is reported truthfully by detecting the theme module on
disk rather than asserting it. Live is never in scope and is restated as blocked.
"""

from __future__ import annotations

PRODUCT = "long_only_t212"
DAILY_PAGE = "Command Center (and the Supervised Paper page for detail)"
RECOMMENDED_DAYS = 90


def _yn(ok: bool) -> str:
    return "YES" if ok else "NO"


def _theme_support() -> dict[str, bool]:
    """Detect theme support by presence of the theme module + tokens."""
    from app.config.settings import PROJECT_ROOT
    fe = PROJECT_ROOT / "frontend" / "src"
    provider = (fe / "theme" / "ThemeProvider.tsx").exists()
    toggle = (fe / "components" / "ui" / "ThemeToggle.tsx").exists()
    css = fe / "index.css"
    has_light = css.exists() and ".light" in css.read_text(encoding="utf-8")
    # dark mode has always existed; light + system arrive with the theme module
    return {"dark": True, "light": bool(provider and has_light),
            "system": bool(provider and toggle)}


def build_forward_start_report(settings, storage) -> tuple[str, bool]:
    """Return (markdown, started)."""
    from app.execution.paper_supervisor import health_for
    from app.execution.supervised_paper import SupervisedPaperStore
    from app.research.paper_preflight import run_preflight

    store = SupervisedPaperStore(settings.runtime_dir, PRODUCT)
    session = store.current_session()
    h = health_for(settings, storage, product=PRODUCT)
    pre = run_preflight(settings, storage)
    theme = _theme_support()

    started = bool(session and session.status == "active"
                   and h.get("forward_days_completed", 0) >= 1)
    mode = session.mode if session else "—"
    session_id = session.session_id if session else "—"
    min_days = h.get("min_days", session.min_days if session else 30)
    live_enabled = settings.live_trading_allowed

    stop_pause = [
        "live trading becomes enabled (terminal)",
        "kill switch activates (pause)",
        "product stops being paper_candidate (terminal)",
        "data becomes stale / unreliable (pause)",
        "paper drawdown breaches policy (pause) or the hard limit (terminal)",
        "concentration breaches the 25% limit (pause)",
        "TCA slippage far worse than expected (pause)",
        "repeated demo broker errors (pause)",
        "a short position or smoothing-constraint breach is detected (terminal)",
    ]
    evidence = [
        "daily reports (equity, exposure, drawdown, holdings, smoothing checks)",
        "planned + refused orders", "reconciliations (drift, short-position guard)",
        "TCA (expected vs realised slippage, fees)", "risk snapshots (breach flags)",
        "benchmark snapshots (SPY equity)", "weekly review reports",
    ]

    q = [
        ("Is the supervised forward paper period started?",
         f"{_yn(started)} — session status '{(session.status if session else 'none')}', "
         f"{h.get('forward_days_completed', 0)} forward day(s) recorded"),
        ("What mode is it running in?", mode),
        ("What is the session ID?", session_id),
        ("What is the minimum required duration?", f"{min_days} forward trading days"),
        ("What is the recommended duration?", f"{RECOMMENDED_DAYS} forward trading days"),
        ("What should the operator do tomorrow?",
         "Open the dashboard Command Center, read Today's Action, and click "
         "**Run Shadow Day** (or Run Demo Preview once demo keys are set)."),
        ("What dashboard page should be opened daily?", DAILY_PAGE),
        ("What automatically stops or pauses the session?",
         "\n".join(f"   - {s}" for s in stop_pause)),
        ("What evidence is being collected?", "\n".join(f"   - {e}" for e in evidence)),
        ("What is required before the 30-day final review?",
         f"At least {min_days} distinct FORWARD trading days recorded (replay days "
         "never count) and no terminal stop rule fired."),
        ("Does the dashboard support dark mode?", _yn(theme["dark"])),
        ("Does the dashboard support light mode?", _yn(theme["light"])),
        ("Does the dashboard support system theme preference?", _yn(theme["system"])),
        ("Is live trading enabled?", f"{_yn(live_enabled)} — LIVE_TRADING/CONFIRM_LIVE_TRADING"),
        ("Is live trading allowed?",
         "NO — hard-blocked for this product; the live order path does not exist."),
    ]

    if started:
        verdict = "Forward supervised paper period started successfully."
    else:
        reason = ("pre-flight not ready: " + "; ".join(pre.blockers)) if not pre.ready else (
            "no active session with a recorded forward day yet — run "
            "`statarb supervised-paper-daily --product long_only_t212 --mode shadow`")
        verdict = f"Forward supervised paper period not started because: {reason}"

    lines = [
        "# Forward Paper START Report — long-only Trading 212",
        "",
        "_Generated by `statarb forward-paper-start-report`. This system is "
        "**NOT LIVE ELIGIBLE**; live trading is hard-blocked and the live order "
        "path does not exist._",
        "",
        "## Status Q&A",
        "",
    ]
    for question, answer in q:
        lines += [f"**{question}**", "", answer, ""]
    lines += [
        "## Final verdict",
        "",
        f"### {'A' if started else 'B'}. {verdict}",
        "",
        "Live trading remains blocked throughout this period. This phase collects "
        "real forward evidence; it does not trade real capital.",
        "",
        "_NOT LIVE ELIGIBLE._",
    ]
    return "\n".join(lines) + "\n", started
