# FINAL RESEARCH REPORT — stat-arb-bot

**Date:** 2026-06-13
**Author:** quant research lead (institutional takeover engagement)
**Scope:** audit + Phases 2-7 of the upgrade (foundations, validation, realism,
governance). This report answers, directly and brutally, the questions the
engagement requires.

> **One-line answer:** the system is now an honest research platform with real
> validation machinery, and that machinery says the flagship is a **Sharpe-~1,
> in-sample, single-window, survivorship-biased, currently-untradable** book —
> a legitimate research candidate, **not a live-ready strategy, and not a money
> machine.** The correct action today is **do not trade real capital.**

---

## What changed versus the previous README

The old README presented `xsec_momentum + tsmom + ml_alpha` at **+48.5% /
Sharpe 1.34 / DD −7.1%** as the flagship. The audit found five issues that
inflate or invalidate that number (AUDIT_REPORT.md F1-F5):

1. no out-of-sample path for basket strategies at all (W-01);
2. ~40-60 configs evaluated on one window, uncorrected for selection (W-02);
3. same-close fills in the basket engine (W-03);
4. survivorship-biased universe (W-04);
5. dividend-blind prices and frictionless shorts/leverage (W-05, W-07).

After fixing the data (dividend adjustment), the engine (next-open fills,
borrow/margin financing), and adding the validation layer (basket walk-forward,
stress, deflated Sharpe, purged CV), the **re-stated flagship is +35.3% /
Sharpe 1.02 / DD −10.1%** at 1x. The Sharpe-0.3 / 13pp gap was the inflation.

## What is the current best strategy?

`xsec_momentum + tsmom + momentum-neutral ml_alpha`, inverse-vol allocated,
`us_stocks_50`, daily. Full detail and caveats:
[`docs/current_best_strategy.md`](docs/current_best_strategy.md). Registry
status **`backtest`** — it has *not* earned walk-forward stage because it fails
the return-concentration gate.

## Which strategies were improved?

- **Cross-sectional momentum** gained optional **crash protection**
  (Daniel-Moskowitz vol-scaling) to address its named failure mode (momentum
  crashes / PR-17). Off by default pending a regime that exercises it.
- **The ensemble allocator** gained ERC / HRP / min-variance / shrinkage modes
  (the inverse-vol "risk parity" was risk parity in name only). They are
  available but **did not beat inverse-vol OOS**, so the default is unchanged
  (this is the acceptance criteria working as intended).
- **The whole basket research path** improved structurally: it now has
  out-of-sample validation, a stress suite, capacity analysis, financing, and
  honest execution timing where before it had none.

## Which strategies were rejected?

`pca_stat_arb`, `sector_stat_arb`, `xsec_reversion`, the ML
`orthogonal_features` block, continuous t-stat sizing, and (this build) the
ERC/HRP allocators as defaults. Evidence and re-open conditions:
[`docs/rejected_strategies.md`](docs/rejected_strategies.md).

## Which results are in-sample / OOS / walk-forward / stress-surviving?

- **In-sample:** every headline number (the +35.3% / Sharpe 1.02) is a
  full-window backtest. Strategy *selection* and *configuration* remain
  in-sample (the deep problem — W-02 — is only partly mitigated because the
  historical trial count is not yet back-filled into the tracker).
- **Out-of-sample (walk-forward):** the anchored basket walk-forward gives
  **OOS Sharpe 0.97**, IS→OOS degradation **0.14**, **3/3 OOS folds positive**.
  This is genuinely encouraging and is the strongest single piece of evidence.
  The pairs strategy's older 4-window OOS Sharpe 0.88 also stands (thin sample).
- **Stress-surviving:** survives costs ×2 (Sharpe 0.70), costs ×3 (0.38),
  borrow ×3 (0.96), a 1-bar execution delay (0.91), and the same-close→next-open
  comparison is small (1.01→1.02, so it is *not* harvesting overnight moves).
