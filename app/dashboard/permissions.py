"""Dashboard permission model.

MVP: a single local operator. The dashboard is READ-ONLY unless
DASHBOARD_CONTROLS_ENABLED=true, in which case the local operator acts as
`admin`. The role ladder below is the production design — wired so adding a
user store later only changes `current_role`.

Roles: viewer < researcher < trader < admin
  viewer      read everything, change nothing
  researcher  + run backtests / pair discovery
  trader      + paper-trading controls (pause/resume, paper kill switch)
  admin       + dangerous actions (deactivate kill switch, anything live)
"""

from __future__ import annotations

from enum import IntEnum

from fastapi import HTTPException

from app.config.settings import Settings

CONFIRM_PHRASES: dict[str, str] = {
    "kill_switch_activate": "ACTIVATE KILL SWITCH",
    "kill_switch_deactivate": "DEACTIVATE KILL SWITCH",
    "flatten_all": "FLATTEN ALL",
    "cancel_all_orders": "CANCEL ALL ORDERS",
    "enable_live": "ENABLE LIVE TRADING",
    "run_demo_paper_day": "RUN DEMO PAPER DAY",
}


class Role(IntEnum):
    VIEWER = 0
    RESEARCHER = 1
    TRADER = 2
    ADMIN = 3


def current_role(settings: Settings) -> Role:
    return Role.ADMIN if settings.dashboard_controls_enabled else Role.VIEWER


def require_role(settings: Settings, minimum: Role) -> None:
    role = current_role(settings)
    if role < minimum:
        raise HTTPException(
            status_code=403,
            detail=(
                f"This action requires the '{minimum.name.lower()}' role. The dashboard is "
                "READ-ONLY: set DASHBOARD_CONTROLS_ENABLED=true to enable controls "
                "(keep the server bound to 127.0.0.1)."
            ),
        )


def require_phrase(action: str, provided: str) -> None:
    expected = CONFIRM_PHRASES.get(action)
    if expected is None:
        raise HTTPException(status_code=400, detail=f"unknown confirmable action '{action}'")
    if provided.strip() != expected:
        raise HTTPException(
            status_code=400,
            detail=f"confirmation phrase mismatch: type exactly \"{expected}\"",
        )
