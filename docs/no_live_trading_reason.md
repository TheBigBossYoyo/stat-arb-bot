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

3. **Return concentration is unresolved.** One month is ~30% of the flagship's
   PnL and the best 5% of days exceed total return. The tradable long-only and
   futures books fail the same gate (just over the 25%/month limit).

4. **No crisis test.** The 2021–2026 window contains no 2008/2020-scale crash —
   exactly momentum's worst case (Phase 4 outstanding).

5. **Survivorship bias.** The universes are today's survivors backtested into the
   past (Phase 3 outstanding).

6. **No supervised paper period.** No product has traded paper/testnet for a
   meaningful, reviewed period with TCA (Phase 5 outstanding).

7. **Execution is not wired.** The Trading 212 demo order path and Binance
   testnet keys are not connected — only shadow planners exist.

8. **Policy.** No CFDs, no shorting on Invest/ISA, no scraping / browser
   automation / reverse-engineered or private APIs, and no leverage to flatter
   results — ever.

Disabling live trading is not a limitation of the build; it is the build working
as designed. See `docs/live_readiness.md` for the exact conditions and
`TRADABLE_PRODUCT_REPORT.md` for the per-product verdicts.
