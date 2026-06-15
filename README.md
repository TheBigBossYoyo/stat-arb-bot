# stat-arb-bot

A statistical-arbitrage research, backtesting and paper-trading system for
**Binance crypto spot** and (in a later phase) **Trading 212 equities**, built
with institutional-style risk controls but adapted for a retail/API
environment.

> **⚠️ No promise of profitability.** Statistical arbitrage strategies decay,
> regimes shift, and costs are real. This software is a research and execution
> framework, not a money machine. **Live trading is disabled by default** and
> stays off until every safety gate passes.

> **⚠️ Audit notice (2026-06).** An institutional audit found that the headline
> research numbers below are **in-sample, selection-inflated upper bounds** on
> survivorship-biased, (pre-fix) dividend-blind data — see
> [`AUDIT_REPORT.md`](AUDIT_REPORT.md), [`RESEARCH_WEAKNESSES.md`](RESEARCH_WEAKNESSES.md),
> [`PRODUCTION_RISK_REGISTER.md`](PRODUCTION_RISK_REGISTER.md) and
> [`STRATEGY_ACCEPTANCE_CRITERIA.md`](STRATEGY_ACCEPTANCE_CRITERIA.md).
> Every strategy's honest validation stage lives in the alpha registry
> (`statarb alpha-registry list`). Re-validated numbers will replace the
> legacy figures as the new pipeline processes them.

> **⚠️ Paper-readiness update (2026-06-14).** A focused sprint took the long-only
> Trading 212 book from "6/7 gates, not paper-eligible" to **ELIGIBLE TO BEGIN a
> supervised paper/shadow period** — see
> [`PAPER_ELIGIBILITY_REPORT.md`](PAPER_ELIGIBILITY_REPORT.md) and run
> `statarb product-decision`. Headlines:
> - **EWMA target-weight smoothing closed the concentration gate** (worst month
>   26.1% → **23.5%**) without breaking OOS (Sharpe 1.65, 2/2 folds) — and lowered
>   turnover and drawdown. Default selected by validation, not curve-fit. See
>   [`docs/concentration_mitigation.md`](docs/concentration_mitigation.md).
> - **Survivorship bounded** (but the edge leans on the top winners) and **crisis
>   tested** (synthetic; the regime filter is the real crash protection).
> - The **Trading 212 DEMO order path is wired** (official API, demo-only; live
>   hard-blocked) with a full demo execution gate, plus a **supervised paper
>   workflow** (`supervised-paper-start/status/daily-report/final-report/stop`).
> - The **market-neutral flagship is still NOT tradable** (no venue; FAILS
>   deflated Sharpe). **Crypto futures** still testnet-only (5/6, short sample).
> - **Nothing is live-eligible.** Long-only is eligible to *begin* paper, not to
>   trade real capital. See
>   [`docs/tradability_matrix.md`](docs/tradability_matrix.md),
>   [`docs/live_readiness.md`](docs/live_readiness.md),
>   [`docs/no_live_trading_reason.md`](docs/no_live_trading_reason.md),
>   [`docs/long_only_t212_paper_plan.md`](docs/long_only_t212_paper_plan.md).

---

## What is statistical arbitrage?

Stat-arb trades *relationships* between instruments rather than direction.
The classic form is **pairs trading**: find two assets whose prices move
together in the long run, and when the gap between them stretches abnormally
wide, bet on the gap closing — long the cheap leg, short the rich leg. Done
properly the position is (approximately) market-neutral: it profits from
*convergence*, not from the market going up.

### Correlation is not enough

Correlation measures whether *returns* move together day to day. Two assets
can be 95% return-correlated while their *price levels* drift apart forever —
there is nothing to mean-revert to. **Cointegration** is the property that
some linear combination of the price levels is *stationary* (it oscillates
around a stable mean). That combination is the **spread**:

```
spread_t = log(A_t) − (alpha + beta · log(B_t))
```

* `beta` is the **hedge ratio** — how many units of B hedge one unit of A.
  It is estimated by OLS regression of log A on log B (and re-estimated on a
  rolling window, or tracked online with a Kalman filter).
* The **Engle-Granger test** checks for cointegration; the **ADF test**
  checks that the residual spread is stationary.
