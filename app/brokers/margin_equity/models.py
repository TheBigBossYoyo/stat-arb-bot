"""Data models for a margin / shorting equity broker (Path C).

The market-neutral flagship needs a venue that can actually *short* equities on
*margin* — something no connected broker does (Binance spot/Invest/ISA cannot
short; CFDs are off-limits). Rather than hardcode one future broker, Path C
defines the interface and the data it must expose. These models capture the
information a shorting book genuinely depends on and that a long-only model
never had to: borrow availability and cost, locate requirements, short-sale
restrictions, maintenance margin, and the short-dividend liability.

Nothing here connects to anything. It is the contract an official margin broker
(e.g. Interactive Brokers / Alpaca via their *official* APIs) would implement.
No unofficial endpoints, ever.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.brokers.models import Position
from app.core.types import AssetClass


class MarginInstrument(BaseModel):
    """An equity instrument with the margin/shorting attributes a long-only
    Instrument never carried."""

    broker: str
    symbol: str
    asset_class: AssetClass = AssetClass.EQUITY
    tick_size: float = 0.01
    step_size: float = 1.0           # most margin brokers trade whole shares short
    min_quantity: float = 0.0
    fractional: bool = False         # fractional shorting is rare
    marginable: bool = True          # can be bought on margin
    shortable: bool = False          # can be sold short at all
    easy_to_borrow: bool = False     # on the broker's ETB list (cheap, no locate)
    maintenance_margin_pct: float = 0.30   # maintenance requirement (long)
    short_maintenance_pct: float = 0.30    # maintenance requirement (short)


class BorrowQuote(BaseModel):
    """Stock-loan terms for shorting one name — the cost the flagship's short
    leg pays in reality and the audit flagged as only blended-modeled."""

    symbol: str
    available_shares: float = 0.0          # locatable inventory (0 = none ⇒ cannot short)
    borrow_rate_bps_annual: float = 0.0    # annualized borrow fee on short notional
    is_hard_to_borrow: bool = False
    locate_required: bool = False          # must obtain a locate before shorting
    rebate_rate_bps_annual: float = 0.0    # cash rebate on collateral (often ~0 retail)
    as_of: datetime | None = None

    @property
    def shortable(self) -> bool:
        return self.available_shares > 0


class ShortabilityStatus(BaseModel):
    """Whether a name can be shorted right now, and under what restriction."""

    symbol: str
    shortable: bool = False
    ssr_active: bool = False               # Reg SHO uptick rule in force today
    locate_required: bool = False
    reason: str = ""


class MarginAccountState(BaseModel):
    """Account snapshot for a margin/shorting book."""

    broker: str
    currency: str = "USD"
    cash: float = 0.0
    equity: float = 0.0                    # net liquidation value
    long_market_value: float = 0.0
    short_market_value: float = 0.0        # positive magnitude of shorts
    margin_buying_power: float = 0.0       # how much can still be bought on margin
    maintenance_margin: float = 0.0        # current maintenance requirement
    excess_liquidity: float = 0.0          # equity - maintenance (cushion to a call)
    sma: float = 0.0                       # Reg-T special memorandum account
    margin_interest_bps_annual: float = 0.0
    positions: list[Position] = Field(default_factory=list)

    @property
    def gross_leverage(self) -> float:
        gross = self.long_market_value + self.short_market_value
        return gross / self.equity if self.equity > 0 else 0.0

    @property
    def margin_call(self) -> bool:
        return self.excess_liquidity < 0


class ShortDividendLiability(BaseModel):
    """When short over an ex-dividend date, the borrower OWES the dividend to the
    lender (a real cost the long-only model never had). Tracked per name."""

    symbol: str
    ex_date: datetime
    dividend_per_share: float
    short_quantity: float

    @property
    def liability(self) -> float:
        return self.dividend_per_share * abs(self.short_quantity)


class CorporateAction(BaseModel):
    """Splits / dividends / spinoffs the broker must apply to open positions —
    on a short book these change the liability, not just the price."""

    symbol: str
    action_type: str                       # split | dividend | spinoff | merger
    ex_date: datetime
    ratio: float = 1.0                     # split ratio
    cash_per_share: float = 0.0            # dividend / special cash
