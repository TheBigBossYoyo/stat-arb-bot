# stat-arb-bot

A statistical arbitrage research, backtesting, and paper-trading system for Binance crypto and Trading 212 equities, including a long-only book I can actually run against a demo account.

**Paper trading only. Live trading is off by default and stays off until every safety gate passes. Nothing here is financial advice.**

## Why I built this

I wanted to find out whether cointegration-based pairs trading and cross-sectional equity strategies could produce a real, tradeable edge for a small retail account, and to build the infrastructure around them (data pipeline, backtester, risk controls, execution) that separates "curve that looks good in a notebook" from "system I'd actually trust." Over time the project became as much about honest measurement as about finding an edge. Most of the later work is validation machinery built specifically to catch myself overstating results, because the first version of this backtest did exactly that.

## What it does

- Downloads market data: Binance public REST for crypto, Yahoo/stooq for equities, or a fully offline synthetic universe with known cointegrated pairs for testing without any network access.
- Finds cointegrated pairs (Engle-Granger plus ADF plus half-life) and trades the spread with z-score entries and exits, an optional Kalman-filter hedge ratio, and a regime filter that skips mean-reversion entries during strong trends.
- Runs cross-sectional basket strategies too: 12-1 cross-sectional momentum, time-series momentum, a gradient-boosted ML alpha sleeve, and PCA/sector residual reversion, combined into a risk-parity ensemble.
- Backtests everything event-driven with realistic costs (commission, slippage, borrow and margin financing, next-bar execution), then walk-forward validates and stress-tests whatever survives.
- Paper-trades with live market data and simulated fills; for the long-only Trading 212 book it can also preview and place DEMO orders through the official API, gated by a risk manager, a kill switch, and an audited action layer.
- Ships a React and FastAPI control panel so the whole workflow can be run without a terminal, read-only until controls are explicitly enabled.

## How it works

The core statistical idea is cointegration, not correlation. Two assets can move 95% together in daily returns while their price levels drift apart forever, with nothing to mean-revert to. Cointegration means a linear combination of the price levels is stationary, so there is an actual mean to come back to. I estimate the hedge ratio by OLS regression (or track it online with a Kalman filter), test for cointegration with Engle-Granger and for stationarity of the residual spread with ADF, and estimate a half-life of mean reversion from an AR(1) fit on the spread, which I use to size time stops. Entries and exits are z-score thresholds on the standardized spread, and a cost-edge gate skips any trade whose expected reversion is smaller than its round-trip cost.

For the cross-sectional strategies, the harder problem wasn't finding a signal, it was not fooling myself about one. Early on I evaluated somewhere around 40 to 60 configurations on the same five-year window before adding any correction for that search, which is exactly the setup that hands you a good-looking Sharpe ratio out of pure noise. The fix was a deflated Sharpe ratio calculation (Bailey and López de Prado): it estimates the best Sharpe you'd expect from N independent zero-skill trials on your sample length, and checks whether your actual result clears that bar. Run honestly against its true trial count, the equity ensemble's Sharpe does not clear the bar, so I record it as an unproven research candidate rather than a strategy.

The rest of the validation stack follows the same instinct. Walk-forward testing fits on a rolling window and only scores the following out-of-sample window. A stress suite reruns everything at two and three times modeled costs, with delayed execution, and with the best trades removed. A survivorship-stress test checks how much of a result depends on names that happen to still exist today. A return-concentration check flags results where one month or a handful of days account for most of the total profit, which turned out to be true of more than one strategy here, and is a real fragility rather than a rounding error.

## What I found

The numbers moved a lot once the validation caught up with the strategies. An internal audit found the original headline figures were in-sample and inflated by same-bar fills, missing dividend adjustments, and frictionless shorting. After fixing those, the re-stated daily equity ensemble (12-1 momentum plus time-series momentum plus a momentum-neutral ML sleeve, on a 50-name US large-cap universe) returns +35.3% over the backtest window with a Sharpe of 1.02 and a max drawdown of -10.1%, and it holds up out-of-sample (walk-forward Sharpe 0.97, degradation 0.14, every fold positive) and under 2x-3x cost stress. It still fails its own return-concentration gate, though, and does not clear the deflated Sharpe bar against its true trial count (P(true Sharpe > noise-max) = 0.375), so I treat it as a research candidate, not something I'd trade. It also cannot actually be shorted on any connected venue, which matters for a book that is supposed to be market-neutral.

The long-only Trading 212 book is the one that has actually gone somewhere. After adding EWMA target-weight smoothing to fix a concentration problem (worst month 26.1% of PnL, now 23.5%, under the 25% limit), it clears every research and operational gate for paper trading: Sharpe 1.44, walk-forward out-of-sample Sharpe 1.65 across both folds, and it beats SPY, QQQ, and an equal-weight benchmark on a risk-adjusted basis. That's still the whole verdict, though: eligible to *begin* a supervised paper period, nothing more, and not eligible for live capital under any circumstances yet. On crypto, pairs trading on stocks was thin but positive out-of-sample (walk-forward Sharpe 0.88); crypto mean reversion mostly did not work over this window, where time-series momentum was the only standalone winner and PCA and reversal strategies were negative enough to drop from the default ensemble.

More detail, including everything I currently know is wrong with the research: [`FINAL_RESEARCH_REPORT.md`](FINAL_RESEARCH_REPORT.md), [`RESEARCH_WEAKNESSES.md`](RESEARCH_WEAKNESSES.md), [`PAPER_ELIGIBILITY_REPORT.md`](PAPER_ELIGIBILITY_REPORT.md), and [`PRODUCTION_RISK_REGISTER.md`](PRODUCTION_RISK_REGISTER.md).

## Running it

Requires Python 3.11+.

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest                                                # test suite, everything mocked or synthetic
statarb init-db
statarb download-data --source synthetic --days 90    # fully offline demo
statarb discover-pairs --universe synthetic_demo
statarb backtest --strategy pairs_zscore --universe synthetic_demo --stress
statarb dashboard                                      # needs: pip install -e ".[dashboard]"
```

For the dashboard's frontend: `cd frontend && npm install && npm run build`, then `statarb dashboard` and open `http://127.0.0.1:8000`. The full command set, including the equity and crypto backtests and the long-only paper-trading workflow, is documented on the CLI itself (`statarb <command> --help`).

## Limitations, and what I'd do next

Live trading is disabled everywhere in the code and sits behind a kill switch, a risk manager, and several independent confirmations, and I intend to keep it that way until a strategy survives a real forward paper period rather than just a backtest. Specific things I know are still wrong or unresolved: the equity universes are survivorship-biased (today's large caps, backtested into the past); the historical trial count behind the deflated Sharpe check is not fully back-filled, so that gate is more honest than it used to be but still incomplete; costs are realistic but not complete (no per-name borrow rates, no taxes); and crisis testing is synthetic because the sample period has not lived through a real crash. The next real step, if I keep going, is running the long-only book through an actual multi-month paper period and seeing whether any of this survives contact with a market it was never fit to.