* The **half-life** of mean reversion (from an AR(1) fit on the spread)
  tells you how fast departures decay — too fast is noise and costs, too slow
  ties up capital.

### Z-score entries and exits

The spread is standardized over a rolling window:
`z = (spread − rolling_mean) / rolling_std`.

| event | rule (defaults) |
| --- | --- |
| short the spread (sell A, buy B) | `z ≥ +2.0` |
| long the spread (buy A, sell B) | `z ≤ −2.0` |
| take profit | `\|z\| ≤ 0.3` |
| stop loss (relationship broke) | `\|z\| ≥ 3.5` |
| time stop | held > 4× the pair's half-life (clamped 24–480 bars) |
| cost-edge gate | skip entries whose expected reversion < 1.3× round-trip cost |

### Risks you must understand before going anywhere near live

* **Model decay** — cointegration found in-sample frequently disappears.
* **Regime shifts** — trends/breakouts are where mean-reversion bleeds.
* **Transaction costs & slippage** — round-trip costs on 4 legs eat thin edges.
* **Latency & partial fills** — one leg filling without the other leaves you
  *directional*, not neutral (this system has hedge-repair/rollback logic).
* **Shorting constraints** — a plain Binance **spot** account cannot short;
  true market-neutral needs margin/futures (disabled by default) or the
  long-only fallback mode (which is *not* market-neutral).
* **Funding rates** (futures), **borrow costs** (equities), **API outages**,
  **overfitting**, **survivorship bias**, **lookahead bias** — the backtester
  guards against the last one structurally (signals at bar close, fills at
  next bar open), and the walk-forward/stress suites exist to expose the rest.

---

## Architecture

```
app/
  config/        settings (.env), broker capability matrix, risk limits, strategy defaults
  core/          types, exceptions, structured JSON logging, clock, math utils
  data/          SQLite/Postgres storage, Binance/yahoo/stooq/synthetic loaders, quality checks, universes + sector map
  brokers/       broker base + capability enforcement; binance/, trading212/ connectors
  research/      ADF, Engle-Granger, pair selection, Kalman filter, regime filter, PCA/sector residuals, ML features
  strategies/    z-score/cointegration/Kalman pairs; PCA & sector stat-arb, TSMOM/XSMOM, reversal, ML alpha baskets; risk-parity ensemble
  backtesting/   event-driven pairs engine + vectorized basket engine, slippage/fees, metrics, walk-forward, stress, reports
  risk/          RiskManager (every signal passes through it), kill switch, sizing
  execution/     semi-atomic pair executor (hedge repair / rollback), pairs + basket paper traders, reconciliation, retries
  portfolio/     position book, PnL
  dashboard/     FastAPI + React control panel (read-only by default, gated controls)
  cli/           `statarb` command-line interface
  tests/         pytest suite (no live API calls — everything mocked/synthetic)
```

