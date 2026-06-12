"""Trading 212 Public API authentication.

HTTP Basic Authentication: API key as username, API secret as password
(verified against https://docs.trading212.com/api, June 2026).

Base URLs:
  demo: https://demo.trading212.com/api/v0
  live: https://live.trading212.com/api/v0   (only with the live-trading gate)
"""

from __future__ import annotations

import base64

BASE_URLS = {
    "demo": "https://demo.trading212.com/api/v0",
    "live": "https://live.trading212.com/api/v0",
}


def basic_auth_header(api_key: str, api_secret: str) -> dict[str, str]:
    token = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def rate_limit_state(headers: dict[str, str]) -> dict[str, int | None]:
    """Parse Trading 212 x-ratelimit-* response headers."""

    def _get(name: str) -> int | None:
        value = headers.get(name)
        return int(value) if value is not None and value.isdigit() else None

    return {
        "limit": _get("x-ratelimit-limit"),
        "period": _get("x-ratelimit-period"),
        "remaining": _get("x-ratelimit-remaining"),
        "reset": _get("x-ratelimit-reset"),
        "used": _get("x-ratelimit-used"),
    }
