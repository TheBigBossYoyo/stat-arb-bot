# Why live trading is disabled

This system refuses live trading by default and will continue to refuse it until
a strategy clears every gate on a real, official venue. The reasons, concretely:

1. **The flagship has no venue.** The market-neutral book shorts and levers.
   Binance spot cannot short; Trading 212 Invest/ISA cannot short or use margin;
   CFDs and unofficial endpoints are out of bounds by policy. There is nowhere
   to actually hold the book.

2. **The flagship fails its corrected statistics.** Deflated against the real
   ~45-config search (not the 1 trial the tracker first saw), its Sharpe is below
   the expected maximum of 45 noise strategies — P(true > noise-max) = 0.375. It
   is an unproven candidate, not an established edge.

3. **Return concentration** — RESOLVED for the long-only book (2026-06-14): EWMA
   smoothing took its worst month from 26.1% to 23.5% (PASS). Crypto futures still
   fails this gate. The best-5%-of-days share remains structurally high for any
   daily directional book (not a defect smoothing can erase).

4. **Crisis evidence is synthetic.** The long-only crisis suite is complete but
   the 2021–2026 window has no real 2008/2020 tail, so the −28% worst-case is a
   synthetic/proxy bound, not observed history.

5. **Survivorship is bounded, not eliminated.** The long-only edge survives random
   name drops but roughly halves when the 5 biggest winners are removed; the
   universe is still today's survivors. Eliminating the bias needs point-in-time
   constituent data (not integrated).

6. **No FORWARD supervised paper period has run.** The workflow exists and the
   product is *eligible to begin* one, but eligibility ≠ a passed period; replayed
   bars never count as forward calendar time.

7. **Execution is demo-only by design.** The Trading 212 DEMO order path is wired
   (official Public API), but the live endpoint is hard-blocked and
   `TRADING212_ALLOW_LIVE_ORDERS` is never consulted.

8. **Policy.** No CFDs, no shorting on Invest/ISA, no scraping / browser
   automation / reverse-engineered or private APIs, and no leverage to flatter
   results — ever.

**Status (2026-06-14):** long-only Trading 212 is now **eligible to BEGIN a
supervised paper/shadow period** (`statarb product-decision` → `paper_candidate`).
That is the strongest status any product holds, and it is still **not** live. The
market-neutral flagship and crypto futures remain further back (reasons 1–4).

Disabling live trading is not a limitation of the build; it is the build working
as designed. See `docs/live_readiness.md`, `PAPER_ELIGIBILITY_REPORT.md` and
`TRADABLE_PRODUCT_REPORT.md`.
