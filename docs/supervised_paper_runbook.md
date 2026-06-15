# Supervised Paper Runbook — long-only Trading 212

**Audience:** the day-to-day operator (no expertise assumed).
**Goal:** run a safe, repeatable, auditable 30–90 day *forward* supervised
shadow/paper period for the long-only Trading 212 candidate.

> ⛔ **LIVE TRADING IS BLOCKED.** Nothing in this runbook can place a real-money
> order. The Trading 212 live endpoint is not reachable from this system; CFDs,
> shorting and margin are impossible. The most that can happen is an order sent
> to the Trading 212 **DEMO** account.

---

## 0. The one thing to do every trading day

```
statarb supervised-paper-daily --product long_only_t212 --mode shadow
```

Then read the last line. It is one of:

- `Shadow day recorded successfully.`
- `Demo preview recorded successfully.`
- `Demo orders submitted successfully.`
- `Paper day refused: <reason>.`

And read the **Next action** line just above it. That's it. Everything below is
detail for when you want to understand what happened or something looks wrong.

---

## 1. The three modes (start here, escalate slowly)

You will almost always use **shadow**. Move to demo modes only once you have
demo API keys and want to exercise the broker plumbing.

| Mode | What it does | Needs broker keys? | Sends anything? |
|------|--------------|--------------------|-----------------|
| `shadow` | Generates the day's target weights and orders, validates them, records everything. **Offline.** | No | **No** |
| `demo_preview` | Connects to the Trading 212 **DEMO** account, plans against its real demo cash/positions, validates. | Yes (demo) | **No** |
| `demo_execute` | Same as preview, then submits the orders to the **DEMO** account — only if the full demo gate passes. | Yes (demo) | DEMO only |

### 1a. Daily shadow workflow (the default)
```
statarb supervised-paper-daily --product long_only_t212 --mode shadow
```
Run it once per trading day. It auto-starts the session on the first run.

### 1b. Daily demo_preview workflow (optional)
```
statarb trading212-demo-setup-check          # one-time: confirm demo keys work
statarb supervised-paper-daily --product long_only_t212 --mode demo_preview
```

### 1c. Optional demo_execute workflow (only when you want to test order submission)
```
statarb supervised-paper-daily --product long_only_t212 --mode demo_execute --confirm-demo
```
This submits to the **DEMO** account only, and only if every gate passes. Without
`--confirm-demo` it refuses. It can never reach live.

---

## 2. Required environment variables

Everything lives in `.env` (copy from `.env.example`; never commit it).

| Variable | For | Safe default |
|----------|-----|--------------|
| `LIVE_TRADING` | global live gate (keep off) | `false` |
| `CONFIRM_LIVE_TRADING` | global live gate (keep off) | `false` |
| `TRADING212_ENABLED` | enable the demo connector | `false` (set `true` for demo modes) |
| `TRADING212_MODE` | must be `demo` | `demo` |
| `TRADING212_API_KEY` / `TRADING212_API_SECRET` | your **demo** keys | empty |
| `TRADING212_ALLOW_DEMO_ORDERS` | allow `demo_execute` to submit | `false` (set `true` only for 1c) |
| `TRADING212_ALLOW_LIVE_ORDERS` | never consulted; leave false | `false` |
| `DASHBOARD_CONTROLS_ENABLED` | enable dashboard run buttons | `false` |

**Shadow mode needs none of these.** You can run the whole period in shadow with
an empty `.env`.

---

## 3. What each command does

