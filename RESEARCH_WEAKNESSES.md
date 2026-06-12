# RESEARCH WEAKNESSES — stat-arb-bot

Every known weakness in the research methodology, classified per the audit protocol:
**severity / affected module / why it matters / how it can fake profitability / required
fix / test proving it is fixed.** Ordered by severity, then by how much of the flagship
result each one could be silently responsible for.

Severity scale: **critical** = can fully account for reported edge; **high** = can account
for a large fraction or change the sign of decisions; **medium** = distorts magnitudes or
specific names; **low** = hygiene.

---

## W-01 — No out-of-sample validation path for basket/ensemble strategies

- **Severity:** CRITICAL
- **Module:** `app/backtesting/walk_forward.py`, `app/backtesting/stress_tests.py` (both pairs-only), `app/cli/main.py`
- **Why it matters:** the flagship ensemble (xsmom + tsmom + ml_alpha) — the headline result of the entire project — can only be run full-window. Walk-forward and the stress suite consume `BacktestEngine`/`BacktestConfig` and cannot touch `run_basket_backtest`. Sleeve composition, allocator window, gate threshold, ML hold band and neutralization were all selected by reading full-window results.
- **How it fakes profitability:** selecting a configuration on the same window you report converts luck into "Sharpe." A family of zero-alpha configs evaluated on one window will hand you a winner; with no OOS re-test, that winner is indistinguishable from real edge.
- **Required fix:** basket/ensemble walk-forward (rolling config-freeze → trade-forward), a true holdout protocol (e.g., reserve the most recent N months untouched until a config is frozen), and a basket stress suite (cost ×2, slippage ×2-3, 1-2 bar execution delay, remove-best-5%-trades, month-concentration check).
- **Proving test:** a synthetic strategy that only profits in the selection window must show OOS Sharpe ≈ 0 in the basket walk-forward report; an integration test asserts `backtest-ensemble --walk-forward` produces IS and OOS metrics and that the stress suite runs all scenarios on a basket strategy.

## W-02 — Multiple testing / selection bias, uncorrected

- **Severity:** CRITICAL
- **Module:** research process (`scripts/exp_*.py`, `scripts/sweep_*.py`, `docs/strategy_research.md`); no `app/research/multiple_testing.py` exists
- **Why it matters:** ≥40-60 documented strategy/config evaluations on the same 5-year window (24 reversal configs, PCA grids, 4 ML variants, fit-window grid, allocator taper grid, vol-window perturbations, sleeve compositions, 2 universes, gate thresholds). The flagship is the argmax of that family.
- **How it fakes profitability:** the expected maximum Sharpe over N independent zero-skill trials grows like √(2·ln N)/√T — with N≈50 on T≈5y, max in-sample Sharpe ≈ 1.1-1.3 is achievable with *zero* true alpha. The reported 1.34 sits inside that band.
- **Required fix:** Deflated Sharpe Ratio (Bailey & López de Prado) computed against the realized trial count and the variance of trial Sharpes; experiment tracking that *counts trials automatically*; Benjamini-Hochberg FDR for sweep families; optionally White's reality-check bootstrap for the flagship vs. its rejected siblings.
- **Proving test:** unit test: DSR of a Sharpe-1.34 strategy after 50 trials on 5y of data is materially below 1.34 and below the acceptance threshold when trials are inflated; regression test: a sweep of 50 random-signal configs through the pipeline yields a best raw Sharpe > 0.8 whose deflated Sharpe/PBO correctly flags it as unacceptable.

## W-03 — Basket engine fills at the signal close (same-bar execution)

