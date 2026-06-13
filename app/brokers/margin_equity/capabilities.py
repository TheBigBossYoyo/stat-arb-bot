"""Capability requirements + readiness check for a margin/shorting broker (Path C).

Defines the capabilities a venue MUST expose to host the market-neutral flagship,
a survey of candidate *official* brokers (status: none connected), and a function
that scores how ready a candidate connector is. The point is to make integration
a checklist, not a guess — and to keep the bar honest: a venue that cannot short,
or only offers an unofficial API, does not qualify.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Hard requirements: the flagship is a market-neutral, margin, equity book.
REQUIRED_CAPABILITIES = (
    "shorting",                 # the binding one — every connected venue fails this
    "margin",
    "equity_asset_class",
    "borrow_quote",             # per-name borrow cost (audit: per-name tiers unmodeled)
    "shortability_check",
    "maintenance_margin",
    "official_api",             # NON-NEGOTIABLE: no scraping / reverse-engineered endpoints
)

# Capabilities that are strongly desired but a book could launch without.
DESIRED_CAPABILITIES = (
    "locate_api", "short_sale_restriction_flag", "corporate_action_feed",
    "fractional_shares", "market_data", "limit_orders",
)


@dataclass(frozen=True)
class BrokerCandidate:
    name: str
    has_official_api: bool
    supports_shorting: bool
    supports_margin: bool
    notes: str
    connected: bool = False        # is a connector implemented + tested here?


# Survey only — informational. NONE are connected; integrating any one is future
# work and must use the broker's official, documented API.
CANDIDATES: tuple[BrokerCandidate, ...] = (
    BrokerCandidate(
        "interactive_brokers", True, True, True,
        "Official Web API / TWS API; full stock-loan, locates, SSR; the reference "
        "venue for a shorting book. Integration is non-trivial (session/gateway).",
    ),
    BrokerCandidate(
        "alpaca", True, True, True,
        "Official REST API with easy-to-borrow list + short support on a margin "
        "account; simpler API, thinner borrow universe than IBKR.",
    ),
    BrokerCandidate(
        "trading212", True, False, False,
        "Official Public API is Invest/ISA equity only — NO shorting, NO margin. "
        "Disqualified for the neutral book (this is why Path A exists).",
    ),
    BrokerCandidate(
        "binance_spot", True, False, False,
        "Spot cannot short. Disqualified for equities entirely.",
    ),
)


@dataclass
class ReadinessReport:
    broker: str
    met: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    desired_missing: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.missing

    def summary(self) -> str:
        verdict = "READY to host the neutral book" if self.ready else "NOT READY"
        return (f"{self.broker}: {verdict} — {len(self.met)}/{len(REQUIRED_CAPABILITIES)} "
                f"required met; missing {self.missing or 'none'}")


def evaluate_candidate(candidate: BrokerCandidate) -> ReadinessReport:
    """Score a candidate against the hard requirements (informational survey)."""
    have = set()
    if candidate.has_official_api:
        have.add("official_api")
    if candidate.supports_shorting:
        have.update({"shorting", "shortability_check", "borrow_quote"})
    if candidate.supports_margin:
        have.update({"margin", "maintenance_margin"})
    have.add("equity_asset_class")     # all candidates here are equity venues
    report = ReadinessReport(broker=candidate.name)
    for cap in REQUIRED_CAPABILITIES:
        (report.met if cap in have else report.missing).append(cap)
    return report


def required_capabilities_summary() -> dict:
    return {"required": list(REQUIRED_CAPABILITIES),
            "desired": list(DESIRED_CAPABILITIES),
            "candidates": [c.name for c in CANDIDATES],
            "connected": [c.name for c in CANDIDATES if c.connected]}
