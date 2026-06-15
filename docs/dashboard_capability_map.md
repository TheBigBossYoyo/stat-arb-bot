# Dashboard Capability Map

> **Status:** Phase 1 deliverable of the "dashboard as primary control panel" sprint.
> **Audience:** the operator and the engineer extending the dashboard.
> **Hard rule:** the dashboard is **NOT LIVE ELIGIBLE**. No endpoint, button, or job
> in this map can place a live order. Every broker-touching action is Trading 212
> **demo only** and is re-validated server-side regardless of how it was triggered.

This document maps every important CLI command to its dashboard coverage so we can
see exactly what is already controllable from the web UI and what still requires the
terminal. It is the source of truth for the remaining phases of the sprint.

## Legend

**Status**

- ✅ `done` — fully usable from the dashboard (read + any required action).
- 🟡 `partial` — some coverage (usually read-only, or action exists but UX/gates incomplete).
- ❌ `missing` — no dashboard equivalent yet; terminal required.
- 🖥 `cli-only` — intentionally left to the terminal (dev / server lifecycle).

**Safety level**

- `read` — read-only, no side effects.
- `research` — runs a research/backtest job; writes reports/DB rows, touches no broker.
- `paper` — paper/shadow action; simulated, no broker connection.
- `demo` — broker-touching **Trading 212 demo** action (connect / validate / demo order).
- `danger` — operational control (kill switch, stop session) with broad effect.

**Confirmation**

- `none` — safe GET / idempotent.
- `role` — requires `DASHBOARD_CONTROLS_ENABLED` + sufficient role.
- `phrase` — requires an exact typed confirmation phrase.
- `phrase+env` — exact phrase **and** an environment gate (e.g. `TRADING212_ALLOW_DEMO_ORDERS=true`).

**Audit** — whether the action must write an audit event (`yes`/`n/a` for reads).

---

## Workflow coverage

### Command Center / product

| CLI command | Purpose | Backend endpoint | Frontend page | Status | Safety | Confirm | Audit |
|---|---|---|---|---|---|---|---|
| `statarb product-decision` | Lead product, action, capital stage; never live | `GET /api/product-decision` ✅ · `POST /api/product-decision/run` ❌ | `ProductDecisionPage` | 🟡 read only, no rerun button | research | role | yes |
| `statarb report` | Build/list research reports | — ❌ (no `/api/reports`) | — ❌ (no Reports Library) | ❌ | research | role | yes |
| `statarb dashboard` | Start the control-panel server | n/a | n/a | 🖥 cli-only | — | — | n/a |

### Long-only Trading 212 readiness & diagnostics

| CLI command | Purpose | Backend endpoint | Frontend page | Status | Safety | Confirm | Audit |
|---|---|---|---|---|---|---|---|
| `statarb long-only-readiness` | 18/18 paper-readiness gates | `GET /api/live-readiness` 🟡 · `GET /api/blockers` 🟡 · `POST /api/long-only/readiness/run` ❌ | `LiveReadinessPage`, `LongOnlyPaperSetupPage` | 🟡 partial gate view, no full 18-gate breakdown or rerun | research | role | yes |
| `statarb concentration-fix-backtest` | Concentration diagnostics (EWMA smoothing) | `GET /api/concentration/{strategy}` 🟡 (reads latest md) · `POST /api/long-only/concentration/run` ❌ | `ConcentrationDiagnosticsPage` | 🟡 read latest report only | research | role | yes |
| `statarb compare-concentration-fixes` | Compare smoothing variants | — ❌ · `POST /api/long-only/concentration/compare-fixes` ❌ | — ❌ | ❌ | research | role | yes |
| `statarb survivorship-stress-long-only` | Survivorship perturbation bound | — ❌ (no `/api/survivorship`) · `POST /api/long-only/survivorship/run` ❌ | — ❌ (no `SurvivorshipPage`) | ❌ | research | role | yes |
| `statarb crisis-test-long-only` | Synthetic crisis scenarios | `GET /api/crisis/{strategy}` 🟡 (reads md) · `POST /api/long-only/crisis/run` ❌ | `CrisisLabPage` | 🟡 read latest report only | research | role | yes |

### Trading 212 setup & order preview

| CLI command | Purpose | Backend endpoint | Frontend page | Status | Safety | Confirm | Audit |
|---|---|---|---|---|---|---|---|
| `statarb trading212-check` | Connection/config sanity | `GET /api/trading212-config` 🟡 (booleans) · `GET /api/brokers` ✅ | `Brokers` | 🟡 config booleans only | read | none | n/a |
| `statarb trading212-demo-setup-check` | 12-step demo readiness wizard | — ❌ · `GET /api/trading212/setup-status`, `POST /api/trading212/setup-check` ❌ | — ❌ (no `Trading212SetupPage`) | ❌ | demo | role | yes |
| `statarb trading212-instruments` | Instrument metadata | — ❌ · `GET /api/trading212/instruments` ❌ | — ❌ | ❌ | read | none | n/a |
| `statarb long-only-order-preview` | Shadow order plan (sends nothing) | `GET /api/long-only-order-preview` ✅ | `Trading212OrderPreviewPage` | ✅ shadow preview | paper | none | n/a |
| `statarb paper-trade-long-only --mode demo_preview` | Connect + validate, send nothing | `POST /api/operator/run/demo_preview` ✅ | `OperatorPaperModePage` | ✅ | demo | role | yes |
| `statarb paper-trade-long-only --mode demo_execute --confirm-demo` | Send **demo** orders only | `POST /api/operator/run/demo_execute` ✅ (phrase `RUN DEMO PAPER DAY`) | `OperatorPaperModePage` | 🟡 works, but no dedicated Order-Preview "Send demo orders" button + `SEND DEMO ORDERS` phrase + env gate | demo | phrase+env | yes |