- **Severity:** CRITICAL (for daily equity results; the entire flagship rests on this engine)
- **Module:** `app/backtesting/basket_engine.py:104-123`
- **Why it matters:** weights computed from a window ending at close[t] earn the close[t]→close[t+1] return — an implicit fill at the exact price the signal observed. Real EOD systems compute signals at/after the close and execute at the next open (or next close), one bar later. The pairs engine got this right; the basket engine did not inherit it.
- **How it fakes profitability:** any signal with short-horizon autocorrelation (reversal, fast ML horizons, vol-scaled momentum at rebalance) harvests the overnight piece of its own trigger. For 12-1 momentum the bias is small; for the 5-day ML sleeve and for vol-targeting rescales it is not obviously small — and nobody has measured it, because there is no delay knob for baskets.
- **Required fix:** execution-timing option on `BasketConfig` (`fill: next_open | next_close | same_close`) defaulting to delayed execution for research reports; add delay scenarios to the basket stress suite; re-state flagship numbers under next-open fills.
- **Proving test:** unit test with a constructed series where same-close vs next-open fills differ by a known amount; regression test asserting the flagship research config runs with delayed fills by default and that `same_close` results carry a warning string in the report.

## W-04 — Survivorship-biased universes

- **Severity:** HIGH
- **Module:** `app/data/universe.py` (hardcoded 2026 constituent lists), all equity results
- **Why it matters:** `us_stocks_50/100` are today's mega-caps backtested from 2021. Names that shrank, delisted, or fell out of the large-cap set are absent. Momentum strategies on survivor universes are the canonical worst case (winners that kept winning are over-represented).
- **How it fakes profitability:** the long book holds tomorrow's known survivors; the short book shorts large-caps that — by construction of the universe — never collapsed. Both legs are biased toward the strategy. Literature estimates for momentum on survivor-only large-cap sets range ~1-4pp/yr of phantom return; on this exact universe it is unmeasured.
- **Required fix:** (a) point-in-time universe support (membership intervals per symbol) with results stamped `survivorship: point_in_time | biased`; (b) where a true PIT source is unavailable, build a best-effort historical large-cap list (e.g., 2021 S&P 100 constituents as the trading universe for 2021-2023) and quantify the delta; (c) every report and dashboard view must display the survivorship status; (d) registry blocks promotion past `paper` for biased-universe results.
- **Proving test:** data-audit CLI flags `us_stocks_50` as survivorship-biased; backtest report contains the flag; a fixture PIT universe with one delisting shows the delisted name held to its last bar and excluded afterward; governance gate test rejects promotion of a biased-universe alpha.

## W-05 — Dividends absent from equity prices; corporate-action module dead code

- **Severity:** HIGH
- **Module:** `app/data/providers_yahoo.py` (reads `quote`, ignores `adjclose`), `app/data/corporate_actions.py` (never imported by the pipeline), README feature matrix (overclaims)
- **Why it matters:** verified empirically against stored bars: prices are split-adjusted (Yahoo does that server-side) but not dividend-adjusted. Every ex-div date injects a phantom negative return proportional to yield (≈2.5-4%/yr for KO/XOM/VZ/MO-type names).
- **How it fakes profitability:** cross-sectional ranks systematically tilt long low-yield growth / short high-yield value — exactly the tilt that performed well 2021-2026, so part of the momentum sleeve's edge may be an accounting artifact; the short book is also silently *credited* dividends it would owe in live trading (shorts pay dividends), flattering the short leg twice.
- **Required fix:** fetch and store `adjclose` (or div events) alongside raw OHLC; build research matrices on total-return prices; keep raw prices for execution-level simulation; correct the README; add dividend liability to short-leg cost modeling (see W-07).
- **Proving test:** data-audit detects un-adjusted series by scanning for systematic ex-div-date return gaps vs adjclose; unit test: a synthetic series with one dividend produces identical research returns whether the dividend is paid or price-adjusted; KO total-return CAGR in storage matches Yahoo adjclose CAGR within tolerance.

## W-06 — Hyperparameters and risk-control settings tuned on the reporting window

