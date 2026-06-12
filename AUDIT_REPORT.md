# AUDIT REPORT — stat-arb-bot

**Date:** 2026-06-12
**Scope:** full repository (app/, scripts/, frontend/, docs/, configs, stored data)
**Verdict in one line:** a well-engineered, unusually honest retail research framework whose
**flagship result (+48.5%, Sharpe 1.34) is not yet evidence of alpha** — it is a single-window,
in-sample-selected, survivorship-biased, dividend-blind, friction-light backtest of a strategy
that no connected broker can actually trade.

Companion documents:

- [RESEARCH_WEAKNESSES.md](RESEARCH_WEAKNESSES.md) — every methodology weakness with severity, module, fake-profit mechanism, fix, and proving test
- [PRODUCTION_RISK_REGISTER.md](PRODUCTION_RISK_REGISTER.md) — live-trading failure modes
- [STRATEGY_ACCEPTANCE_CRITERIA.md](STRATEGY_ACCEPTANCE_CRITERIA.md) — the gates every strategy must pass from idea to live

---

## Summary scorecard

| area | grade | one-line assessment |
| --- | --- | --- |
| 1. Code architecture | **B+** | clean module boundaries, typed, small files, good logging; no experiment/governance layer; 40KB CLI monolith |
| 2. Research methodology | **D** | honest narration, but flagship = argmax over ~40+ configs on ONE window; no OOS validation of the basket path at all |
| 3. Backtester realism | **C** | pairs engine is genuinely careful (next-open fills, risk-gated); basket engine fills at the signal close, flat-bps costs only |
| 4. Data quality | **C−** | splits OK (Yahoo server-side), **dividends NOT adjusted**, corporate_actions.py never wired in, README claims otherwise |
| 5. Survivorship bias | **D** | hardcoded 2026 survivor universes backtested to 2021; documented but unquantified and unmitigated |
| 6. Lookahead bias | **B** | structurally prevented in both engines within their assumptions; basket same-close fill is the residual hole |
| 7. Feature leakage | **B−** | ML panel construction is correct in-window; overlapping 5-day labels + no purged CV + hyperparams tuned on the test window |
| 8. Transaction cost realism | **C−** | flat bps per unit turnover; zero borrow, zero margin interest, zero impact, zero spread dynamics; VolumeAwareSlippage exists but is dead code |
| 9. Execution realism | **C** | no partial fills, no rejects, no latency, no market hours in backtests; paper traders simulate margin accounts that do not exist |
| 10. Risk controls | **B** | solid limit/kill-switch machinery; nothing portfolio-level (no factor exposure, no VaR/CVaR, no beta caps) |
| 11. Broker capability enforcement | **A−** | capability matrix enforced pre-order; CFDs excluded by policy; T212 sell convention still flagged VERIFY |
| 12. Portfolio construction | **C+** | inverse-vol + binary t-stat gate, honestly cost-aware; no covariance estimation, no HRP/ERC, allocator params tuned in-sample |
| 13. Dashboard usefulness | **B** | good ops cockpit with real safety model; zero research/validation/governance surface |
| 14. Testing coverage | **B−** | 154 tests, all passing, well-mocked; no leakage traps, no overfit-rejection regression tests, no property tests |
| 15. Production readiness | **D+** | live gate correctly refuses (connectors absent); but **zero git commits**, no CI, in-memory paper books, sqlite |
| 16. Security | **B** | secrets gitignored, dashboard read-only default + confirmation phrases + audit; .env.example missing, token is plain env |
| 17. Documentation | **B+** | unusually honest; two overclaims: "corporate-action adjustment ✅" and "validated daily flagship" |

---

## What is genuinely good (keep, do not regress)

1. **The pairs backtest engine** (`app/backtesting/engine.py`): signal at bar i, fill at
   bar i+1 open, optional extra delay, every entry through the RiskManager, hard per-pair
   money stop, kill-switch semantics identical to paper. This is the realism standard the
   basket engine must be brought up to.
2. **Cost-edge gating and hysteresis discipline.** The pre-trade `min_edge_ratio` gate,
   hold-band ML execution, and carry entry/exit hysteresis all encode the single most
   important retail-quant lesson (turnover kills) and are backed by documented negative
   results (−46.5% → +7.0% carry; −24.6% → +28.5% ML).
3. **Sleeve tracking net of own costs** in the ensemble — the gross-of-cost allocator trap
   was found and fixed, and the lesson is written down.
