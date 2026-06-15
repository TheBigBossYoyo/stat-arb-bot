# Dashboard Completion Report

Sprint: make the web dashboard the **primary operator control panel** so the
supervised-paper workflow needs no terminal for normal use. Branch:
`paper-long-only-t212`. Hard invariant throughout: **NOT LIVE ELIGIBLE**.

## Status summary

| Phase | Scope | State |
|---|---|---|
| 1 | Capability map | ✅ `docs/dashboard_capability_map.md` |
| 2 | Backend action/job orchestrator | ✅ `app/dashboard/{action_schemas,job_store,action_permissions,action_audit,actions,jobs}.py` |
| 3 | Dashboard API endpoints | ✅ wired into `app/dashboard/api.py` |
| 4–5 | Nav redesign + Command Center | ✅ `Layout.tsx`, `CommandCenterPage.tsx` |
| 6 | Supervised Paper control center | ✅ `SupervisedPaperPage.tsx` |
| 7 | Trading 212 setup wizard | ✅ `Trading212SetupPage.tsx` |
| 8 | Order preview / demo execute | 🟡 shadow + demo via supervised flow (see Q7) |
| 9 | Readiness/diagnostics pages | ✅ Survivorship new; concentration/crisis/live-readiness read; rerun via jobs |
| 10 | Reports library | ✅ `ReportsLibraryPage.tsx` |
| 11 | Safety center | ✅ `SafetyCenterPage.tsx` |
| 13 | Job-progress UX | ✅ `useAction.ts` + `JobProgress.tsx` |
| 14 | Permissions / control modes | ✅ role + env + phrase gates enforced server-side |
| 15 | Frontend test infra | ✅ Vitest + RTL + jsdom |
| 16 | Backend tests | ✅ `app/tests/test_dashboard_actions.py` |
| 17–18 | Docs + this report | ✅ |

## The 15 acceptance questions

**1. Can the operator use the dashboard instead of terminal commands?**
Yes, for the normal supervised-paper loop: product decision, readiness/diagnostics,
Trading 212 demo setup, order preview, start/run/stop a supervised paper session,
health monitoring, reports, audit, and the kill switch are all dashboard-driven.

**2. Which workflows are fully dashboard-supported?**
Product decision (view + run), Trading 212 demo setup check, shadow order preview,
supervised paper start, daily shadow / demo_preview / demo_execute runs, paper
health + paper-vs-backtest, final report generation, stop session, survivorship /
concentration / crisis / readiness reads + reruns, reports library (view +
download), kill switch engage/disengage, audit trail, safe settings view.

**3. Which workflows remain CLI-only and why?**
Initial data download, DB init, research sweeps (`scripts/`), and deep
crypto/futures research — developer/ops actions outside the operator loop. They
stay in the terminal as the emergency fallback the sprint preserves.

**4. Can the operator start supervised paper from the dashboard?** Yes —
Supervised Paper → Control Center → *Start session* (`POST /api/paper/start`), with
mode / min-days / starting-cash. Refused unless the product is paper-eligible.

**5. Can the operator run a daily shadow day from the dashboard?** Yes —
*Run shadow day* (`POST /api/paper/daily`, mode `shadow`). TRADER role + controls.

**6. Can the operator run a demo preview from the dashboard?** Yes —
*Run demo preview day* (mode `demo_preview`): connects to the Trading 212 DEMO API,
validates, submits nothing.

**7. Can the operator send Trading 212 demo orders from the dashboard?** Yes, only
via the supervised **demo_execute** day, which requires admin controls, the exact
phrase `RUN DEMO PAPER DAY`, and `TRADING212_ALLOW_DEMO_ORDERS=true` — all
re-validated server-side. (A standalone "send demo orders" button was deliberately
not added: there is no standalone demo-order endpoint; demo submission only happens
inside the gated daily routine. The Order Preview page is shadow-only.)

**8. Are live orders possible from the dashboard?** No. There is no live endpoint,
no live button, and no `live_*` job type. `trading212_allow_live_orders` is never
consulted. Every action returns `live_eligible: false`.

**9. Are secrets exposed?** No. Settings/config endpoints report only *whether* a
key is configured; the setup check scrubs secrets from every detail; job params are
redacted; browser secret entry is disabled. Tests assert secrets never appear in
job results or `/api/settings`.

**10. Are all actions audited?** Yes. Every submission — accepted **or refused** —
writes an audit event (`actor="dashboard"`), and the result writes a second event;
the job stores its `audit_id`.

**11. Are dangerous actions confirmation-gated?** Yes: `RUN DEMO PAPER DAY`,
`STOP PAPER SESSION`, `ACTIVATE KILL SWITCH`, `DISENGAGE KILL SWITCH` (disengage is
admin + stricter). Demo execute additionally needs the env gate.

**12. Are frontend tests implemented?** Yes — Vitest + React Testing Library +
jsdom. `npm run test:run` (7 tests: not-live banners, exact-phrase ConfirmModal,
demo-execute disabled by default, no live button, read-only disables runs).
`npm run typecheck` and `npm run build` pass.

**13. Are backend tests passing?** Yes — `app/tests/test_dashboard_actions.py`
(12 tests) plus the existing dashboard/operator suites. `ruff check .` is clean.

**14. Exact daily dashboard workflow.** See `docs/no_terminal_required_workflow.md`:
Command Center → (setup check) → Control Center start/run day → watch job progress
→ review health + reports → check Safety Center/audit → eventually generate final
report.

**15. What remains before live can ever be discussed?** Unchanged by this sprint
(it only adds operator usability, never eligibility): a completed forward
supervised paper period (≥30 days), the standing research blockers (point-in-time
survivorship, real-crisis validation, deflated-Sharpe for the market-neutral
flagship), a connected execution venue with the full live gate, and production
hardening. The dashboard exists to *run and supervise* the paper period — not to
shorten this list.

## How to run

```
# .env: DASHBOARD_CONTROLS_ENABLED=true (bind to 127.0.0.1)
cd frontend && npm install && npm run build
statarb dashboard
```

## Verification snapshot

- Backend: dashboard test suites pass; `ruff check .` clean.
- Frontend: `npm run typecheck` ✅, `npm run test:run` ✅ (7), `npm run build` ✅.
- Safety: 18 action types, all `live_eligible:false`; no `live` job type exists.
