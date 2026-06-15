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
| 8 | Order preview / demo execute | ✅ operator-friendly offline preview; standalone demo/live buttons removed (see Q7) |
| 9 | Readiness/diagnostics pages | ✅ Readiness/Concentration/Crisis/Survivorship/Product-Decision rerun from UI via jobs |
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
jsdom. `npm run test:run` now runs **28 tests**: not-live banners, exact-phrase
ConfirmModal, the `todaysAction` state machine (10), Command Center renders Today's
Action, the app shell shows NOT LIVE ELIGIBLE + grouped sidebar, Order Preview has
no standalone/live button, Safety Center kill switch, Concentration rerun creates a
job, read-only disables the rerun, and "no live button anywhere". `npm run
typecheck` and `npm run build` pass.

**13. Are backend tests passing?** Yes — `app/tests/test_dashboard_actions.py`
(**25 tests**: gate refusals for every rerun action, kill-switch blocks setup
check, demo gating, reports list/view/download, refusal+success auditing,
no-secrets) plus the existing dashboard/operator suites and the full `pytest` run.
`ruff check .` is clean.

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

## Polish + redesign sprint (this sprint)

**Already done in the previous sprint:** the action/job orchestrator, the API
endpoints, the navigation shell, the Command Center, Supervised Paper, Trading 212
Setup, Reports Library, Safety Center, Survivorship, job-progress UX, and the
permission gates — all green.

**Added in this polish sprint:**

* **No-terminal UX.** Command Center rebuilt around an explicit **Today's Action**
  state machine (`lib/todaysAction.ts`, unit-tested) that names the single next
  safe action and links to it; product status grid; paper-equity chart.
* **Rerun from the UI.** Readiness (new page), Concentration (+ EWMA-vs-unsmoothed),
  Crisis (+ scenario chart), Survivorship, and Product Decision all rerun via the
  orchestrator with live `JobProgress`. Rerun buttons are disabled in read-only.
* **Order preview made operator-friendly and safer.** Target weights, planned
  buys/sells, skipped orders + reasons, cash/fees/slippage, market hours,
  tradability/validation, demo eligibility. The standalone "Execute on DEMO…" and
  "GO LIVE" buttons were **removed**; a banner states demo execution only happens
  inside the gated supervised daily run.
* **Visual redesign.** A shared design system (tokens, `PageHeader`, `StatusBadge`,
  `ActionCard`, `Tabs`, richer `Button`/`MetricCard`/`EmptyState`/`ErrorState`,
  icon set, chart containers), a collapsible icon sidebar, and a compact always-on
  safety bar. See `DASHBOARD_REDESIGN_REPORT.md`.
* **Docs.** `docs/dashboard_operator_guide.md`, `dashboard_actions.md`,
  `dashboard_permissions.md`, `dashboard_safety_model.md`,
  `trading212_dashboard_workflow.md`, `supervised_paper_dashboard_workflow.md`.
* **Acceptance.** `DASHBOARD_NO_TERMINAL_ACCEPTANCE.md` answers all 25 acceptance
  questions.

**Pages implemented/redesigned:** Command Center, Product Decision, Tradability,
Readiness, Concentration, Survivorship, Crisis Lab, Order Preview, Supervised Paper
(Control Center / Daily Run / Monitor), Trading 212 Setup, Account, Live Readiness,
Safety Center, Blockers, Reports Library, Backtests, Deflated Sharpe, plus legacy
System pages.

**Actions implemented:** product decision, long-only readiness, concentration (+
compare fixes), survivorship, crisis, Trading 212 setup check, order preview, paper
start, daily shadow/demo_preview/demo_execute, health, final report, stop, kill
switch engage/disengage, report generation — 18 action types, every one
`live_eligible: false`.

**Remaining CLI-only workflows:** install/build, editing `.env`, dev mode, data
download / DB init, research sweeps, emergency fallback, advanced debugging — see
`DASHBOARD_NO_TERMINAL_ACCEPTANCE.md`.

**Live trading impossible from the UI:** no live job type, endpoint, or executor;
the live flag is inert and demo actions refuse if it is set; no standalone order
button. **No secrets exposed:** config/settings return booleans only; tests assert
secrets never appear in job results or `/api/settings`.

**Exact daily dashboard workflow:** Command Center → read *Today's required action*
→ click the primary button → watch `JobProgress` → review the generated report in
Reports Library → check the audit trail in Safety Center → stop.

## Verification snapshot

- Backend: full `pytest` suite green incl. `test_dashboard_actions.py` (25);
  `ruff check .` clean.
- Frontend: `npm run typecheck` ✅, `npm run test:run` ✅ (28), `npm run build` ✅.
- Safety: 18 action types, all `live_eligible:false`; no `live` job type exists;
  Order Preview has no order-sending button; demo orders gated to the supervised
  daily run only.