4. **Negative results are preserved** (`docs/strategy_research.md`): reversal, PCA residuals,
   sector residuals, orthogonal features, continuous t-stat sizing — all documented as
   settled-negative with the evidence. This is institutional behavior and rare.
5. **Broker capability matrix + live-trading gate**: live orders are structurally impossible
   today, CFDs are excluded by policy, and the dashboard's dangerous controls are
   confirmation-phrase gated and audited.
6. **Test hygiene**: 154 passing tests, no live API calls, synthetic fixtures.

---

## The five findings that dominate everything else

### F1 — CRITICAL: the flagship has never been validated out-of-sample

`walk_forward.py` and `stress_tests.py` operate **only on the pairs engine**
(`BacktestConfig`/`BacktestEngine`). The basket/ensemble path — where the flagship lives —
has no walk-forward, no stress suite, no holdout. Every flagship number in the README
(+48.5%, Sharpe 1.34, DD −7.1%) is a full-period backtest on the same 2021-06 → 2026-06
window that was used to choose the sleeve set, the allocator window, the gate threshold,
the ML hold band, and the neutralization scheme. The strategies *retrain/refit inside* the
window (walk-forward *by construction* at the model level), but **strategy selection and
configuration are 100% in-sample**.

### F2 — CRITICAL: multiple-testing inflation, uncorrected

`docs/strategy_research.md` and `scripts/` document at minimum: 24 reversal sweep configs,
PCA sweeps across book sizes and factor rules, 4 ML variants, 3 fit-window experiments,
allocator taper grids, 3 vol-window perturbations, multiple sleeve compositions, two
universes, and gate-threshold changes — **≥ 40-60 strategy evaluations on one window**,
with the flagship chosen as the best. With that search breadth, the expected maximum Sharpe
of a *zero-alpha* family on a 5-year window is materially above 1.0. No deflated Sharpe
ratio, no White reality check, no FDR control exists anywhere in the codebase. Until the
flagship's Sharpe is deflated for the search and reproduced on data it never touched, treat
1.34 as an upper bound with unknown (possibly ~half) real value.

### F3 — CRITICAL: nothing that was researched can actually be traded

The flagship is ~50% short book. Trading 212 Invest/ISA cannot short. Binance spot cannot
short. Binance futures is implemented as a capability stub and explicitly not connected.
Therefore the flagship is executable only inside its own simulator. The paper trader
(`basket_paper_trader.py`) honestly says so, but the system has no governance object that
*hard-blocks* promotion of a strategy whose requirements exceed every connected venue —
today that is convention, not code. The realistic tradable menu today is: long-only
fallbacks (NOT market-neutral, different risk entirely), or crypto strategies within spot
constraints. This should reframe research priorities (see RESEARCH_WEAKNESSES W-12).

### F4 — HIGH: the equity data is wrong in two known ways

- **Dividends are not adjusted.** `providers_yahoo.py` reads Yahoo's `quote` arrays
  (split-adjusted only) and ignores `adjclose`; `corporate_actions.py` is wired into
  nothing (verified: only tests import it). Stored KO closes confirm raw prices. Effect:
  every ex-div day injects a phantom negative return (~2.5-4%/yr for staples/energy/telecom
  names, ~0-0.5% for growth); 12-1 momentum ranks are systematically tilted long
  low-yield/short high-yield; TSMOM signs flip on borderline names; the short book is
  *credited* dividends it would owe in reality. The README feature matrix claims
  "Corporate-action adjustment (splits/dividends) ✅" — false in the pipeline.
- **Survivorship bias.** `us_stocks_50/100` are 2026 survivors backtested from 2021.
  Honest warnings exist, but no point-in-time universe, no delisting handling, no
  quantification. Momentum on surviving mega-caps is the classic worst case for this bias.

### F5 — HIGH: the short side and leverage are frictionless

No borrow fee, no locate constraint, no margin interest, no short dividend liability, no
funding cost anywhere in the basket path. The flagship at 3x leverage is reported at 24%
CAGR with the caveat "margin costs not modeled" — at 2026 retail margin rates (~6-8% on
the borrowed 2x) that line item alone is roughly **−12 to −16pp of CAGR**, i.e. most of the
leverage benefit. Stock borrow on the short decile (often hard-to-borrow momentum losers)
plus short dividend liability take several more points. The leverage table in
`docs/strategy_research.md` §8 should be considered marketing-shaped until costs are in.

