"""Product decision engine (Phase 6).

Synthesizes everything — the three product paths plus the market-neutral
flagship — into one operator-facing decision: what (if anything) to trade, on
what venue, with which strategy, what is still missing, and the safest next
action. It reads the readiness reports each path writes (gracefully degrading to
"not evaluated" when one is absent) plus the deflated-Sharpe verdict, and never
asserts live eligibility.

The honest default today is "do not trade real capital — continue research",
with the long-only equity book named the lead candidate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProductStatus:
    product_id: str
    name: str
    venue: str
    asset_class: str
    requires_short: bool
    requires_leverage: bool
    venue_connected: bool          # is an order path to a real venue wired?
    venue_kind: str = "none"       # none | official_not_wired | testnet | live
    gates_passed: int = 0
    gates_total: int = 0
    eligible_label: str = ""       # PAPER / TESTNET / NONE
    status: str = "not_evaluated"  # do_not_trade | not_yet | paper_candidate | testnet_candidate
    risk_level: str = "unknown"    # low | medium | high | extreme
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        """Rank candidates by gate completion, with a principled penalty for how
        far the venue is from a real-capital path and for fundamental risk. A
        venue that merely lacks an order-path wiring (T212 official API exists)
        is penalized far less than 'no venue exists at all'; testnet is not a
        real-capital path, so it gets only modest credit and pays its risk."""
        base = (self.gates_passed / self.gates_total) if self.gates_total else 0.0
        base -= {"none": 0.30, "official_not_wired": 0.05, "official_demo": 0.03,
                 "testnet": 0.10, "live": 0.0}.get(self.venue_kind, 0.20)
        base -= {"extreme": 0.30, "high": 0.10, "medium": 0.05}.get(self.risk_level, 0.0)
        return round(base, 3)


@dataclass
class ProductDecision:
    products: list[ProductStatus]
    recommended: str
    action: str
    capital_stage: str
    headline: str


def _read_report(reports_dir: Path, name: str) -> str:
    p = reports_dir / name
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _parse_gates(text: str) -> tuple[int, int, list[str]]:
    """Count PASS/FAIL gate lines and collect failures from a readiness report."""
    passes = len(re.findall(r"PASS\b", text))
    fails = re.findall(r"FAIL\s*[—-]\s*(.+)", text)
    total = passes + len(fails)
    return passes, total, [f.strip() for f in fails]


def evaluate_products(settings, storage) -> ProductDecision:
    rd = settings.reports_dir

    products: list[ProductStatus] = []

    # 1) market-neutral equity flagship — the research candidate, untradable
    deflated = _read_report(rd, "deflated_sharpe_equity_daily_book_selection.md")
    deflated_fails = "FAILS DEFLATED SHARPE" in deflated
    mn = ProductStatus(
        product_id="market_neutral_equity",
        name="xsec_momentum + tsmom + ml_alpha (market-neutral)",
        venue="(needs margin/shorting broker — none connected)",
        asset_class="equity", requires_short=True, requires_leverage=True,
        venue_connected=False, venue_kind="none", status="do_not_trade", risk_level="medium",
        missing=["a shorting venue (Path C, none connected)",
                 "true-deflated-Sharpe FAILS the 45-trial correction"
                 if deflated_fails else "deflated-Sharpe not yet evaluated",
                 "return-concentration gate"],
        notes=["NOT tradable on any connected venue.",
               "Deflated against the real ~45-config search it is an UNPROVEN "
               "candidate (P(true>noise)=0.375), not an established edge."
               if deflated_fails else "Run deflated-sharpe-report."],
    )
    products.append(mn)

    # 2) long-only equity (Trading 212 Invest/ISA)
    lo_text = _read_report(rd, "long_only_readiness_long_only_xsec_momentum_us_stocks_50.md") \
        or _read_report(rd, "long_only_readiness_long_only_ensemble_us_stocks_50.md")
    # the Trading 212 DEMO order path is wired (demo-only; live hard-blocked)
    try:
        import app.brokers.trading212.demo_execution  # noqa: F401
        demo_wired = True
    except Exception:  # noqa: BLE001
        demo_wired = False
    lo = ProductStatus(
        product_id="long_only_equity",
        name="long-only momentum (Trading 212 Invest/ISA)",
        venue=("Trading 212 Invest/ISA (official API; DEMO order path wired, live blocked)"
               if demo_wired else "Trading 212 Invest/ISA (official API; order path not wired)"),
        asset_class="equity", requires_short=False, requires_leverage=False,
        venue_connected=demo_wired,
        venue_kind="official_demo" if demo_wired else "official_not_wired",
        risk_level="high",   # directional long book
    )
    if lo_text:
        text_l = lo_text.lower()
        lo.gates_passed, lo.gates_total, lo.missing = _parse_gates(lo_text)
        paper_eligible = ("paper_eligible: true" in text_l
                          or "eligible to begin supervised paper/shadow" in text_l)
        research_passed = "research_gate_passed: true" in text_l or paper_eligible
        lo.status = "paper_candidate" if paper_eligible else "not_yet"
        lo.eligible_label = "PAPER" if paper_eligible else "NONE"
        lo.notes.append("Beats SPY/QQQ/equal-weight on Sharpe with positive alpha; "
                        "directional (NOT market-neutral). EWMA smoothing closed the "
                        "concentration gate (worst month 23.5%).")
        if research_passed and not paper_eligible:
            lo.notes.append("Research gates passed; pending operational paper setup "
                            "(survivorship/crisis/order-path).")
        if paper_eligible:
            lo.notes.append("Eligible to BEGIN a supervised paper/shadow period; "
                            "LIVE REMAINS BLOCKED.")
    else:
        lo.notes.append("Run long-only-readiness --full to evaluate.")
    products.append(lo)

    # 3) crypto futures (Binance futures testnet)
    fut_text = _read_report(rd, "futures_readiness_crypto_futures_ensemble_crypto_top_20.md")
    fut = ProductStatus(
        product_id="crypto_futures",
        name="crypto futures ensemble (Binance USDT-perp)",
        venue="Binance futures testnet (live blocked)",
        asset_class="crypto_futures", requires_short=True, requires_leverage=True,
        venue_connected=True, venue_kind="testnet", risk_level="extreme",   # 44% vol, -27% DD
    )
    if fut_text:
        fut.gates_passed, fut.gates_total, fut.missing = _parse_gates(fut_text)
        eligible = "NOT YET" not in fut_text and "TESTNET/PAPER ELIGIBLE" in fut_text
        fut.status = "testnet_candidate" if eligible else "not_yet"
        fut.eligible_label = "TESTNET" if eligible else "NONE"
        fut.notes.append("Can short on perps; LIVE BLOCKED. High crypto risk and a "
                         "short (~0.84y) aligned sample.")
    else:
        fut.notes.append("Run futures-readiness to evaluate.")
    products.append(fut)

    # decide: any product fully eligible? else the highest-scoring not_yet candidate.
    eligible = [p for p in products if p.status in ("paper_candidate", "testnet_candidate")]
    candidates = [p for p in products if p.status in ("not_yet",)]
    if eligible:
        best = max(eligible, key=lambda p: p.score)
        recommended = best.product_id
        action = f"Begin a SUPERVISED {best.eligible_label} period for {best.name}."
        capital_stage = "paper/testnet only — zero real capital until the period passes"
        headline = f"{best.eligible_label}-ELIGIBLE: {best.name}"
    elif candidates:
        best = max(candidates, key=lambda p: p.score)
        recommended = best.product_id
        action = (f"Close the remaining gate(s) on the lead candidate "
                  f"({best.name}): {', '.join(best.missing[:3]) or 'see report'}.")
        capital_stage = "NONE — do not trade real capital; continue research"
        headline = ("NO product is paper/testnet eligible yet; continue research. "
                    f"Lead candidate: {best.name}")
    else:
        recommended = "none"
        action = "Run the readiness commands for each path, then re-decide."
        capital_stage = "NONE"
        headline = "Insufficient evidence — run readiness reports."

    return ProductDecision(products=products, recommended=recommended, action=action,
                           capital_stage=capital_stage, headline=headline)