- **Does NOT survive:** the **return-concentration gate** — one month is 30.3%
  of total PnL and the best 5% of days exceed total return.

## What are the realistic costs?

Modeled: 2 bps commission + 3 bps slippage per side on liquid US large caps
(5 bps round-trip); **75 bps/yr borrow** on the short notional; **700 bps/yr
margin interest** on any leverage above 1x; square-root market impact for
capacity. Not yet modeled: per-name borrow tiers (hard-to-borrow momentum
losers can cost far more), short dividend liability beyond the adjustment, FX,
taxes. The cost stack is honest at the blended level, still optimistic on the
hardest-to-borrow short names.

## What is the expected capacity?

Net Sharpe holds to **$50M+** before impact removes 20% of it (mega-cap ADV).
Capacity is not the binding constraint at any plausible size for this operator.

## What is the worst historical drawdown?

−10.1% at 1x in the base case; −16.8% at costs ×3. At leverage the drawdown
scales roughly linearly (and margin interest compounds the bleed) — see below.

## What happens if costs double / slippage doubles / execution is delayed?

Costs ×2 → Sharpe 0.70 (+22.5%); ×3 → 0.38 (+10.9%, thin). One-bar execution
delay → Sharpe 0.91. The strategy degrades gracefully rather than collapsing,
which is the point of the stress suite. (Slippage is folded into the cost
multiplier for baskets; the ×2/×3 cost rows bound it.)

## What happens in crisis regimes?

Untested directly — the 2021-2026 window contains the 2022 bear but no 2008/2020
-scale momentum crash, which is precisely momentum's worst case. The crash-
protection scalar exists to mitigate this but is off by default and unproven on
a real crash. **This is a known, unmeasured tail risk** (PR-17).

## Can it be traded with...?

- **Binance spot?** No — it shorts; spot cannot short.
- **Binance futures?** Mechanically yes (futures support shorting), but the
  connector is not implemented/connected, and the strategy is equities, not
  crypto. Not applicable.
- **Trading 212 Invest/ISA?** No — cannot short. A **long-only variant** could
  trade there but is a different, directional strategy needing its own validation.
- **What cannot be traded because of broker limits?** The market-neutral book
  as designed, on every connected venue. This is the binding constraint, not
  the alpha.

## Is it paper-trading eligible? Live eligible?

- **Paper:** yes, as a **research artifact only** (`statarb paper-trade-basket`),
  with simulated shorts clearly labeled. It is not paper-eligible as a *product*
  because no venue can hold its book.
- **Live:** **No.** It fails the venue gate (no shorting venue), fails the
  return-concentration gate, and its deflated Sharpe is not yet truly deflated.
  Nothing in this repository is live-eligible.

## If not live eligible, exactly what remains missing?

1. **A shorting venue** (Binance futures connected + tested, or a margin equity
   broker) — or a validated **long-only variant** as the tradable product.
2. **Back-fill the trial family** so the deflated Sharpe corrects for the real
   ~50-config search (today it sees 1 trial). This may lower the verdict.
3. **Resolve or bound the return concentration** (30% in one month).
4. **A real crisis-regime test** (extend history; exercise crash protection).
5. **Point-in-time universe** to remove survivorship bias (W-04) and re-measure.
6. **A supervised paper period** (30-90 days) once a venue exists, with TCA.
7. **Production hardening** from the risk register: persistent book state and
   risk baselines (PR-02/PR-05), reconciliation in the basket path (PR-08),
   crash-loop budget (PR-12), alerting (PR-13).

## Honest bottom line

The engagement asked for process quality, not a profit promise. That is what
was delivered: a system that now *catches its own overfitting*. The flagship is
a plausible Sharpe-~1 research candidate whose true out-of-sample, net-of-real-
costs, post-deflation value is most likely **somewhat below 1.0**, that **cannot
currently be traded**, and that **should not receive real capital** until the
seven items above are closed. The best improvement this quarter was not a higher
return — it was making the number trustworthy and smaller.
