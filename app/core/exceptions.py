"""Exception hierarchy. Everything raised by the app derives from StatArbError."""

from __future__ import annotations


class StatArbError(Exception):
    """Base class for all application errors."""


class ConfigurationError(StatArbError):
    """Invalid or missing configuration."""


class DataQualityError(StatArbError):
    """Historical/live data failed quality checks."""


class BrokerError(StatArbError):
    """Broker API failure (network, HTTP error, malformed response)."""


class BrokerNotEnabledError(BrokerError):
    """A broker connector was used without being enabled/configured."""


class CapabilityError(BrokerError):
    """Requested action is not supported by the broker capability matrix."""


class OrderRejectedError(BrokerError):
    """Order failed validation (precision, min notional, capability, risk)."""


class RiskViolationError(StatArbError):
    """A risk limit blocked the action."""


class KillSwitchActiveError(RiskViolationError):
    """The kill switch is engaged; all order flow is halted."""


class ExecutionError(StatArbError):
    """Order execution failed at runtime (e.g. one leg of a pair)."""


class LiveTradingBlockedError(StatArbError):
    """The live-trading gate refused to enable live order placement."""
