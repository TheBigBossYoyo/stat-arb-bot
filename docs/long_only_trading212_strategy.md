# Long-only Trading 212 Invest/ISA strategy (Path A)

**Status:** research / backtest — *candidate* for supervised paper trading, **not
live-eligible**. NOT market-neutral.

## Why this product exists

The market-neutral flagship (`xsec_momentum + tsmom + ml_alpha`) cannot be
traded on Trading 212 Invest/ISA: those accounts cannot short, cannot use margin
and cannot trade CFDs, and the official Public API exposes none of them. Rather
than pretend otherwise, Path A builds a **different, directional product** that
*can* actually be held in an Invest/ISA account: it ranks the universe by the
same momentum signals but **buys only the leaders and holds cash** instead of
shorting the laggards.

This is a long book. Its dominant risk is market direction, not spread
convergence. It must therefore clear a higher bar than the neutral book: beating
*buy-and-hold SPY on a risk-adjusted basis*, because buying SPY is the free
alternative every Invest/ISA holder always has.

## Components

| File | Role |
|------|------|
| `app/strategies/long_only_momentum.py` | `long_only_xsec_momentum`, `long_only_tsmom` + regime trend filter |
| `app/strategies/long_only_ml_alpha.py` | long-only wrapper over the momentum-neutral ML forecaster |
| `app/strategies/long_only_ensemble.py` | risk-parity blend of the three long-only sleeves, book-level regime filter, hard long-only/gross guard |
| `app/backtesting/long_only_engine.py` | runs the book + benchmark-relative metrics (alpha/beta/info ratio/cash drag) |
| `app/risk/long_only_risk.py` | no-short / no-margin / per-name / per-sector enforcement |
| `app/execution/trading212_rebalancer.py` | turns target weights into a Trading 212 order plan (shadow) |

### Constraints enforced (the Invest/ISA reality)

- **No shorting** — every weight ≥ 0 (a negative weight reaching execution is a
  bug and raises).
- **No margin / no leverage** — gross exposure ≤ 1.0; cash absorbs the rest
  (a real, modeled cash drag).
- **No CFDs, no unofficial endpoints** — ever.
- **Fractional shares** only where the instrument supports them, else whole
  shares; **minimum order value**; **market-hours awareness** (orders planned
  while closed are queued for the next open); **limit-order preference** to
  bound slippage; **instrument tradability** check (skip names not on T212).
- **Costs** 5 bps/side (liquid US large caps, zero-commission retail), next-open
  fills, dividends via total-return prices. **No borrow, no short rebate, no
  margin interest** (none apply long-only).

### Regime / risk-off cash filter

A trend filter scales the whole book toward cash when the equal-weight market
proxy is below its 200-day moving average (`--regime`, on by default;
`--risk-off-exposure` sets the gross to hold when risk-off). It is an *internal*
proxy so it needs no extra data; the comparison command can substitute a real
SPY/QQQ trend.

## Backtest results (us_stocks_50, daily, 2021-06 → 2026-06, total-return, 5 bps)

Weekly rebalance; benchmarks are buy-and-hold over the **same active window**.

| Book | Total return | Sharpe | Max DD | Turnover | Alpha vs SPY | Beats SPY Sharpe |
|------|-------------:|-------:|-------:|---------:|-------------:|:----------------:|
| **long_only_xsec_momentum** | +311% | **1.53** | −17.4% | 42×/yr | **+23.2%/yr** | ✅ |
| **long_only_ensemble** (incl. ML) | +85% | **1.67** | small | 45×/yr | ≈ 0% | ✅ (lower vol) |
| *benchmark* SPY | +83% | 1.05 | — | — | — | — |
| *benchmark* QQQ | +125% | 1.11 | — | — | — | — |
| *benchmark* equal-weight | +125% | 1.33 | — | — | — | — |

**Reading it honestly.**

- `long_only_xsec_momentum` is the compelling product: it beats SPY on both
  return *and* risk-adjusted return, with ~23%/yr alpha and info ratio ≈ 1.0.
  The cost is a deeper drawdown (−17%, vs −10% for the neutral book) — that is
  the price of being directional and long-only.
- `long_only_ensemble` has the **highest Sharpe** (smoothest ride) but barely
  adds alpha over SPY: with the ML sleeve, vol targeting and the regime filter
  it runs at ~62% average exposure, so it delivers roughly SPY-like *returns*
  with materially less risk. Valuable as a low-risk equity sleeve, weak as an
  alpha story.

## Readiness gate (`statarb long-only-readiness`)

The gate (never asserts live eligibility) checks: beats-benchmark Sharpe,
positive alpha, OOS walk-forward Sharpe > 0.3, survives costs ×2 and ×3,
concentration (no month > 25% of PnL), and acceptable turnover.

Latest run — **`long_only_xsec_momentum`: 6/7 gates pass**, OOS walk-forward
Sharpe **1.71** (2/2 folds positive). The single failure is the **concentration
gate** (worst month 26.1% of PnL, just over the 25% limit). So the verdict is
**NOT YET paper-eligible** — and the recommended next step is the Phase 1
concentration mitigation (EWMA weight smoothing lowers concentration without
hurting OOS) plus a real supervised paper period.

## What is NOT done (blockers to paper, then live)

1. The concentration gate is not yet passed (close). Apply the Phase 1 `smooth`
   mitigation and re-validate.
2. No supervised paper/shadow period has been run (the Phase 5 layer).
3. Survivorship bias of `us_stocks_50` is unresolved (Phase 3) — these are
   2026 mega-caps backtested into the past, the worst case for momentum.
4. No crisis-regime test for a long book (Phase 4).
5. The Trading 212 **demo** order path is not wired; shadow mode plans orders
   but sends nothing.

## CLI

```
statarb backtest-long-only   --strategy long_only_ensemble --universe us_stocks_50 --interval 1d
statarb compare-long-only    --universe us_stocks_50 --benchmark SPY
statarb paper-trade-long-only --broker trading212 --mode shadow
statarb long-only-readiness  --strategy long_only_ensemble
```

## Tax note

Trading 212 ISA is tax-sheltered (UK); Invest is not — a 42×/yr-turnover book in
a taxable Invest account realizes short-term gains constantly. **Tax is not
modeled.** Prefer the ISA wrapper, or treat the Invest after-tax return as
materially lower than the pre-tax backtest. This is a warning, not a model.
