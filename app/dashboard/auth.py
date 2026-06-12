"""Dashboard authentication.

MVP posture: LOCAL-ONLY. Bind to 127.0.0.1 and do not port-forward. An
optional bearer token (DASHBOARD_TOKEN) adds a second factor for the API;
it is strongly recommended whenever controls are enabled.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from app.config.settings import Settings
from app.core.logging import get_logger

log = get_logger(__name__)


def check_token(settings: Settings, request: Request) -> None:
    """Enforce the bearer token when one is configured. No-op otherwise."""
    if not settings.dashboard_token:
        return
    header = request.headers.get("Authorization", "")
    provided = header.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(provided, settings.dashboard_token):
        raise HTTPException(status_code=401, detail="invalid or missing dashboard token")


def warn_if_public(host: str) -> str | None:
    """Returns a warning string when the bind address is publicly reachable."""
    if host in ("127.0.0.1", "localhost", "::1"):
        return None
    return (
        f"Dashboard binding to {host} — this may be reachable from the network. "
        "The dashboard is designed for LOCAL use; put it behind a VPN/reverse "
        "proxy with auth before exposing it, and set DASHBOARD_TOKEN."
    )
