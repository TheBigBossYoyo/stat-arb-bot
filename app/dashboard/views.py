"""Server-side HTML helpers for the dashboard index page."""

from __future__ import annotations

from typing import Any


def live_banner(live_enabled: bool) -> str:
    if live_enabled:
        return (
            "<div style='background:#c00;color:#fff;padding:12px;font-weight:bold'>"
            "⚠ LIVE TRADING ENABLED — REAL MONEY AT RISK</div>"
        )
    return (
        "<div style='background:#2a6;color:#fff;padding:12px'>"
        "Paper / backtest mode — no real orders</div>"
    )


def html_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "<p>(none)</p>"
    columns = list(rows[0].keys())
    head = "".join(f"<th>{c}</th>" for c in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{row.get(c, '')}</td>" for c in columns) + "</tr>"
        for row in rows
    )
    return f"<table><tr>{head}</tr>{body}</table>"