**Capability gating:** `config/broker_capabilities.yaml` declares what each
broker can legally/technically do. The risk manager checks it before every
order. Trading 212 **CFDs are marked unsupported** — the official Public API
(https://docs.trading212.com/api) only covers Invest/Stocks-ISA equities, and
this project will never trade CFDs via scraping or reverse-engineered
endpoints.

---

## Quickstart (MVP — fully offline, no API keys)

Requires Python 3.11+.

```bash
cd stat_arb_bot
python -m venv .venv
# Windows: .venv\Scripts\activate     Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # optional — defaults are safe

# 1. run the test suite
pytest

# 2. create the database
statarb init-db

# 3a. OFFLINE demo (synthetic universe with known cointegrated pairs)
statarb download-data --source synthetic --days 90
statarb discover-pairs --universe synthetic_demo
statarb backtest --strategy pairs_zscore --universe synthetic_demo --stress

# 3b. REAL market data (public Binance REST, still no API key)
statarb download-data --universe crypto_top_10 --interval 15m --days 90
statarb discover-pairs --universe crypto_top_10 --interval 15m --lookback-days 90
#   thresholds are overridable for research: --max-half-life 250 --max-eg-pvalue 0.1 ...
statarb backtest --strategy cointegration_pairs --universe crypto_top_10
statarb backtest --strategy kalman_pairs --universe crypto_top_10 --allocate
statarb walk-forward --strategy cointegration_pairs --universe crypto_top_10

# 3c. basket strategies (PCA/sector residuals, reversal, TSMOM, 12-1 momentum)
statarb backtest-basket --strategy pca_stat_arb --universe crypto_top_10
statarb backtest-basket --strategy tsmom --universe crypto_top_10
statarb backtest-basket --strategy xsec_reversion --universe crypto_top_10 --long-only
statarb backtest-basket --strategy xsec_momentum --universe us_stocks_50 --interval 1d
statarb backtest-basket --strategy sector_stat_arb --universe us_stocks_50 --interval 1d

# 3d. multi-strategy risk-parity ensemble (sleeves from strategy_defaults.yaml)
statarb backtest-ensemble --universe crypto_top_10

# 3e. funding-rate carry research (public futures funding data, no key needed)
statarb carry-backtest --universe crypto_top_10 --days 730

# 3f. ML alpha sleeve (gradient-boosted cross-sectional forecasts) on stocks,
#     and the FLAGSHIP daily ensemble (xsec_momentum + tsmom + ml_alpha)
statarb backtest-basket --strategy ml_alpha --universe us_stocks_50 --interval 1d
statarb backtest-ensemble --universe us_stocks_50 --interval 1d --leverage 2.0

# 4. inspect results
statarb report
statarb dashboard            # needs: pip install -e ".[dashboard]"

# 5. paper trade with live market data (simulated fills, NO real orders)
statarb paper-trade --broker binance --strategy cointegration_pairs

# 5b. paper trade the daily stocks flagship (ensemble weights -> simulated
#     portfolio rebalanced through the risk manager; shorting SIMULATED)
statarb paper-trade-basket --universe us_stocks_50 --interval 1d
```

`python -m app.cli.main <command>` works identically to `statarb <command>`.

---

## Command reference

Every CLI command (run `statarb <command> --help` for the full option list):

| command | what it does | key options |
| --- | --- | --- |
| `init-db` | create the database tables | — |
| `download-data` | download bars into local storage (no API key) | `--universe/--symbols`, `--interval`, `--days`, `--source binance\|yahoo\|stooq\|synthetic` |
| `discover-pairs` | cointegration pair discovery (EG + ADF + half-life) on stored data | `--universe`, `--interval`, `--lookback-days`, threshold overrides (`--max-eg-pvalue`, `--max-half-life`, ...) |
| `backtest` | event-driven pairs backtest on the saved pairs, costs included | `--strategy`, `--universe`, `--interval`, `--days`, `--stress`, `--allocate` (inverse-vol pair weights) |
| `backtest-basket` | vectorized backtest of one cross-sectional basket strategy | `--strategy`, `--universe`, `--interval`, `--long-only`, `--rebalance-every` |
| `backtest-ensemble` | risk-parity multi-sleeve ensemble backtest | `--sleeves`, `--universe`, `--interval`, `--leverage`, `--long-only` |
| `walk-forward` | rolling in-sample selection / out-of-sample trading validation | `--strategy`, `--universe`, `--interval`, `--train-bars`, `--test-bars` |
| `carry-backtest` | delta-neutral funding-rate carry research (funding leg only) | `--universe/--symbols`, `--days`, `--entry-apr`, `--exit-apr`, `--cost-bps` |
| `paper-trade` | live-data paper trading of PAIRS strategies (simulated fills) | `--broker`, `--strategy`, `--universe`, `--interval`, `--iterations` |
| `paper-trade-basket` | live-data paper trading of the BASKET ensemble (daily EOD refresh, risk-gated rebalancing, simulated shorts) | `--universe`, `--interval`, `--sleeves`, `--leverage`, `--source`, `--iterations`, `--no-refresh` |
| `live-trade` | attempt to enable live trading; refuses unless every gate passes | `--broker`, `--strategy`, `--confirm-live` |
| `kill-switch` | engage/disengage/inspect the global kill switch | `--engage`, `--disengage`, `--reason` |
| **Long-only T212 paper-readiness (Path A)** | | |
| `concentration-fix-backtest` | baseline vs one concentration fix (EWMA for long-only) | `--strategy long_only_xsec_momentum`, `--method ewma` |
| `compare-concentration-fixes` | sweep the smoothing family, recommend the fix (trials registered) | `--strategy long_only_xsec_momentum` |
| `long-only-readiness` | full research + operational gate; honest paper-eligibility verdict | `--strategy`, `--smoothing`, `--full`, `--write-report` |
| `survivorship-stress-long-only` | random/sector-balanced/best-5/worst-5 drops + bootstrap; eliminated/bounded/unresolved | `--strategy`, `--universe` |
| `universe-bias-report` | universe survivorship status + the strategy bias bound | `--universe`, `--strategy` |
| `crisis-test-long-only` | expanded synthetic crisis suite + regime/smoothing effects | `--strategy`, `--universe` |
| `crisis-report` | crisis + crash-protection summary | `--product long_only_t212` |
| `trading212-check` | check the Trading 212 DEMO connection (read-only; live blocked) | `--mode demo` |
| `trading212-instruments` | list instrument metadata (tradability/fractional/minimums) | `--mode demo`, `--universe` |
| `long-only-order-preview` | preview today's orders (shadow or demo_preview); sends nothing | `--broker trading212`, `--mode` |
| `paper-trade-long-only` | plan/preview/submit long-only orders; demo-only, live hard-blocked | `--mode shadow\|demo_preview\|demo_execute`, `--confirm-demo` |
| `supervised-paper-start` | start/advance a calendar-aware supervised paper period | `--product long_only_t212`, `--mode`, `--replay`, `--min-days` |
| `supervised-paper-status` / `-daily-report` / `-final-report` / `-stop` | inspect / report / stop the supervised period | `--product`, `--min-days`, `--reason` |
| `report` | show the most recent backtest run | `--last-backtest/--all` |
| `dashboard` | serve the web control panel (FastAPI + React) | `--port`, `--host` |

## Strategy reference

All tradeable strategies, their config home, and where each stands after the
research in [`docs/strategy_research.md`](docs/strategy_research.md):

**Pairs strategies** (`backtest`, `paper-trade`; configured in
`strategy_defaults.yaml` under `zscore_signal` / `cointegration_strategy` /
`kalman_signal`):

| strategy | idea | status |
| --- | --- | --- |
| `pairs_zscore` | rolling z-score on a fixed hedge ratio | baseline/demo |
| `cointegration_pairs` | EG/ADF-validated pairs, periodic refits, probation on failed refits, cost-edge gate | thin but positive out-of-sample (walk-forward OOS Sharpe 0.88 on stocks) |
| `kalman_pairs` | Kalman-filter hedge ratio with innovation drift gate | contained on crypto (−2.3%); use walk-forward to reject bad configs |

**Basket strategies** (`backtest-basket`, ensemble sleeves; configured under
`basket` / `momentum` / `ml_alpha`):

| strategy | idea | status |
| --- | --- | --- |
| `xsec_momentum` | Jegadeesh-Titman 12-1 cross-sectional momentum, decile books | **flagship sleeve** (Sharpe 1.11 standalone on us_stocks_50) |
| `tsmom` | time-series momentum, inverse-vol sized | **flagship sleeve** (Sharpe 0.88 standalone) |
| `ml_alpha` | gradient-boosted cross-sectional forecasts on ranked features, walk-forward retrained; `momentum_neutral: true` trains on the momentum-orthogonal residual | **flagship sleeve** (the neutralized version is what earns the ensemble slot) |
| `pca_stat_arb` | Avellaneda-Lee PCA residual reversion (OU scoring + hysteresis) | negative on current daily windows; **dropped from the default ensemble** (bled ~8pp in gate-funded spells) |
| `sector_stat_arb` | same OU machinery on leave-one-out sector-factor residuals (US stock universes only) | **settled negative** on daily mega-caps — research capability only |
| `xsec_reversion` | short-term reversal (long losers / short winners) | **settled negative** net of costs at crypto cost levels |

**Meta-strategies:**

| strategy | idea | status |
| --- | --- | --- |
| ensemble (`backtest-ensemble`, `paper-trade-basket`) | inverse-vol risk parity across sleeves, net-of-cost sleeve tracking, trailing t-stat gate, vol targeting, `--leverage` | **the flagship**: `xsec_momentum + tsmom + ml_alpha` on us_stocks_50 daily = +48.5%, Sharpe 1.34, max DD −7.1% (research numbers, single window) |
| funding carry (`carry-backtest`) | long spot / short perp, collect funding, entry/exit hysteresis | +7%/2y funding-leg-only; basis/margin unmodeled; no futures venue connected |

**Universes** (`app/data/universe.py`): `crypto_top_10`, `crypto_majors`,
`synthetic_demo` (offline demo), `us_stocks_demo`, `us_stocks_50`,
`us_stocks_100`, `fx_majors` (research only). US stock universes carry the
sector map used by `sector_stat_arb`.

---

## Configuration

Copy `.env.example` to `.env` (never commit `.env`). Key settings:

| variable | default | meaning |
| --- | --- | --- |
| `LIVE_TRADING` | `false` | master switch; nothing real happens while false |
| `CONFIRM_LIVE_TRADING` | `false` | second, independent confirmation |
| `DATABASE_URL` | `sqlite:///stat_arb.db` | Postgres works unchanged; relative sqlite paths resolve to the project root regardless of working directory |
| `BINANCE_ENABLED` / `BINANCE_MODE` | `false` / `testnet` | account access (Phase 4) |
| `TRADING212_ENABLED` / `TRADING212_MODE` | `false` / `demo` | account access (Phase 5) |
| `MAX_DAILY_LOSS_PCT` … `MAX_TRADES_PER_DAY` | see file | env-level risk overrides |

Full limits live in `app/config/risk_limits.yaml`; strategy parameters in
`app/config/strategy_defaults.yaml`.

### Setting up Binance API keys (Phase 4 — account access)

1. Prefer the **Spot Testnet** first: https://testnet.binance.vision (log in,
   generate HMAC keys; `BINANCE_MODE=testnet`).
