# Data quality: what the data is, what is wrong with it, and how to check

The audit (AUDIT_REPORT.md §4, RESEARCH_WEAKNESSES.md W-04/W-05/W-10) found the
data layer to be the second-largest source of potential fake profitability
after validation methodology. This document is the honest state of the data,
kept current as fixes land.

## Datasets

| dataset | source | span | granularity | known biases |
| --- | --- | --- | --- | --- |
| US equities (us_stocks_50/100) | Yahoo chart API | ~5y rolling | 1d | survivorship (static 2026 universe), pre-fix rows lack dividend adjustment |
| Crypto spot (crypto_top_10) | Binance public REST | ~90d (extendable to years) | 15m | survivor-selected list; single regime at current depth |
| Crypto funding | Binance futures REST | ~2y | 8h | none known; funding leg only |
| FX (fx_majors) | Yahoo | research only | 1d | volume is meaningless |
| Synthetic | generated | any | any | none — known-truth fixtures |

## Adjustment status (audit W-05 — FIXED in code, data needs refresh)

- Yahoo's `quote` arrays are **split-adjusted but not dividend-adjusted**.
  Stored `close` is therefore a price series, not a total-return series.
- Since the fix, the loader also stores `adj_close` (Yahoo's `adjclose`:
  split + dividend adjusted). Re-running `download-data` backfills it into
  existing rows (raw OHLCV is never restated by a re-download; `adj_close`
  is, because back-adjustment cascades with every new dividend).
- Research entry points (`backtest`, `backtest-basket`, `backtest-ensemble`,
  `walk-forward`) now default to **total-return prices** for daily equity
  universes (`--adjusted/--raw` to override) and print the adjustment status.
- Why it matters: raw prices understate high-yield names by their yield
  (KO/XOM/VZ ≈ 2.5-4%/yr), tilt 12-1 momentum ranks long low-yield growth,
  and silently credit the short book with dividends it would owe in reality.

## Survivorship status (audit W-04 — OPEN)

Every current universe is `static_survivor`: the symbol lists were written in
2026 and backtested into 2021. There is no point-in-time membership and no
delisting handling. Consequences:

- equity momentum results are upper bounds (the canonical worst case for this bias);
- `statarb data-audit` stamps every universe with its survivorship status, and
  the verdict can never be better than `research_only` for these universes;
- the alpha registry blocks promotion past paper for strategies whose only
  evidence is survivor-universe backtests (governance gates, Phase 7).

Planned mitigation: point-in-time membership intervals (best-effort historical
constituent lists), delisted-name inclusion where data permits, and a measured
bias delta for the flagship.

## Pipeline behavior you must know (audit W-10 — partially OPEN)

- `build_price_matrix` forward-fills gaps up to 3 bars (3 *days* on daily
  data) and then **aligns all symbols on the intersection of timestamps** —
  the youngest symbol truncates everyone's history. `data-audit` reports the
  alignment loss per universe.
- Bars that fail download-time quality checks are **stored anyway** with a
  warning (`historical_loader.py`). Outlier returns warn but never quarantine.
  Use `data-audit` before trusting any universe.
- Daily bars are normalized to dates (tz-naive UTC); the 1d "missing bars"
  expectation uses a weekday calendar, so ~9 US holidays/yr appear as
  tolerated gaps.

## Commands

```bash
statarb data-audit --universe us_stocks_50 --interval 1d   # verdict + report file
statarb data-coverage --universe us_stocks_100             # per-symbol spans
statarb download-data --universe us_stocks_100 --interval 1d --days 1825 --source yahoo
```

`data-audit` writes `reports/data_audit_<universe>_<interval>.md` and exits
non-zero on a `not_acceptable` verdict, so it can gate scripted research runs.

## Verdict semantics

- **ok** — clean, point-in-time data: usable as evidence.
- **research_only** — usable for viability work; the named biases (survivorship,
  partial adjustment, soft quality warnings) cap what conclusions are allowed.
- **not_acceptable** — broken data (large gaps, duplicates, near-empty
  symbols): conclusions drawn from it are void.
