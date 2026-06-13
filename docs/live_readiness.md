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

- **long-only equity (Trading 212):** lead candidate, **6/7** readiness gates —
  fails concentration. NOT YET paper-eligible.
- **crypto futures (Binance testnet):** **5/6** — fails concentration; LIVE
  BLOCKED unconditionally; ~0.84y sample.
- **market-neutral equity:** DO NOT TRADE — no venue + fails deflated Sharpe.

## The path to the first paper period

Close the long-only concentration gate (Phase 1 smoothing), resolve survivorship
(Phase 3), run a crisis test (Phase 4), wire the Trading 212 demo order path, then
run the supervised paper period (Phase 5). Only after that does any live
conversation begin — and only on an official venue.