2. For a real key later: Binance → API Management → create key with
   **trading only** (no withdrawals!), restrict to your IP, store in `.env`.
3. Revoke at any time from the same API Management page — revoke immediately
   if a key may have leaked.

### Setting up Trading 212 API keys (Phase 5)

1. In the Trading 212 app: Settings → API. Generate a key for **Practice
   (demo)** first; `TRADING212_MODE=demo`.
2. Auth is HTTP Basic — API key as username, API secret as password. The
   official Public API covers **Invest and Stocks ISA** accounts only.
   **CFDs are not supported** and will not be implemented through unofficial
   means.
3. Keys can be invalidated/regenerated from the same screen.

---

## Risk controls

* **RiskManager** — every signal passes through it: max daily loss, max
  drawdown, gross/net exposure, open pairs, trades/day, per-trade and
  per-asset notional, broker capability (shorting/order types), expected
  slippage.
* **Kill switch** — `statarb kill-switch --engage` halts all order flow
  immediately (file-backed; survives restarts; auto-engaged on daily-loss or
  drawdown breach, or on a failed pair rollback). `--disengage` to clear.
* **Pair executor** — never assumes a fill: leg 2 failure triggers hedge
  repair, then rollback of leg 1, then kill-switch escalation.
* **Reconciliation** — local book vs broker positions after executions.