- **Severity:** HIGH
- **Module:** `app/config/strategy_defaults.yaml` (daily profile), `app/strategies/ml_alpha.py`, `app/strategies/ensemble.py`
- **Why it matters:** documented decisions — `hold_frac=0.35`, `forward_bars=5`, `min_sleeve_t: 0.0` (chosen *because* −0.5 lost money on us_stocks_100), `vol_window=60`, `momentum_neutral: true`, dropping pca — were each made by comparing full-window results. Tuning a *risk control* (the gate) in-sample is especially insidious because it looks like prudence.
- **How it fakes profitability:** each tuned knob transfers a little of the window's noise into "edge"; jointly they compound with W-01/W-02. The perturbation checks that exist (vol_window 40/80, seeds) are a good instinct but were also evaluated on the same window.
- **Required fix:** config-freeze discipline via the experiment tracker (a config hash is frozen before OOS data is opened); parameter-stability analysis (perturb each knob ±50% and report the OOS Sharpe surface, not the IS one); the acceptance criteria require flat-ish parameter neighborhoods.
- **Proving test:** experiment tracker refuses to mark a run "OOS" if its config hash was first seen after the OOS window's data hash; research report includes a parameter-sensitivity table generated programmatically.

## W-07 — Frictionless shorts and leverage

