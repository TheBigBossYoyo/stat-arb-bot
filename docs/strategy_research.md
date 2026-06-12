# Strategy research: what multi-strategy funds run, and what survived here

This document records the research behind the Phase-7 strategy expansion, the
parameter reasoning, and — most importantly — **which strategies survived net
of transaction costs on our data and which did not**. Negative results are
kept on purpose: they are the cheapest thing this framework produces.

> Simulated results only. Nothing here is a promise of profitability.

---

## 1. What hedge funds actually run

Quantitative equity/crypto funds rarely live off a single signal. The common
building blocks, in rough order of capacity:

| family | idea | canonical reference |
| --- | --- | --- |
| Pairs / cointegration stat-arb | long-short a stationary spread between co-moving assets | [Statistical arbitrage overview (Bawa)](https://navnoorbawa.substack.com/p/statistical-arbitrage-the-quant-strategy) |
| PCA residual stat-arb | strip market/sector factors with PCA, mean-revert the residual | [Avellaneda & Lee 2010, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1153505) |
| Time-series momentum (TSMOM) | each asset's own 12-month return predicts its next month | [Moskowitz, Ooi & Pedersen — Quantpedia summary](https://quantpedia.com/strategies/time-series-momentum-effect) |
| Cross-sectional momentum (XSMOM) | long recent winners, short recent losers (12-1) | Jegadeesh & Titman 1993 |
| Short-term reversal | long last week's losers, short winners | Lehmann 1990 |
| Funding-rate / basis carry | collect perp funding while delta-hedged | [Funding-rate arbitrage explainer](https://www.coinglass.com/learn/what-is-funding-rate-arbitrage) |
| Multi-strategy combination | risk-parity blend of lowly-correlated sleeves | [Crypto hedge fund industry guide 2025](https://www.cryptoinsightsgroup.com/resources/industry-guide-to-crypto-hedge-funds-2025-edition) |

What the combination buys: mean-reversion sleeves bleed in trends exactly when
momentum sleeves print. The blend has a smoother equity curve than any
component — that is the product multi-strat funds sell.

## 2. What is implemented

* **Pairs**: rolling z-score, cointegration (monthly refit, probation on
  failed refits), Kalman-filter hedge ratio. Half-life-adaptive time stops,
  trend-regime filter, innovation drift gate, pre-trade cost-edge gate
  (expected reversion capture must exceed `min_edge_ratio ×` round-trip cost).
* **PCA residual stat-arb** (`pca_stat_arb`): Avellaneda-Lee OU scoring —
  each cumulative residual is fitted as an Ornstein-Uhlenbeck process,
  standardized against its equilibrium distribution, and *excluded* unless it
  mean-reverts fast enough (`max_residual_half_life`). Entry/exit hysteresis
  (`s_entry`/`s_exit`) holds positions across rebalances instead of
  re-ranking the book every time (the naive version's turnover bill was fatal).
* **Sector-relative stat-arb** (`sector_stat_arb`): same OU scoring and
  hysteresis, but residuals come from a leave-one-out sector-mean regression
  per stock (Avellaneda-Lee's ETF-factor design) using the sector map in
  `app/data/universe.py`. US stock universes only. Tested negative on daily
  mega-caps (section 5) — kept as a research capability.
* **TSMOM** (`tsmom`): sign of the skip-adjusted lookback return per asset,
  inverse-vol sized, gross-normalized, per-asset weight cap.
* **XSMOM** (`xsec_momentum`): classic 12-1 — rank skip-adjusted lookback
  returns, long the top k, short the bottom k.
* **Short-term reversal** (`xsec_reversion`): long recent losers / short
  recent winners over a days-scale lookback.
* **Risk-parity ensemble** (`backtest-ensemble`): combines sleeves with
  inverse-vol allocations estimated on each sleeve's own realized returns,
  **net of that sleeve's turnover costs**, with a trailing-performance t-stat
  gate that cuts a sleeve's allocation to zero while it bleeds. Tracking
  sleeve returns gross of costs is a trap we hit: a high-churn sleeve looked
  profitable while its costs were quietly paid by the portfolio.

* **Funding-rate carry** (`carry-backtest`): delta-neutral long-spot /
  short-perp positions collecting the 8h funding rate, with entry/exit
  hysteresis on annualized trailing carry. Research-only — funding data comes
  from the public Binance futures REST API, but no futures account is
  connected and basis risk is not modeled.
* **ML alpha** (`ml_alpha`): gradient-boosted cross-sectional return
  forecaster on ranked tabular features, walk-forward retrained, with
  hold-band execution and self-throttling to its forecast horizon
  (section 7).

## 3. Cost model

| market | per-leg cost | basket `cost_bps` |
| --- | --- | --- |
| Binance crypto spot, 15m bars | 10 bps commission + 5 bps slippage | 15 |
| Liquid US large caps, daily bars | 2 bps commission + 3 bps slippage | 5 |

All parameters live in `app/config/strategy_defaults.yaml`. The base sections
are tuned in 15m bars; the `daily:` profile overrides them for `--interval 1d`
(daily lookbacks, exchange-calendar annualization of 252, equity costs).

## 4. Results — crypto (10 names, 15m bars, ~90 days)

| strategy | net return | verdict |
| --- | --- | --- |
| cointegration pairs (fixed sizing + gates) | small positive, low utilization | keep, niche sleeve |
| kalman pairs (delta 1e-7 + drift gate) | −2.3% (was −10.4%) | contained; walk-forward should reject configs like this |
| pca_stat_arb (Avellaneda-Lee) | −15.9% (was −46.7% naive) | **not viable at this breadth** |
| xsec_reversion | all 24 sweep configs lose; best zero-cost ≈ +5% | **structurally unviable at 15 bps** |
| xsec_momentum (2-week) | −3.4% | needs breadth |
| tsmom (1-week) | **+7.1%** | the one standalone winner on this window |
| ensemble (pca + reversal + tsmom) | +1.7%, gate zeroes the reversal sleeve | works as designed |

Two structural lessons, not parameter problems:

1. **Breadth.** Cross-sectional strategies on 10 names are starved — the
   Avellaneda-Lee strategy was built for hundreds of equities.
2. **Costs.** 15 bps per unit turnover kills any signal that needs daily-or-
   faster churn on this universe. The pre-trade edge gate and entry/exit
   hysteresis exist because of this.

## 5. Results — US stocks (50 names, daily bars, 5 years, 5 bps)

The same code, given the breadth it was designed for:

| strategy | net return (3.8y traded) | Sharpe | max DD |
| --- | --- | --- | --- |
| pca_stat_arb | +7.7% | 0.27 | −13.6% |
| tsmom (12-month) | +28.8% | 0.88 | −12.7% |
| xsec_momentum (12-1) | +92.9% | 1.11 | −24.4% |
| **ensemble (pca + xsmom + tsmom)** | **+36.3%** | **1.05** | **−7.4%** |
| pairs walk-forward (4 windows OOS) | +1.2% | 0.88 OOS | thin but positive |

The ensemble line is the point of the whole exercise: a Sharpe near its best
sleeve with a third of the momentum sleeve's drawdown, and its
trailing-performance gate ends the period allocating tsmom 0.73 / xsmom 0.27 /
pca 0.0. (With the original looser gate it returned +41.1% / Sharpe 1.24 on
this window — the stricter gate gives up some benign-case upside to cap the
failure mode found at 100 names, below.)

**Update:** the flagship is now **xsec_momentum + tsmom + momentum-neutral
ml_alpha** — +48.5%, Sharpe 1.34, max DD −7.1% on the same window
(sections 7c/7d; pca is dropped — it bleeds in the spells the gate funds it).

Caveats, honestly: single 5-year window; survivorship bias (today's 50 large
caps were not 2021's 50); momentum had a famously good run in this period;
daily bars assume next-day-open fills at 5 bps. Treat these as *viability*
numbers, not expected returns.

### Breadth is not free: the 100-name experiment

Widening to `us_stocks_100` did **not** improve anything:

* **12-1 momentum diluted**: Sharpe 1.11 (50 names) → 0.81 at the decile spec
  (the added defensive names — utilities, telecoms, staples — carry weaker
  momentum). `xsmom_top_frac` now sizes books as a fraction of the universe so
  the spec scales, but more breadth was not more alpha on this window.
* **PCA residual reversion failed outright**: −20% to −29% across every
  combination of book size (8/16/32 per side) and factor-selection rule
  (fixed 5 components vs Avellaneda-Lee's 55% explained-variance threshold,
  now implemented as `var_threshold`). Daily-frequency residual reversion on
  US large caps in 2021-2026 is simply negative — consistent with Avellaneda
  & Lee's own report of sharp decay after 2007.
* **The ensemble gate was the real lesson**: at `min_sleeve_t: -0.5` a
  Sharpe −0.95 sleeve (trailing 60-day t-stat ≈ −0.46) stayed funded and
  dragged the 100-name ensemble to −2.0%. Requiring a non-negative trailing
  t-stat (`min_sleeve_t: 0.0`, i.e. strategy-level momentum) turned the same
  ensemble to +14.8% with pca correctly cut to zero.

### Sector-relative residuals do not revive daily reversion

The natural rescue attempt for the failed PCA sleeve — Avellaneda & Lee's
own original design, regressing each stock on its sector factor instead of
abstract PCA components — was built (`sector_stat_arb`: leave-one-out
sector-mean factors, GICS-ish map in `app/data/universe.py`, same OU
scoring and hysteresis) and tested (`scripts/exp_sector_stat_arb.py`):

| variant (us_stocks_50, 1d, 5 bps) | net return | Sharpe |
| --- | --- | --- |
| flat pca (current defaults, current window) | −6.8% | −0.18 |
| sector-relative, defaults | −13.8% | −0.41 |
| sector-relative, hl=10 / s_entry=1.5 / top_k=5 | −24.7% / −13.8% / −20.7% | all < 0 |

Its returns are perfectly orthogonal to momentum (corr +0.00) — but
orthogonal and *losing* diversifies nothing: swapping it into the flagship
dropped the Sharpe to 1.13 and adding it as a fifth sleeve gave 1.17 (vs
1.32), because the sleeve gets funded in spells whenever its trailing
t-stat pokes above zero, and bleeds them. **Settled negative**: daily
residual reversion on US mega-caps 2021-2026 is dead in sector-relative
form too, consistent with the post-2007 decay Avellaneda-Lee themselves
report. The code stays as a research capability (it may behave differently
on small caps, other markets, or intraday bars).

## 6. Results — funding-rate carry (10 perps, 8h periods, 2 years)

Trailing funding averaged 5-6%/yr on BTC/LINK/LTC perps — the carry is real.
The implementation lesson dwarfed the signal:

| version | net return (2y) | turnover | fees on $10k |
| --- | --- | --- | --- |
| naive top-k re-rank every 8h | **−46.5%** | 247 | $5,653 |
| entry/exit hysteresis (enter > 5% APR, exit < 0%) | **+7.0%** | 13 | $422 |

Same signal, same costs (30 bps both legs) — only the trading discipline
changed. The +7.0% (≈3.5%/yr, max DD −1.0%) models the **funding leg only**:
basis convergence risk, margin interest and liquidation risk on the short perp
leg are NOT included, so the printed Sharpe (≈6) is meaningless; the *return
level* is the honest takeaway. Run it with `statarb carry-backtest`.
Live execution would require a futures account (not connected) and is out of
scope until then.

## 7. Machine-learning alpha (`ml_alpha`)

Implemented the way systematic equity funds actually use ML (Gu, Kelly & Xiu,
"Empirical Asset Pricing via Machine Learning", 2020): **gradient-boosted
trees on cross-sectionally ranked tabular features** — multi-horizon returns,
vols, price-vs-MA z-score, drawdown — predicting forward *relative* returns,
retrained walk-forward inside the backtest window. Deep nets were considered
and deliberately rejected: ~1,255 daily bars per asset is orders of magnitude
short of what they need, and an overfit net is indistinguishable from alpha
in-sample.

The model had signal from the first run; the implementation lessons were —
again — about turnover:

| version (us_stocks_50, daily, 5 bps) | net return | turnover |
| --- | --- | --- |
| re-rank quintiles every day, 5-day forecasts | −24.6% | 660 |
| trade at the forecast horizon | +15.3% | 196 |
| + hold-band hysteresis (enter quintile, hold to 35%) | **+28.5% (Sharpe 0.84)** | 129 |

The sleeve self-throttles by bars elapsed, so a daily-cadence caller (the
ensemble) cannot make it churn. Breadth findings repeat the pattern: +5.8% at
100 names (diluted), −12.3% on 10 crypto names at 15 bps.

**It does not earn an ensemble slot yet**: its forecasts lean on the same
momentum features `xsec_momentum` trades, so adding it diluted the blend
(Sharpe 1.05 → 0.95) and substituting it for momentum was worse still
(Sharpe 0.40). A learned signal must be *uncorrelated*, not merely positive,
to improve a multi-strat book. Next iteration: feed it features the momentum
sleeve cannot see (volume, vol-surface, cross-asset signals).

### 7b. The orthogonalization experiment (`scripts/exp_ml_orthogonal.py`)

The "next iteration" above was built and tested: aux OHLCV data now flows
through the basket engine (`wants_aux` weight functions), and `ml_alpha`
gained two independently-switchable mechanisms — `orthogonal_features`
(market beta/idio-vol, abnormal volume, volume trend, Amihud illiquidity,
overnight/intraday split, Parkinson range vol) and `momentum_neutral`
(training target and live scores residualized per date against the two
longest-horizon return ranks). Results, us_stocks_50 daily, 5 bps:

| ml_alpha variant | net return | Sharpe | corr w/ xsmom sleeve |
| --- | --- | --- | --- |
| A legacy features (baseline reproduced) | +28.5% | 0.84 | +0.19 |
| B + orthogonal features | +0.2% | 0.05 | +0.12 |
| C + momentum neutralization only | +26.7% | **0.89** | +0.20 |
| D both | +7.8% | 0.30 | +0.15 |

Two findings, one negative and one diagnostic:

1. **The orthogonal features destroyed the signal** (0.84 → 0.05). A
   50-name × ~170-date training panel supports ~9 ranked features; nearly
   doubling the feature count buried the real predictors in noise the trees
   happily overfit. The capacity reading was then tested directly
   (`scripts/exp_ml_fitwindow.py`): at fit_window 600 — double the panel —
   the gap narrows but never closes (legacy 0.52 vs orthogonal 0.33 on the
   same ~2.6y traded span), and the data to double again does not exist.
   **Settled negative for this universe at any feasible window.**
   `orthogonal_features` stays available but OFF. (Same test shows window
   300 beats 600 for the legacy sleeve — recency beats sample size here.)
2. **The premise was wrong: correlation was never the problem.** The
   realized daily correlation between the ml sleeve and xsec_momentum is
   only ~0.19 (the rank-feature overlap does not translate into realized
   return correlation at the book level). The documented dilution
   (1.05 → 0.95, reproduced exactly) comes from the ALLOCATOR: inverse-vol
   hands the low-vol ml sleeve a large capital share the moment its
   trailing t-stat clears the binary gate, starving the Sharpe-1.11
   momentum sleeve. Momentum neutralization (variant C) is kept as a small
   free improvement (Sharpe 0.89 standalone), but the ensemble fix is an
   allocator change, not a feature change — see section 7c.

### 7c. The allocator experiment (`scripts/exp_allocator_taper.py`)

Hypothesis: replace the binary t-stat gate with a continuous taper
(share ∝ inv_vol × clip(t/t_scale, 0, 1), `t_stat_scale` in
`EnsembleConfig`) so a sleeve is funded in proportion to the evidence of
its edge. Result: **rejected** — the taper is monotonically harmful on
this window (3-sleeve: Sharpe 1.05 → 0.94-0.95; 4-sleeve: 1.32 → 1.06-1.17
as the scale rises). Trailing t-stats are too noisy to size positions
continuously; as a binary regime detector they work. The option stays
available but OFF (0.0).

The control row of that sweep was the real discovery: **the 4-sleeve
ensemble with the momentum-neutral ml sleeve under the unchanged binary
gate beats the 3-sleeve baseline on every metric**:

| book (us_stocks_50, 1d, 5 bps) | net return | Sharpe | max DD |
| --- | --- | --- | --- |
| 3-sleeve (pca + xsmom + tsmom) | +36.3% | 1.05 | −7.4% |
| 4-sleeve + ml_alpha (legacy, no neutral) | +28.4% | 0.95 | −9.6% |
| **4-sleeve + ml_alpha (momentum_neutral)** | **+40.7%** | **1.32** | **−7.3%** |

Momentum neutralization barely moved the sleeve's standalone Sharpe
(0.84 → 0.89) but flipped its ensemble contribution from dilutive to
accretive — exactly what training on the momentum-orthogonal residual is
for: the sleeve now prints at different times than the momentum sleeves,
so risk parity has something to diversify with. Ending allocations:
tsmom 0.51 / ml 0.35 / xsmom 0.14 / pca 0.

Robustness (`scripts/exp_4sleeve_robustness.py`): identical results across
tree seeds 1/7/42 (the booster is deterministic at this panel size — no
early-stopping subsampling kicks in), and the advantage survives allocator
vol_window perturbation: Sharpe 1.13 / 1.32 / 1.38 at windows 40 / 60 / 80,
all above the 3-sleeve's 1.05.
The usual caveats stand: one historical window, survivorship-biased
universe, margin costs unmodeled at leverage.

### 7d. Dropping the dead sleeve (`scripts/exp_drop_pca.py`)

With ml_alpha in the book, pca_stat_arb earns nothing: it is negative
standalone on the current window (−6.8%), ends every test at zero
allocation — and an unfunded sleeve is *not* free, because the gate funds
it whenever its noisy trailing t-stat pokes above zero, and those spells
bleed. Removing it raised the blend on every metric and at every allocator
window tested:

| book (us_stocks_50, 1d, 5 bps) | net return | Sharpe | max DD |
| --- | --- | --- | --- |
| 4-sleeve (pca + xsmom + tsmom + ml) | +40.7% | 1.32 | −7.3% |
| **3-sleeve flagship (xsmom + tsmom + ml)** | **+48.5%** | **1.34** | **−7.1%** |

(vol_window 40/80: Sharpe 1.14/1.43 vs the 4-sleeve's 1.13/1.38.)
**`xsec_momentum + tsmom + ml_alpha` is the default daily ensemble.** The
mean-reversion sleeves stay implemented; if residual reversion comes back
to life in some future regime, re-adding one is a single `--sleeves` flag.

## 8. Leverage: how a Sharpe-1 book becomes a hedge-fund return

The ensemble is market-neutral-ish with realized vol ~8%/yr — comparing its
raw return to the S&P 500 confuses risk levels. Funds run exactly such books
at 2-6x. `backtest-ensemble --leverage N` (research only: margin/borrow costs
not modeled, turnover costs do scale):

3-sleeve book (historical):

| leverage | CAGR | ann vol | Sharpe | max DD |
| --- | --- | --- | --- | --- |
| 1x | 9.0% | 8.1% | 1.05 | −7.4% |
| 2x | 12.9% | 12.9% | 1.01 | −11.3% |
| 3x | 15.8% | 16.0% | 1.00 | −13.5% |

**Flagship (xsmom + tsmom + ml_alpha, sections 7c/7d):**

| leverage | CAGR | ann vol | Sharpe | max DD |
| --- | --- | --- | --- | --- |
| 1x | 11.0% | 8.0% | 1.34 | −7.1% |
| 2x | 19.2% | 12.8% | 1.44 | −10.0% |
| 3x | 24.1% | 15.8% | 1.45 | −11.9% |

At 3x the flagship prints a 24% CAGR below S&P-level volatility with a
−12% worst drawdown (margin/borrow costs still unmodeled). The product is
the *Sharpe*; leverage converts it into return.

## 9. Future work

* Supervised paper period for the flagship via `paper-trade-basket`
  (daily EOD refresh, risk-gated rebalancing, simulated shorts) — the
  research→execution gap is closed; what is needed now is calendar time.
* Execute funding carry against a real futures venue (basis modeling first).
* Re-test `orthogonal_features` where the panel can support them: longer
  history or a universe wide enough that ~16 ranked features are not
  over-parameterized (the 50-name × 170-date panel was not — section 7b).
* ~~Sector-relative PCA residuals~~ — tested, settled negative (section 5).
* Borrow-cost modeling for equity shorts (T212 Invest/ISA cannot short — the
  market-neutral stock results are research-only until a shorting venue is
  connected).

## 10. Engineering rules distilled from this research

1. **Charge every sleeve its own costs** — any allocator fed gross-of-cost
   returns will fund churners.
2. **Hysteresis beats re-ranking** everywhere a book is held: PCA stat-arb
   (−46.7% → −15.9% on crypto), funding carry (−46.5% → +7.0%).
3. **Gate on trailing performance, not just vol** — inverse-vol alone funds
   low-vol losers; require a non-negative trailing t-stat.
4. **Vol targeting is a stocks tool here**: at 5 bps it is cheap insurance;
   at crypto's 15 bps the rescaling churn cost more than it saved
   (+1.7% → −3.0%), so it is off for crypto.
5. **Trade at the forecast horizon** — predicting 5-day returns and
   re-trading daily turned a +28.5% ML strategy into a −24.6% one.
6. **A new sleeve must be uncorrelated, not merely profitable** — ml_alpha's
   standalone Sharpe 0.84 still *lowered* the ensemble because it rides the
   same momentum factor as an existing sleeve.
7. **Judge a sleeve by its marginal contribution, not its standalone Sharpe
   or even its return correlation** — momentum neutralization moved the
   sleeve's Sharpe 0.84 → 0.89 and its xsmom correlation not at all
   (~0.19 → 0.20), yet flipped the blend from 0.95 to 1.32. The only test
   that matters is in-ensemble, with the allocator live.
8. **Count features against panel size** — adding 7 orthogonal features to
   a 50-name × 170-date training panel buried a Sharpe-0.84 signal
   (→ 0.05). Feature ideas are cheap; degrees of freedom are not.
9. **Trailing t-stats are regime detectors, not position sizers** — the
   binary performance gate works; sizing continuously on the same t-stat
   (`t_stat_scale`) was monotonically worse at every scale tried.
10. **A gated sleeve is not a free option** — the gate funds a sleeve
    whenever its noisy trailing t-stat crosses zero; if the sleeve has no
    edge, those funded spells are pure bleed (keeping dead pca in the daily
    ensemble cost ~8pp of return). Remove sleeves that never earn; re-adding
    one later is a flag.