## Enabling live trading (deliberately hard)

`statarb live-trade --broker binance --confirm-live` runs a gate that
requires **all** of: `LIVE_TRADING=true`, `CONFIRM_LIVE_TRADING=true`, the
`--confirm-live` flag, kill switch off, broker connectivity, a recent
backtest report, and a completed paper-trading period. **In this phase the
live order connectors are intentionally not implemented**, so the gate always
refuses — that is by design until Phases 4/5 land and the strategy has
survived stress tests and a minimum paper period.

## Control panel (web dashboard)

A full React + FastAPI command center: dashboard, portfolio, risk cockpit,
execution monitor, strategy monitor, pair discovery, backtesting lab with
saved-result viewer and quality warnings, broker capability matrix, logs and
a tamper-evident audit trail. **Dark and light themes** (plus a `system`
preference that follows your OS) via a top-bar toggle that persists to
`localStorage` and never affects trading logic or safety gates; WebSocket live
updates with auto-reconnect; sortable/filterable tables with CSV export.

```bash
cd frontend && npm install && npm run build && cd ..   # one-time build
statarb dashboard                                       # http://127.0.0.1:8000
```

Dev mode (hot reload): `statarb dashboard` in one terminal, `cd frontend &&
npm run dev` in another → http://localhost:5173.

