"""Shorting risk model (Path C).

Risks unique to the short leg of a market-neutral equity book — the ones the
long-only model never faced and the blended cost model under-counts:

* **No-locate / not-shortable** — you cannot short what you cannot borrow.
* **Short-sale restriction (SSR / Reg SHO uptick)** — when active you may only
  short at or above the best bid, so a market short can be rejected.
* **Hard-to-borrow concentration** — HTB names carry punitive borrow fees and
  buy-in (recall) risk; a book stacked into HTB shorts is fragile.
* **Short squeeze / buy-in** — a recalled borrow forces a market buy-in at the
  worst possible time. Capped by limiting per-name and HTB exposure.

This module screens a proposed short book against borrow/shortability data
(from a `MarginEquityBrokerBase`) and returns the feasible, de-risked book plus
the reasons anything was cut.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.brokers.margin_equity.models import BorrowQuote, ShortabilityStatus


@dataclass
class ShortingConstraints:
    max_short_per_name: float = 0.05       # |weight| cap per short name
    max_htb_gross: float = 0.20            # total gross in hard-to-borrow names
    max_borrow_rate_bps: float = 2000.0    # refuse shorts above this borrow fee (20%/yr)
    require_locate: bool = True


@dataclass
class ShortScreenResult:
    weights: pd.Series                     # feasible short weights (<= 0)
    cut: list[tuple[str, str]] = field(default_factory=list)   # (symbol, reason)
    htb_gross: float = 0.0
    est_borrow_cost_bps_annual: float = 0.0   # book-weighted borrow cost


def screen_short_book(
    weights: pd.Series,
    borrow: dict[str, BorrowQuote],
    shortability: dict[str, ShortabilityStatus],
    constraints: ShortingConstraints | None = None,
) -> ShortScreenResult:
    """Project the short leg onto the feasible set given borrow/shortability.

    `weights` may contain longs (>=0, passed through untouched) and shorts (<0).
    Each short is checked for shortability, locate, borrow availability and
    borrow cost; survivors are capped per-name and the HTB bucket is capped."""
    c = constraints or ShortingConstraints()
    out = weights.copy()
    cut: list[tuple[str, str]] = []
    htb_names: list[str] = []
    cost_num = 0.0
    cost_den = 0.0

    for sym, w in weights.items():
        if w >= 0:
            continue                       # longs are not a shorting risk
        status = shortability.get(sym)
        quote = borrow.get(sym)
        if status is None or not status.shortable or quote is None or not quote.shortable:
            out[sym] = 0.0
            cut.append((sym, "not shortable / no borrow inventory"))
            continue
        if c.require_locate and quote.locate_required and quote.available_shares <= 0:
            out[sym] = 0.0
            cut.append((sym, "locate required, none available"))
            continue
        if quote.borrow_rate_bps_annual > c.max_borrow_rate_bps:
            out[sym] = 0.0
            cut.append((sym, f"borrow {quote.borrow_rate_bps_annual:.0f}bps "
                             f"> cap {c.max_borrow_rate_bps:.0f}bps"))
            continue
        if abs(out[sym]) > c.max_short_per_name:      # per-name cap
            out[sym] = -c.max_short_per_name
            cut.append((sym, f"capped to {c.max_short_per_name:.0%}"))
        if quote.is_hard_to_borrow:
            htb_names.append(sym)
        cost_num += abs(out[sym]) * quote.borrow_rate_bps_annual
        cost_den += abs(out[sym])

    # cap aggregate hard-to-borrow gross
    htb_gross = float(out[htb_names].abs().sum()) if htb_names else 0.0
    if htb_gross > c.max_htb_gross > 0:
        scale = c.max_htb_gross / htb_gross
        out[htb_names] = out[htb_names] * scale
        cut.append(("<HTB bucket>", f"scaled HTB shorts to {c.max_htb_gross:.0%} gross"))
        htb_gross = c.max_htb_gross

    return ShortScreenResult(
        weights=out, cut=cut, htb_gross=round(htb_gross, 4),
        est_borrow_cost_bps_annual=round(cost_num / cost_den, 1) if cost_den else 0.0,
    )
