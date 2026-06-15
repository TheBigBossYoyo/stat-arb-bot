# Dashboard Safety Model

The dashboard is designed so that **live trading is structurally impossible** and
**every action is audited**. This document explains why.

## The one invariant

> **NOT LIVE ELIGIBLE.** No real-money order can be placed from this system — not
> from the dashboard, not from the CLI, not by flipping a flag.

This is asserted everywhere it matters: the always-on top bar, a badge on every
operator page, the product-decision verdict, and every action result
(`live_eligible: false`).

## Why there is no live button

1. **No live job type exists.** The action catalogue
   (`JobType` in `app/dashboard/action_schemas.py`) contains only read, research,
   paper, and demo actions. There is no enum value, handler, or endpoint that
   submits a live order. You cannot call what does not exist.
2. **The live flag is inert.** `TRADING212_ALLOW_LIVE_ORDERS` is never read by any
   executor. As defence in depth, the demo-environment gate **refuses loudly** if
   it ever finds that flag set.
3. **Trading 212 live order endpoints are not wired.** The broker client exposes
   the official Invest/ISA demo surface only.

## Why there is no standalone demo-order button

Demo orders can only be sent **inside the gated supervised paper daily run**
(`demo_execute`). There is deliberately no "send demo orders" button on the Order
Preview page or anywhere else. This guarantees every order — even a demo one —
passes the full daily gate (controls → admin role → phrase → demo env → product
decision), is part of a supervised session, and is audited.

The Order Preview page is therefore a **read-only planning view**: it shows what a
day *would* plan (orders, skips, weights, fees, validation) and connects to no
broker.

## Structurally unsupported (by design)

| Capability | Why it is impossible |
|---|---|
| Live orders | No live job type / endpoint / executor; the flag is never consulted |
| Trading 212 CFDs | Official Invest/ISA Public API only; CFDs are unreachable. `assert_no_cfd` rejects the `cfd` asset class; `UNSUPPORTED_PRODUCTS = (cfd, short_selling, margin, leverage)` |
| Trading 212 shorting | Long-only by construction; negative target weights are clipped to zero before planning |
| Trading 212 margin / leverage | Cash equities only; no margin path is wired |
| Unofficial / private endpoints | No scraping or reverse-engineered endpoints — ever |

## The gate chain (server-side, every time)

Every action is re-validated by `evaluate_gates`, in order:

1. **controls enabled + role** — read-only by default; controls require
   `DASHBOARD_CONTROLS_ENABLED=true`.
2. **kill switch** — engaged → all blocking actions refuse.
3. **confirmation phrase** — exact match for dangerous/demo actions.
4. **demo environment** — `TRADING212_ENABLED` + `TRADING212_MODE=demo` +
   `TRADING212_ALLOW_DEMO_ORDERS=true`; refuse if the live flag is set.
5. **acknowledgement** — checkbox where required.
6. **product decision** — session actions need a paper-eligible product.

The frontend is never trusted: the same chain runs whether a request comes from
the UI, a script, or `curl`. A failure becomes a **refused** job (HTTP 200) with a
reason, and is audited.

## The kill switch

* A persistent flag (`runtime/kill_switch.flag`) that survives restarts.
* **Engage** needs trader role + `ACTIVATE KILL SWITCH`.
* **Disengage** is stricter — admin role + `DISENGAGE KILL SWITCH`. You must never
  be able to lift the halt as easily as you set it.
* While engaged, every action that `blocks_when_killed` is refused.

## Audit

* Every action attempt — **allowed or refused** — is written to the audit trail
  (`storage.record_audit_event`) and the structured audit log, with actor, action,
  confirmation status, payload, and result.
* Job records and audit events are linked (`audit_id`).
* Refused actions are audited *before* anything could run.
* The Safety Center surfaces recently refused, recently approved, the confirmation
  policy table, and the latest audit events.

## Secrets

* Trading 212 API key/secret are read from `.env` on the server and **never** sent
  to the browser. The config endpoint returns booleans only
  (`api_key_configured: true/false`).
* Browser secret entry is intentionally disabled — credentials are edited in
  `.env` only.

## What remains CLI-only (and why)

* **Install / environment setup** — `npm install`, `npm run build`, editing `.env`.
* **Dev mode** — running the Vite dev server.
* **Emergency fallback / advanced debugging** — direct CLI commands.

Normal operator workflow is fully dashboard-supported.
