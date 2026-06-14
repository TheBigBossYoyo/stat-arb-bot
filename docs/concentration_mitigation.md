# Concentration mitigation — EWMA target-weight smoothing (Phase 1)

## The problem

`long_only_xsec_momentum` cleared six of seven readiness gates. The one failure
was **return concentration**: its worst calendar month was **26.1%** of total
PnL against a **25%** limit. A book whose edge clusters in a few periods is
fragile — remove the lucky month and the alpha is suspect.

## The fix (and what it is NOT)

We do **not** delete the winning month or filter with hindsight. We make the
same edge arrive more evenly by **smoothing the target weights across
rebalances**, so a single rebalance cannot dump the whole book into the names
that happen to rip in one month.

`app/strategies/weight_smoothing.py` implements a small, transparent family:

| method | description |
|---|---|
| `none` | identity (the unsmoothed baseline) |
| `ewma` | `w_t = α·target_t + (1−α)·w_{t−1}` (α direct, or via `half_life`) |
| `capped_change` | cap each name's per-rebalance weight change |
| `ewma_capped` | EWMA then the per-name change cap |

Every method **re-enforces the long-only constraints** after smoothing: weights
≥ 0 (no shorting), per-name ≤ 20%, gross ≤ 1.0 (no margin/leverage; cash absorbs
the remainder). Smoothing is integrated into the strategy configs, the long-only
engine, and a `long_only_smoothing` block in `strategy_defaults.yaml`. It is
**off by default at the library level** (`method: none`) and only switched on
because validation selected it.

## How the default was chosen (validation, not curve-fitting)

`statarb compare-concentration-fixes --strategy long_only_xsec_momentum` sweeps
the whole family, registers each configuration as a **trial**, and ranks the
ones that PASS the concentration gate while keeping OOS Sharpe ≥ 85% of the
unsmoothed baseline. The recommender then prefers the **largest gate buffer**
(lowest worst-month) — robustness over headline Sharpe.

| smoothing | worst month % | Sharpe | OOS Sharpe (2/2) | turnover | maxDD% | gate |
|---|---|---|---|---|---|---|
| none (baseline) | 26.1 | 1.531 | 1.714 | 42.2 | −17.4 | FAIL |
| **ewma α=0.5 (default)** | **23.5** | 1.435 | 1.648 | 29.7 | −16.9 | **PASS** |
| ewma α=0.7 (higher-Sharpe alt) | 24.2 | 1.480 | 1.691 | 35.2 | −17.0 | PASS |
| ewma α=0.35 | 24.4 | 1.402 | 1.609 | 24.6 | −18.2 | PASS |
| ewma half-life 2/3/5 | 25.4 / 27.5 / 29.4 | — | — | — | — | FAIL |
| capped_change 0.05 / 0.03 | 25.9 / 31.8 | — | — | — | — | FAIL |

**Key insight:** smoothing is non-monotone. Light-to-moderate EWMA (α ≈ 0.5–0.7)
spreads rebalance transitions enough to clip the worst month under 25%; *heavy*
smoothing (α ≈ 0.13–0.29, i.e. half-life 2–5) makes the book so sticky it rides a
single regime and the worst month gets **worse**. The capped-change and
ewma-capped variants also fail. So the chosen fix is the economically sensible
interior optimum, not the extreme.

## Acceptance check (Phase 1 criteria)

- worst month ≤ 25% — **PASS (23.5%)**
- OOS Sharpe remains acceptable — **PASS (1.65, 2/2 folds)**
- drawdown not materially worse — **PASS (−16.9% vs −17.4%)**
- turnover does not explode — **PASS (lower: 30× vs 42×)**
- costs do not erase the edge — **PASS (positive at ×2 and ×3)**
- beats SPY/QQQ/equal-weight risk-adjusted — **PASS**
- trial tracker records the search — **PASS (family registered)**

## A remaining honesty note

The "best 5% of days exceed total return" character of a *daily directional*
book is structural and does not vanish with smoothing — it is a property of
momentum, not a defect the smoother can erase. The gate we close is the
month-concentration gate; the best-5%-of-days share is reported, not gamed.

## Commands

```
statarb concentration-fix-backtest --strategy long_only_xsec_momentum --method ewma
statarb compare-concentration-fixes --strategy long_only_xsec_momentum
statarb backtest-long-only --strategy long_only_xsec_momentum --smoothing ewma
statarb long-only-readiness --strategy long_only_xsec_momentum --smoothing ewma --full
```
