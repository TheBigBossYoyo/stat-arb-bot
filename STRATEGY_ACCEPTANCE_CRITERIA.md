# STRATEGY ACCEPTANCE CRITERIA — stat-arb-bot

The promotion pipeline and the hard gates between stages. These criteria are the contract:
**no strategy advances a stage without every gate of that stage passing, and the evidence
recorded in the alpha registry.** A failed gate is a recorded rejection, not a retry-until-green.

Pipeline:

```
idea → research → backtest → walk-forward → stress → paper → shadow-live → live-tiny → live-scaled → retired
```

Any stage can also exit to `rejected` (with reason) or `retired` (with reason). Promotion
is always manual (human approval recorded); demotion can be automatic (decay triggers).

---

## Stage 0 → 1: idea → research

Required artifacts:
- **Economic hypothesis** (one paragraph: who is on the other side of this trade and why
  they keep paying — risk premium, behavioral effect, structural constraint, flow).
- Asset class, universe, horizon, expected turnover and capacity class (order of magnitude).
- **Failure-mode statement**: the market condition in which this strategy loses, named in advance.
- Required data and its known quality/bias status (from the data-audit module).

Hard gates:
- [ ] hypothesis is falsifiable (a result that would reject it is stated in advance)
- [ ] required data exists with an acceptable DataQualityReport, or the work item is data acquisition, not research

## Stage 1 → 2: research → backtest

Hard gates:
- [ ] experiment-tracked runs only (run ID, git hash, config snapshot, data hash, seed)
- [ ] costs on from the first run (no zero-cost exploratory metrics in registry records)
- [ ] universe survivorship status recorded on every result
- [ ] for ML: hyperparameters selected by **purged & embargoed CV only** — never by reading the backtest

## Stage 2 → 3: backtest → walk-forward

