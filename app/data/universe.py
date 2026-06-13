"""Trading universes.

The MVP uses a static list of liquid Binance USDT spot pairs. Dynamic
filtering (24h quote volume, listing age, spread) is applied on top when
live exchange info is available.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.exceptions import ConfigurationError


@dataclass(frozen=True)
class UniverseMeta:
    """Bias/tradability metadata. Every research artifact must surface
    `survivorship` — a backtest on a `static_survivor` universe is a
    viability sketch, not evidence (audit W-04)."""

    asset_class: str                    # equity | crypto_spot | fx | synthetic
    survivorship: str                   # point_in_time | static_survivor | not_applicable
    selection_note: str = ""

UNIVERSES: dict[str, list[str]] = {
    "crypto_top_10": [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
        "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "LTCUSDT",
    ],
    "crypto_majors": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
    # 20 liquid USDT perps for the crypto-futures research path (Path B). All
    # have deep perp markets and funding history; still survivor-selected (these
    # are today's liquid perps, not 2021's).
    "crypto_top_20": [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
        "AVAXUSDT", "LINKUSDT", "DOGEUSDT", "LTCUSDT", "DOTUSDT", "MATICUSDT",
        "TRXUSDT", "BCHUSDT", "ATOMUSDT", "UNIUSDT", "ETCUSDT", "FILUSDT",
        "APTUSDT", "NEARUSDT",
    ],
    # Synthetic universe for offline demos/tests: pairs (SYN0,SYN1), (SYN2,SYN3)...
    # are cointegrated by construction.
    "synthetic_demo": [f"SYN{i}" for i in range(8)],
    # US large caps with classic pair candidates (daily research data via
    # yahoo; execution would go through Trading 212 — long-only on Invest/ISA).
    "us_stocks_demo": [
        "KO", "PEP", "XOM", "CVX", "V", "MA",
        "JPM", "BAC", "HD", "LOW", "WMT", "TGT",
    ],
    # 50 liquid US large caps across sectors (daily research data via yahoo).
    # Cross-sectional strategies (PCA stat-arb, xsec momentum) need this kind
    # of breadth — they are structurally starved on a 10-name crypto universe.
    "us_stocks_50": [
        # technology / communication
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "AVGO", "ORCL",
        "CRM", "ADBE", "CSCO", "INTC", "AMD", "QCOM", "TXN",
        # financials
        "JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "BLK",
        # healthcare
        "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT",
        # consumer
        "PG", "KO", "PEP", "WMT", "COST", "HD", "LOW", "MCD", "NKE",
        # energy / industrials
        "XOM", "CVX", "COP", "CAT", "DE", "BA", "HON", "UPS", "GE",
    ],
    # 100-name extension of us_stocks_50 (defined below, after the dict) —
    # more breadth for the cross-sectional strategies.
    # FX majors (Yahoo '=X' symbols) — RESEARCH ONLY: no connected broker
    # executes spot FX and FX CFDs are out of scope by policy.
    "fx_majors": [
        "EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDCHF=X",
        "AUDUSD=X", "NZDUSD=X", "USDCAD=X", "EURGBP=X",
    ],
}

# us_stocks_50 plus 50 more long-listed S&P 100/500 large caps. All names were
# public well before the 5-year research window; the universe is still chosen
# TODAY, so survivorship bias remains — treat results as viability checks.
UNIVERSES["us_stocks_100"] = UNIVERSES["us_stocks_50"] + [
    # tech / communication / semis
    "TMUS", "VZ", "T", "CMCSA", "DIS", "NFLX", "IBM", "MU", "AMAT", "LRCX",
    "ADI", "KLAC",
    # financials
    "SCHW", "USB", "PNC", "COF", "MET", "AIG", "PGR", "CB", "SPGI",
    # healthcare
    "AMGN", "GILD", "BMY", "CVS", "CI", "ISRG", "SYK", "MDT", "DHR",
    # consumer
    "PM", "MO", "CL", "KMB", "MDLZ", "TJX", "BKNG", "ORLY", "CMG", "MAR",
    # industrials / energy / utilities / materials
    "RTX", "LMT", "UNP", "CSX", "FDX", "EMR", "MMM", "SLB", "EOG", "NEE",
]

UNIVERSE_META: dict[str, UniverseMeta] = {
    "crypto_top_10": UniverseMeta(
        "crypto_spot", "static_survivor",
        "today's top-10 by cap/liquidity; coins that died out of the top 10 are absent"),
    "crypto_majors": UniverseMeta("crypto_spot", "static_survivor",
                                  "hand-picked current majors"),
    "crypto_top_20": UniverseMeta("crypto_futures", "static_survivor",
                                  "today's 20 liquid USDT perps; survivor-selected"),
    "synthetic_demo": UniverseMeta("synthetic", "not_applicable", "generated data"),
    "us_stocks_demo": UniverseMeta("equity", "static_survivor",
                                   "hand-picked classic pairs, chosen today"),
    "us_stocks_50": UniverseMeta(
        "equity", "static_survivor",
        "2026 mega-caps backtested into the past; the worst case for momentum bias"),
    "us_stocks_100": UniverseMeta(
        "equity", "static_survivor",
        "us_stocks_50 plus 50 long-listed large caps, still selected today"),
    "fx_majors": UniverseMeta("fx", "not_applicable",
                              "major FX pairs do not delist; research only"),
}

STABLECOINS = {"USDT", "USDC", "FDUSD", "TUSD", "DAI", "BUSD"}

# Sector map for the US stock universes (sector-relative residual stat-arb).
# Roughly GICS, with one pragmatic merge: communication-services mega caps
# (GOOGL, META, NFLX, DIS, ...) are grouped with tech — as a 2-name GICS
# sector inside us_stocks_50 they cannot support a leave-one-out factor.
SECTORS: dict[str, str] = {
    # tech + communication
    **dict.fromkeys(
        ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AVGO", "ORCL", "CRM",
         "ADBE", "CSCO", "INTC", "AMD", "QCOM", "TXN", "TMUS", "VZ", "T",
         "CMCSA", "DIS", "NFLX", "IBM", "MU", "AMAT", "LRCX", "ADI", "KLAC"],
        "tech"),
    # financials (V/MA moved to GICS financials in 2023)
    **dict.fromkeys(
        ["JPM", "BAC", "WFC", "GS", "MS", "V", "MA", "AXP", "BLK", "SCHW",
         "USB", "PNC", "COF", "MET", "AIG", "PGR", "CB", "SPGI"],
        "financials"),
    # healthcare
    **dict.fromkeys(
        ["UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "AMGN",
         "GILD", "BMY", "CVS", "CI", "ISRG", "SYK", "MDT", "DHR"],
        "healthcare"),
    # consumer discretionary
    **dict.fromkeys(
        ["AMZN", "HD", "LOW", "MCD", "NKE", "TJX", "BKNG", "ORLY", "CMG",
         "MAR"],
        "cons_disc"),
    # consumer staples
    **dict.fromkeys(
        ["PG", "KO", "PEP", "WMT", "COST", "PM", "MO", "CL", "KMB", "MDLZ"],
        "cons_staples"),
    # energy
    **dict.fromkeys(["XOM", "CVX", "COP", "SLB", "EOG"], "energy"),
    # industrials
    **dict.fromkeys(
        ["CAT", "DE", "BA", "HON", "UPS", "GE", "RTX", "LMT", "UNP", "CSX",
         "FDX", "EMR", "MMM"],
        "industrials"),
    # utilities (single name in us_stocks_100 — excluded from sector books
    # by min_sector_size, kept here so the consistency test passes)
    "NEE": "utilities",
}


def get_universe(name: str) -> list[str]:
    try:
        return list(UNIVERSES[name])
    except KeyError as exc:
        raise ConfigurationError(f"unknown universe {name!r}; choose from {list(UNIVERSES)}") from exc


def get_universe_meta(name: str) -> UniverseMeta:
    """Metadata for a universe; ad-hoc symbol lists are treated as
    survivor-selected (the researcher chose them knowing the present)."""
    return UNIVERSE_META.get(
        name,
        UniverseMeta("unknown", "static_survivor", "ad-hoc symbol list, chosen today"),
    )


def get_sectors(universe: str) -> dict[str, str]:
    """Sector map restricted to one universe; {} when no sectors are defined
    (crypto, FX, synthetic)."""
    return {s: SECTORS[s] for s in get_universe(universe) if s in SECTORS}


def is_stable_stable(symbol: str) -> bool:
    """True for stablecoin/stablecoin symbols like FDUSDUSDT — excluded from stat-arb."""
    for quote in STABLECOINS:
        if symbol.endswith(quote) and symbol[: -len(quote)] in STABLECOINS:
            return True
    return False