### Supervised paper session

| CLI command | Purpose | Backend endpoint | Frontend page | Status | Safety | Confirm | Audit |
|---|---|---|---|---|---|---|---|
| `statarb supervised-paper-start` | Begin a supervised paper session | — ❌ · `POST /api/paper/start` ❌ | — ❌ (no start control) | ❌ | paper | phrase | yes |
| `statarb paper-trade-long-only --mode shadow` / `supervised-paper-daily` | Run today's shadow day | `POST /api/operator/run/shadow` ✅ · `POST /api/paper/daily` (alias) ❌ | `OperatorPaperModePage` | ✅ | paper | role | yes |
| `statarb supervised-paper-daily --mode demo_preview` | Run today's demo-preview day | `POST /api/operator/run/demo_preview` ✅ | `OperatorPaperModePage` | ✅ | demo | role | yes |
| `statarb supervised-paper-daily --mode demo_execute` | Run today's demo-execute day | `POST /api/operator/run/demo_execute` ✅ | `OperatorPaperModePage` | ✅ | demo | phrase+env | yes |
| `statarb supervised-paper-status` | Session status | `GET /api/paper-status/{product}` ✅ | `SupervisedPaperMonitorPage` | ✅ | read | none | n/a |
| `statarb supervised-paper-health` | Forward-period health | `GET /api/operator/status` ✅ (embeds health) · `GET /api/paper/health` ❌ (alias) | `OperatorPaperModePage` | ✅ | read | none | n/a |
| `statarb supervised-paper-daily-report` | Today's paper summary | `GET /api/operator/status` 🟡 (`latest_summary`) | `OperatorPaperModePage` | 🟡 latest only, no per-day history | read | none | n/a |
| `statarb supervised-paper-final-report` | Final review (refuses < min days) | `GET /api/paper-final/{product}` 🟡 (read) · `POST /api/paper/final-report` ❌ | `SupervisedPaperMonitorPage` | 🟡 read only, no generate action | research | role | yes |
| `statarb supervised-paper-stop` | Stop the session | — ❌ · `POST /api/paper/stop` ❌ (phrase `STOP PAPER SESSION`) | — ❌ | ❌ | danger | phrase | yes |
| `statarb paper-vs-backtest` | Paper vs backtest drift | `GET /api/operator/paper-vs-backtest` ✅ | `OperatorPaperModePage` | ✅ | read | none | n/a |

### Risk & safety

| CLI command | Purpose | Backend endpoint | Frontend page | Status | Safety | Confirm | Audit |
|---|---|---|---|---|---|---|---|
| `statarb kill-switch --engage` | Halt all activity | `POST /api/risk/kill-switch/activate` ✅ (phrase `ACTIVATE KILL SWITCH`) | `KillSwitch` component | ✅ | danger | phrase | yes |
| `statarb kill-switch --disengage` | Resume | `POST /api/risk/kill-switch/deactivate` ✅ (phrase `DEACTIVATE KILL SWITCH`) | `KillSwitch` component | 🟡 works; spec wants phrase `DISENGAGE KILL SWITCH` + stricter warnings + a Safety Center page | danger | phrase | yes |
| (live readiness) | Always NOT LIVE ELIGIBLE | `GET /api/live-readiness` ✅ | `LiveReadinessPage` | ✅ | read | none | n/a |
| (audit trail) | Every audited action | `GET /api/audit` ✅ | `Logs` | 🟡 shown in Logs; no dedicated Safety Center | read | none | n/a |

### Settings

| CLI surface | Purpose | Backend endpoint | Frontend page | Status | Safety | Confirm | Audit |
|---|---|---|---|---|---|---|---|
| `.env` / settings | Safe config + env flags (no secrets) | `GET /api/settings` ✅ · `GET /api/settings/env-status`, `/api/settings/broker-status` ❌ | `Settings` | 🟡 masked config; missing env-status / broker-status split + strategy/risk/smoothing config | read | none | n/a |

---

## What is already strong

- A real **read** surface exists end-to-end: system status, product decision, tradability
  matrix, blockers, live-readiness, concentration/crisis report viewers, deflated Sharpe,
  Trading 212 config (booleans only), shadow order preview, supervised-paper status / final /
  health, paper-vs-backtest, audit, masked settings.
