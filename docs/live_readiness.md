# Live readiness

## NOT LIVE ELIGIBLE

No product in this repository is eligible for live trading, and none is yet
eligible for a supervised paper/testnet period. This is the deliberate, honest
state — the gates exist precisely to stop a plausible-looking backtest from
reaching real capital.

A product becomes **live-eligible only when ALL of the following hold** (none do
today):

1. A real, **official** broker supports the exact required trades (the
   market-neutral book needs a margin/shorting venue — none is connected).
2. All broker constraints pass (capabilities, locates, margin, market hours).
3. All risk gates pass (leverage, liquidation buffer, kill switch).
4. The **return-concentration** gate passes (no month > 25% of PnL, etc.).
5. **Crisis-regime** tests pass (2008/2020-style; Phase 4).
6. **Multiple-testing** corrections pass (deflated Sharpe vs the true trial
   count — the market-neutral flagship currently **FAILS** this).
7. A **supervised paper/shadow period** (30–90 days) passes with TCA.
8. Execution / TCA shows expected ≈ actual slippage.
9. The `live-trade` gate's every condition is green (it refuses by default).

## Current standings (`statarb product-decision`)

- **long-only equity (Trading 212):** lead candidate. **UPDATE (2026-06-14):**
  EWMA smoothing closed the concentration gate (worst month 26.1% → 23.5%); all
  research gates + operational gates pass. **ELIGIBLE TO BEGIN a supervised
  paper/shadow period** (`paper_candidate`). The DEMO order path is wired
  (demo-only). **Still NOT live-eligible** — no forward paper period has run,
  survivorship is bounded not eliminated, crisis evidence is synthetic.
- **crypto futures (Binance testnet):** **5/6** — fails concentration; LIVE
  BLOCKED unconditionally; ~0.84y sample.
- **market-neutral equity:** DO NOT TRADE — no venue + fails deflated Sharpe.

## The path to the first paper period — DONE; now run it

Phases 1 (smoothing), 3 (survivorship bound), 4 (crisis), 5 (T212 demo order
path) and 6 (supervised-period workflow) are complete. The remaining step is
operational, not code: **actually run** a 30–90 day forward supervised period
(`statarb supervised-paper-start --product long_only_t212 --mode shadow`, daily —
see `docs/long_only_t212_paper_plan.md`). Only after a passed FORWARD period, and
with point-in-time survivorship data + governance sign-off, does any live
conversation begin — and only on an official venue. Live is hard-blocked today.
