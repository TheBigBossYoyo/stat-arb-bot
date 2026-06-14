# Long-only crisis test (Phase 4)

The 2021–2026 research window contains the 2022 bear but **no 2008/2020-scale
crash**. So the long-only book's tail is measured with **synthetic / proxy**
crisis scenarios injected into the historical panel — clearly labeled as
synthetic, never presented as history.

Run: `statarb crisis-test-long-only --strategy long_only_xsec_momentum`
or `statarb crisis-report --product long_only_t212`.

## Scenarios (`app/backtesting/crisis.py :: long_only_scenarios`)

momentum_crash, correlation_spike, vol_spike, market_gap, short_squeeze,
**covid_crash_rebound** (2020-style V), **sustained_bear_2008** (a deep grinding
bear), **vol_whipsaw**, **gap_up_after_crash** (relief rally a de-risked book can
miss), **tech_sector_crash** and **sector_rotation_shock** (sector-targeted).

## Results (certified book: regime ON + EWMA α=0.5)

- **Worst synthetic crisis drawdown: −28%** (vol-whipsaw); base full DD −16.9%.
  Bounded (> −45%) and not catastrophic.
- Momentum crash −19%, COVID crash/rebound −11%, sustained 2008-style bear ~0%
  (the regime filter goes to cash), tech-sector crash −14%.
- Reference (REAL history, not synthetic): SPY max DD −24.5%, QQQ −35.1%. The
  book's base DD (−16.9%) is shallower than both; its worst *synthetic* tail sits
  between them.

## The decisive finding: the regime filter is the crash protection

| variant | base return | worst crisis DD | momentum-crash DD | 2008-bear DD |
|---|---|---|---|---|
| regime ON + EWMA | 257% | **−28%** | −19% | **~0%** |
| regime ON + no smooth | 299% | −29% | −14% | ~0% |
| regime OFF + EWMA | 488% | **−51%** | −23% | −21% |
| regime OFF + no smooth | 485% | −51% | −21% | −19% |

Turning the regime filter **off** roughly doubles the worst crisis drawdown
(−28% → −51%) and exposes the book to the grinding bear (−21%). It is the single
most important defensive component and stays ON by default.

EWMA smoothing **marginally worsens** the momentum-crash drawdown (the sticky
book is slower to exit winners into a reversal) — an honest tradeoff accepted in
exchange for closing the concentration gate. It does not change the verdict.

## Acceptance

- crisis drawdown explainable and bounded — **PASS** (−28%, driven by the
  regime filter's behavior)
- no catastrophic loss beyond risk policy — **PASS**
- crash protection (regime filter) improves the tail without destroying
  normal-regime return — **PASS** (it costs return in calm regimes but the
  default keeps it because the tail protection is decisive)

All scenarios are synthetic; this bounds the tail, it does not prove behavior in
a specific historical crash. That is a reason live remains blocked.
