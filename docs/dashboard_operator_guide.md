# Dashboard Operator Guide

The web dashboard is the **primary control panel** for running the long-only
Trading 212 supervised shadow/paper workflow. For normal day-to-day operation you
do **not** need a terminal — the terminal is only for initial install, editing
`.env`, dev mode, emergency fallback, and advanced debugging.

> ⛔ **This system is NOT LIVE ELIGIBLE.** No real-money order can be placed from
> the dashboard or the CLI. The most powerful broker action available anywhere is
> a Trading 212 **DEMO** order, and even that is gated (see below).

---

## 1. Open the dashboard

From the project root, in a terminal (one-time per machine / per boot):

```bash
# build the frontend bundle once (or after a frontend change)
cd frontend && npm install && npm run build && cd ..

# start the API + dashboard (serves the built bundle)
statarb dashboard
```

Then open the printed URL (default `http://127.0.0.1:8000`). Keep the server bound
to `127.0.0.1` — it is a single-operator local panel.

By default the dashboard is **READ-ONLY**: you can see everything, but every
control (anything that runs a job) is disabled. To enable controls, set in `.env`:

```dotenv
DASHBOARD_CONTROLS_ENABLED=true
```

and restart the backend. The top bar shows `controls` (enabled) or `read-only`.

---

## 2. The layout

* **Top safety bar** (always visible): `NOT LIVE ELIGIBLE`, current mode, product
  decision, kill-switch state, Trading 212 demo state, controls/read-only, backend
  connection, and the last update time.
* **Left sidebar** (collapsible): grouped navigation — Command Center, Long-only
  T212, Supervised Paper, Broker, Risk & Safety, Research, System.
* **Main area**: the selected page.

### What each page does

| Group | Page | Purpose |
|---|---|---|
| Command Center | **Overview** | Today's single required action + product standing + recent activity |
| Command Center | **Product Decision** | What to trade, recommended action; rerun the decision |
| Command Center | **Tradability** | Per-product tradability matrix |
| Long-only T212 | **Readiness** | Readiness gate scorecard (e.g. 18/18); rerun the battery |
| Long-only T212 | **Concentration** | Return-concentration gate; rerun + EWMA-vs-unsmoothed |
| Long-only T212 | **Survivorship** | Survivor-set perturbation bound; rerun |
| Long-only T212 | **Crisis Lab** | Synthetic crisis stress; rerun + scenario chart |
| Long-only T212 | **Order Preview** | What a paper day would plan today (sends nothing) |
| Supervised Paper | **Control Center** | Start / run / monitor / close the supervised paper period |
| Supervised Paper | **Daily Run / Monitor** | Operator daily run + health monitor |
| Broker | **Trading 212 Setup** | Verify the demo connection (secrets never shown) |
| Risk & Safety | **Safety Center** | Kill switch, what is structurally blocked, audit trail |
| Risk & Safety | **Live Readiness / Blockers** | The live gate (always false) and remaining blockers |
| Research | **Reports Library** | Browse / open / download every generated report |
| System | **Logs & Audit / Settings** | Logs, settings (read-only), and lower-level pages |

---

## 3. What to do each day (normal operation)

1. Open **Command Center → Overview**.
2. Read the **"Today's required action"** card. It tells you exactly one thing to
   do, with a primary button to the right page. Possible states:
   * *Start a supervised paper session* (no session yet)
   * *Run today's shadow / demo-preview day* (session active, nothing today)
   * *No action needed today* (already ran today)
   * *Review the missed paper day(s)* (a gap opened)
   * *Review the failed job* (a run failed)
   * *Run the Trading 212 setup check* (broker not configured)
   * *Stop and review the product decision* (no longer a paper candidate)
   * *Resolve the kill switch* (kill switch engaged)
   * *Generate the final paper report* (minimum forward period reached)
3. Click the button, **watch the job progress** bar, and read the result.
4. If a report was produced, open it in **Reports Library**.
5. Check the **audit trail** in Safety Center if you want a record of what ran.
6. Stop — there is nothing else to do most days.

---

## 4. How to run the core actions

* **Start a paper session** — Supervised Paper → choose mode (`shadow`,
  `demo_preview`, `demo_execute`) → *Start session*. Start in `shadow`.
* **Run a shadow day** — Supervised Paper → *Run shadow day*. Sends nothing.
* **Run a demo preview** — Supervised Paper → *Run demo preview day*. Connects to
  the Trading 212 **demo** API, validates, but submits nothing.
* **Run a gated demo execute day** — Supervised Paper → *Run demo execute day…* →
  type the exact phrase **`RUN DEMO PAPER DAY`** in the modal. Requires controls,
  `TRADING212_ALLOW_DEMO_ORDERS=true`, and a paper-candidate product.
* **Preview orders** — Order Preview → *Generate shadow preview*. This page never
  sends orders and has **no** order-sending button.
* **Rerun a diagnostic** — open the page (Concentration / Crisis / Survivorship /
  Readiness / Product Decision) and click its rerun button.
* **Generate the final report** — Supervised Paper → *Generate final report* (only
  PASSES after the minimum forward days).

---

## 5. Why there is no live button (and no standalone order button)