| Command | What it does |
|---------|--------------|
| `supervised-paper-start --product long_only_t212 --mode shadow` | Starts the session (once). `supervised-paper-daily` also auto-starts it. |
| `supervised-paper-daily --product long_only_t212 --mode <mode>` | Runs the **whole** daily routine (below) and prints the next action. |
| `supervised-paper-health --product long_only_t212` | Your morning check: one status line + every metric. |
| `paper-vs-backtest --product long_only_t212` | Is the forward run *behaving* like the backtest? |
| `trading212-demo-setup-check` | Beginner check that your demo setup is correct (no secrets shown). |
| `supervised-paper-daily-report --product long_only_t212` | Re-print the most recent recorded day. |
| `supervised-paper-final-report --product long_only_t212` | The end-of-period pass/fail report (after ≥30 forward days). |
| `supervised-paper-stop --product long_only_t212 --reason "..."` | Manually stop the period. |
| `supervised-paper-preflight` | Final pre-flight check; writes `PAPER_PREFLIGHT_REPORT.md` (Ready / Not-ready). Run **before** you start. |
| `supervised-paper-monitor --product long_only_t212` | Health score (0–100, explained) + active alerts + suggested next action. |
| `supervised-paper-reminder --product long_only_t212` | Local nudge: does today need a run? alerts? reports due? Writes `runtime/paper/reminder.txt`. |
| `paper-monitoring-report` | Writes `PAPER_MONITORING_REPORT.md` + `PAPER_MONITORING_COMPLETION_REPORT.md`. |
| `supervised-paper-weekly-report --product long_only_t212` | Weekly review; writes `runtime/paper/weekly_report_YYYY-MM-DD.md` (continue / pause / investigate / fail). |
| `supervised-paper-start-report` | Regenerate `SUPERVISED_PAPER_START_REPORT.md`. |
| `forward-paper-start-report` | Regenerate `FORWARD_PAPER_START_REPORT.md` (is the forward period running? what's next?). |

> **One forward day per calendar day.** `supervised-paper-daily` records at most
> one forward day per day. Run it twice and the second run says *"Today's paper
> day is already completed — no duplicate recorded"* and changes nothing. Pass
> `--force` only if you genuinely must record a second day.

### What `supervised-paper-daily` does, step by step
1. Loads the current strategy config.
2. Verifies the product-decision still says **paper_candidate**.
3. Verifies **live trading is disabled**.
4. Verifies the **kill switch is off**.
5. Refreshes / loads market data (warns if stale).
6. Generates target weights and **applies EWMA smoothing**.
7. Validates the long-only constraints (no shorts, no leverage).
8. Validates the Trading 212 constraints (tradable, fractional, min order, cash) when a broker mode is used.
9. Builds the order **preview**.
10. In `demo_execute` only: submits to the **DEMO** account (gated).
11. Reconciles positions (demo modes).
12. Computes **paper PnL**.
13. Computes **benchmark (SPY) PnL**.
14. Computes **TCA** (expected vs realized slippage).
15. Computes **risk** metrics (drawdown, concentration, exposure).
16. Updates the session tables.
17. Writes the **daily report** + the daily summary file.
18. Evaluates the **stop rules**.
19. Prints the **exact next action**.

---

## 4. What files/tables are updated

All under `runtime/paper/` (git-ignored — generated data is never committed):

- `runtime/paper/long_only_t212/session.json` — the session (product, mode, start, min days).
- `runtime/paper/long_only_t212/daily_reports.jsonl` — one row per day.
- `.../orders.jsonl`, `.../reconciliations.jsonl`, `.../tca.jsonl`, `.../risk_snapshots.jsonl`, `.../benchmark_snapshots.jsonl`.
- `runtime/paper/latest_daily_summary.md` — the human summary of the most recent day (see §11).
- `runtime/shadow/paper_long_only_t212_book.json` — the simulated paper book (cash + positions).

---

## 5. What to check each day

Run `supervised-paper-health` (or open the **Operator Paper Mode** dashboard page) and confirm:

- **State** is `IN PROGRESS` (or `READY FOR FINAL REVIEW`).
- **Stop rules: none triggered.**
- `broker_errors` = 0, `rejected_orders` low.
- `concentration_top_weight` ≤ 0.25.
- `current_drawdown_pct` not alarming.
- `missing_days_gap` small (you didn't skip days).
- The daily checklist is all ✓.

---

## 6. What the warnings mean

| Warning | Meaning | Do |
|---------|---------|----|
| `latest bar ... is stale` | Market data hasn't been refreshed | run `statarb download-data` |
| `concentration above limit` | A single name exceeds 25% | confirm EWMA smoothing is active |
| `order reject rate too high` | Many orders skipped/rejected | inspect tradability / min order value |
| `demo broker errors exceeded` | Demo API failing | run `trading212-demo-setup-check` |
| `reconciliation drift too high` | Demo book drifted from target | re-plan / reconcile |
| `severe underperformance vs benchmark` | Far behind SPY (only after ~15 days) | run `paper-vs-backtest` |

Each stop rule prints its own **remediation** line.

---

## 7. When to STOP the paper period

Stop (and investigate) when health shows **FAILED**, or manually if you lose
confidence:
```
statarb supervised-paper-stop --product long_only_t212 --reason "why"
```
A **FAILED** state is terminal — start a fresh period with
`supervised-paper-start --reset` after fixing the cause.

---

## 8. When the kill switch triggers

If the kill switch is engaged (by you or by risk), the daily command **refuses**
with `kill switch is ENGAGED` and health shows **PAUSED**. The period is *paused*,
not failed: resolve the cause, then `statarb kill-switch --off`, then resume the
daily command. (Paper days simply don't record while the switch is on.)

---

## 9. How to produce daily reports

The daily command writes them automatically. To re-print or re-read:
```
statarb supervised-paper-daily-report --product long_only_t212   # last recorded day
cat runtime/paper/latest_daily_summary.md                        # human summary
```

## 10. How to produce the final report (after 30 days)

```
statarb supervised-paper-final-report --product long_only_t212
```
It **only** recommends PASS with ≥ 30 distinct **forward** calendar days. It writes
`reports/supervised_paper_final_long_only_t212.md`. Even a PASS is paper-only and
explicitly **not** a live authorization.

---

## 11. The daily notification summary

Every daily run writes `runtime/paper/latest_daily_summary.md` with the date,
mode, session health, target weights, planned/refused orders, paper & benchmark
PnL, risk status, TCA and the next action. It is structured so it can later be
forwarded to Telegram/Discord/email without changing how it is produced. (No
external notifications are configured yet — file + console only.)

---

## 12. Why replay does NOT count as a forward paper period

`supervised-paper-start --replay N` re-runs the last N historical bars to prove
the pipeline works. Those rows are labelled **REPLAY** and **never** count toward
the 30-day forward minimum. A supervised period is about *calendar time you
actually waited through* with the live data feed — you cannot fast-forward it.
The final report counts forward days separately and refuses to "pass" on replay.

---

## 13. Why live trading is still blocked

- The Trading 212 connector is hard-coded to `mode="demo", allow_live=False`; the live base URL is never constructed.
- `TRADING212_ALLOW_LIVE_ORDERS` is **never consulted** — no single flag can enable live.
- The global `LIVE_TRADING` gate is asserted **off** by the daily pre-flight.
- The product remains a directional long book that has not yet completed a real forward period or production/governance sign-off.

Live becomes a *conversation* only after a genuine forward period passes — and
even then it would require separate, deliberate engineering. This runbook never
enables it.
