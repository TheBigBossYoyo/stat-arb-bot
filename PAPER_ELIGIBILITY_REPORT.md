# PAPER ELIGIBILITY REPORT — long-only Trading 212 (Path A)

**Date:** 2026-06-14
**Scope:** the paper-readiness sprint — convert `long_only_xsec_momentum` on
Trading 212 Invest/ISA from "lead candidate, 6/7 gates, not paper-eligible" into
a clear, honest verdict on supervised paper/shadow eligibility.

> **VERDICT: Long-only Trading 212 is ELIGIBLE TO BEGIN a supervised
> shadow/paper period.** EWMA target-weight smoothing closed the one failing
> gate (return concentration) without breaking out-of-sample performance. The
> Trading 212 **demo** order path is wired and safe. **It is NOT live-eligible**
> and must run a real forward supervised period before any live conversation.

Reproduce: `statarb long-only-readiness --strategy long_only_xsec_momentum --full`
then `statarb product-decision`.

---

## The 17 questions

### 1. Did EWMA smoothing close the concentration gate?
**Yes.** The unsmoothed book's worst calendar month was **26.1%** of total PnL
versus the 25% limit (the only failing gate). With the validated default
(**EWMA, alpha 0.5**) the worst month falls to **23.5%** — a PASS with a ~1.5pp
buffer. The smoothing default was *selected by validation across a parameter
family*, not tuned on the failing month (`compare-concentration-fixes
--strategy long_only_xsec_momentum`), and each family member is registered as a
trial. Notably, *heavy* smoothing (half-life 2–5 ≈ alpha 0.13–0.29) makes the
worst month **worse** (a sticky book rides one regime), so the family has an
interior optimum — an honest, economically sensible result, not a monotone knob.

### 2. What are the new long-only results? (EWMA alpha 0.5, the certified book)
| metric | unsmoothed | EWMA α=0.5 (default) |
|---|---|---|
| total return (3.8y) | 311% | **259%** |
| Sharpe | 1.531 | **1.435** |
| max drawdown | −17.4% | **−16.9%** (slightly better) |
| turnover | 42×/yr | **30×/yr** (lower) |
| cash drag | 12.4% | 12.8% |
| beats SPY/QQQ/EW (Sharpe) | yes | **yes** (1.44 vs 1.05 / 1.11 / 1.33) |
| positive alpha vs SPY | yes | **yes** (+19.6%/yr, IR 0.90) |

Return is lower (expected — we are not optimizing CAGR); the *risk-adjusted* and
*concentration* picture is what improved. A higher-return alternative
(EWMA α=0.7: worst month 24.2%, Sharpe 1.48, OOS 1.69) also passes; α=0.5 was
chosen for the larger gate buffer and lower turnover (robustness over headline).

### 3. What are the new OOS results?
Walk-forward OOS Sharpe **1.648** (vs 1.714 unsmoothed), **2/2 folds positive** —
comfortably above the 85%-of-baseline floor. OOS remains strong.

### 4. What are the new concentration numbers?
Worst month **23.5%** (≤25% PASS); concentration score 53.1/100; best-5%-of-days
share ~204% (structurally high for a daily directional book and unchanged in
character — see `docs/concentration_mitigation.md`); per-name cap 20% holds.

### 5. What happened to turnover?
It **fell** from ~42×/yr to ~30×/yr — smoothing spreads rebalances, so costs go
*down*, not up.

### 6. What happened to drawdown?
Essentially unchanged / marginally better: −16.9% vs −17.4%. Smoothing did not
worsen the drawdown.

### 7. What happened under costs ×2 and ×3?
The book remains **positive under both** 2× and 3× the cost model (readiness gate
PASS). The edge is not a cost artifact.

### 8. What happened under survivorship stress?
**BOUNDED, with an honest caveat.** Random 10/20/30% name drops keep Sharpe at
1.30–1.48; a sector-balanced 20% drop → 1.25; bootstrap median 1.38, 5th
percentile 1.10; worst-case DD −22.8%. **But removing the 5 biggest individual
winners roughly halves the Sharpe to 0.78** — the edge has real dependence on the
top winners, which is exactly the residual survivorship risk. "Bounded" is
acceptable for *paper*; *live* would require actual point-in-time constituent
data (not integrated). `statarb survivorship-stress-long-only`.