**Primary operator control panel (no terminal for the normal loop).** The
dashboard now drives the whole supervised-paper workflow through an audited
action orchestrator (`app/dashboard/{actions,jobs,job_store,action_permissions,
action_audit,action_schemas}.py`). From the browser you can:

- open the **Command Center** to see today's status and the single next safe action;
- **start a supervised paper session** and run a daily **shadow** / **demo preview**
  / **demo execute** day, watching live job progress (Supervised Paper → Control
  Center; `POST /api/paper/start`, `/api/paper/daily`);
- run the **Trading 212 demo setup wizard** (`/api/trading212/setup-check`);
- preview orders (shadow), generate the **final report**, **stop** the session;
- rerun **product decision / concentration / survivorship / crisis / readiness**;
- open/download every report in the **Reports Library**;
- engage/disengage the kill switch and read the audit trail in the **Safety Center**.

Demo orders need admin controls + the exact phrase `RUN DEMO PAPER DAY` +
`TRADING212_ALLOW_DEMO_ORDERS=true`, all re-validated server-side. **Live trading
remains impossible from the dashboard** — there is no live endpoint, button, or job
type. Full workflow: `docs/no_terminal_required_workflow.md`. Coverage map:
`docs/dashboard_capability_map.md`. Sprint outcome: `DASHBOARD_COMPLETION_REPORT.md`.

Frontend tests: `cd frontend && npm run test:run` (Vitest + React Testing Library),
plus `npm run typecheck` and `npm run build`.

**Safety model:**
- READ-ONLY by default. Every control endpoint (kill switch, pause strategy,
  run backtest, pair discovery) returns 403 until `DASHBOARD_CONTROLS_ENABLED=true`.
- Dangerous actions require typing an exact confirmation phrase
  ("ACTIVATE KILL SWITCH", "FLATTEN ALL", ...) which the backend re-validates.
- Every control action — allowed or refused — lands in the `audit_events`
  table, visible on the Logs page.
- A red "LIVE TRADING ACTIVE" banner appears if live mode is ever enabled;
  otherwise the green paper/research banner is always visible.
- Secrets never reach the browser: settings views only show whether keys are
  configured. Optional `DASHBOARD_TOKEN` adds bearer-token auth; the CLI
  warns if you bind to anything other than 127.0.0.1.
- Pausing a strategy writes `runtime/paused_strategies.json`, which the paper
  trader honors on its next cycle (no new entries; open pairs still exit).
- Roles (viewer/researcher/trader/admin) are modeled in
  `app/dashboard/permissions.py`; the MVP maps the local operator to admin
  only when controls are enabled.

## Stocks & forex

- **Equities**: research data via the configurable daily provider
  (`--source yahoo`); execution via Trading 212 (demo) once enabled. T212
  Invest/ISA cannot short, so market-neutral pairs are paper/research-only —
  live equity trading would use the long-only fallback mode.
- **Forex**: RESEARCH ONLY. No connected broker executes spot FX and FX CFDs
  are out of scope by policy. The `fx_majors` universe exists for cointegration
  research (e.g. EURUSD|GBPUSD).

With `--interval 1d` the `daily:` profile in `strategy_defaults.yaml` is
merged over the 15m-tuned defaults automatically (daily lookbacks, 5 bps
equity costs, 252-day annualization). The `us_stocks_50` universe provides the
cross-sectional breadth that PCA stat-arb and 12-1 momentum need:

```bash
statarb download-data --universe us_stocks_50 --interval 1d --days 1825 --source yahoo
statarb backtest-basket --strategy xsec_momentum --universe us_stocks_50 --interval 1d
statarb backtest-ensemble --universe us_stocks_50 --interval 1d
statarb discover-pairs --universe us_stocks_50 --interval 1d --lookback-days 1825
statarb walk-forward --strategy cointegration_pairs --universe us_stocks_50 --interval 1d
```

## Docker

```bash
docker compose run --rm bot pytest          # tests in a container
docker compose run --rm bot statarb init-db
docker compose up dashboard                 # dashboard on :8000
```

## Current feature matrix