- The **NOT LIVE ELIGIBLE** invariant is enforced: `live_eligible` is hard-`False` in every
  product endpoint; `trading212_allow_live_orders` is a hard block; `flatten-all` and
  `cancel-all-orders` return `501` because no live connector exists.
- Control actions already audited and gated: kill switch engage/deactivate, strategy
  pause/resume, `operator/run/{shadow|demo_preview|demo_execute}`, backtest/pair-discovery jobs.
- Confirmation + role model exists (`require_role`, `require_phrase`, `CONFIRM_PHRASES`).
- Secrets never leave the server — settings views report only *whether* a key is configured.

## Missing dashboard features (drives Phases 2–18)

1. **No general job orchestrator.** `DashboardService.start_job` only handles `backtest` and
   `discover_pairs`. The diagnostics/paper/report jobs in the spec have no job type, no status
   lifecycle (`queued/running/succeeded/failed/refused/cancelled`), no logs stream, no
   cancellation, no dedup/conflict guard. → **Phase 2** (`app/dashboard/actions.py`, `jobs.py`,
   `job_store.py`, `action_schemas.py`, `action_permissions.py`, `action_audit.py`).
2. **No "run" endpoints** for product-decision, long-only readiness, concentration (+ compare
   fixes), survivorship, crisis. Today these are CLI-only; the dashboard can only read the last
   report. → **Phase 3**.
3. **No supervised-paper lifecycle actions**: `start`, `stop` (phrase `STOP PAPER SESSION`),
   `final-report` generate. Only the daily run + reads exist. → **Phase 3 / 6**.
4. **No Trading 212 setup wizard** (12-step `trading212-demo-setup-check`) and no
   `instruments` endpoint/page. → **Phase 3 / 7**.
5. **No Order-Preview demo-execute UX**: dedicated page with "Send demo orders" button, phrase
   `SEND DEMO ORDERS`, checkbox, and `TRADING212_ALLOW_DEMO_ORDERS` env gate. (Backend daily
   demo_execute exists but not this targeted flow.) → **Phase 8**.
6. **No Reports Library** endpoint or page (`/api/reports`, `/api/reports/{id}`,
   `/download`). → **Phase 3 / 10**.
7. **No Safety Center** page consolidating kill switch, live-blocked status, unsupported
   features (CFDs / T212 shorting / margin / live / unofficial endpoints), refused vs approved
   actions, and the confirmation policy. Disengage phrase should become
   `DISENGAGE KILL SWITCH` with stricter warnings. → **Phase 11**.
8. **No Survivorship page**, and Concentration/Crisis/Readiness pages are read-only (no rerun
   button + job progress). → **Phase 9**.
9. **Navigation** does not match the 7-section sidebar (Command Center / Long-only T212 /
   Supervised Paper / Broker / Risk & Safety / Research Reports / Settings) and the top bar is
   missing several always-on indicators (mode, product decision, T212 demo status, last paper
   day). → **Phase 4**.
10. **Command Center overview** ("Today's Action" card with the single next safe step) does not
    exist as specified. → **Phase 5**.
11. **No job-progress UX** (modal, log stream, step label, retry, report link) for long actions.
    → **Phase 13**.
12. **Roles are coarse** — a single local admin when `DASHBOARD_CONTROLS_ENABLED=true`. The
    viewer/researcher/operator/admin ladder and the demo `phrase+env` gate need explicit
    enforcement per action. → **Phase 14**.
13. **No frontend test runner.** `package.json` has only `dev`/`build`/`preview` — Vitest +
    RTL + jsdom and `test`/`test:run`/`typecheck` scripts are absent. → **Phase 15**.
14. **No dashboard-action backend tests** (run actions, demo refusals, secret redaction, audit
    creation, job transitions, controls-disabled behavior). → **Phase 16**.
15. **Docs** for the no-terminal workflow, actions, permissions, safety model, and the
    completion report are not yet written. → **Phase 17 / 18**.

## Confirmation-phrase inventory (target state)

| Action | Phrase | Extra gate |
|---|---|---|
| Engage kill switch | `ACTIVATE KILL SWITCH` | role ≥ trader |
| Disengage kill switch | `DISENGAGE KILL SWITCH` *(currently `DEACTIVATE KILL SWITCH`)* | role = admin |
| Run demo-execute paper day | `RUN DEMO PAPER DAY` | role = admin + `TRADING212_ALLOW_DEMO_ORDERS=true` |
| Send demo orders (Order Preview) | `SEND DEMO ORDERS` | role = admin + `TRADING212_ALLOW_DEMO_ORDERS=true` + checkbox |
| Stop paper session | `STOP PAPER SESSION` | role = admin |
| Enable live trading | *(unreachable — hard-blocked, no endpoint)* | impossible |

## Intentionally CLI-only

- `statarb dashboard` (server lifecycle), `init-db`, `download-data`, `download-futures-data`,
  research sweeps under `scripts/`, and the deep crypto/futures research commands. These are
  developer/operations actions, not part of the supervised-paper operator loop, and stay in the
  terminal as the "emergency fallback" the sprint preserves.
