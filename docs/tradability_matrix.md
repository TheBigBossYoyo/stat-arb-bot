# Tradability matrix

Updated by the readiness commands; verdicts as of 2026-06-13. ✅ pass / ❌ fail /
➖ n/a / ❔ not yet evaluated.

| product | broker avail. | shorting | data | backtest | OOS | stress | concentration | crisis | paper | live eligible |
|---------|:-------------:|:--------:|:----:|:--------:|:---:|:------:|:-------------:|:------:|:-----:|:-------------:|
| **stock market-neutral** | ❌ none connected | needs it | ✅ | ✅ | ✅ | ✅ | ❌ | ❔ | ➖ (no venue) | ❌ |
| **stock long-only (T212)** | ✅ official API (order path unwired) | ➖ no | ✅ | ✅ (Sharpe 1.53) | ✅ (1.71) | ✅ (×2/×3) | ❌ (26.1%) | ❔ | ❔ | ❌ |
| **crypto spot** | ✅ Binance | ❌ cannot short | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ❌ |
| **crypto futures** | ✅ testnet (live blocked) | ✅ | ✅ (~0.84y) | ✅ (Sharpe 1.16) | ✅ (1.59) | ✅ | ❌ | ❔ | ❔ | ❌ |
| **funding carry** | ✅ testnet | ✅ | ✅ | ✅ (funding leg) | ❔ | ❔ | ❔ | ❔ | ❔ | ❌ |
| **basis carry** | ✅ testnet | ✅ | ❔ needs spot+perp | ❔ | ❔ | ❔ | ❔ | ❔ | ❌ |

Key reads:

- **The binding column is "live eligible": every row is ❌.**
- The market-neutral book fails on **broker availability** (no shorting venue)
  *and* on its corrected deflated Sharpe.
- Long-only and crypto futures both fail only the **concentration** gate so far;
  both still need **crisis** and a **paper** period.
- Crypto's data row is ✅ but thin (~0.84y aligned) — a real weakness.
