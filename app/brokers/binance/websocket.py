"""Binance WebSocket kline streams (Phase 4).

Subscribes to combined kline streams, emits only CLOSED bars as BarEvents,
and reconnects with exponential backoff. The message parser is a pure
function so it is unit-testable without a network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.core.events import BarEvent
from app.core.logging import get_logger

log = get_logger(__name__)

WS_BASE = {
    "live": "wss://stream.binance.com:9443",
    "testnet": "wss://stream.testnet.binance.vision",
}


def stream_url(symbols: list[str], interval: str, mode: str = "live") -> str:
    streams = "/".join(f"{s.lower()}@kline_{interval}" for s in symbols)
    return f"{WS_BASE[mode]}/stream?streams={streams}"


def parse_kline_message(message: dict[str, Any]) -> BarEvent | None:
    """Parse a combined-stream kline payload. Returns None for open bars."""
    data = message.get("data", message)
    if data.get("e") != "kline":
        return None
    k = data["k"]
    if not k.get("x"):          # bar not closed yet
        return None
    return BarEvent(
        ts=datetime.fromtimestamp(k["t"] / 1000, tz=UTC).replace(tzinfo=None),
        symbol=k["s"],
        open=float(k["o"]),
        high=float(k["h"]),
        low=float(k["l"]),
        close=float(k["c"]),
        volume=float(k["v"]),
    )


class BinanceKlineStream:
    """Reconnecting kline stream. Call `await run()` inside an event loop."""

    def __init__(
        self,
        symbols: list[str],
        interval: str,
        on_bar: Callable[[BarEvent], None],
        mode: str = "live",
        max_backoff: float = 60.0,
    ) -> None:
        self.url = stream_url(symbols, interval, mode)
        self.on_bar = on_bar
        self.max_backoff = max_backoff
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install websockets to use the live stream") from exc

        backoff = 1.0
        while not self._stopped:
            try:
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
                    log.info("websocket connected: %s", self.url)
                    backoff = 1.0
                    async for raw in ws:
                        if self._stopped:
                            break
                        bar = parse_kline_message(json.loads(raw))
                        if bar is not None:
                            self.on_bar(bar)
            except asyncio.CancelledError:  # pragma: no cover
                raise
            except Exception as exc:  # noqa: BLE001 — reconnect on any stream error
                log.warning("websocket dropped (%s); reconnecting in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.max_backoff)
