"""Local paper-period reminder (Phase 9).

A small, offline nudge for the operator: does today need a paper run, in which
mode, are there alerts to review, and is a weekly/final report due. It writes a
plain-text file (`runtime/paper/reminder.txt`) so a local scheduler (Windows Task
Scheduler / cron) can surface it — no external messaging is performed. Live is
never in scope.
"""

from __future__ import annotations

from pathlib import Path

from app.core.types import utc_now

PRODUCT = "long_only_t212"
REMINDER_NAME = "reminder.txt"


def build_reminder(settings, storage, *, product: str = PRODUCT, min_days: int = 30) -> dict:
    """Return a structured reminder derived from the monitoring engine."""
    from app.research.paper_monitor import run_monitor

    res = run_monitor(settings, storage, product=product, min_days=min_days,
                      persist=False).as_dict()
    if not res["active"]:
        return {
            "product": product, "generated_at": utc_now().replace(tzinfo=None).isoformat(),
            "headline": "No active paper session — start one to begin the forward period.",
            "needs_attention": True, "needs_run_today": False, "mode": None,
            "lines": ["Run `statarb supervised-paper-start --product long_only_t212 --mode shadow`."],
            "live_eligible": False,
        }

    met = res["metrics"]
    counts = res["alert_counts"]
    ran_today = bool(met.get("ran_today"))
    final_ready = bool(met.get("can_generate_final_report"))
    needs_run = not ran_today and not final_ready
    mode = met.get("mode", "shadow")

    lines: list[str] = []
    if needs_run:
        lines.append(f"Run today's paper day in {mode} mode "
                     f"(`statarb supervised-paper-daily --product {product} --mode {mode}`) "
                     "or use the dashboard Command Center → Run Shadow Day.")
    elif ran_today:
        lines.append(f"Today's paper day ({met.get('last_run_date')}) is already recorded.")
    if counts["critical"]:
        lines.append(f"{counts['critical']} CRITICAL alert(s) need attention — open Paper Monitoring.")
    if counts["warning"]:
        lines.append(f"{counts['warning']} warning alert(s) to review.")
    if met.get("weekly_due"):
        lines.append("A weekly review report is due "
                     "(`statarb supervised-paper-weekly-report`).")
    if final_ready:
        lines.append(f"The final review is available ({met.get('forward_days_completed')} "
                     f"forward days >= {min_days}) — generate the final report. NOT live-eligible.")
    if not lines:
        lines.append("Nothing to do today — the session is healthy and up to date.")

    needs_attention = needs_run or counts["critical"] > 0 or counts["warning"] > 0 \
        or bool(met.get("weekly_due"))
    if counts["critical"]:
        headline = f"ACTION NEEDED: {counts['critical']} critical alert(s) on the paper session."
    elif needs_run:
        headline = f"Today needs a paper run ({mode} mode)."
    elif met.get("weekly_due"):
        headline = "Weekly review report is due."
    elif final_ready:
        headline = "Final review available (still NOT live-eligible)."
    else:
        headline = "All caught up — no paper action needed today."

    return {
        "product": product, "generated_at": res["generated_at"],
        "headline": headline, "needs_attention": needs_attention,
        "needs_run_today": needs_run, "mode": mode,
        "health_score": res["health_score"]["score"],
        "classification": res["health_score"]["classification"],
        "alert_counts": counts, "weekly_due": bool(met.get("weekly_due")),
        "final_review_ready": final_ready, "next_expected_run": met.get("next_expected_run"),
        "lines": lines, "live_eligible": False,
    }


def render_reminder(rem: dict) -> str:
    ts = rem.get("generated_at", "")
    body = [
        "STAT-ARB PAPER REMINDER",
        f"generated: {ts}",
        f"product: {rem.get('product')}",
        "",
        rem["headline"],
        "",
        *[f"- {line}" for line in rem["lines"]],
        "",
        f"health: {rem.get('health_score', '?')}/100 ({rem.get('classification', '?')})",
        "NOT LIVE ELIGIBLE — paper/shadow only.",
    ]
    return "\n".join(body) + "\n"


def write_reminder_file(settings, rem: dict) -> Path:
    out = Path(settings.runtime_dir) / "paper" / REMINDER_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_reminder(rem), encoding="utf-8")
    return out
