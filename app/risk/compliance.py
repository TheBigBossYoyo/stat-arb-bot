"""Compliance checks: market hours and data staleness.

Crypto trades 24/7; equity orders must land inside the exchange session.
The session window here is the US regular session in UTC — a deliberate
simplification flagged for replacement with a proper trading calendar
(exchange_calendars) when international equities are added in Phase 5+.
"""

from __future__ import annotations

from datetime import datetime, time

from app.core.types import AssetClass

# US regular session in UTC (no DST handling — conservative inner window).
US_EQUITY_OPEN_UTC = time(14, 30)
US_EQUITY_CLOSE_UTC = time(20, 0)


def market_is_open(asset_class: AssetClass | str, ts: datetime) -> bool:
    ac = asset_class.value if isinstance(asset_class, AssetClass) else asset_class
    if ac in ("crypto_spot", "crypto_futures"):
        return True
    if ts.weekday() >= 5:        # Saturday/Sunday
        return False
    return US_EQUITY_OPEN_UTC <= ts.time() <= US_EQUITY_CLOSE_UTC


def order_compliance_issues(
    *,
    asset_class: AssetClass | str,
    ts: datetime,
    last_data_ts: datetime | None,
    max_stale_seconds: float = 120.0,
    reject_outside_market_hours: bool = True,
) -> list[str]:
    """Empty list = compliant. Each entry is a human-readable violation."""
    issues: list[str] = []
    if reject_outside_market_hours and not market_is_open(asset_class, ts):
        issues.append(f"market closed for {asset_class} at {ts.isoformat()}")
    if last_data_ts is None:
        issues.append("no market data received yet")
    else:
        age = (ts - last_data_ts).total_seconds()
        if age > max_stale_seconds:
            issues.append(f"market data stale: {age:.0f}s old (max {max_stale_seconds:.0f}s)")
    return issues
