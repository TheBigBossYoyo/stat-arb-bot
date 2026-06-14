# Trading 212 demo execution (Phase 5)

The long-only order path uses the **official Trading 212 Public API in DEMO mode
only**. No CFDs, no shorting, no margin, no unofficial/scraped endpoints, and the
live endpoint is **hard-blocked**. Nothing here can place a real-money order.

## Modules

| module | role |
|---|---|
| `app/brokers/trading212/instrument_cache.py` | cached instrument metadata; tradability / fractional / min-order lookups; offline synthetic fallback |
| `app/brokers/trading212/order_validation.py` | pure plan/order checks + US market-hours |
| `app/brokers/trading212/demo_execution.py` | the demo-only executor + the demo execution gate |
| `app/execution/long_only_order_planner.py` | target weights → validated order plan |
| `app/execution/long_only_demo_executor.py` | orchestrates the three modes |
| `app/execution/long_only_reconciliation.py` | local target book vs demo broker positions |

## The three modes (strictly escalating)

1. **shadow** — build + validate the plan; **send nothing**; no broker
   connection. Banner: "SHADOW MODE — SENDS NO ORDERS."
2. **demo_preview** — connect to the DEMO account (read cash/positions/
   instruments), plan against the real demo balances, validate, reconcile;
   **send nothing**. Banner: "DEMO ONLY — PREVIEW."
3. **demo_execute** — submit to the DEMO account, and only if the full demo
   execution gate passes. Banner: "DEMO ONLY — EXECUTE."

## Environment flags

```
TRADING212_ENABLED=false
TRADING212_MODE=demo
TRADING212_API_KEY=
TRADING212_API_SECRET=
TRADING212_ALLOW_DEMO_ORDERS=false
TRADING212_ALLOW_LIVE_ORDERS=false   # NEVER consulted — live is not reachable
```

## Demo execution gate (ALL must hold to submit a demo order)

`TRADING212_ENABLED=true` · `TRADING212_MODE=demo` ·
`TRADING212_ALLOW_DEMO_ORDERS=true` · `--confirm-demo` · kill switch off ·
**global live-trading flag OFF** · API key+secret configured · strategy
paper-eligible · market data fresh · order plan validated (no negative weights,
gross ≤ 1.0, every instrument tradable, every order ≥ minimum value, correct
fractional/whole-share rounding, slippage within limit, cash sufficient — no
margin). If any condition fails, the executor **refuses** and audits the refusal.

## Why live is unreachable

- the demo executor constructs the client with `mode="demo", allow_live=False`,
  so the live base URL is never built;
- the gate requires the **global** live-trading flag to be OFF;
- `TRADING212_ALLOW_LIVE_ORDERS` is intentionally never read — a single env var
  cannot enable live; that code path does not exist in this product.

## Commands

```
statarb trading212-check --mode demo
statarb trading212-instruments --mode demo
statarb long-only-order-preview --broker trading212 --mode demo_preview
statarb paper-trade-long-only --broker trading212 --mode shadow
statarb paper-trade-long-only --broker trading212 --mode demo_preview
statarb paper-trade-long-only --broker trading212 --mode demo_execute --confirm-demo
```

Tests: `app/tests/test_trading212_demo.py` (no-short, no-margin, no-CFD, minimum
order value, fractional/whole-share rounding, market-hours, the full gate, refusal
without confirmation, and the live hard-block).
