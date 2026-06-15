# Trading 212 Dashboard Workflow

This covers connecting the **Trading 212 DEMO** environment and using it from the
dashboard. Live trading is hard-blocked and CFDs/shorting/margin/leverage are
unsupported — see `dashboard_safety_model.md`.

## 1. Configure demo credentials (one-time, in `.env`)

Secrets are entered in `.env` only — the dashboard never accepts or shows them.

```dotenv
TRADING212_ENABLED=true
TRADING212_MODE=demo
TRADING212_API_KEY=<your demo key>
TRADING212_API_SECRET=<your demo secret>
TRADING212_ALLOW_DEMO_ORDERS=false   # leave false until you are ready to send demo orders
TRADING212_ALLOW_LIVE_ORDERS=false   # MUST remain false — never set true
```

Restart the backend after editing `.env`.

## 2. Verify the connection (Broker → Trading 212 Setup)

The setup page shows booleans only (no secrets):

* `TRADING212_ENABLED`, `mode = demo`
* API key configured / API secret configured
* demo orders allowed
* live orders supported → **no (hard-blocked)**

Click **"Run setup check (probe demo endpoints)"** to run the
`trading212_setup_check` action. It connects to the **demo** API and returns a
checklist (pass/fail per item). Use **"Config-only check"** to validate without
connecting. The verdict reads `DEMO READY` or `not ready`. `live eligible: false`
is always shown.

If keys are missing, the page shows the exact `.env` block to add.

## 3. Preview what a day would trade (Long-only T212 → Order Preview)

Click **"Generate shadow preview"** (or **"Generate demo preview (offline)"**).
This runs the `order_preview` action, which builds the *validated* long-only plan
and **sends nothing**. You see:

* smoothed target weights
* planned buys / sells, quantities, marketable-limit prices, notionals
* skipped orders **and the reason** each was skipped
* estimated cash after orders, estimated slippage (bps)
* market-hours status (orders queue for the next open when closed)
* tradability / minimum-order-value / rounding / slippage validation checks
* demo eligibility (whether the demo gate is configured)

> The Order Preview page has **no order-sending button**. A banner makes this
> explicit: *"Demo execution is only available inside the gated supervised paper
> daily run."*

## 4. How demo execution is gated

`TRADING212_ALLOW_DEMO_ORDERS=true` only *allows* demo orders — it does not send
them and it never enables live. Demo orders are sent only by the
`supervised_paper_daily_demo_execute` action, which requires **all** of:

1. `DASHBOARD_CONTROLS_ENABLED=true` (admin role)
2. the exact phrase **`RUN DEMO PAPER DAY`**
3. the demo environment gate: `TRADING212_ENABLED` + `TRADING212_MODE=demo` +
   `TRADING212_ALLOW_DEMO_ORDERS=true` (and `TRADING212_ALLOW_LIVE_ORDERS` **not**
   set)
4. a paper-eligible product decision
5. the kill switch **not** engaged

Any missing condition → the job is **refused** (audited) and nothing is sent.

## 5. Where demo execution actually runs

Supervised Paper → **"Run demo execute day…"** → type `RUN DEMO PAPER DAY`. This is
the only path that submits demo orders, and only to the demo account. See
`supervised_paper_dashboard_workflow.md`.

## 6. Why live and CFDs are unsupported

* **Live:** no live job type, endpoint, or executor exists. The live flag is inert.
* **CFDs / shorting / margin / leverage:** unreachable via the official API; the
  capability layer (`UNSUPPORTED_PRODUCTS`, `assert_no_cfd`) rejects them, and the
  strategy is long-only by construction.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Setup check fails to connect | check demo key/secret in `.env`; restart backend |
| Demo execute refused: "demo orders are blocked" | set `TRADING212_ALLOW_DEMO_ORDERS=true` |
| Demo execute refused: "TRADING212_ALLOW_LIVE_ORDERS is set" | unset the live flag |
| Setup check disabled (greyed out) | controls are read-only — set `DASHBOARD_CONTROLS_ENABLED=true` |
