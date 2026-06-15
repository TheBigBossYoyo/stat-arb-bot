# Dashboard Actions Catalogue

Every dashboard control funnels through **one** orchestrator
(`app/dashboard/jobs.py` → `ActionOrchestrator.submit`). The orchestrator:

1. re-validates every safety gate **server-side** (`evaluate_gates`);
2. refuses duplicate / conflicting jobs;
3. creates a job record + an audit event and links them;
4. runs the handler on a worker thread, capturing logs / progress / result;
5. transitions the job to `succeeded` / `failed` / `refused` / `cancelled`.

A blocked attempt becomes a **`refused`** job (HTTP 200) with a reason — the
frontend is never trusted. **No handler can reach a live order.**

## Job lifecycle

`queued → running → succeeded | failed | refused | cancelled`

* **succeeded** — handler completed; `result` (and maybe `report_path`) populated.
* **failed** — handler raised; `error` populated.
* **refused** — a gate rejected it before running; `refusal_reason` populated.
* **cancelled** — operator cancelled before/while running.

## Action catalogue

The columns map to each `ActionSpec` in `app/dashboard/action_permissions.py`.

| Action (job type) | Endpoint | Safety | Min role | Confirm | Blocked by kill switch | Needs product OK |
|---|---|---|---|---|---|---|
| `product_decision` | `POST /api/product-decision/run` | research | researcher | role | no | no |
| `long_only_readiness` | `POST /api/long-only/readiness/run` | research | researcher | role | no | no |
| `concentration_analysis` | `POST /api/long-only/concentration/run` | research | researcher | role | no | no |
| `compare_concentration_fixes` | `POST /api/long-only/concentration/compare-fixes` | research | researcher | role | no | no |
| `survivorship_stress` | `POST /api/long-only/survivorship/run` | research | researcher | role | no | no |
| `crisis_test` | `POST /api/long-only/crisis/run` | research | researcher | role | no | no |
| `trading212_setup_check` | `POST /api/trading212/setup-check` | demo | trader | role | yes | no |
| `order_preview` | `POST /api/trading212/order-preview` | paper | researcher | role | no | no |
| `supervised_paper_start` | `POST /api/paper/start` | paper | trader | role | yes | **yes** |
| `supervised_paper_daily_shadow` | `POST /api/paper/daily` (`mode=shadow`) | paper | trader | role | yes | **yes** |
| `supervised_paper_daily_demo_preview` | `POST /api/paper/daily` (`mode=demo_preview`) | demo | trader | role | yes | **yes** |
| `supervised_paper_daily_demo_execute` | `POST /api/paper/daily` (`mode=demo_execute`) | demo | **admin** | **phrase + env** | yes | **yes** |
| `supervised_paper_health` | `GET /api/paper/health` | read | viewer | none | no | no |
| `supervised_paper_final_report` | `POST /api/paper/final-report` | research | researcher | role | no | no |
| `supervised_paper_stop` | `POST /api/paper/stop` | danger | **admin** | **phrase** | no | no |
| `paper_vs_backtest` | `GET /api/operator/paper-vs-backtest` | read | viewer | none | no | no |
| `report_generation` | `POST` (orchestrator) | research | researcher | role | no | no |
| `kill_switch_action` | `POST /api/risk/kill-switch/{engage,disengage}` | danger | trader/admin | **phrase** | no | no |

`Confirm` legend: **role** = controls enabled + sufficient role; **phrase** = also
an exact typed phrase; **phrase + env** = also the demo-order environment gate.

## Confirmation phrases

| Action | Phrase |
|---|---|
| `supervised_paper_daily_demo_execute` | `RUN DEMO PAPER DAY` |
| `supervised_paper_stop` | `STOP PAPER SESSION` |
| `kill_switch_action` (engage) | `ACTIVATE KILL SWITCH` |
| `kill_switch_action` (disengage) | `DISENGAGE KILL SWITCH` |

## What each action produces

* **product_decision** — lead product, recommended action, capital stage,
  per-product gate counts.
* **long_only_readiness** — runs the readiness battery (allow-listed subprocess),
  writes `PAPER_ELIGIBILITY_REPORT.md`.
* **concentration_analysis** — baseline vs smoothed OOS Sharpe and the gate pass.
* **compare_concentration_fixes** — EWMA vs unsmoothed comparison log.
* **survivorship_stress** — median / 5th-pct Sharpe, worst-case DD, verdict; writes
  a survivorship report.
* **crisis_test** — per-scenario synthetic drawdowns, worst scenario, verdict;
  writes a crisis report.
* **trading212_setup_check** — demo connection checklist (no secrets returned).
* **order_preview** — validated long-only plan: orders, skipped + reasons, target
  weights, cash after, est. slippage, validation checks. **Sends nothing.**
* **supervised_paper_start / _daily_* / _final_report / _stop** — see
  `supervised_paper_dashboard_workflow.md`.
* **kill_switch_action** — engages/disengages the halt flag.

## Job endpoints

* `GET /api/dashboard/summary` — one call powering the Command Center.
* `GET /api/dashboard/capabilities` — the action catalogue + controls/role.
* `GET /api/dashboard/jobs` / `GET /api/dashboard/jobs/{id}` — list / poll jobs.
* `GET /api/dashboard/jobs/{id}/logs` — streamed job log tail.
* `POST /api/dashboard/jobs/{id}/cancel` — request cancellation.
* `GET /api/reports`, `GET /api/reports/{id}`, `GET /api/reports/{id}/download`.

Every action is rendered in the UI with a live `JobProgress` component (status
badge, step text, progress bar, refusal/error, and a report pointer).
