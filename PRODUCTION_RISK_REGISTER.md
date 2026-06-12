# PRODUCTION RISK REGISTER — stat-arb-bot

Risks that can cause capital loss, broken hedges, or silent corruption **in paper/live
operation** (research-methodology risks live in [RESEARCH_WEAKNESSES.md](RESEARCH_WEAKNESSES.md)).
Each entry: severity × likelihood, affected module, failure mode, mitigation status,
required action, and the test/drill that proves mitigation.

Status legend: ✅ mitigated · 🟡 partially mitigated · ❌ open

---

## A. Capital-loss / execution risks

### PR-01 Broken hedge: one leg fills, the other does not
- **Severity:** critical · **Likelihood:** medium (every live pair entry is exposed)
- **Module:** `app/execution/pair_executor.py`
- **Failure mode:** leg 2 rejected/timeout → position is directional, not neutral.
- **Status:** 🟡 hedge-repair → rollback → kill-switch escalation is implemented and unit-tested against mocks; never exercised against a real venue (no live connector), and rollback itself can fail in fast markets (slippage between legs is unbounded).
- **Action:** testnet drill with forced leg-2 rejection; max-rollback-slippage budget with alerting; reconciliation immediately after any repair.
- **Proof:** testnet chaos test (kill the connection between legs) ends with flat book or engaged kill switch within N seconds, and an audit trail.

### PR-02 Paper/live book state lost on restart
- **Severity:** high · **Likelihood:** high (restarts are routine)
- **Module:** `app/execution/paper_trader.py`, `basket_paper_trader.py` (in-memory books)
- **Failure mode:** process restarts → trader believes it is flat while equity snapshots continue; in live mode the equivalent bug would re-enter duplicate positions.
- **Status:** ❌ documented as a known limitation; no persistence/recovery.
- **Action:** persist book state per bar (positions table already exists); on startup reconcile stored book vs broker positions and refuse to trade on mismatch.
- **Proof:** integration test: kill the trader mid-session, restart, book identical and one reconciliation audit event emitted.

### PR-03 Kill switch trusted but single-channel
- **Severity:** high · **Likelihood:** low-medium
- **Module:** `app/risk/kill_switch.py` (file-backed flag)
- **Failure mode:** file deleted/unwritable/NFS-weird → order flow resumes silently; or two processes race (CLI + dashboard + trader all toggle it).
- **Status:** 🟡 file-backed, survives restarts, auto-engages on breaches; no write-failure alarm, no heartbeat, no process-level lock.
- **Action:** fail-closed semantics (cannot *read* the flag ⇒ treat as engaged); audit every transition with actor; alert on disengage.
- **Proof:** unit test: unreadable flag file ⇒ `is_active == True`; concurrency test of engage/disengage races.

