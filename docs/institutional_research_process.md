# Institutional research process

The repeatable loop every candidate improvement goes through. The tooling makes
each step a command, and the experiment tracker makes the whole loop auditable.

## The loop

1. **Hypothesis** — state the economic mechanism and who pays (risk premium,
   behavioral effect, structural constraint). Register it: `alpha-registry`.
2. **Failure mode** — name, in advance, the condition under which it loses.
3. **Data** — confirm an acceptable `data-audit` verdict for the universe.
4. **Implement minimally** — a `WeightFn` or pair strategy; reuse the engines.
5. **In-sample backtest** — `backtest-basket` / `backtest-ensemble`. Every run
   is recorded as a trial in its family (the count matters later).
6. **Out-of-sample** — `validate-ensemble` (anchored walk-forward): OOS Sharpe,
   IS→OOS degradation, fold positivity.
7. **Purged CV** (ML only) — `app/research/purged_cv.py`: select hyperparameters
   here, never by reading the backtest; report the naive-vs-purged gap.
8. **Stress** — cost ×2/×3, financing ×3, execution delay, timing optimism.
9. **Concentration** — no month > 25% of PnL, no day-cluster dominating.
10. **Deflated Sharpe** — `validate-ensemble` deflates against the family's
    recorded trial count. A headline number without its trial count is marketing.
11. **Capacity** — `capacity-report`: net Sharpe vs capital with impact.
12. **Compare to flagship** — marginal contribution *in-ensemble with the
    allocator live*, not standalone Sharpe (the §7c lesson).
13. **Decide** — reject / research-only / paper-candidate, recorded in the
    registry with the experiment IDs as evidence.

## Rules distilled (and enforced)

- Charge every sleeve its own costs; gate on trailing performance, not just vol.
- A new sleeve must be uncorrelated AND positive, judged in-ensemble.
- Count features against panel size; trailing t-stats detect regimes, they do
  not size positions.
- A gated dead sleeve still bleeds — remove sleeves that never earn.
- Reproducibility is non-negotiable: every cited run carries a git commit, a
  config hash, a data fingerprint and a seed (`statarb experiments`).

## Acceptance bar

A candidate must improve at least one of: OOS net Sharpe, OOS drawdown,
return/drawdown, capacity, cost robustness, turnover, diversification, or live
execution realism — without worsening overfitting risk. A higher in-sample CAGR
that worsens drawdown, turnover, concentration or robustness is **rejected**.