| feature | status |
| --- | --- |
| Binance spot market data (public REST + WebSocket kline stream) | ✅ |
| Synthetic offline universe | ✅ |
| Cointegration pair discovery (EG + ADF + half-life, CLI threshold overrides) | ✅ |
| Rolling z-score / cointegration / Kalman pair strategies | ✅ |
| Half-life-adaptive time stops + pre-trade cost-edge gate | ✅ |
| Trend-regime filter (skip mean-reversion entries in strong trends) | ✅ (ON by default) |
| PCA residual stat-arb (Avellaneda-Lee OU scoring + hysteresis) | ✅ |
| Time-series momentum (TSMOM) + 12-1 cross-sectional momentum | ✅ |
| Cross-sectional reversal (basket engine) | ✅ (fails net of costs — documented) |
| Multi-strategy risk-parity ensemble with cost-adjusted performance gate | ✅ |
| Portfolio-level volatility targeting (stocks profile; off for crypto) | ✅ |
| Funding-rate carry research backtest (`carry-backtest`, funding leg only) | ✅ |
| ML alpha sleeve (gradient-boosted forecasts, walk-forward retraining) | ✅ |
| Momentum-neutral ML alpha (target/score residualization; in default daily ensemble) | ✅ |
| Aux OHLCV data for basket strategies (`wants_aux`: volume/open/high/low windows) | ✅ |
| Sector-relative residual stat-arb (`sector_stat_arb`, leave-one-out sector factors) | ✅ (tested negative on daily mega-caps — documented) |
| Ensemble leverage option (`--leverage`, margin costs not modeled) | ✅ |
| Percent-of-equity risk limits (absolute limits kept as backstops) | ✅ |
| Daily parameter profile for stocks/FX (`--interval 1d`) | ✅ |
| 50/100-name US large-cap universes (`us_stocks_50`, `us_stocks_100`) | ✅ |
| Long-only fallback mode for baskets (explicitly NOT market-neutral) | ✅ |
| Inverse-vol capital allocation across pairs (`backtest --allocate`) | ✅ |
| Event-driven backtester (costs, no-lookahead, hard money stop per pair) | ✅ |
| Walk-forward + stress suite | ✅ |
| Risk manager + kill switch + pair executor (hedge repair/rollback) | ✅ |
| Order manager (risk-gated submission, audit, fill confirmation) | ✅ |
| Smart order router (liquidity-first legs, spread budget) | ✅ |
| Paper trading (live data, simulated fills, reconciliation, equity snapshots) | ✅ |
| Basket/ensemble paper trading (`paper-trade-basket`: daily EOD refresh, risk-gated rebalancing, simulated shorts) | ✅ |
| Dashboard (status, pairs, signals, orders, trades, equity, performance) | ✅ |
| Binance signed orders | ✅ testnet-first; LIVE blocked unless the gate grants it |
| Trading 212 equities connector (official Public API, Basic auth) | ✅ demo-first; sell-qty convention flagged VERIFY |
| Compliance checks (market hours, stale data) | ✅ (simplified US session; calendar lib later) |
| Corporate-action adjustment | ✅ splits (Yahoo server-side) + dividends via stored `adj_close`; re-run `download-data` to backfill older rows — see [`docs/data_quality.md`](docs/data_quality.md) |
| Experiment tracking (`statarb experiments`; every research run = a counted trial) | ✅ |
| Alpha registry with promotion gates (`statarb alpha-registry`) | ✅ live stages blocked pending governance |
| Data audit with survivorship/adjustment verdicts (`statarb data-audit`) | ✅ |
| **Trading 212 CFDs** | ❌ **unsupported by official API — will not be built** |
| Binance futures / leverage / true shorting | ❌ off by default; spot cannot short |

## Why this is still not guaranteed to be profitable

A deliberately brutal list. None of the engineering below changes the verdict
in [`FINAL_RESEARCH_REPORT.md`](FINAL_RESEARCH_REPORT.md): **do not trade real
capital yet.**

- **Single-window, in-sample selection.** The flagship was chosen as the best
  of ~40-60 configurations on ONE 5-year window. The experiment tracker now
  counts trials, but the historical trials are not back-filled, so the deflated
  Sharpe does not yet correct for that search. The true out-of-sample edge is
  most likely **below the reported Sharpe ~1.0**.
- **Survivorship bias.** `us_stocks_50/100` are 2026 survivors backtested into
  2021 — the worst case for momentum. No point-in-time universe yet.
- **Costs are real and only partly modeled.** We now charge commission,
  slippage, next-open execution, borrow and margin interest. Still missing:
  per-name hard-to-borrow rates (your short decile is the expensive one), short
  dividend liability beyond adjustment, FX, taxes/stamp duty.
