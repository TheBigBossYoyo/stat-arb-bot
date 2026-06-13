# Binance Futures crypto research path (Path B)

**Status:** research / paper / **testnet** only. **Mainnet live trading is
blocked unconditionally** in code (`futures_testnet_execution.refuse_live`).
This is NOT the equity flagship ported to crypto — it is a separate crypto-native
alpha stack built around what perps actually offer (shorting, funding, basis).

## Why this path

Perpetual futures *can* short and lever, so unlike Trading 212 they can host a
two-sided book — and crypto has structural carry (funding, basis) that equities
do not. The question Path B answers: **is a leverage-disciplined crypto-futures
book testnet/paper eligible, net of fees, funding and liquidation risk?**

## Components

| File | Role |
|------|------|
| `app/data/futures.py` | public USDT-perp klines / mark price / open interest |
| `app/data/funding.py` | funding-rate panels + APR summary |
| `app/data/basis.py` | perp-vs-spot basis |
| `app/backtesting/futures_engine.py` | fees + funding P&L + leverage cap + liquidation monitor |
| `app/strategies/crypto_tsmom_futures.py` | multi-horizon trend, vol-scaled, BTC/ETH beta cap, crash de-risk |
| `app/strategies/funding_carry.py` | short rich-funding perps / long deeply-negative (hysteresis) |
| `app/strategies/basis_carry.py` | short rich basis / long cheap basis (hysteresis, convergence-vol sizing) |
| `app/strategies/funding_adjusted_momentum.py` | trend net of expected carry |
| `app/strategies/crypto_futures_ensemble.py` | risk-parity blend + BTC/ETH beta / per-symbol / funding-concentration caps |
| `app/risk/futures_risk.py` | leverage cap, liquidation buffer, funding-cancels-edge, spread/liquidity gates, kill switch |
| `app/brokers/binance/futures_client.py` | public data + testnet base URL + symbol filters |
| `app/brokers/binance/futures_testnet_execution.py` | paper/testnet executor — **live refused** |

## Risk rules (enforced)

- **Leverage** default **1x**, hard research cap **2x** (`FuturesRiskModel` scales
  any book above the cap down).
- **Liquidation buffer** must stay healthy; positions are shrunk to keep the
  distance-to-liquidation above the floor; the engine counts buffer breaches.
- **No trade** when funding cost cancels the edge, when spread is abnormally wide,
  or when liquidity is below threshold.
- **Kill switch** (fail-closed → flat) on abnormal funding, spread widening, or a
  liquidation-buffer breach.

## Cost model

Maker/taker fees (4 bps taker), slippage (3 bps), **funding paid/received every
period** (longs pay positive funding; shorts receive), leverage, and a
liquidation-distance monitor. NOT in the base case (they are stress scenarios):
the full liquidation cascade, auto-deleveraging, and exchange outages.

## Backtest result (crypto_top_20, daily, funding applied, 1x)

`crypto_futures_ensemble`:

| metric | value |
|--------|------:|
| total return | +42.0% |
| Sharpe | 1.16 |
| ann. vol | **44.4%** |
| max drawdown | **−27.3%** |
| 2nd-half (OOS) Sharpe | 1.59 |
| net funding paid | $296 (longs paid) |
| liquidation breaches @1x | 0 |
| min liquidation distance | 0.95 |

**Read it honestly.** The book is profitable and survives at 1x with a huge
liquidation buffer, but its risk is crypto-native: **44% annualized vol and a
−27% drawdown** dwarf the equity books. The Sharpe (1.16) is respectable but the
*ride* is violent. The biggest caveat is **sample length**: the aligned window is
only ~0.84 years (the youngest perp in the universe limits the common window) —
far too short to call structural. Funding is fetched from the public API; the
basis sleeve idles in this run (needs aligned spot bars; use `basis-report`).

## Readiness (`statarb futures-readiness`)

**5/6 gates pass** (positive return, Sharpe > 0.5, 2nd-half OOS Sharpe > 0, no
liquidation breaches at 1x, healthy buffer). Fails **concentration** (a single
month > 25% of PnL — crypto returns are bursty). Verdict: **NOT YET testnet/paper
eligible**, and **LIVE BLOCKED** regardless.

## CLI

```
statarb download-futures-data --universe crypto_top_20 --days 1095
statarb backtest-futures      --strategy crypto_futures_ensemble --universe crypto_top_20
statarb funding-report        --universe crypto_top_20
statarb basis-report          --universe crypto_top_20
statarb futures-stress        --strategy crypto_futures_ensemble
statarb futures-paper         --broker binance --mode testnet
statarb futures-readiness     --strategy crypto_futures_ensemble
```

## Blockers to testnet, then live

1. **Longer history** — the current ~0.84y aligned window is not evidence of
   structure; download more (or trim the universe to long-listed perps).
2. **Concentration** — a single month dominates; apply the Phase 1 smoothing /
   de-risk before paper.
3. **Basis sleeve** needs stored spot bars to contribute.
4. **Supervised testnet period** with real testnet keys + TCA (Phase 5).
5. **Live remains refused** — mainnet enablement is a separate, deliberate step
   that does not exist and should not until 1-4 pass.
