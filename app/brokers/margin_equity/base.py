"""MarginEquityBrokerBase — the interface a shorting equity venue must implement.

This is the integration contract for a *future*, official margin/shorting broker
(Interactive Brokers, Alpaca, etc. through their documented APIs). It extends the
generic BrokerBase with everything a market-neutral / short book needs and a
long-only spot connector never did: margin buying power, borrow availability and
cost, locates, short-sale restrictions, margin interest and short-dividend
liability.

Every method is abstract. A connector is "ready" only when it implements all of
them against an OFFICIAL API — see `capabilities.py` for the readiness check.
Until then the flagship has no venue and stays research-only.

We will not implement any of this through scraping, browser automation, or
reverse-engineered/private endpoints.
"""

from __future__ import annotations

from abc import abstractmethod

from app.brokers.base import BrokerBase
from app.brokers.margin_equity.models import (
    BorrowQuote,
    CorporateAction,
    MarginAccountState,
    MarginInstrument,
    ShortabilityStatus,
    ShortDividendLiability,
)
from app.core.types import AssetClass


class MarginEquityBrokerBase(BrokerBase):
    """Abstract base for a margin/shorting equity broker connector."""

    asset_class: AssetClass = AssetClass.EQUITY

    # -- account / buying power -------------------------------------------------
    @abstractmethod
    def get_margin_account(self) -> MarginAccountState: ...

    @abstractmethod
    def get_margin_buying_power(self) -> float: ...

    @abstractmethod
    def get_maintenance_margin(self) -> float:
        """Current maintenance requirement across the book (long + short)."""

    @abstractmethod
    def get_margin_interest_rate(self) -> float:
        """Annualized margin interest rate (bps) on debit balances."""

    # -- borrow / shortability --------------------------------------------------
    @abstractmethod
    def get_borrow_quote(self, symbol: str) -> BorrowQuote:
        """Stock-loan terms: availability, borrow fee, hard-to-borrow, locate."""

    @abstractmethod
    def is_shortable(self, symbol: str) -> ShortabilityStatus:
        """Whether `symbol` can be shorted now, plus SSR / locate state."""

    @abstractmethod
    def request_locate(self, symbol: str, quantity: float) -> bool:
        """Obtain a locate for `quantity` shares (where the venue requires one).
        Returns True if granted. Default brokers without locates return True."""

    # -- corporate actions / short liabilities ----------------------------------
    @abstractmethod
    def get_corporate_actions(self, symbols: list[str] | None = None) -> list[CorporateAction]:
        """Pending splits/dividends/spinoffs affecting open positions."""

    @abstractmethod
    def get_short_dividend_liabilities(self) -> list[ShortDividendLiability]:
        """Dividends owed to lenders on short positions held over ex-date."""

    # -- market structure -------------------------------------------------------
    @abstractmethod
    def get_margin_instruments(
        self, symbols: list[str] | None = None
    ) -> list[MarginInstrument]: ...

    # -- shared, non-abstract validation ---------------------------------------
    def can_short(self, symbol: str, quantity: float) -> tuple[bool, str]:
        """Composite shortability check used before placing a short:
        capability + shortable flag + SSR + locate + borrow availability."""
        if not self.capabilities.shorting:
            return False, f"{self.name}: shorting not enabled in capabilities"
        status = self.is_shortable(symbol)
        if not status.shortable:
            return False, f"{symbol}: not shortable ({status.reason or 'no inventory'})"
        if status.ssr_active:
            # SSR does not forbid shorting outright; it forbids hitting the bid.
            # Surface it so the executor uses an at-or-above-best limit.
            pass
        quote = self.get_borrow_quote(symbol)
        if quote.available_shares < quantity:
            return False, (f"{symbol}: borrow inventory {quote.available_shares} "
                           f"< requested {quantity}")
        if quote.locate_required and not self.request_locate(symbol, quantity):
            return False, f"{symbol}: locate not granted"
        return True, ""
