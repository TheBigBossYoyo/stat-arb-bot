# Rejected strategies (kept on purpose)

Negative results are the cheapest thing this framework produces and the most
expensive thing to re-discover. Every rejection here is recorded in the alpha
registry (`statarb alpha-registry list --status rejected`) with its evidence,
so nobody re-runs a settled dead end. A rejection is reversible only with
*materially different* conditions (new regime, new universe, new cost
structure) and a recorded reason.

| strategy | why rejected | evidence | re-open condition |
| --- | --- | --- | --- |
| **pca_stat_arb** (Avellaneda-Lee PCA residual reversion) | negative everywhere tested; an unfunded-but-gated sleeve still bled the ensemble ~8pp in spells the gate funded it | crypto −15.9%; us_stocks_100 −20 to −29% across all book sizes/factor rules; us_stocks_50 −6.8% | residual reversion revives in some regime/universe (the authors themselves report post-2007 decay) |
| **sector_stat_arb** (leave-one-out sector-factor residuals) | all variants negative; orthogonal to momentum but *losing*, so it diversifies nothing | −13.8% to −24.7% across hl/s_entry/top_k variants; swapping into the flagship dropped Sharpe to 1.13 | small caps, intraday bars, or another market |
| **xsec_reversion** (short-term cross-sectional reversal) | every swept config negative net of costs at crypto cost levels | all 24 sweep configs lose; best zero-cost ≈ +5% (eaten by 15 bps) | a materially lower cost structure or a liquidity-shock-conditioned variant |
| **ml_alpha orthogonal_features** (volume/overnight/range-vol block) | 7 extra features on a 50×170 panel buried the Sharpe-0.84 signal (→0.05); a model-capacity limit, not a tuning one | fit-window 600 narrows but never closes the gap; data to double again does not exist | a universe wide enough (or history long enough) that ~16 ranked features are not over-parameterized |
| **continuous t-stat sleeve sizing** (`t_stat_scale`) | monotonically worse than the binary gate at every scale; trailing t-stats are too noisy to size continuously | 3-sleeve Sharpe 1.05→0.94; 4-sleeve 1.32→1.06-1.17 | — (kept available, off) |
| **ERC / HRP allocators** (this build) | did not beat inverse-vol on the validation window net of turnover | Sharpe: inverse_vol 1.02, erc 0.986, hrp 0.921 | beat inverse_vol out-of-sample (then they become default per the acceptance criteria) |

## Things that are *contained*, not rejected

These are not dead, but have no positive evidence yet — they sit in `research`,
not `rejected`:

- **kalman_pairs (crypto)** — drift gate contains it to −2.3% on one window; no edge demonstrated.
- **funding_carry** — +7%/2y on the funding leg only; the real trade (with basis, margin, liquidation) has never been backtested, and no futures venue is connected. Promising, unproven.
- **tsmom (crypto 15m)** — +7.1% on a single ~90-day momentum regime; one regime is not evidence of structure.

## The discipline (why these stay written down)

From the engineering rules distilled in `docs/strategy_research.md` and
re-affirmed by the audit:

1. A gated dead sleeve is **not** a free option — it bleeds in funded spells. Remove sleeves that never earn.
2. A new sleeve must be **uncorrelated and positive**, judged *in-ensemble with the allocator live* — standalone Sharpe and even return-correlation mislead.
3. Count features against panel size; degrees of freedom are not free.
4. Trailing t-stats are **regime detectors, not position sizers**.
5. Orthogonal-but-losing diversifies nothing.

Re-deriving any of these costs days of compute and judgment. That is what this
file saves.