* **No live button anywhere.** There is no job type, endpoint, or UI control that
  can place a real-money order. `TRADING212_ALLOW_LIVE_ORDERS` is never consulted
  by any executor; if it were ever set, demo actions refuse loudly.
* **No standalone demo-order button.** Demo orders are only ever sent *inside* the
  gated supervised paper daily run (`demo_execute`). The Order Preview page is a
  read-only planning view. This keeps every order behind the full daily gate.

See `docs/dashboard_safety_model.md` for the full model.

---

## 6. Confirmation phrases

| Action | Exact phrase |
|---|---|
| Run a demo execute paper day | `RUN DEMO PAPER DAY` |
| Stop a supervised paper session | `STOP PAPER SESSION` |
| Engage the kill switch | `ACTIVATE KILL SWITCH` |
| Disengage the kill switch | `DISENGAGE KILL SWITCH` |

Phrases must be typed **exactly** (case-sensitive) — the Confirm button stays
disabled until they match, and the backend re-checks them.

---

## 7. What to do when a job is refused

A **refused** job is normal and safe — the backend re-validated a gate and
declined. The job shows a refusal reason (also written to the audit trail). Common
reasons and fixes:

| Refusal reason | Fix |
|---|---|
| dashboard is READ-ONLY | set `DASHBOARD_CONTROLS_ENABLED=true`, restart |
| this action requires the '…' role | enable controls (single-operator → admin) |
| kill switch is ENGAGED | disengage it in Safety Center first |
| confirmation phrase mismatch | type the exact phrase |
| demo orders are blocked | set the demo env vars (see Trading 212 doc) |
| product '…' is not paper-eligible | review Product Decision |

---

## 8. How to read the audit trail

Safety Center → **Audit trail** lists every dashboard action (allowed or refused)
with timestamp, actor, action, and result. Refused and approved jobs are also
summarised on that page. Every action — including refusals — is recorded.

---

## 9. How to stop safely

* To pause everything immediately: Safety Center → **Engage kill switch**
  (`ACTIVATE KILL SWITCH`). It persists across restarts until disengaged.
* To end a paper period: Supervised Paper → **Stop session…** (`STOP PAPER
  SESSION`).
* To shut the dashboard down: stop the `statarb dashboard` process. Nothing live
  is ever running, so there is no open real-money exposure to flatten.

---

## 10. Switching between dark mode and light mode

The dashboard ships with a polished **dark** theme and a premium **light** theme.
A theme toggle sits in the **top bar**, on the right next to the clock. Click it
to cycle through three preferences:

| Icon | Preference | Behaviour |
| --- | --- | --- |
| 🌙 moon | **Dark** | Always the dark theme (the default). |
| ☀️ sun | **Light** | Always the light theme. |
| 🖥️ monitor | **System** | Follows your operating system's light/dark setting, live. |

- Your choice is saved in the browser's `localStorage` under the key
  `statarb.theme`, so it persists across reloads and restarts (per browser).
- In **System** mode the dashboard switches automatically when your OS flips
  between light and dark.
- The theme is applied before the page paints, so there is no flash of the wrong
  theme on load.

**The theme is purely cosmetic.** It does **not** change trading logic, the
product decision, the stop rules, or any safety gate. In both themes the red
**NOT LIVE ELIGIBLE** badge, an active kill switch, the live-trading banner, and
demo-only / shadow-mode banners all stay highly visible, and danger/refused
actions stay visually distinct. There is no "go live" control in either theme —
the live order path does not exist.

---

## 11. Daily, weekly and pre-flight reports

- **Pre-flight** (before you start a period): `statarb supervised-paper-preflight`
  writes `PAPER_PREFLIGHT_REPORT.md` and prints a Ready / Not-ready verdict.
- **Weekly** (during the period): `statarb supervised-paper-weekly-report` writes
  `runtime/paper/weekly_report_YYYY-MM-DD.md` with a continue / pause / investigate
  / fail recommendation. The dashboard exposes the same data at
  `GET /api/operator/weekly-report`.
- **Final** (after ≥30 forward days): `statarb supervised-paper-final-report`.

All of these reports also appear in the dashboard **Reports Library**, which is
fully themed in both light and dark mode.

---

## 12. Paper Monitoring page

The **Paper Monitoring** page (`/paper-monitor`, "Health Monitor" in the sidebar)
is the quality-control cockpit for the running paper period:

- a **0–100 health score** with its classification (healthy / watch / degraded /
  failed / paused) and the component breakdown that explains it;
- every metric (days, PnL vs benchmark, drawdown, concentration, turnover, cash
  drag, tracking error, stop-rule state);
- charts: health score, paper-vs-benchmark PnL, concentration, and alerts over
  time;
- the **active** and **resolved** alert tables. Resolve a non-critical alert with
  a note (recorded in the audit trail) — a critical alert whose condition is still
  active is refused until you fix the cause.

The **Command Center** mirrors the headline: health score, critical/warning alert
counts, and the next expected run; a critical alert becomes Today's Action. See
`paper_monitoring.md` and `paper_alert_rules.md` for the full rules.

---

See also: `paper_monitoring.md`, `paper_alert_rules.md`, `dashboard_actions.md`,
`dashboard_permissions.md`,
`dashboard_safety_model.md`, `trading212_dashboard_workflow.md`,
`supervised_paper_dashboard_workflow.md`.
