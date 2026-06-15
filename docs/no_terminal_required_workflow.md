# No-terminal operator workflow

The dashboard is now the primary control panel. For the normal supervised-paper
loop you do **not** need the terminal — the CLI remains only for development and
emergency fallback.

## One-time setup (terminal, once)

1. Configure `.env` (secrets never go in the browser):
   ```
   DASHBOARD_CONTROLS_ENABLED=true       # enables actions; keep the server on 127.0.0.1
   TRADING212_ENABLED=true
   TRADING212_MODE=demo
   TRADING212_API_KEY=<demo key>
   TRADING212_API_SECRET=<demo secret>
   TRADING212_ALLOW_DEMO_ORDERS=false    # flip to true only when ready for demo_execute
   TRADING212_ALLOW_LIVE_ORDERS=false    # never true — and never consulted
   ```
2. Build + start:
   ```
   cd frontend && npm install && npm run build
   statarb dashboard
   ```
3. Open the dashboard (bound to localhost).

Everything below is done **in the browser**.

## The daily loop (dashboard only)

1. **Command Center → Overview.** Read the big *Today's required action* card. It
   names the single next safe step and links straight to it.
2. **Trading 212 Setup** (first run / whenever config changes). Click *Run setup
   check*. Confirm the demo checklist is green. Secrets are never shown.
3. **Supervised Paper → Control Center.**
   - If no session: pick a mode (`shadow` / `demo_preview` / `demo_execute`), set
     min days + starting cash, click **Start session**.
   - Each trading day: click **Run shadow day** (or **Run demo preview day**). For
     **Run demo execute day** you must type `RUN DEMO PAPER DAY`, hold admin
     controls, and have `TRADING212_ALLOW_DEMO_ORDERS=true` — all re-checked on the
     server.
   - Watch the live **job progress**; the daily summary (orders planned/refused,
     TCA, target weights) is captured as a report.
4. **Health & drift.** The Control Center shows forward-days completed, days
   remaining, paper-vs-benchmark PnL, drawdown, concentration, turnover, rejected
   orders and the stop rules. Use **Daily Run** / **Monitor** for per-day detail.
5. **Reports Library.** View or download any report (paper, crisis, concentration,
   survivorship, product decision) right in the browser.
6. **Safety Center.** Check the kill switch, the structurally-blocked features, and
   the audit trail. Engage the kill switch (`ACTIVATE KILL SWITCH`) any time;
   disengage is stricter (`DISENGAGE KILL SWITCH`, admin).
7. After the minimum forward days, click **Generate final report**. It refuses to
   PASS early and never asserts live eligibility.

## What is impossible from the dashboard

- Placing a **live order** — there is no endpoint, no button, no job type for it.
- **CFDs, shorting, margin/leverage** on Trading 212.
- **Entering secrets** in the browser.
- Bypassing a gate — every action is re-validated server-side and audited, whether
  it came from the dashboard or the CLI.

## When the terminal is still useful

- Initial data download, DB init, research sweeps under `scripts/`.
- Deep crypto/futures research commands not part of the operator loop.
- Emergency fallback if the web server itself is down (e.g. `statarb kill-switch`,
  `statarb supervised-paper-daily`).

See also: `docs/dashboard_capability_map.md`, `DASHBOARD_COMPLETION_REPORT.md`.