---

## Area-by-area audit detail

### 1. Code architecture — B+
Clean layering (`data → research → strategies → backtesting → risk → execution →
dashboard`), pydantic configs, structured JSON logging with an audit channel, types and
exceptions centralized. Weaknesses: `app/cli/main.py` is a 40KB god-module mixing wiring,
config-merging and presentation; strategy parameter merging (`daily:` profile) is implicit
and easy to misread; `scripts/` experiments are not reproducible runs (no seeds/config
snapshots/IDs); no experiment or governance layer exists; zero git history (see §15).

### 2. Research methodology — D
See F1/F2. Additional notes: the walk-forward that *does* exist (pairs) stitches OOS windows
correctly and reports IS→OOS degradation — good design, tiny sample (4 windows on stocks).
The research docs honestly label caveats, but the *process* has no holdout discipline: every
"experiment" in `scripts/exp_*.py` reads the full window and reports full-window metrics.
There is no experiment registry, no config hash, no data snapshot, no seed logging beyond
the ML `random_state`.

### 3. Backtester realism — C
Pairs engine: genuinely good (see above). Basket engine
(`basket_engine.py:104-123`): weights computed on a window ending at close[t] earn
close[t]→close[t+1] — an implicit fill **at the very close the signal observed**, costed at
flat `cost_bps`. No next-open execution, no delay option, no impact, no per-asset costs, no
borrow, no halt/missing-bar handling beyond global ffill. The `entry_delay_bars` stress that
exists for pairs has no basket equivalent. Metrics module is correct and conservative
(separate daily resample for worst-day; bars_per_year override prevents phantom-weekend
Sharpe inflation — good).

### 4. Data quality — C−
`check_bars` catches duplicates/gaps/non-positive prices; outlier returns only warn (a 2:1
split-style break would pass with a log line) and failed symbols are **stored anyway**
(`historical_loader.py:74`). `build_price_matrix` ffills up to 3 bars (3 *days* on daily
data — stale prices can enter momentum/vol calculations silently) then drops any row with
any NaN, so the matrix is truncated to the youngest symbol's history (alignment bias; on
crypto this silently shortens everyone's history to the newest listing). No dataset-level
quality report is persisted; no timezone/calendar validation; the 15m crypto history is ~90
days (one regime).

