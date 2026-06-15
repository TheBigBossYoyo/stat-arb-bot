# Dashboard — No-Terminal Acceptance

Branch: `paper-long-only-t212`. Invariant throughout: **NOT LIVE ELIGIBLE**.

> **Verdict:** *Normal operator workflow is dashboard-supported. The terminal is
> only needed for initial install, environment setup (`.env`), dev mode, emergency
> fallback, and advanced debugging.*

Each answer names the page and the endpoint behind it. Every action runs through
the audited orchestrator and re-validates its gates server-side.

| # | Question | Answer | Where / how |
|---|---|---|---|
| 1 | Can the operator start the dashboard? | **Yes** | `cd frontend && npm run build` then `statarb dashboard`; open `http://127.0.0.1:8000` |
| 2 | Can the operator see the product decision? | **Yes** | Command Center → Product Decision (`GET /api/product-decision`) |
| 3 | Can the operator rerun the product decision? | **Yes** | Product Decision → *Rerun product decision* (`POST /api/product-decision/run`) |
| 4 | Can the operator see long-only paper candidacy? | **Yes** | Readiness page + Command Center status grid (paper-candidate badge, gates X/Y) |
| 5 | Can the operator rerun readiness? | **Yes** | Readiness → *Rerun long-only readiness* (`POST /api/long-only/readiness/run`) |
| 6 | Can the operator see concentration diagnostics? | **Yes** | Concentration page (`GET /api/concentration/...` + last run) |
| 7 | Can the operator rerun concentration diagnostics? | **Yes** | Concentration → *Rerun* + *Compare EWMA vs unsmoothed* (`/api/long-only/concentration/run`, `/compare-fixes`) |
| 8 | Can the operator see survivorship diagnostics? | **Yes** | Survivorship page |
| 9 | Can the operator rerun survivorship diagnostics? | **Yes** | Survivorship → *Rerun survivorship stress* (`POST /api/long-only/survivorship/run`) |
| 10 | Can the operator see crisis diagnostics? | **Yes** | Crisis Lab (scenario chart + table + report) |
| 11 | Can the operator rerun crisis diagnostics? | **Yes** | Crisis Lab → *Rerun crisis test* (`POST /api/long-only/crisis/run`) |
| 12 | Can the operator run the Trading 212 setup check? | **Yes** | Trading 212 Setup → *Run setup check* (`POST /api/trading212/setup-check`) |
| 13 | Can the operator preview orders? | **Yes (sends nothing)** | Order Preview → *Generate shadow / demo preview* (`POST /api/trading212/order-preview`) |
| 14 | Can the operator start supervised paper? | **Yes** | Supervised Paper → *Start session* (`POST /api/paper/start`) |
| 15 | Can the operator run a daily shadow day? | **Yes** | Supervised Paper → *Run shadow day* (`POST /api/paper/daily`, `mode=shadow`) |
| 16 | Can the operator run a daily demo_preview? | **Yes** | Supervised Paper → *Run demo preview day* (`mode=demo_preview`) — validates, sends nothing |
| 17 | Can the operator run a gated demo_execute? | **Yes, fully gated** | Supervised Paper → *Run demo execute day…* → phrase `RUN DEMO PAPER DAY` + admin + demo env + product OK |
| 18 | Can the operator view paper health? | **Yes** | Control Center + Health Monitor (`GET /api/paper/health`) — days, PnL, drawdown, stop rules |
| 19 | Can the operator generate reports? | **Yes** | Final report (`POST /api/paper/final-report`); diagnostics write reports; all in Reports Library |
| 20 | Can the operator view the audit trail? | **Yes** | Safety Center → Audit trail (`GET /api/audit`) — every action, allowed or refused |
| 21 | Can the operator engage the kill switch? | **Yes** | Safety Center → *Engage* → `ACTIVATE KILL SWITCH` (`POST /api/risk/kill-switch/engage`) |
| 22 | Can the operator disengage with stricter confirmation? | **Yes** | Safety Center → *Disengage* → admin + `DISENGAGE KILL SWITCH` |
| 23 | Are live orders possible? | **No** | No live job type / endpoint / executor; the live flag is never consulted; every result is `live_eligible: false` |
| 24 | Are secrets exposed? | **No** | Config/settings return booleans only; setup check scrubs secrets; browser entry disabled; tests assert no secret leaks |
| 25 | Which workflows remain CLI-only, and why? | See below | install/build, `.env`, dev mode, data/DB init, research sweeps, emergency fallback, advanced debugging |

## CLI-only workflows (and why)

| Workflow | Why it stays in the terminal |
|---|---|
| `npm install` / `npm run build` | one-time/asset build; not a daily operator task |
| Editing `.env` (controls flag, demo credentials) | secrets and process configuration — intentionally never in the browser |
| Vite dev server (`npm run dev`) | development only |
| Initial market-data download / DB init | ops bootstrap, run once |
| Research sweeps / deep crypto/futures research (`scripts/`) | developer research outside the operator loop |
| Emergency fallback / advanced debugging | last-resort access; the dashboard is the normal path |

## Safety confirmations

* **Live trading:** structurally impossible — no live job type, endpoint, or
  executor; `TRADING212_ALLOW_LIVE_ORDERS` is inert and demo actions refuse if it
  is set.
* **Standalone orders:** none — demo orders are only sent inside the gated
  supervised paper `demo_execute` day. The Order Preview page has no send button.
* **CFDs / shorting / margin / leverage:** unsupported by construction.
* **Audit:** every action attempt (allowed or refused) is recorded.

## Test evidence

* Backend: `pytest` — full suite green, including `test_dashboard_actions.py`
  (25 tests: gate refusals, kill-switch blocks, demo gating, reports, audit,
  no-secrets). `ruff check .` clean.
* Frontend: `npm run typecheck` ✅, `npm run test:run` ✅ (28 tests), `npm run
  build` ✅.
