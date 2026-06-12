"""WebSocket fan-out for live dashboard updates.

Channels: system, portfolio, risk, orders, trades, signals, brokers, logs.
A background task pushes fresh snapshots every few seconds to channels with
subscribers; the frontend reconnects automatically on drop.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.core.logging import get_logger

log = get_logger(__name__)

CHANNELS = {"system", "portfolio", "risk", "orders", "trades", "signals", "brokers", "logs"}


class ConnectionManager:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = {c: set() for c in CHANNELS}

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._subscribers[channel].add(websocket)

    def disconnect(self, channel: str, websocket: WebSocket) -> None:
        self._subscribers[channel].discard(websocket)

    def has_subscribers(self, channel: str) -> bool:
        return bool(self._subscribers.get(channel))

    async def broadcast(self, channel: str, payload: Any) -> None:
        message = json.dumps({"channel": channel, "data": payload}, default=str)
        dead: list[WebSocket] = []
        for websocket in self._subscribers.get(channel, ()):
            try:
                await websocket.send_text(message)
            except Exception:  # noqa: BLE001 — drop broken sockets
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(channel, websocket)


async def channel_endpoint(manager: ConnectionManager, channel: str, websocket: WebSocket) -> None:
    if channel not in CHANNELS:
        await websocket.close(code=4404)
        return
    await manager.connect(channel, websocket)
    try:
        while True:
            # client messages are ignored (read-only stream); this keeps the
            # connection alive and lets us detect disconnects
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(channel, websocket)


async def snapshot_broadcaster(manager: ConnectionManager, service: Any,
                               interval_seconds: float = 5.0) -> None:
    """Periodic push of system/risk/portfolio snapshots."""
    while True:
        try:
            if manager.has_subscribers("system"):
                await manager.broadcast("system", service.system_status().model_dump(mode="json"))
            if manager.has_subscribers("risk"):
                await manager.broadcast("risk", service.risk_status().model_dump(mode="json"))
            if manager.has_subscribers("portfolio"):
                await manager.broadcast(
                    "portfolio", service.portfolio_summary().model_dump(mode="json")
                )
        except Exception as exc:  # noqa: BLE001 — the loop must survive
            log.warning("snapshot broadcast failed: %s", exc)
        await asyncio.sleep(interval_seconds)
