"""Plotly chart builders for reports and the dashboard (optional extra).

All functions degrade gracefully: if plotly is not installed they raise a
clear RuntimeError instead of failing at import time.
"""

from __future__ import annotations

import pandas as pd


def _plotly():
    try:
        import plotly.graph_objects as go
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pip install -e '.[dashboard]' for charts (plotly)") from exc
    return go


def equity_curve_figure(equity: pd.Series, title: str = "Equity"):
    go = _plotly()
    fig = go.Figure(go.Scatter(x=equity.index, y=equity.values, mode="lines", name="equity"))
    fig.update_layout(title=title, xaxis_title="time", yaxis_title="equity")
    return fig


def drawdown_figure(equity: pd.Series, title: str = "Drawdown"):
    go = _plotly()
    drawdown = equity / equity.cummax() - 1.0
    fig = go.Figure(go.Scatter(x=drawdown.index, y=drawdown.values,
                               fill="tozeroy", mode="lines", name="drawdown"))
    fig.update_layout(title=title, yaxis_tickformat=".1%")
    return fig


def zscore_figure(zscores: pd.Series, entry_z: float = 2.0, exit_z: float = 0.3,
                  title: str = "Spread z-score"):
    go = _plotly()
    fig = go.Figure(go.Scatter(x=zscores.index, y=zscores.values, mode="lines", name="z"))
    for level, dash in ((entry_z, "dash"), (-entry_z, "dash"), (exit_z, "dot"), (-exit_z, "dot")):
        fig.add_hline(y=level, line_dash=dash)
    fig.update_layout(title=title)
    return fig
