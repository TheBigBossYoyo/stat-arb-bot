# TRADABLE PRODUCT REPORT — stat-arb-bot

**Date:** 2026-06-13
**Scope:** the tradable-product engagement — turn the research candidate into a
deployable product across three paths (A long-only equity, B crypto futures,
C margin-broker abstraction) and close the FINAL_RESEARCH_REPORT blockers.

> **One-line verdict:** **No product is live-eligible, and none is yet
> paper/testnet-eligible.** The honest lead candidate is the **long-only Trading
> 212 book** (closest to a paper period, real venue, lower fundamental risk).
> The original market-neutral flagship is **not tradable** and, corrected for the
> real trial search, **fails its deflated Sharpe** — it is an unproven candidate,
> not an edge.

Run it yourself: `statarb product-decision`.

---

## Is the original market-neutral stock flagship tradable today?

**No — on two independent grounds.**

1. **Venue.** It shorts and levers. No connected venue can host it: Binance spot
   cannot short, Trading 212 Invest/ISA cannot short or use margin, and CFDs /
   unofficial endpoints are out of bounds. Path C defines the interface a real
   margin/shorting broker (IBKR, Alpaca) would implement, but **none is
   connected**.
2. **Statistics.** Back-filling the real ~45-config equity search (Phase 2) and
   deflating against it: **E[max Sharpe] of 45 noise trials ≈ 1.03**, the
   flagship's restated Sharpe is ~0.9–1.0, so **P(true Sharpe > noise-max) =
   0.375 → FAILS** the deflated-Sharpe gate. Bonferroni passes 0/34. It also
   still fails the return-concentration gate (one month ≈ 30% of PnL; the best
   5% of days exceed total return; tech sector = 80%, the xsmom sleeve = 76% of
   PnL). **It is a plausible but unproven research candidate — do not trade it.**

## Is the Trading 212 long-only version viable?

**Yes as a research product, and it is the lead candidate — but not yet
paper-eligible.** It is a *different, directional* strategy (NOT market-neutral):
rank by momentum, buy the leaders, hold cash instead of shorting.

- `long_only_xsec_momentum`: **+311%** over 3.8y, **Sharpe 1.53**, max DD −17%,
  turnover 42×/yr. **Beats SPY (Sharpe 1.05), QQQ (1.11) and equal-weight (1.33)
  on risk-adjusted return**, with **+23%/yr alpha** vs SPY and info ratio ≈ 1.0.
  Walk-forward OOS Sharpe **1.71**. Readiness: **6/7 gates** — fails only
  concentration (worst month 26.1% vs the 25% limit).
- `long_only_ensemble` (incl. ML): highest **Sharpe 1.67** (smoothest) but ~0
  alpha vs SPY and 38% cash drag — a low-risk equity sleeve, not an alpha story.

Blockers: the concentration gate (apply the Phase 1 EWMA-smoothing mitigation),
a supervised paper period, the survivorship caveat, and wiring the T212 demo
order path. **Verdict: NOT YET paper-eligible (6/7).**

## Is the Binance futures crypto version viable?

**Promising but unproven, and high-risk.** Futures *can* short, so the book is
genuinely two-sided, and a testnet path exists.

- `crypto_futures_ensemble` (1x, fees + funding): **+42%** / **Sharpe 1.16**, but
  **44% annualized vol and −27% drawdown** — crypto-native risk that dwarfs the
  equity books. 0 liquidation breaches at 1x (min buffer 0.95). 2nd-half OOS
  Sharpe 1.59. Readiness: **5/6 gates** — fails concentration.
- **The decisive caveat is sample length:** the aligned window is only ~0.84
  years (the youngest perp limits it). That is not enough to call structural.

**Verdict: NOT YET testnet/paper-eligible (5/6), and LIVE BLOCKED unconditionally.**

## Which product path is best / safest / most profitable / easiest?

| question | answer |
|----------|--------|
| **Best overall** | **Long-only Trading 212** — real venue, beats the index risk-adjusted, lowest fundamental risk, closest to a paper period. |
| **Safest** | **Long-only** — no leverage, no shorting, no liquidation; a long book in an ISA. |
| **Most profitable (net)** | `long_only_xsec_momentum` on total return (+311%); crypto has a higher *ceiling* but extreme risk and a tiny sample. |
| **Easiest to deploy** | **Long-only** — Trading 212 has an official Invest/ISA API; only the order path needs wiring. |
| **Live eligible** | **None.** |
| **Paper first** | **Long-only**, once the concentration gate is closed. |

## Remaining blockers

1. **Concentration** — long-only (26.1%) and futures both miss the month-≤25% gate; apply the Phase 1 smoothing mitigation and re-validate.
2. **Supervised paper/shadow period** — not yet run (Phase 5 infra: shadow planners exist; a calendar-time period does not).
3. **Survivorship bias** — `us_stocks_50` / `crypto_top_20` are today's survivors backtested into the past (Phase 3 not yet done).
4. **Crisis-regime test** — no 2008/2020-style crash exercised for the long/futures books (Phase 4 not yet done).
5. **Venue wiring** — T212 demo order path and Binance testnet keys are not wired (shadow planners only).
6. **Margin/shorting broker** — none connected (Path C is the interface only), so the market-neutral book has no home.

## What should the operator do next?

1. Apply the **EWMA-smoothing** concentration mitigation to `long_only_xsec_momentum` and re-run `long-only-readiness` — target 7/7.
2. Resolve/bound **survivorship** (Phase 3) and run a **crisis** test (Phase 4) on the long-only book.
3. Wire the **Trading 212 demo** order path and run a **supervised paper period** (30–90 days) with TCA.
4. Keep the market-neutral flagship in **research only**; do not fund it. Treat Path C as the future home if a real margin broker is integrated via its official API.
5. Treat crypto futures as a **separate, smaller-risk-budget testnet experiment** only after a longer sample is collected.

## What should NOT be traded?

- **Anything, live.** Nothing is live-eligible.
- **The market-neutral flagship** — no venue, fails deflated Sharpe.
- **Crypto futures with real capital** — testnet only; extreme risk, short sample.
- **No CFDs, no shorting on Invest/ISA, no unofficial endpoints — ever.**

## Evidence index

`statarb product-decision` · `long-only-readiness` · `futures-readiness` ·
`deflated-sharpe-report` · `multiple-testing-report` · `concentration-report` ·
`compare-long-only`. Supporting docs: `docs/tradability_matrix.md`,
`docs/live_readiness.md`, `docs/no_live_trading_reason.md`,
`docs/long_only_trading212_strategy.md`, `docs/binance_futures_research.md`,
`docs/margin_equity_broker_requirements.md`.
