# Long-only Trading 212 — supervised paper/shadow plan (Phase 6)

The product `long_only_t212` (= `long_only_xsec_momentum` on `us_stocks_50`,
weekly rebalance, EWMA α=0.5 smoothing, regime filter ON) is **eligible to BEGIN**
a supervised paper/shadow period. This is the operator runbook. **Live remains
blocked throughout.**

## What a supervised period is (and is not)

A supervised period earns confidence by surviving **forward calendar time** with
sane execution — not by a backtest number. The workflow counts only distinct
**forward** days; replayed bars are recorded but labeled REPLAY and never count
toward the minimum. `supervised-paper-final-report` cannot return PASS on replay.

## Modes

- **shadow** (default, offline): generate signals, build + validate the order
  plan, simulate fills against a persisted paper book, record everything. Sends
  nothing. Use this for the first period — no broker keys required.
- **demo_preview**: additionally connect to the Trading 212 DEMO account and plan
  against its real balances. Sends nothing.
- **demo_execute --confirm-demo**: additionally submit to the DEMO account when
  the demo execution gate passes. Never live.

## Persistent state (`runtime/paper/long_only_t212/`)

`session.json` plus seven append-only tables: `daily_reports`, `orders`,
`reconciliations`, `tca`, `risk_snapshots`, `benchmark_snapshots`.

## Daily runbook (30–90 days)

1. Once per trading day (a cron, **not** a loop), run:
   ```
   statarb supervised-paper-start --product long_only_t212 --mode shadow
   ```
   Each call records ONE forward day (signals → plan → simulated fills →
   reconciliation → TCA → risk snapshot → benchmark snapshot).
2. Review the day:
   ```
   statarb supervised-paper-status
   statarb supervised-paper-daily-report --product long_only_t212
   ```
   Watch: reject rate, expected-vs-realized slippage, drift from target,
   concentration (top weight), drawdown vs the 25% policy, cash drag, turnover.
3. To validate the pipeline immediately (without waiting), replay recent bars —
   clearly labeled REPLAY, not forward:
   ```
   statarb supervised-paper-start --product long_only_t212 --mode shadow --replay 30 --reset
   ```
4. After ≥30 forward days:
   ```
   statarb supervised-paper-final-report --product long_only_t212 --min-days 30
   ```
5. Stop early if needed (records the reason):
   ```
   statarb supervised-paper-stop --product long_only_t212 --reason "..."
   ```

## Pass criteria (final report)

≥ `min_days` distinct **forward** calendar days, no short positions ever, reject
rate < 5%, no broker errors, drawdown within the 25% policy, no risk breaches,
paper PnL not catastrophic. A PASS recommends proceeding to the next governance
stage — it does **not** authorize live capital.

## Optional: enable the Trading 212 DEMO account

```
TRADING212_ENABLED=true
TRADING212_MODE=demo
TRADING212_API_KEY=...        # demo keys only
TRADING212_API_SECRET=...
TRADING212_ALLOW_DEMO_ORDERS=true   # plus --confirm-demo for demo_execute
```
Then `statarb trading212-check --mode demo` and run the period in `demo_preview`
or `demo_execute`. See `docs/trading212_demo_execution.md`.

## After a passed forward period

Do not go live. Next: obtain point-in-time constituent data to upgrade
survivorship from *bounded* to *eliminated*, complete governance/risk sign-off,
and only then open a separate, explicit live-readiness discussion. Live stays
blocked until that is done.
