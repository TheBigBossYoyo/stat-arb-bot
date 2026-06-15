# Paper Alert Rules

The alert engine (`app/research/paper_alerts.py`) turns the monitoring metrics
into discrete, persisted alerts. Each alert has a severity (`info` / `warning` /
`critical`), a category, a title, a message, evidence, and a suggested action.

> ⛔ **NOT LIVE ELIGIBLE.** Alerts watch a paper/shadow period; none can trade.

## Lifecycle

- The rule engine emits at most **one spec per category** (the highest applicable
  severity), with a stable de-dup key `category:severity`.
- `AlertStore.sync` reconciles specs with persisted alerts: a new condition
  creates an alert; a cleared condition **auto-resolves** its alert (note
  "condition cleared automatically"); an escalation (warning → critical)
  auto-resolves the warning and raises a fresh critical.
- Alerts are **never deleted** — resolution only marks them resolved (kept in
  history).
- An operator may resolve an `info`/`warning` alert with a note (audited). A
  **critical** alert whose condition is still active is **refused** — fix the
  underlying issue; it cannot be dismissed while live.

## Categories and thresholds

| category | severity | fires when | suggested action |
| --- | --- | --- | --- |
| `live_flag_detected` | critical | the global live-trading gate is ON | set LIVE_TRADING/CONFIRM_LIVE_TRADING false now |
| `kill_switch_active` | critical | kill switch engaged | investigate, then disengage from Safety Center |
| `product_decision_changed` | critical | product is no longer `paper_candidate` | re-run readiness; restart when eligible |
| `readiness_lost` | critical | readiness gates lost | re-run `long-only-readiness --full` |
| `paper_drawdown` | warning / critical | drawdown > 20% policy / > 35% hard limit | pause & review / stop |
| `concentration_breach` | warning / critical | top-name weight > 25% / > 30% | confirm EWMA smoothing |
| `missed_day` | warning / critical | ≥2 days since last run / ≥4 gap or ≥2 missed | run today's day; investigate the gap |
| `data_stale` | warning | latest bar behind today | `statarb download-data` |
| `data_missing` | warning / critical | data-quality events > 0 / > 3 | `statarb data-audit` |
| `benchmark_underperformance` | warning / critical | ≥15 days and excess < −10ppt / < −20ppt | run paper-vs-backtest |
| `turnover_drift` | warning | turnover < 0.3× or > 2.5× expected | check rebalance schedule |
| `cash_drag_high` | warning | uninvested cash > 30% | check why targets aren't filled |
| `tca_degradation` | warning | realised slippage > 3× expected and > 25bps | check liquidity / limit offsets |
| `broker_error` | warning / critical | demo broker errors > 0 / > 3 | `trading212-demo-setup-check` |
| `rejected_orders` | warning | reject rate > 10% over ≥10 attempts | inspect rejected orders |
| `skipped_orders_high` | warning | ≥20 cumulative skipped/refused | review refusal reasons |
| `report_missing` | warning | latest daily summary file missing | re-run today's day |
| `duplicate_day_blocked` | info | a second run today was blocked | none — guard working |
| `final_review_ready` | info | ≥30 forward days recorded | generate the final report (NOT live) |

## Severity → action

- **critical** — stop / fix the underlying issue. Surfaces first in the Command
  Center's Today's Action and blocks manual resolution while active.
- **warning** — review on Paper Monitoring; resolve with a note once understood.
- **info** — a milestone or benign event; acknowledge and resolve.
