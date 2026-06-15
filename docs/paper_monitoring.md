# Paper Monitoring

The monitoring layer turns the recorded supervised-paper session into a single,
explainable **health score**, a set of **alerts**, and a clear **next action** —
so the operator knows immediately whether the period is healthy, degraded, or
failing. It runs automatically after every daily paper run and on demand.

> ⛔ **NOT LIVE ELIGIBLE.** Monitoring observes a paper/shadow period. It cannot
> place an order and never asserts live eligibility.

## What it computes

`app/research/paper_monitor.py` composes the existing building blocks
(`paper_supervisor.health`, `paper_vs_backtest.compare`) and adds the milestone
flags. It produces, every run:

- days completed / missed / expected, last run, **next expected run**;
- paper / benchmark / **excess** return, daily volatility, drawdown, turnover,
  concentration, cash drag, holdings, tracking error, benchmark beta;
- order / skipped / rejected counts, broker + data-quality events, slippage/TCA;
- the paper-vs-backtest behaviour status and the stop-rule state;
- a **0–100 health score** with its component breakdown, and the **alerts**.

## The health score (`paper_health_score.py`)

A weighted blend of independent components, each scored 0–100 with a reason:

| component | weight | rewards |
| --- | --- | --- |
| operational_completeness | 0.20 | recording the expected forward days, no missed days |
| data_integrity | 0.12 | no stale data, no data-quality events |
| broker_integrity | 0.10 | no demo broker errors |
| risk_limits | 0.12 | no risk-snapshot breaches |
| concentration | 0.12 | top-name weight well under the 25% cap |
| drawdown | 0.12 | drawdown far from the policy / fail limits |
| turnover_drift | 0.08 | turnover near the backtest expectation |
| benchmark_relative | 0.08 | not underperforming the benchmark |
| paper_vs_backtest | 0.06 | behaving like the backtest |

**Hard overrides** on the *classification* (not the arithmetic): a FAILED stop
rule or lost eligibility ⇒ `failed` (score capped at 30); an engaged kill switch
or a PAUSED stop rule ⇒ `paused`. Otherwise the band is `healthy` (≥85),
`watch` (≥70), or `degraded`.

Classifications: **healthy · watch · degraded · failed · paused.**

## Alerts

See `paper_alert_rules.md` for the full catalogue. Alerts are condition-derived,
de-duplicated, persisted (`runtime/paper/<product>/paper_alerts.json`), and
auto-resolve when their condition clears (kept in history). A **critical** alert
whose condition is still active cannot be hand-resolved — fix the cause.

Health snapshots are appended to `runtime/paper/<product>/paper_health_snapshots.jsonl`
(one per day, latest wins) to drive the time-series charts.

## How to use it

- **Dashboard:** open **Paper Monitoring** (`/paper-monitor`) — score, components,
  charts, active + resolved alerts (resolve with an audited note), daily history.
  The **Command Center** shows the score, alert counts and next expected run.
- **CLI:** `statarb supervised-paper-monitor` prints the score breakdown + alerts;
  `statarb supervised-paper-reminder` writes a local nudge
  (`runtime/paper/reminder.txt`); `statarb paper-monitoring-report` writes
  `PAPER_MONITORING_REPORT.md` + `PAPER_MONITORING_COMPLETION_REPORT.md`.

## Endpoints

| method | path | purpose |
| --- | --- | --- |
| GET | `/api/paper/health` | full monitoring view + snapshots (read-only) |
| POST | `/api/paper/health/run` | run + persist (TRADER role, audited) |
| GET | `/api/paper/alerts` | active + resolved alerts with counts |
| POST | `/api/paper/alerts/{id}/resolve` | resolve with a note (TRADER, audited) |

None of these can place a live order.
