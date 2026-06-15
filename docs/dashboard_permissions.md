# Dashboard Permissions

## Roles

The production design is a four-rung ladder (`app/dashboard/permissions.py`):

```
viewer < researcher < trader < admin
```

| Role | Can |
|---|---|
| **viewer** | read everything; change nothing |
| **researcher** | + run research/diagnostic jobs (product decision, readiness, concentration, crisis, survivorship, order preview, reports) |
| **trader** | + paper-trading controls (setup check, start/run paper, shadow & demo-preview days, engage kill switch) |
| **admin** | + dangerous / demo-execute actions (demo execute day, stop session, disengage kill switch) |

## How the current role is decided (single-operator MVP)

There is no user store yet. The local operator's role is derived purely from one
flag:

```python
current_role = ADMIN if DASHBOARD_CONTROLS_ENABLED else VIEWER
```

So in practice:

* **`DASHBOARD_CONTROLS_ENABLED` unset/false → read-only (viewer).** Every control
  is disabled in the UI and refused by the backend. You can browse, view reports,
  and read the audit trail.
* **`DASHBOARD_CONTROLS_ENABLED=true` → admin.** All role checks pass, but the
  per-action **phrase**, **environment**, **kill-switch**, and **product-decision**
  gates still apply independently.

Enabling controls is *not* a backdoor to anything live — there is no live action
in the catalogue at any role.

## What each role can and cannot do (effective today)

| Capability | read-only (viewer) | controls on (admin) |
|---|---|---|
| View pages, reports, audit | ✅ | ✅ |
| Run diagnostics (readiness, concentration, crisis, …) | ❌ | ✅ |
| Generate order preview (sends nothing) | ❌ | ✅ |
| Start / run shadow & demo-preview paper days | ❌ | ✅ |
| Run **demo execute** paper day | ❌ | ✅ *(+ phrase + env + product)* |
| Engage / disengage kill switch | ❌ | ✅ *(+ phrase)* |
| Place a **live** order | ❌ (impossible) | ❌ (impossible) |

## Environment flags that gate the dashboard

| Variable | Effect |
|---|---|
| `DASHBOARD_CONTROLS_ENABLED` | `true` enables controls (operator → admin). Default off = read-only. |
| `TRADING212_ENABLED` | must be `true` for any Trading 212 demo action |
| `TRADING212_MODE` | must be `demo` for demo actions |
| `TRADING212_API_KEY` / `TRADING212_API_SECRET` | demo credentials (read from `.env`; never sent to the browser) |
| `TRADING212_ALLOW_DEMO_ORDERS` | must be `true` for `demo_execute` to send demo orders |
| `TRADING212_ALLOW_LIVE_ORDERS` | **must remain `false`.** Never consulted by any executor; if set, demo actions refuse loudly. |

## Gate evaluation order

`evaluate_gates` checks, in order — the first failure is the one reported:

1. **controls enabled + role**
2. **kill switch** (for actions that block when killed)
3. **confirmation phrase** (exact match)
4. **demo environment** (enabled + demo mode + allow-demo-orders; refuse if
   live-orders flag set)
5. **acknowledgement checkbox** (where required)
6. **product decision** (must be paper-eligible for session actions)

The same function is called by both the API and the orchestrator, so the UI can
never widen a permission.

## Notes on hardening

* Keep the server bound to `127.0.0.1`. The panel assumes a single trusted local
  operator.
* A token guard (`app/dashboard/auth.py`) protects API routes when configured.
* When a real user store is added, only `current_role` changes — the per-action
  specs already encode the intended minimum role for each capability.
