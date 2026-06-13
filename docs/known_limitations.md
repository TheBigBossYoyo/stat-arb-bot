# Known limitations

Consolidated, current as of 2026-06-13. Cross-references the audit documents.
Each item says what is true *now*, not what is planned.

## Data
- **Survivorship bias** (W-04): all equity universes are static 2026 survivors.
  No point-in-time membership, no delisted names. `data-audit` caps these at
  `research_only`. Momentum results are upper bounds.
- **Dividend adjustment** (W-05): FIXED in code (Yahoo `adj_close` stored;
  research uses total-return prices). Older rows need a re-download to backfill;
  `data-audit` reports coverage.
- **Crypto depth**: 15m history is ~90 days = one regime (W-14). "Structural"
  crypto verdicts are single-regime until history is extended.
- **Pipeline** (W-10): intersection alignment truncates to the youngest symbol;
  ffill up to 3 bars can pass stale prices; failed-QC bars are stored with a
  warning. `data-audit` surfaces these; they are not yet hard-blocked.

## Methodology
- **Selection inflation NOT fully corrected** (W-02): the experiment tracker
  counts trials going forward, but the ~40-60 historical configs are not
  back-filled, so the deflated Sharpe currently sees 1 trial and does not
  correct for the real search. This is the most important open methodological gap.
- **Config selection is in-sample**: model retraining is walk-forward, but the
  choice of sleeves/allocator/gates was made on the reporting window (W-06).
- **Hyperparameters**: purged CV exists (`app/research/purged_cv.py`) but the
  ML sleeve's hyperparameters were originally tuned by reading the backtest;
  they have not yet been re-selected purely by purged CV.

## Backtest realism
- **Execution timing** (W-03): FIXED — next-open fills are the default; the
  same-close legacy path warns. Timing optimism measured small for the flagship.
- **Financing** (W-07): FIXED — borrow + margin interest modeled per bar.
  Still flat-rate, not per-name; hard-to-borrow shorts are under-charged.
- **Impact/capacity** (W-09): square-root impact capacity curve exists; uses
  average dollar volume, not intraday book depth.

## Execution / production (PRODUCTION_RISK_REGISTER.md)
- Paper/live book state and risk baselines are **in-memory** — lost on restart
  (PR-02, PR-05). Not yet persisted.
- No reconciliation loop in the basket path (PR-08); no alerting (PR-13);
  trader loops swallow exceptions without a crash-loop budget (PR-12).
- Kill switch now **fails closed** (PR-03, fixed). T212 sell convention still
  flagged VERIFY (PR-06).

## Tradability
- The flagship and all market-neutral equity strategies **cannot be executed**
  on any connected venue (no shorting). This is the binding constraint.
- Funding carry is modeled funding-leg-only; the real trade (basis, margin,
  liquidation) is unmodeled and unconnected.

## Tail risk
- No crisis-regime (2008/2020-scale) test in the window. Momentum's worst case
  is unmeasured; crash protection is unproven live (PR-17).

## What is genuinely solid
Experiment tracking, the alpha registry + governance gates, the data-audit
verdicts, the validation statistics (deflated Sharpe / purged CV / bootstrap
reality check), the cost/financing/capacity machinery, and the broker-capability
+ kill-switch safety model. The *process* is trustworthy; the *numbers* are
honestly small and caveated.