- **Severity:** HIGH
- **Module:** `app/backtesting/basket_engine.py` (no financing of any kind), `app/strategies/ensemble.py` (`leverage` multiplies the book; comment admits costs unmodeled), `docs/strategy_research.md` §8
- **Why it matters:** the flagship is ~half short book and is advertised at 3x leverage (24% CAGR). Missing: stock borrow fees (10-300+ bps, occasionally thousands for hard-to-borrow momentum losers — i.e., precisely the short book), short dividend liability, margin interest on the levered portion (~6-8%/yr retail in 2026), cash drag/rebates, crypto funding for any synthetic short.
- **How it fakes profitability:** at 3x, margin interest alone is roughly −12 to −16pp of the +24% CAGR; borrow plus short dividends plausibly take several more points from the 1x number. The leverage table is the least honest artifact in an otherwise honest repo.
- **Required fix:** financing model in the basket engine: per-asset borrow-rate input (default conservative tiers when no data), margin interest on gross > equity, short dividend charge (needs W-05's dividend data), funding for crypto; re-publish the leverage table net.
- **Proving test:** unit tests for each financing term against hand-computed examples; regression test: flagship at 3x with default financing shows CAGR reduced by ≥ margin-rate × 2 vs the frictionless number; report must refuse to print leveraged results without a financing model attached.

## W-08 — ML methodology: overlapping labels, no purged CV, no importance/calibration

- **Severity:** MEDIUM-HIGH
- **Module:** `app/research/ml_features.py`, `app/strategies/ml_alpha.py`
- **Why it matters:** 5-day forward labels sampled daily are ~80% overlapping; in-window fit quality is therefore overstated and `retrain_every`/`max_iter` choices rest on unreliable internal signal. There is no purged & embargoed CV, no feature importance tracking, no calibration, no decay monitoring.
- **How it fakes profitability:** overlap doesn't leak future data here (targets complete in-window), but it *does* make every in-window model-selection decision noisier than it looks — combined with W-06 it means the ML sleeve's configuration is fit to autocorrelated noise. A leakage *regression-trap* is also absent: nothing would catch a future refactor that accidentally shifts a feature.
- **Required fix:** purged k-fold CV with embargo (`app/research/purged_cv.py`) used for all ML hyperparameter decisions; sample-weight or non-overlapping label option; permutation importance logged per retrain; an automated leakage detector (shift-features-forward test: a model trained on deliberately future-shifted features must show its advantage, proving the detector works).
- **Proving test:** purged-CV unit tests (no train/test index overlap within embargo, naive-CV-vs-purged gap reported); leakage trap test: injecting `close.shift(-1)` as a feature must be flagged by the detector and must blow up naive CV vs purged CV scores.

## W-09 — Flat-bps cost model; impact model exists but is dead code; no capacity analysis

- **Severity:** MEDIUM-HIGH
- **Module:** `app/backtesting/basket_engine.py` (`cost_bps`), `app/backtesting/slippage.py` (`VolumeAwareSlippage` unused), no capacity module
- **Why it matters:** 5 bps flat on equities / 15 bps on crypto regardless of name, time, size, or volatility. The ML and ensemble sleeves trade the cross-section's tails, where spreads are widest. No turnover-vs-ADV participation is ever computed, so capacity is unknown (and unverifiable claims like "~24% CAGR at 3x" have no stated capital range).
- **How it fakes profitability:** under-costing the exact names a strategy concentrates in (high-vol momentum tails) is a classic source of paper edge; and a strategy that only works at $10k is not the same product at $1M.
- **Required fix:** per-asset cost inputs (spread estimates from daily high-low or stored book data; impact via square-root participation using stored volume — the `VolumeAwareSlippage` class is a starting point); capacity curve report (Sharpe vs capital grid); cost-sensitivity CLI.
- **Proving test:** unit test that per-asset costs route through the basket engine; capacity report on the flagship produces monotonically declining net Sharpe across the capital grid; regression test pins the flagship's net return at 2x costs (must stay positive per acceptance criteria, or the strategy is flagged).

## W-10 — Data pipeline silently degrades: stale ffill, intersection alignment, warn-only outliers, failed-QC storage

- **Severity:** MEDIUM
- **Module:** `app/data/market_data.py` (`max_ffill=3`, `dropna(how="any")`), `app/data/historical_loader.py:74` (stores failed-QC data), `app/data/data_quality.py` (outliers warn only)
- **Why it matters:** 3-day-stale prices can enter momentum/vol signals unmarked; aligning on the intersection truncates the whole matrix to the youngest symbol (on crypto this quietly deletes history; on equities it can silently shrink the research window); bars failing QC are stored with only a log line; outlier returns (bad ticks, missed splits) never quarantine a symbol.
- **How it fakes profitability:** stale prices manufacture phantom mean-reversion and understate vol (inflating vol-targeted sizing); truncated history changes results silently between downloads; bad ticks create fake reversal trades.
- **Required fix:** staleness flags surfaced into research (mask, don't ffill, beyond 1 bar for daily data); per-dataset persisted DataQualityReport with an explicit acceptable-for-research verdict; alignment report (per-symbol coverage before/after); quarantine list honored by `build_price_matrix`.
- **Proving test:** matrix built from fixtures with a 5-bar gap leaves NaN (not ffill) beyond the limit and reports the mask; loader refuses (or stores-with-quarantine-flag) bars whose QC failed, and `build_price_matrix` excludes quarantined symbols unless `--include-quarantined`.

## W-11 — Allocator is statistically primitive and its evidence base is one window

- **Severity:** MEDIUM
- **Module:** `app/strategies/ensemble.py`
- **Why it matters:** "risk parity" is actually inverse-vol on ≤60 noisy observations with a binary t-stat gate; sleeve correlations are never used; there is no turnover-aware allocation, no drawdown de-allocation, no covariance shrinkage. The documented allocator failure (inverse-vol starving the Sharpe-1.11 sleeve, §7b) was patched by neutralizing the *sleeve* rather than fixing the *allocator*.
- **How it fakes profitability:** allocator pathologies cut both ways — here the binary gate's funded-spell bleed was measured (≈8pp from dead pca) only because someone looked. Un-measured: gate whipsaw cost across sleeves, vol-window luck (1.14-1.43 Sharpe range across 40/80 *is* a wide range), correlation regime shifts between sleeves.
- **Required fix:** ERC/HRP with Ledoit-Wolf shrinkage as candidate modes, allocation backtest comparing modes OOS, turnover-penalized re-allocation, drawdown-based de-risking; the new allocator must beat or match inverse-vol OOS net of turnover or it does not ship as default (per acceptance criteria).
- **Proving test:** allocator comparison harness with synthetic sleeves of known vol/correlation recovers ERC weights analytically; OOS comparison report generated by CLI; default-mode change requires a recorded comparison artifact.

## W-12 — Research effort is concentrated on books no connected venue can hold

- **Severity:** MEDIUM (research-portfolio level)
- **Module:** strategy roadmap / registry (absent)
- **Why it matters:** the flagship needs equity shorting; T212 Invest/ISA cannot short, Binance spot cannot short, futures are not connected. Meanwhile tradable-today configurations (long-only momentum/TSMOM tilts on T212, spot-only crypto TSMOM, testnet-first futures carry with basis modeling) are secondary in the docs.
- **How it fakes profitability:** it doesn't fake numbers — it fakes *progress*: a beautiful untradeable Sharpe postpones the discovery of what live execution does to the tradable subset.
- **Required fix:** alpha registry must carry `executable_venues` per alpha; governance blocks promotion past paper when empty; a tradable-today research track (long-only variants with honest "NOT market-neutral" risk framing; futures-testnet carry with basis/margin model) gets first-class status.
- **Proving test:** governance gate test: an alpha with no executable venue cannot reach `live_*` states; registry list view shows venue executability for every alpha.

## W-13 — Pairs walk-forward sample too small to support its headline

- **Severity:** LOW-MEDIUM
- **Module:** `app/backtesting/walk_forward.py` usage on stocks (4 OOS windows), README ("OOS Sharpe 0.88")
- **Why it matters:** 4 windows × 126 test days is ~2 years of stitched OOS with heavy small-sample noise; the 0.88 carries no confidence interval.
- **How it fakes profitability:** quoting a point-estimate OOS Sharpe from 4 windows as a "thin but positive" verdict invites overweighting it.
- **Required fix:** report bootstrap CIs on stitched OOS curves; require a minimum OOS bar count in acceptance criteria; extend history (more windows) before re-stating.
- **Proving test:** walk-forward summary includes CI fields; acceptance-criteria checker rejects OOS samples below the minimum.

## W-14 — Crypto research window is one regime (~90 days of 15m)

- **Severity:** LOW-MEDIUM (correctly labeled in docs)
- **Module:** stored data; `docs/strategy_research.md` §4
- **Why it matters:** every 15m crypto conclusion ("TSMOM the only winner", "reversal structurally unviable") is one ~90-day momentum-regime sample. The conclusions may be right; the evidence cannot establish "structural."
- **Required fix:** extend 15m history (Binance provides years), re-run the settled-negative menu across ≥3 regimes before treating any verdict as structural; mark current verdicts "single-regime" in docs.
- **Proving test:** data-coverage CLI shows ≥3 labeled regimes for any "settled" verdict; doc lint (manual) — verdicts cite regime count.

## W-15 — No reproducibility substrate: zero git commits, no experiment IDs, no data snapshots

- **Severity:** HIGH (operational, enables everything else to go unverified)
- **Module:** repository state; `scripts/exp_*.py`
- **Why it matters:** none of the documented experiments can be re-run as-was: no commit hash existed when they ran, configs live in mutable YAML, the database mutates in place with every download (upsert), and experiment scripts print to stdout.
- **How it fakes profitability:** unreproducible results cannot be audited; silent data refreshes change past results; "we saw Sharpe 1.34" becomes folklore.
- **Required fix:** initial git commit immediately; experiment tracker (run ID, git hash, config snapshot, universe snapshot, data content hash, seed, metrics) for every research entry point; immutable result artifacts in `reports/`.
- **Proving test:** any `backtest*`/`research-run` CLI invocation produces an experiment record with non-null git hash and data hash; re-running with identical inputs reproduces metrics bit-for-bit (seeded) and links to the same data hash.

---

## How much of the flagship +48.5% / Sharpe 1.34 is at risk?

A rough, honest decomposition of *potential* (not proven) inflation — each row is the
plausible range the corresponding weakness could remove, on this window:

| weakness | plausible Sharpe haircut |
| --- | --- |
| W-02 selection over ~50 trials | 0.3 – 0.6 |
| W-04 survivorship (momentum on survivors) | 0.1 – 0.3 |
| W-05 dividend blindness (short credit + rank tilt) | 0.05 – 0.2 |
| W-03 same-close fills | 0.0 – 0.2 (unmeasured; measure first) |
| W-07 borrow/short-dividend at 1x | 0.05 – 0.15 |
| **Combined (not additive, but correlated downward)** | **the honest prior for true OOS net Sharpe is ~0.3 – 0.9, not 1.34** |

That range still permits a real, fundable strategy — momentum/TSMOM/ML-residual ensembles
are economically grounded and the engineering discipline here is real. But the burden of
proof now sits on the validation work in Phases 2-5, not on the existing window.