- **Broker limitations are binding.** The strategy is market-neutral; no
  connected venue can short (T212 Invest/ISA can't, Binance spot can't, futures
  isn't connected). What you can actually trade is a *different*, long-only,
  directional strategy that has not been validated.
- **Regime shift.** Momentum crashes in panic rebounds (2009-style). The 2021-26
  window has no such event; the crash-protection scaler is unproven on a real one.
- **Return concentration.** One month is 30% of the flagship's PnL; the best 5%
  of days exceed its total return. Event-concentrated edges are fragile.
- **Model decay, capacity, psychology, API outages, slippage drift** — all the
  usual ways a paper edge dies in production, none yet observed live.

Detail: [`docs/known_limitations.md`](docs/known_limitations.md),
[`RESEARCH_WEAKNESSES.md`](RESEARCH_WEAKNESSES.md),
[`PRODUCTION_RISK_REGISTER.md`](PRODUCTION_RISK_REGISTER.md).

### Honest results disclosure

Full research notes with sources: [`docs/strategy_research.md`](docs/strategy_research.md).
**Re-validated numbers** (after the audit fixes) are in
[`docs/current_best_strategy.md`](docs/current_best_strategy.md) — the legacy
figures below predate the dividend/execution/financing corrections and overstate
performance by roughly Sharpe 0.3.

**Crypto (10 names, 15m bars, ~90 days, 15 bps costs):** mean reversion bled
while momentum dominated the window. TSMOM was the only standalone winner
(+7.1%); Kalman pairs were contained to −2.3% by the drift gate; PCA stat-arb
(−15.9%) and short-term reversal (every swept config negative) are **not
viable at this breadth and cost level** — that is a structural finding, not a
tuning problem. The ensemble's cost-adjusted gate correctly de-funds the
losing sleeves (+1.7%).

**US stocks (50 names, daily bars, 5 years, 5 bps costs):** with the breadth
these strategies were designed for, 12-1 cross-sectional momentum returned
+92.9% (Sharpe 1.11), TSMOM +28.8% (Sharpe 0.88), and the original 3-sleeve
risk-parity ensemble +36.3% with Sharpe 1.05 (since superseded — the current
flagship is the ML-alpha blend below at **+48.5% / Sharpe 1.34**). Pairs
trading was thin but positive out-of-sample (walk-forward OOS Sharpe 0.88).
Widening to 100 names made things *worse* (momentum diluted; PCA residual
reversion lost 20-29% in every configuration) — the ensemble's tightened
performance gate (`min_sleeve_t: 0`) is what kept the 100-name blend
positive (+14.8%).

**Funding-rate carry (10 perps, 2 years, funding leg only):** the same signal
went from −46.5% (naive 8h re-ranking; $5.6k of fees on $10k) to **+7.0%
(~3.5%/yr, max DD −1.0%)** with entry/exit hysteresis. Basis risk and margin
are not modeled; no futures account is connected.

**ML alpha (gradient-boosted forecasts, us_stocks_50 daily):** +28.5%
standalone (Sharpe 0.84) once trading was throttled to the forecast horizon
with a hold band — the identical model lost 24.6% re-ranked daily. The raw
sleeve diluted the ensemble (its forecasts ride the same momentum factor as
the 12-1 sleeve), but training it on the momentum-orthogonal residual
(`momentum_neutral: true`) flipped it accretive, and dropping the dead pca
sleeve helped again: the **flagship daily ensemble (xsmom + tsmom +
ml_alpha) prints +48.5%, Sharpe 1.34, max DD −7.1%** — robust to
allocator-window perturbation (Sharpe 1.14–1.43); ~24% CAGR at 3x leverage
(margin costs not modeled). Settled negatives from the same research
cycles: extra volume/overnight/range-vol features buried the ML signal at
every feasible training-window size; sector-relative residual reversion
loses on daily mega-caps in every variant; continuous t-stat sleeve sizing
was worse than the binary gate at every scale tried.

Caveats everywhere: single historical windows, survivorship bias in the stock
universes, a strong momentum regime. These are viability numbers, not
expected returns. Do not trade anything that has not survived walk-forward,
the stress suite and a long supervised paper period.
