# Margin / shorting equity broker requirements (Path C)

**Status:** abstraction layer only. **No margin/shorting broker is connected.**
The market-neutral flagship cannot trade until one is — that is the binding
constraint, not the alpha.

## Why this exists

The flagship (`xsec_momentum + tsmom + ml_alpha`) is a market-neutral book: it
shorts. None of the connected venues can host it:

- **Binance spot** — cannot short.
- **Trading 212 Invest/ISA** — cannot short, cannot use margin; CFDs are out of
  scope (official API doesn't expose them and we will not use unofficial routes).

Rather than hardcode one future broker, Path C defines the **integration
contract** a real, official margin/shorting equity broker would implement, plus
the risk models the short leg needs. When such a venue is integrated (via its
*official* API), the flagship has a home; until then it is research-only.

## Components

| File | Role |
|------|------|
| `app/brokers/margin_equity/models.py` | `MarginInstrument`, `BorrowQuote`, `ShortabilityStatus`, `MarginAccountState`, `ShortDividendLiability`, `CorporateAction` |
| `app/brokers/margin_equity/base.py` | `MarginEquityBrokerBase` — the abstract connector interface |
| `app/brokers/margin_equity/capabilities.py` | required capabilities + candidate-broker survey + readiness check |
| `app/risk/shorting_risk.py` | shortability/locate/SSR/HTB screening of a short book |
| `app/risk/borrow_risk.py` | per-name borrow-cost model (fixes the blended-rate audit gap) |

## The interface a venue must implement (`MarginEquityBrokerBase`)

- **Account** — cash, equity (net liquidation), long/short market value,
  **margin buying power**, **maintenance margin**, excess liquidity, SMA,
  margin-call flag.
- **Borrow** — `get_borrow_quote(symbol)`: available shares, **borrow rate**,
  hard-to-borrow flag, **locate requirement**, rebate.
- **Shortability** — `is_shortable(symbol)`: shortable now?, **short-sale
  restriction (Reg SHO uptick)** state, locate required.
- **Locate** — `request_locate(symbol, qty)` where the venue requires one.
- **Orders** — placement / cancellation / status (inherited from `BrokerBase`),
  with the sell-to-open (short) convention.
- **Market structure** — `get_margin_instruments` with marginable / shortable /
  ETB / maintenance% per name; market hours.
- **Corporate actions** — splits/dividends/spinoffs, and **short-dividend
  liability** (a borrower owes the dividend to the lender over ex-date).
- **Margin interest** — annual rate on debit balances.

`can_short(symbol, qty)` composes capability + shortability + SSR + locate +
borrow-inventory into one pre-trade gate.

## Hard requirements (a venue must clear ALL)

`shorting`, `margin`, `equity` asset class, `borrow_quote` (per-name cost),
`shortability_check`, `maintenance_margin`, and an **official API**
(non-negotiable: no scraping, no browser automation, no reverse-engineered or
private endpoints).

## Candidate venues (survey — none connected)

| broker | official API | shorting | margin | verdict |
|--------|:-----------:|:--------:|:------:|---------|
| Interactive Brokers | ✅ | ✅ | ✅ | **Reference venue.** Full stock-loan, locates, SSR. Integration non-trivial (gateway/session). |
| Alpaca | ✅ | ✅ | ✅ | Viable. Simpler REST API; ETB list; thinner borrow universe than IBKR. |
| Trading 212 | ✅ | ❌ | ❌ | Disqualified for the neutral book (→ Path A long-only instead). |
| Binance spot | ✅ | ❌ | ❌ | Disqualified for equities. |

Run `evaluate_candidate` for the readiness scorecard.

## Risk models the short leg needs (and the long-only book never did)

- **Borrow cost is per-name and right-skewed.** The current backtest charges a
  blended 75 bps/yr; `borrow_risk.py` replaces that with a tiered per-name cost
  (`gc` ~30 / `moderate` ~150 / `hard` ~600 / `special` ~3000 bps) and a
  `per_asset_cost_bps` builder the basket engine can charge. `momentum_loser_tiers`
  provides a conservative stress: a momentum book shorts beaten-down, often
  hard-to-borrow names, so its true borrow cost is materially above blended.
- **Shorting screen.** `shorting_risk.screen_short_book` cuts not-shortable /
  no-locate / too-expensive shorts, caps per-name short weight, and caps the
  aggregate hard-to-borrow bucket (squeeze/buy-in control).

## What integrating a venue would take (future work)

1. Implement a `MarginEquityBrokerBase` subclass against the broker's official
   API (account, borrow, shortability, orders, corporate actions).
2. Wire its `BorrowQuote`/`ShortabilityStatus` into `screen_short_book` and the
   per-name borrow cost into the backtest, then re-validate the flagship with
   *realistic* borrow (it will be worse than the blended number).
3. Add the broker to `config/broker_capabilities.yaml` and the governance gates.
4. Only then can the flagship reach a supervised paper period on a real venue.

**No part of this should ever be built on an unofficial API.**
