# Supervised Paper Dashboard Workflow

The supervised paper period is the **forward** out-of-sample test for long-only
Trading 212. You run one paper day per trading day, for at least the minimum
forward period (default 30 days), then generate a final report. Nothing here is
live; demo execution is gated.

All of this is driven from **Supervised Paper → Control Center**.

## Modes

| Mode | What it does | Sends orders? |
|---|---|---|
| `shadow` | Simulates the day end-to-end | No (no broker) |
| `demo_preview` | Connects to the Trading 212 **demo** API and validates | No |
| `demo_execute` | Submits orders to the **demo** account when the full gate passes | Demo only |

Replay days never count as forward days.

## 1. Start a session

Supervised Paper → choose **Mode**, **Min forward days** (default 30) and
**Starting cash** → **Start session**. Start in `shadow`.

* Action: `supervised_paper_start` (trader role; requires a paper-eligible
  product).
* If a stopped session already exists, pass `reset` to start a fresh one.

## 2. Run a shadow day

**Run shadow day** → action `supervised_paper_daily_shadow`. Simulated, sends
nothing. Do this daily while you build confidence.

## 3. Run a demo preview day

**Run demo preview day** → action `supervised_paper_daily_demo_preview`. Connects
to the Trading 212 demo API and validates the plan, but **submits nothing**.
Requires demo credentials configured.

## 4. Run a gated demo execute day

**Run demo execute day…** opens a confirmation modal. Type the exact phrase
**`RUN DEMO PAPER DAY`** to proceed. This is the **only** path that sends demo
orders. It requires, and re-checks server-side:

1. controls enabled (admin)
2. phrase `RUN DEMO PAPER DAY`
3. demo env: `TRADING212_ENABLED` + `TRADING212_MODE=demo` +
   `TRADING212_ALLOW_DEMO_ORDERS=true` (and the live flag **not** set)
4. paper-eligible product
5. kill switch off

Any missing condition → **refused** (audited), nothing sent. Orders go to the
**demo** account only — live is hard-blocked.

> There is no live button and no standalone order button. Demo orders exist only
> inside this gated daily run.

## 5. Monitor health

The Control Center and the Health Monitor show:

* forward days completed / minimum, days remaining, last run date, gap
* paper PnL vs benchmark, drawdown, concentration top-weight
* turnover, slippage, rejected orders, risk breaches
* **stop rules** — any triggered rule with severity, detail, and remediation

Action: `supervised_paper_health` (read-only, viewer).

## 6. Generate the final report

**Generate final report** → action `supervised_paper_final_report`. It **refuses
to PASS** before the minimum forward days are complete. The result shows a
recommendation (PASS / not yet), a verdict, and `live eligible: false`, and writes
`supervised_paper_final_<product>.md` to the reports directory (open it from
Reports Library).

## 7. Stop a session

**Stop session…** → type **`STOP PAPER SESSION`** (admin). Ends the active forward
period and records the reason. Start a new session (with reset) to resume. Stopping
does not enable anything live.

## The daily routine (most days)

1. Command Center → read **Today's required action**.
2. If it says *Run today's shadow / demo-preview day*, click through to Supervised
   Paper and run the day in your chosen mode.
3. Watch the job progress; read the result.
4. Open any generated report in Reports Library.
5. Done. If *No action needed today*, stop.

## State → action quick reference

| Session state | Today's action |
|---|---|
| no session | Start a supervised paper session |
| active, nothing today | Run today's shadow / demo-preview day |
| active, ran today | No action needed today |
| active, multi-day gap | Review the missed paper day(s) |
| failed run | Review the failed job |
| minimum reached | Generate the final paper report |
| not a paper candidate | Stop and review the product decision |
| kill switch engaged | Resolve the kill switch first |

See also `dashboard_operator_guide.md` and `trading212_dashboard_workflow.md`.