### 5./6./7. Biases — D / B / B−
Covered in F4 (survivorship), F1 (selection). Lookahead: both engines are structurally
sound given their fill assumptions; `ml_features.build_panel` correctly stops training
dates `forward_bars` before the window end and ranks per-date. Residual concerns: (a)
overlapping 5-day forward labels at daily sampling inflate effective training fit (not a
backtest lookahead, but it makes the model's in-window confidence unreliable); (b) ML
hyperparameters (depth/lr/iters), `top_frac`, `hold_frac`, horizons, and
`momentum_neutral` were all chosen by reading the same single window's output — that is
test-set tuning; (c) no purged/embargoed CV exists.

### 8. Transaction costs — C−
What exists: flat per-leg bps (pairs), flat per-turnover bps (baskets), per-broker
commission models, a square-root `VolumeAwareSlippage` class that **no engine
instantiates**. What is missing entirely: borrow/locate, short dividend liability, margin
interest, funding for synthetic shorts, spread as f(asset, time), market impact as
f(participation), FX conversion, stamp duty/PTM on non-US if ever added, taxes. The 5 bps
daily-equity assumption is defensible for liquid mega-caps at small AUM but is asserted,
not derived from spread data.

### 9. Execution realism — C
Paper traders simulate fills at close ± flat slippage with no partial fills, no rejects
(other than risk), no latency, no halts, no market-hours enforcement in the basket loop,
and an in-memory book that resets on restart. SmartOrderRouter and the pair executor's
hedge-repair/rollback are good designs awaiting a real venue. TCA does not exist
(no arrival/decision price capture).

### 10. Risk controls — B
Strong: layered limits (pct-of-equity primary, absolute backstop), kill switch
(file-backed, auto-engage on loss/DD breach, survives restarts), exits never blocked,
audit log of rejections. Missing: any portfolio-level analytics — no beta to
SPY/QQQ/BTC, no sector concentration, no VaR/CVaR/stress, no correlation-spike de-risking,
no capital escalation policy. `validate_pair_entry` hardcodes `broker="binance_spot"` in
the backtest path (cosmetic but wrong label in audit logs). Daily-loss/DD checks run
inside backtests — good parity discipline.

### 11. Broker enforcement — A−
`broker_capabilities.yaml` is checked by the risk manager before orders; T212 CFDs are
policy-excluded; futures capped at 1x by default. Open item: T212 sell-quantity convention
is still `VERIFY on demo before first use` — correctly flagged, must stay blocking.

### 12. Portfolio construction — C+
Inverse-vol with a binary trailing-t gate, max-share cap, optional vol targeting, costs
netted per sleeve. It is honest but statistically primitive: vols estimated on ≤60
observations, no covariance/correlation between sleeves used at all (risk parity in name
only — it is inverse-vol, not ERC), gate threshold and window tuned on the single window
(`min_sleeve_t: 0.0` was *chosen because* −0.5 lost money on us_stocks_100 — that is
in-sample fitting of a risk control), no turnover penalty at the allocator level, no
drawdown-based de-allocation, no regime awareness.

### 13. Dashboard — B
Real safety model (read-only default, confirmation phrases, audit trail, token, live
banner). Operationally useful pages. Nothing for: experiments, validation status, data
quality, factor exposure, capacity, governance, decay. The backtesting-lab page surfaces
saved runs with warnings — a good foundation for the Experiment Explorer.

### 14. Testing — B−
154 passing, fast, no network. Good unit coverage of corporate-action math (ironically —
the function is correct, just never called), risk limits, capability enforcement, basket
engine mechanics, T212/Binance clients (mocked), dashboard permissions. Missing: a
deliberate leakage trap (a feature that peeks ahead must be caught), a synthetic
overfit-rejection regression, basket execution-delay tests, cost-doubling kill tests,
property-style invariants (no order > limit, no promotion without gates), and any CI.

### 15. Production readiness — D+
The live gate refuses by design — correct. But: **the repository has no commits** (the
entire codebase is untracked working files — one bad `rm`/disk event loses everything, and
no experiment can ever be tied to a code version); sqlite under a long-running dashboard +
paper trader + CLI is a single-writer bottleneck with no WAL configuration visible; paper
book state is in-memory (restart = silent flat book while equity history continues);
`.env.example` referenced by the README does not exist; no backups, no deploy story beyond
docker-compose, no monitoring/alerting.

### 16. Security — B
Secrets via env only, `.env` gitignored (and present locally — fine), settings never
expose secrets to the browser, dashboard binds 127.0.0.1 with a warning otherwise,
controls 403 by default, dangerous actions re-validated server-side, tamper-evident audit
trail. Minor: no rate limiting/lockout on token auth, token compared in app code (use
constant-time compare — verify), CSP/security headers not audited here, Binance HMAC
signing module small and testable (good).

### 17. Documentation — B+
Best-in-class honesty for this tier. Two material overclaims to fix: the feature-matrix
line "Corporate-action adjustment (splits/dividends) ✅" (the code exists, the pipeline
never calls it — and dividends are genuinely absent from stored data), and the phrase
"validated daily flagship" in `basket_paper_trader.py` (nothing about the flagship is
validated in the OOS sense). `.env.example` is referenced but missing.

---

## Priority order for remediation

Matches the mission's Phase 16 and the dependency structure of the findings:

1. **Put the repo under version control** (git commit now; nothing else is reproducible without it).
2. **Experiment tracking + alpha registry** — stop the bleeding: every future run gets an ID, config hash, data hash, git hash.
3. **Data layer fixes** — dividend adjustment via Yahoo `adjclose` (store both raw and adjusted), data-audit CLI, survivorship status flags on every result, delisting awareness.
4. **Basket-engine realism** — next-open execution mode, delay/cost stress parity with the pairs engine, borrow/margin/funding cost hooks.
5. **Validation layer** — basket walk-forward, holdout protocol, purged CV for ML, deflated Sharpe + multiple-testing report over the documented experiment family.
6. **Re-run the flagship through all of the above and re-state its numbers honestly** — expect material degradation; report it.
7. Allocator upgrade, governance gates, dashboard surfaces, tests, docs — per plan.

**The most important sentence in this audit:** the system's *engineering* deserves more
trust than its *numbers*. Until F1-F5 are fixed and the flagship survives them, the honest
status of every README performance figure is "in-sample viability sketch, upper bound."
