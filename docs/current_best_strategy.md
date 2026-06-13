# Current best strategy (honest, re-validated)

**As of 2026-06-13, after the institutional audit and the Phase 2-5 fixes.**

The current best *research* strategy is the daily equity ensemble
**`xsec_momentum + tsmom + momentum-neutral ml_alpha`** on `us_stocks_50`,
inverse-vol allocated with a trailing-t-stat gate. It is **not** live-eligible
and is **not** market-neutral-tradable on any connected venue.

> **⚠️ Update (2026-06-13, tradable-product engagement).** This market-neutral
> book is now a **research candidate only** for two reasons: (1) no connected
> venue can short it, and (2) deflated against the **true ~45-config trial
> search** (Phase 2 backfill), its Sharpe sits *below* the expected maximum of
> 45 noise strategies — **P(true Sharpe > noise-max) = 0.375, so it FAILS the
> deflated-Sharpe gate**. Treat it as unproven, not as an edge. The **tradable
> lead candidate is now the long-only Trading 212 book**
> ([`long_only_trading212_strategy.md`](long_only_trading212_strategy.md)),
> which beats SPY/QQQ risk-adjusted with positive alpha. See
> [`../TRADABLE_PRODUCT_REPORT.md`](../TRADABLE_PRODUCT_REPORT.md) and
> `statarb product-decision`.

## The numbers that matter (net of modeled costs)

All figures: daily bars, 2021-06 → 2026-06, **total-return (dividend-adjusted)
prices, next-open fills, 75 bps annual short borrow** — i.e. the honest cost
stack the audit added, not the legacy one.

| metric | legacy README claim | re-stated (this build) |
| --- | --- | --- |
| total return (1x) | +48.5% | **+35.3%** |
| Sharpe (1x) | 1.34 | **1.02** |
| max drawdown (1x) | −7.1% | **−10.1%** |
| OOS walk-forward Sharpe | (none existed) | **0.97** (degradation 0.14, 3/3 folds positive) |

The ~0.3 Sharpe and ~13pp return that disappeared are the audit's predicted
inflation: same-close fills (W-03), dividend-blind prices (W-05) and
frictionless shorts (W-07). What remains is still a real, economically-grounded
result — but it is a Sharpe-~1 book, not a Sharpe-1.34 one.

## What it survives, and what it does not

Stress suite (`statarb validate-ensemble`):

| scenario | return | Sharpe | verdict |
| --- | --- | --- | --- |
| base | +35.3% | 1.02 | — |
| costs ×2 | +22.5% | 0.70 | survives |
| costs ×3 | +10.9% | 0.38 | survives (thin) |
| borrow ×3 | +33.0% | 0.96 | borrow is not the binding cost |
| same-close fill | +34.8% | 1.01 | timing optimism is small (good — not an overnight-harvest signal) |
| next-open + 1-bar delay | +30.9% | 0.91 | survives |

**It FAILS two acceptance gates:**

1. **Return concentration** — one month accounts for **30.3%** of total PnL
   (limit 25%), and the best 5% of days account for **>100%** of total return
   (the median day loses). The edge is event-concentrated; that is fragile.
2. **Deflated Sharpe is not yet truly deflated** — the deflated-Sharpe check
   *passes* (P(true>benchmark)=0.976), but only **1 trial** is recorded in the
   experiment registry. The ~40-60 historical configurations from
   `docs/strategy_research.md` were run before the tracker existed and are not
   counted. Until they are back-filled (or the family is re-explored under the
   tracker), the deflation is a formality, not a correction. **This is the
   single most important open caveat.**

## Allocator

Tested `equal / inverse_vol / erc / hrp` on the same window
(`statarb compare-allocators`):

| mode | Sharpe |
| --- | --- |
| equal | 1.053 |
| **inverse_vol (default)** | **1.020** |
| erc | 0.986 |
| hrp | 0.921 |

The newer covariance-aware allocators (ERC, HRP) **did not beat** inverse-vol
on this window, so per the acceptance criteria they remain opt-in and the
default is unchanged. Equal-weight edged inverse-vol, but inside noise and
without OOS confirmation — not a basis to change the default.

## Capacity

`statarb capacity-report --strategy xsec_momentum`: net Sharpe holds to
**$50M+** before square-root impact erodes 20% of it (mega-cap ADV is huge).
Capacity is *not* the binding constraint at any retail or small-fund size.
Bottleneck names: UPS, NKE, ADBE, QCOM, META.

## Tradability (the hard wall)

The book is ~50% short. **No connected venue can hold it:** Trading 212
Invest/ISA cannot short, Binance spot cannot short, Binance futures is not
connected. Therefore:

- it is **paper/research only**, and only as a research artifact (the paper
  trader simulates the shorts);
- a **long-only variant** is executable on T212 but is a *different strategy*
  with different (directional) risk and must be validated separately before it
  means anything.

## Verdict

Registry status: **`backtest`**. To advance it must (a) pass the concentration
gate or have the concentration explained and bounded, (b) have its trial family
back-filled so the deflated Sharpe is real, (c) acquire an executable shorting
venue (or be replaced by a validated long-only variant). Until then the honest
recommendation is **do not trade it** — see
[`FINAL_RESEARCH_REPORT.md`](../FINAL_RESEARCH_REPORT.md).
