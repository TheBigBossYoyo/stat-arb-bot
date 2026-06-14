# Tradability matrix

Updated by the readiness commands; verdicts as of 2026-06-14. ✅ pass / ❌ fail /
➖ n/a / ❔ not yet evaluated.

| product | broker avail. | shorting | data | backtest | OOS | stress | concentration | crisis | paper | live eligible |
|---------|:-------------:|:--------:|:----:|:--------:|:---:|:------:|:-------------:|:------:|:-----:|:-------------:|
| **stock market-neutral** | ❌ none connected | needs it | ✅ | ✅ | ✅ | ✅ | ❌ | ❔ | ➖ (no venue) | ❌ |
| **stock long-only (T212)** | ✅ official API (DEMO order path wired) | ➖ no | ✅ | ✅ (Sharpe 1.44) | ✅ (1.65, 2/2) | ✅ (×2/×3) | ✅ (23.5%) | ✅ (synthetic, bounded −28%) | ✅ eligible to BEGIN | ❌ |
| **crypto spot** | ✅ Binance | ❌ cannot short | ✅ | ➖ | ➖ | ➖ | ➖ | ➖ | ➖ | ❌ |
| **crypto futures** | ✅ testnet (live blocked) | ✅ | ✅ (~0.84y) | ✅ (Sharpe 1.16) | ✅ (1.59) | ✅ | ❌ | ❔ | ❔ | ❌ |
| **funding carry** | ✅ testnet | ✅ | ✅ | ✅ (funding leg) | ❔ | ❔ | ❔ | ❔ | ❔ | ❌ |
| **basis carry** | ✅ testnet | ✅ | ❔ needs spot+perp | ❔ | ❔ | ❔ | ❔ | ❔ | ❌ |

Key reads:

- **The binding column is "live eligible": every row is ❌.** Live stays blocked.
- **Long-only (T212) now clears every research gate** after EWMA smoothing closed
  the concentration gate (23.5%), plus operational gates (DEMO order path wired,
  survivorship bounded, crisis tested). It is **eligible to BEGIN** a supervised
  paper/shadow period — the "paper" ✅ means *eligible to start*, NOT a passed
  forward period. Survivorship is *bounded*, crisis is *synthetic*; both keep
  live blocked.
- The market-neutral book fails on **broker availability** (no shorting venue)
  *and* on its corrected deflated Sharpe.
- Crypto futures still fails the **concentration** gate; data row ✅ but thin
  (~0.84y aligned) — a real weakness.