Hard gates (research window, net of modeled costs):
- [ ] ≥ 5 years of daily-equity history, or maximum-available crypto history (≥ 2 years; 90 days is exploration, not evidence)
- [ ] window spans ≥ 3 distinct regimes (labeled by the regime module: e.g., 2021 melt-up, 2022 bear, 2023-24 recovery, ...)
- [ ] net Sharpe > 0 with **realistic execution timing** (next-open or worse; same-close fills disqualify the run)
- [ ] no single month > 25% of total PnL; no single trade/position-episode > 10%
- [ ] turnover is affordable: net return at 2× modeled costs remains > 0
- [ ] **deflated Sharpe ratio** (against the registry's recorded trial count for this family) > 0

## Stage 3 → 4: walk-forward → stress

Hard gates:
- [ ] walk-forward with config frozen per train window; **OOS net Sharpe ≥ 0.8** for flagship candidates (≥ 0.5 for diversifying sleeves entering an ensemble)
- [ ] IS→OOS Sharpe degradation < 50%
- [ ] ≥ 60% of OOS windows positive, and stitched OOS curve max DD within mandate (below)
- [ ] parameter stability: ±50% perturbation of each key parameter keeps OOS Sharpe within 40% of the chosen config (no needle-point optima)

## Stage 4 → 5: stress → paper

Hard gates — strategy must remain net-positive (and within DD mandate) under each:
- [ ] costs × 2
- [ ] slippage × 2 (and reported at × 3)
- [ ] execution delayed one full bar
- [ ] best 5% of trades/position-episodes removed
- [ ] worst historical regime in the window isolated (strategy may lose, but within its pre-stated failure-mode bounds)
- [ ] leverage > 1 only with the financing model on (margin interest, borrow, funding); liquidation/forced-deleverage scenario simulated
- [ ] capacity: at the user's intended capital, participation < 5% of ADV per name per day, and modeled impact at that size keeps net Sharpe ≥ 80% of small-capital Sharpe

Risk mandate (defaults; per-alpha overrides must be approved and recorded):
- [ ] research max drawdown < 15% at 1× (flagship), < 20% (sleeves)
- [ ] OOS annualized vol within 1.5× of design target
- [ ] no unhedged single-name weight > 10%; no sector net > 25% (equities)

## Stage 5 → 6: paper → shadow-live

Paper period requirements:
- [ ] ≥ 30 trading days minimum, 90 recommended; ≥ 20 round-trip decisions (or 20 rebalances for basket strategies)
- [ ] tracking error vs research expectation explained: realized minus expected return gap attributable to (timing, costs, data) with no unexplained residual trend
- [ ] realized paper slippage ≤ modeled slippage (else the cost model is updated and stress gates re-run)
- [ ] zero unresolved risk-manager breaches, zero unexplained reconciliation breaks
- [ ] data-quality gates green for the whole period

## Stage 6 → 7: shadow-live → live-tiny

Hard gates — **the venue gate is absolute**:
- [ ] every position the strategy can request is executable on a **connected, officially supported** venue (shorting requires a venue that shorts; leverage requires margin support; no exceptions, no CFD workarounds)
- [ ] live connectors exercised on testnet/demo: order place/cancel/fill/partial-fill/reject paths all observed
- [ ] T212 sell-convention verification artifact recorded (if T212 is the venue)
- [ ] reconciliation loop live; kill switch fail-closed verified; book-state persistence verified across restart
- [ ] capital: $25–$100 (live-tiny is an execution test, not an investment)
- [ ] `LIVE_TRADING=true`, `CONFIRM_LIVE_TRADING=true`, `--confirm-live`, kill switch off, recent backtest + paper artifacts — the existing gate, all green
- [ ] human approval recorded in the registry with name and date

## Stage 7 → 8: live-tiny → live-scaled

Capital escalation protocol (never skip a stage, never escalate inside a drawdown):
| stage | capital | minimum proving period |
| --- | --- | --- |
| live-tiny | $25–100 | 20 trading days, ≥ 10 fills |
| stage 1 | $250 | 20 more days |
| stage 2 | $500 | 30 more days |
| stage 3 | $1000+ | 60 more days, then review cadence |

Gates at each escalation:
- [ ] live slippage within 1.5× model; fill rate ≥ 95% of intended; zero capability rejections
- [ ] live PnL within 2σ of paper expectation over the period
- [ ] no risk breaches, no manual interventions required
- [ ] current drawdown < 50% of mandate (no scaling while bleeding)

## Automatic demotion / retirement triggers

Any of the following demotes a live strategy one stage (and alerts); two triggers in 90
days, or one critical, retires it pending review:
- rolling 60-day live Sharpe below the 5th percentile of the OOS bootstrap distribution (decay)
- realized slippage > 2× model for 10 consecutive days (critical)
- tracking error vs paper/backtest unexplained for 15 days
- data-quality gate red for the strategy's universe
- venue capability change (e.g., borrow withdrawn) — critical, immediate flatten
- risk-manager breach caused by the strategy's own orders (critical)

## Ensemble-specific rules

- A sleeve enters the ensemble only after passing Stage 4 standalone (sleeve thresholds).
- The sleeve must improve the ensemble's **OOS** net Sharpe or net return/DD — judged
  in-ensemble with the allocator live (the §7c lesson: marginal contribution, not
  standalone metrics), on data not used to choose the sleeve.
- A sleeve at zero allocation for 2 consecutive quarters is removed (the §7d lesson:
  a gated dead sleeve still bleeds in funded spells).
- Allocator changes are themselves strategies: a new allocation mode must beat or match
  the incumbent OOS net of turnover before becoming default.

## Multiple-testing bookkeeping (applies to every stage)

- Every evaluated configuration counts as a trial in its family, automatically, via the
  experiment tracker. Researchers do not get to forget sweeps.
- Family-level FDR (Benjamini-Hochberg at 10%) for sweep tables; Deflated Sharpe for any
  headline number, using the family's recorded trial count and Sharpe variance.
- A result reported without its trial count is treated as marketing, not evidence.

## What current strategies must do before promotion claims

| strategy | current honest status | gates it has NOT passed |
| --- | --- | --- |
| flagship ensemble (xsmom+tsmom+ml) | backtest (in-sample, biased data) | W-F (none exists for baskets), stress, DSR, dividend-adjusted re-run, venue gate (no shorting venue) |
| cointegration pairs (stocks) | walk-forward, thin sample | regime breadth, CI on OOS, capacity, paper |
| tsmom crypto | single 90-day window | history depth, regimes, walk-forward |
| funding carry | research (funding leg only) | basis/margin/liquidation model, any venue |
| pca/sector/reversal | rejected (recorded) | — properly rejected; keep the records |

**Standing rule:** nothing currently in this repository qualifies for any `live_*` stage.
The flagship does not currently qualify for `paper` *as a market-neutral product* (no
venue can hold its short book); its paper runs are research artifacts and must be labeled
as such in the registry.
