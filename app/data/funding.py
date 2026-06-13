"""Funding-rate panels for a crypto-futures universe (Path B).

Thin builder over `BinanceFundingRates` (public REST) that assembles a wide
funding-rate panel (index = 8h funding timestamps, columns = perp symbols) for a
whole universe, plus annualization helpers. Research only — no account.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.core.logging import get_logger
from app.data.providers_binance_futures import BinanceFundingRates

log = get_logger(__name__)

PERIODS_PER_YEAR = 3 * 365.0          # 8h funding periods, 24/7


def build_funding_panel(symbols: list[str], start: datetime, end: datetime,
                        client: BinanceFundingRates | None = None) -> pd.DataFrame:
    """Wide funding-rate panel for `symbols`. Missing symbols are skipped."""
    client = client or BinanceFundingRates()
    panels: dict[str, pd.Series] = {}
    for sym in symbols:
        df = client.fetch_funding(sym, start, end)
        if df.empty:
            log.warning("no funding history for %s — skipped", sym)
            continue
        panels[sym] = df.set_index("ts")["funding_rate"]
    if not panels:
        return pd.DataFrame()
    return pd.DataFrame(panels).sort_index()


def annualized_funding(panel: pd.DataFrame) -> pd.Series:
    """Mean annualized funding APR per symbol over the panel."""
    return (panel.mean() * PERIODS_PER_YEAR).sort_values(ascending=False)


def funding_summary(panel: pd.DataFrame) -> pd.DataFrame:
    """Per-symbol funding stats: mean APR, volatility, % of periods positive."""
    if panel.empty:
        return pd.DataFrame()
    return pd.DataFrame({
        "apr_pct": (panel.mean() * PERIODS_PER_YEAR * 100).round(2),
        "apr_vol_pct": (panel.std() * PERIODS_PER_YEAR * 100).round(2),
        "pct_periods_positive": (100 * (panel > 0).mean()).round(1),
        "n_periods": panel.notna().sum(),
    }).sort_values("apr_pct", ascending=False)
