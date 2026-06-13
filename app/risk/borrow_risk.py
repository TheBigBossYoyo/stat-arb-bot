"""Per-name borrow-cost model (Path C).

The audit (W-cost) flagged that the flagship charges a single blended 75 bps/yr
borrow on the whole short notional, while in reality borrow is per-name and
heavily right-skewed: general-collateral (GC) names cost a few bps, but the
hard-to-borrow momentum *losers* — exactly the short decile a momentum book
holds — can cost hundreds to thousands of bps. A blended rate flatters precisely
the names a momentum short book is most exposed to.

This module turns a borrow-tier schedule into a per-name annual cost and a
per-asset cost vector the basket engine can charge (`per_asset_cost_bps`), and
estimates the borrow-cost drag a short book actually pays. It needs only a
classification of each short name into a tier (GC / moderate / hard / special),
which a `MarginEquityBrokerBase.get_borrow_quote` supplies live, or a static
schedule supplies for stress testing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# Indicative 2026 retail borrow tiers (annualized bps on short notional).
DEFAULT_BORROW_TIERS: dict[str, float] = {
    "gc": 30.0,            # general collateral: large, liquid, easy to borrow
    "moderate": 150.0,
    "hard": 600.0,         # hard-to-borrow
    "special": 3000.0,     # on special / very hard to borrow
}


@dataclass
class BorrowCostResult:
    per_name_bps: dict[str, float]         # annual borrow bps per short name
    blended_bps_annual: float              # notional-weighted average
    worst_name: str | None
    worst_bps: float
    tiers_used: dict[str, str] = field(default_factory=dict)

    def cost_drag_pct_annual(self, short_gross: float) -> float:
        """Annual borrow-cost drag (% of equity) for a book with `short_gross`
        short exposure (fraction of equity)."""
        return round(self.blended_bps_annual / 100.0 * short_gross, 3)


def borrow_cost_for_book(
    weights: pd.Series,
    tier_of: dict[str, str],
    tiers: dict[str, float] | None = None,
) -> BorrowCostResult:
    """Compute per-name and blended borrow cost for the short leg of `weights`.

    `tier_of` maps each short symbol to a tier key ('gc'|'moderate'|'hard'|
    'special'); names absent default to GC. Only short legs (weight < 0) pay."""
    schedule = tiers or DEFAULT_BORROW_TIERS
    shorts = weights[weights < 0]
    per_name: dict[str, float] = {}
    tiers_used: dict[str, str] = {}
    num = den = 0.0
    worst_name, worst_bps = None, 0.0
    for sym, w in shorts.items():
        tier = tier_of.get(sym, "gc")
        bps = schedule.get(tier, schedule["gc"])
        per_name[sym] = bps
        tiers_used[sym] = tier
        notional = abs(float(w))
        num += notional * bps
        den += notional
        if bps > worst_bps:
            worst_name, worst_bps = sym, bps
    return BorrowCostResult(
        per_name_bps=per_name,
        blended_bps_annual=round(num / den, 1) if den else 0.0,
        worst_name=worst_name, worst_bps=worst_bps, tiers_used=tiers_used,
    )


def per_asset_cost_bps(
    weights: pd.Series,
    tier_of: dict[str, str],
    base_trade_bps: float,
    bars_per_year: float,
    tiers: dict[str, float] | None = None,
) -> dict[str, float]:
    """Build a `per_asset_cost_bps` dict for the basket engine that folds the
    PER-BAR borrow cost into each short name's trade cost. Long names keep the
    base trading cost; shorts add their tier borrow rate amortized per bar.

    This lets a backtest charge realistic, name-specific borrow instead of a
    flat blended rate — the honest fix for the audit's cost concern."""
    schedule = tiers or DEFAULT_BORROW_TIERS
    out: dict[str, float] = {}
    for sym, w in weights.items():
        cost = base_trade_bps
        if w < 0 and bars_per_year > 0:
            tier = tier_of.get(sym, "gc")
            cost += schedule.get(tier, schedule["gc"]) / bars_per_year
        out[sym] = cost
    return out


def momentum_loser_tiers(short_symbols: list[str], hard_fraction: float = 0.4) -> dict[str, str]:
    """Stress assumption: a momentum short book is disproportionately hard-to-
    borrow (it shorts beaten-down names). Classifies the worst `hard_fraction`
    of the given shorts as 'hard'/'special' for a conservative borrow stress."""
    n = len(short_symbols)
    n_hard = int(n * hard_fraction)
    tiers: dict[str, str] = {}
    for i, sym in enumerate(short_symbols):
        if i < n_hard // 2:
            tiers[sym] = "special"
        elif i < n_hard:
            tiers[sym] = "hard"
        else:
            tiers[sym] = "gc"
    return tiers