### 9. What happened under crisis tests?
Worst **synthetic** crisis drawdown **−28%** (vol-whipsaw), bounded and not
catastrophic; base full DD −16.9%. The decisive finding: **the regime filter is
the real crash protection** — with it off the worst synthetic crisis DD is −51%
and the 2008-style grinding bear −21%; with it on those are −28% and ~0%. EWMA
smoothing marginally *worsens* momentum-crash resilience (the sticky-book
tradeoff). All scenarios are clearly labeled SYNTHETIC/proxy — the 2021–2026
sample has no real 2008/2020 tail. `statarb crisis-report --product long_only_t212`.

### 10. Is the Trading 212 demo path wired?
**Yes — demo only.** `app/brokers/trading212/{instrument_cache,order_validation,
demo_execution}.py` + `app/execution/long_only_{order_planner,demo_executor,
reconciliation}.py`, using the official Public API in **demo** mode. Live is
hard-blocked on multiple independent grounds (see Q16).

### 11. Can the system preview orders?
**Yes.** `statarb long-only-order-preview --broker trading212 --mode demo_preview`
(connects to the demo account, plans + validates, sends nothing) and `--mode
shadow` (fully offline). Order plans respect no-short, no-margin, fractional /
whole-share rounding, minimum order value, market-hours / queueing and a limit
offset to bound slippage.

### 12. Can the system send demo orders?
**Yes, to the DEMO account only**, via `statarb paper-trade-long-only --broker
trading212 --mode demo_execute --confirm-demo`, and only when the full demo
execution gate passes. It never reaches the live endpoint.

### 13. Did demo order safety gates pass?
**Yes (verified by tests).** The demo execution gate requires ALL of:
`TRADING212_ENABLED=true`, `TRADING212_MODE=demo`,
`TRADING212_ALLOW_DEMO_ORDERS=true`, `--confirm-demo`, kill-switch off, the
GLOBAL live-trading flag OFF, API keys configured, the strategy paper-eligible,
fresh market data, and a fully validated order plan (no negative weights, gross
≤ 1.0, every instrument tradable, every order ≥ minimum value, correct rounding,
slippage within limit, cash sufficient — no margin). Refusal-without-confirmation
and the live hard-block are covered by `app/tests/test_trading212_demo.py`.

### 14. Is the product eligible to begin a supervised paper/shadow period?
**Yes.** All 15 research gates + the operational gates (order path wired,
survivorship bounded, crisis tested) pass, so `long-only-readiness --full`
returns **"ELIGIBLE TO BEGIN SUPERVISED PAPER/SHADOW PERIOD"** and
`product-decision` classifies it **paper_candidate**. Begin with
`statarb supervised-paper-start --product long_only_t212 --mode shadow`.

### 15. Is it live eligible?
**No.**

### 16. If not live eligible, why not?
- **No forward paper period has run.** Eligibility to *begin* ≠ a *passed*
  period. The supervised workflow counts only forward calendar days; replayed
  bars never satisfy it.
- **Survivorship is bounded, not eliminated** — and the edge leans on the top
  winners (Q8). Live needs point-in-time constituent data.
- **Crisis evidence is synthetic** — the sample has no real 2008/2020 tail.
- **The order path is demo-only by design**; the live endpoint is hard-blocked
  and `TRADING212_ALLOW_LIVE_ORDERS` is never consulted.
- Governance/risk sign-off for real capital has not been granted.

### 17. What is the next operator action?
1. (Optional) configure Trading 212 **demo** keys and run `statarb
   trading212-check --mode demo`, then `long-only-order-preview --mode demo_preview`.
2. Start a **supervised shadow/paper period**: run `statarb supervised-paper-start
   --product long_only_t212 --mode shadow` once per day (a cron, not a loop) for
   30–90 calendar days; review `supervised-paper-daily-report` and watch drift,
   reject rate, slippage, drawdown and concentration.
3. After ≥30 forward days, run `statarb supervised-paper-final-report --min-days 30`.
4. Keep live blocked. Pursue point-in-time constituent data before any
   live/real-capital discussion.

---

## Final verdict

**A. Long-only Trading 212 is eligible to begin a supervised shadow/paper
period.** It is **not** live-eligible, for the reasons in Q16. It must never be
described as live-eligible, margin/short/CFD-enabled, or ready for real capital.