### PR-04 Stale or gapped market data drives live decisions
- **Severity:** high · **Likelihood:** medium
- **Module:** `app/data/market_data.py` (ffill≤3 bars), `basket_paper_trader.py` (trades on the last stored bar), `risk_limits.yaml` (`reject_if_stale_data_seconds: 120` enforced only at order level)
- **Failure mode:** provider outage → trader happily rebalances on yesterday's closes; vol estimates shrink on ffilled flats → sizing *increases* exactly when data is worst.
- **Status:** 🟡 order-level staleness check exists; signal-level staleness is invisible.
- **Action:** per-symbol staleness budget at signal time; skip (don't resize) symbols beyond it; data-quality gate before each rebalance; alert channel.
- **Proof:** paper-trader test with a frozen provider: no orders, one warning audit event per cycle.

### PR-05 Daily-loss / drawdown limits measured against in-memory state
- **Severity:** high · **Likelihood:** medium
- **Module:** `app/risk/risk_manager.py` (`daily_start`, `peak` reset on process start)
- **Failure mode:** restart resets `peak_equity`/`daily_start_equity` → a 9% intraday loss followed by a restart re-arms the limits from the lower base; sequential small losses across restarts never trip anything.
- **Status:** ❌ state is process-local.
- **Action:** persist daily-start and peak equity (equity_snapshots already stores history — load on boot).
- **Proof:** restart-mid-drawdown test: limits computed from persisted peak, not boot equity.

### PR-06 Trading 212 sell-quantity convention unverified
- **Severity:** critical (sign error = doubling a position instead of closing) · **Likelihood:** low (flagged everywhere)
- **Module:** `app/brokers/trading212/client.py`, `broker_capabilities.yaml` (`sell_convention: negative_quantity # VERIFY`)
- **Status:** 🟡 flagged; demo-mode-first policy documented.
- **Action:** scripted demo-account verification (place 1-share buy, close with documented convention, assert flat) before any T212 order path is enabled; record the result in the capability file.
- **Proof:** the verification script's output stored as an artifact; capability flag flips from VERIFY only with that artifact.

### PR-07 Synthetic shorting in paper has no live counterpart
- **Severity:** high (expectation risk → user funds a strategy that cannot exist) · **Likelihood:** certain until a shorting venue connects
- **Module:** `basket_paper_trader.py` (`allow_short=True` "simulated margin account"), strategy roadmap
- **Status:** 🟡 honestly documented; not enforced by governance (nothing stops a human flipping `LIVE_TRADING` once connectors exist and discovering T212 rejects every short).
- **Action:** governance gate: an alpha whose paper book uses shorts cannot pass live-readiness while no connected venue supports shorting; long-only fallback must be separately validated (it is a *different strategy*).
- **Proof:** gate unit test; live-readiness report shows venue-capability cross-check per alpha.

### PR-08 No reconciliation loop in basket paper/live path
- **Severity:** medium-high · **Likelihood:** medium
- **Module:** `app/execution/reconciliation.py` exists for pairs; basket trader never calls it
- **Failure mode:** simulated (later: real) fills drift from the book (partial fills, rejected orders mid-rebalance, restarts) and nobody notices until PnL is wrong.
- **Action:** end-of-cycle position reconciliation + EOD equity reconciliation with tolerance alarms, for the basket path.
- **Proof:** integration test injecting a phantom fill → reconciliation flags within one cycle.

## B. Infrastructure / operational risks

### PR-09 Repository has zero commits
- **Severity:** critical (total loss possible) · **Likelihood:** low but real
- **Module:** the repo itself
- **Failure mode:** disk failure / bad delete loses the only copy of ~100 source files; no change can be reverted; no experiment is tied to code.
- **Status:** ❌
- **Action:** `git commit` immediately; remote backup; commit discipline from now on (experiment tracker depends on commit hashes).
- **Proof:** `git log` non-empty; experiment records carry commit hashes.

### PR-10 SQLite as the single concurrent store
- **Severity:** medium · **Likelihood:** medium-high once dashboard + paper trader + CLI run together
- **Module:** `app/data/storage.py` (`sqlite:///stat_arb.db`)
- **Failure mode:** writer lock contention → "database is locked" mid-rebalance; no WAL configuration visible; one file, no backups.
- **Action:** enable WAL + busy_timeout for sqlite; document Postgres for any multi-process deployment; scheduled DB backup.
- **Proof:** concurrent writer test passes with WAL; backup file exists and restores.

### PR-11 Data refresh mutates research data in place
- **Severity:** medium · **Likelihood:** certain (upsert by design)
- **Module:** `storage.upsert_bars`, provider re-downloads
- **Failure mode:** provider restates history (Yahoo does) → yesterday's backtest is unreproducible and nobody is told; paper trader and researcher share one mutable table.
- **Action:** dataset content-hash recorded per experiment (Phase 3); optionally snapshot research extracts to parquet in `data_store/`.
- **Proof:** experiment re-run detects data-hash drift and says so instead of silently differing.

### PR-12 Long-running trader loops swallow all exceptions
- **Severity:** medium · **Likelihood:** medium
- **Module:** `paper_trader.py` / `basket_paper_trader.py` `run()` (`except Exception: log + continue`)
- **Failure mode:** a deterministic bug (bad symbol, schema change) throws every cycle forever; the loop burns API quota and the operator sees "running" — a zombie trader.
- **Action:** consecutive-failure budget → engage kill switch + exit non-zero; failure-streak metric on the dashboard.
- **Proof:** unit test: N consecutive step() exceptions stop the loop with kill switch engaged.

### PR-13 No alerting/monitoring channel
- **Severity:** medium · **Likelihood:** certain
- **Module:** ops (absent)
- **Failure mode:** kill-switch engagement, data staleness, reconciliation breaks — all observable only by reading logs or the dashboard.
- **Action:** minimal alert hook (email/webhook) on: kill-switch transitions, risk breaches, reconciliation mismatch, data-quality gate failures, trader crash-loops.
- **Proof:** alert fires in a test harness for each event class.

## C. Security risks

### PR-14 API keys in plaintext .env on a desktop
- **Severity:** high (if live keys ever added) · **Likelihood:** medium
- **Module:** `.env`, `app/config/settings.py`
- **Status:** 🟡 gitignored, never logged, never sent to browser — good; but trade-enabled keys on a general-purpose Windows machine are one infostealer away.
- **Action:** keep keys trade-only + IP-restricted (documented); revoke drill; consider OS keychain when live phase starts; never store withdrawal-enabled keys.
- **Proof:** documented key-scope checklist in live-readiness gate; `.env.example` (currently missing) lists only placeholder values.

### PR-15 Dashboard auth is a single static token, optional
- **Severity:** medium (low while 127.0.0.1-only) · **Likelihood:** low
- **Module:** `app/dashboard/auth.py`
- **Failure mode:** if ever bound beyond localhost without a token (CLI warns, doesn't block), every read endpoint is open; token compare may not be constant-time; no lockout.
- **Action:** refuse non-localhost bind without token (hard error, not warning); constant-time compare; failed-auth audit events.
- **Proof:** binding 0.0.0.0 without token exits with error in test; timing test on comparator.

### PR-16 Dashboard controls enabled = full admin, one env var away
- **Severity:** medium · **Likelihood:** low
- **Module:** `app/dashboard/permissions.py` (local operator = admin when controls enabled)
- **Status:** 🟡 confirmation phrases + audit cover the dangerous endpoints.
- **Action:** keep; when live phase starts, per-action roles and a second factor for kill-switch disengage / flatten-all.
- **Proof:** permissions tests per role (some exist); live-phase checklist item.

## D. Model / market risks (live-phase, pre-registered now)

### PR-17 Regime shift: momentum crash
- **Severity:** high · **Likelihood:** medium over any multi-year horizon
- **Failure mode:** 12-1 momentum's documented failure mode is violent reversal (2009-style); the ensemble's t-stat gate reacts with a 20-60 day lag; vol targeting reacts after the vol prints.
- **Mitigation plan:** crash-protected momentum variant in the research queue (Phase 6); drawdown-based de-allocation in the allocator (Phase 5); stress scenario "momentum crash month" in the suite.

### PR-18 Correlated-sleeve breakdown
- **Failure mode:** xsmom/tsmom/ml share regime exposure; the blend's smoothness is partly window luck (their realized correlation is low *in this window*).
- **Mitigation plan:** rolling sleeve-correlation monitor with de-risk trigger (Phase 10 regime/dynamic scaling).

### PR-19 Funding-carry tail risk
- **Failure mode:** the carry book's true risks (basis blowout, liquidation of the short perp in a squeeze, exchange outage during stress) are exactly the unmodeled ones; current +7%/2y figure is the funding leg only.
- **Mitigation plan:** basis + margin + liquidation modeling before any futures connectivity (Phase 6B); position-level liquidation-distance limit; venue-outage drill.

### PR-20 Live slippage exceeds the 5 bps research assumption
- **Failure mode:** thin-edge sleeves (pairs especially) die quietly at 8-12 bps real.
- **Mitigation plan:** TCA from day one of paper-with-real-quotes (Phase 8/9); automatic de-risk when realized slippage > modeled slippage for N days (Phase 10).

---

## Top five actions by risk-reduction per effort

1. **PR-09**: `git commit` — minutes, removes a total-loss scenario.
2. **PR-05 + PR-02**: persist risk baselines and book state — small, removes two silent-loss modes.
3. **PR-03**: fail-closed kill switch — one function change plus tests.
4. **PR-12**: crash-loop budget in trader loops — small.
5. **PR-04**: signal-level staleness gate in the basket trader — small, prevents the worst data-driven sizing failure.
