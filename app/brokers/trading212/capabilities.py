"""Trading 212 capability matrix.

The official Public API (https://docs.trading212.com/api) supports Invest and
Stocks ISA *equity* accounts only:

  * CFDs:          UNSUPPORTED — not exposed by the official API. We will not
                   trade CFDs via scraping, browser automation or any
                   reverse-engineered endpoint, ever.
  * Short selling: UNSUPPORTED on Invest/ISA accounts.
  * Margin:        UNSUPPORTED.

These facts are encoded in config/broker_capabilities.yaml and enforced by
the risk manager before any order is created.
"""

from __future__ import annotations

from app.brokers.base import BrokerCapabilities, load_capabilities

UNSUPPORTED_PRODUCTS = ("cfd", "short_selling", "margin", "leverage")


def trading212_capabilities() -> BrokerCapabilities:
    return load_capabilities()["trading212"]


def assert_no_cfd(asset_class: str) -> None:
    from app.core.exceptions import CapabilityError

    if asset_class == "cfd":
        raise CapabilityError(
            "CFDs are not supported by the official Trading 212 Public API. "
            "This system will not trade CFDs through unofficial means."
        )
