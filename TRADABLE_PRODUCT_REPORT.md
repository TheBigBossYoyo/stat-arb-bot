# TRADABLE PRODUCT REPORT — stat-arb-bot

**Date:** 2026-06-14 (paper-readiness sprint; supersedes the 2026-06-13 verdict)
**Scope:** the tradable-product engagement — turn the research candidate into a
deployable product across three paths (A long-only equity, B crypto futures,
C margin-broker abstraction) and close the FINAL_RESEARCH_REPORT blockers.

> **One-line verdict:** **No product is live-eligible.** But the **long-only
> Trading 212 book is now ELIGIBLE TO BEGIN a supervised paper/shadow period** —
> EWMA target-weight smoothing closed its one failing gate (return concentration:
> worst month 26.1% → 23.5%) without breaking out-of-sample performance, the
> Trading 212 **demo** order path is wired (live hard-blocked), and the
> survivorship/crisis/paper-workflow gates are complete. See
> `PAPER_ELIGIBILITY_REPORT.md`. The market-neutral flagship is still **not
> tradable** (no shorting venue) and **fails its deflated Sharpe**; crypto futures
> is still testnet/research-only.

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

**Yes — and it is now ELIGIBLE TO BEGIN a supervised paper/shadow period.** It is
a *different, directional* strategy (NOT market-neutral): rank by momentum, buy
the leaders, hold cash instead of shorting.

- `long_only_xsec_momentum` with the validated **EWMA α=0.5** smoothing default:
  **+259%** over 3.8y, **Sharpe 1.44**, max DD −16.9%, turnover 30×/yr. **Beats
  SPY (1.05), QQQ (1.11) and equal-weight (1.33)** risk-adjusted, **+19.6%/yr
  alpha** vs SPY (IR 0.90). Walk-forward OOS Sharpe **1.65, 2/2 folds**. Worst
  month **23.5%** (≤25% PASS). **All 15 research + operational gates pass.**
  (Unsmoothed it was +311% / Sharpe 1.53 / worst month 26.1% — failed only
  concentration; smoothing trades a little headline return for the gate, lower
  turnover and a slightly better drawdown.)
- `long_only_ensemble` (incl. ML): highest **Sharpe** (smoothest) but ~0 alpha vs
  SPY and high cash drag — a low-risk equity sleeve, not an alpha story.

Status: concentration **closed** (Phase 1 EWMA smoothing), survivorship
**bounded** (Phase 3), crisis **tested** (Phase 4, synthetic), T212 **demo order
path wired** (Phase 5), supervised-period **workflow** built (Phase 6). The only
remaining step is operational — **run a real forward supervised period**.
**Verdict: ELIGIBLE TO BEGIN supervised paper/shadow; NOT live-eligible.**

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
| **Easiest to deploy** | **Long-only** — official Invest/ISA API; the DEMO order path is now wired. |
| **Live eligible** | **None.** |
| **Paper first** | **Long-only** — eligible to BEGIN now (concentration gate closed). |

## Remaining blockers

For the long-only product, the research/operational blockers are **closed**; the
remaining items are operational or apply to the other paths:

1. **Run the forward supervised period** — the long-only workflow exists and the
   product is *eligible to begin*; a real 30–90 day FORWARD period has not yet
   run (replay validates the pipeline only). Live stays blocked until it passes.
2. **Survivorship — bounded, not eliminated** for long-only; the edge leans on
   the top winners. Eliminating it needs point-in-time constituent data.
3. **Crisis evidence is synthetic** — no real 2008/2020 tail in the sample.
4. **Crypto futures** still fails concentration; ~0.84y sample (testnet only).
5. **Margin/shorting broker** — none connected (Path C is the interface only), so
   the market-neutral book still has no home.

## What should the operator do next?

1. **DONE this sprint:** EWMA smoothing closed the long-only concentration gate
   (26.1% → 23.5%); survivorship bounded; crisis tested; T212 demo order path
   wired; supervised-period workflow built. `statarb product-decision` now reports
   long-only as **paper_candidate**.
2. **Run a real forward supervised paper period:** `statarb supervised-paper-start
   --product long_only_t212 --mode shadow` once per day for 30–90 days, then
   `supervised-paper-final-report --min-days 30` (see `docs/long_only_t212_paper_plan.md`).
3. (Optional) configure Trading 212 **demo** keys and run the period in
   `demo_preview` / `demo_execute --confirm-demo` (see `docs/trading212_demo_execution.md`).
4. Pursue **point-in-time constituent data** to upgrade survivorship to *eliminated*
   before any live conversation. Keep the market-neutral flagship research-only.
5. Treat crypto futures as a **separate testnet experiment** only after a longer
   sample.

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
