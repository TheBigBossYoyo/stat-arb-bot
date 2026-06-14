"""Trading 212 instrument metadata cache (Phase 5).

The official Public API exposes the full Invest/ISA instrument list at
`/equity/metadata/instruments`. It is large and changes rarely, so we cache it on
disk (JSON) with a TTL and expose the few lookups the order path needs:

* is a symbol TRADABLE on Invest/ISA at all (offered + an equity, never a CFD),
* does it support FRACTIONAL shares (else whole shares only),
* its MINIMUM trade quantity and price/quantity increments.

Offline-safe: when no live client is supplied (or the fetch fails) it falls back
to conservative synthetic stubs so shadow planning still works without network
or keys. The cache NEVER places orders — it is pure market structure.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from app.brokers.models import Instrument
from app.core.logging import get_logger
from app.core.types import AssetClass

log = get_logger(__name__)

DEFAULT_TTL_SECONDS = 24 * 3600


@dataclass
class InstrumentCache:
    """Symbol -> Instrument, with tradability/fractional/min-order lookups."""

    instruments: dict[str, Instrument]
    source: str = "synthetic"        # synthetic | demo | cache
    fetched_at: float = 0.0

    # -- lookups ---------------------------------------------------------------

    def get(self, symbol: str) -> Instrument | None:
        return self.instruments.get(symbol)

    def is_tradable(self, symbol: str) -> tuple[bool, str]:
        inst = self.instruments.get(symbol)
        if inst is None:
            return False, "not offered on Trading 212 Invest/ISA"
        if inst.asset_class is not AssetClass.EQUITY:
            return False, f"asset class {inst.asset_class.value} is not Invest/ISA-eligible (no CFDs)"
        if inst.shortable:  # defensive: Invest/ISA instruments are never shortable
            return False, "instrument flagged shortable — refusing (no shorting on Invest/ISA)"
        return True, ""

    def is_fractional(self, symbol: str) -> bool:
        inst = self.instruments.get(symbol)
        return bool(inst and inst.fractional)

    def min_quantity(self, symbol: str) -> float:
        inst = self.instruments.get(symbol)
        return float(inst.min_quantity) if inst else 0.0

    def min_notional(self, symbol: str) -> float:
        inst = self.instruments.get(symbol)
        return float(inst.min_notional) if inst else 0.0

    def as_dict(self) -> dict[str, Instrument]:
        return dict(self.instruments)


def synthetic_instruments(symbols: list[str]) -> dict[str, Instrument]:
    """Conservative offline Invest/ISA stubs: every name an equity, fractional,
    penny tick, $1 minimum order — matches Trading 212's real defaults closely
    enough for shadow planning. The demo connector replaces these with the real
    list when keys are configured."""
    return {
        s: Instrument(broker="trading212", symbol=s, asset_class=AssetClass.EQUITY,
                      tick_size=0.01, step_size=0.0001, min_quantity=0.0,
                      min_notional=1.0, fractional=True, shortable=False)
        for s in symbols
    }


def _cache_path(runtime_dir: Path) -> Path:
    return Path(runtime_dir) / "trading212_instruments.json"


def load_instrument_cache(
    symbols: list[str],
    *,
    client=None,
    runtime_dir: Path | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    refresh: bool = False,
) -> InstrumentCache:
    """Return an InstrumentCache for `symbols`.

    Priority: a fresh disk cache (within TTL) -> the live `client` (demo) -> the
    on-disk cache regardless of age -> synthetic stubs. Any failure degrades to
    the next source; it never raises, so the order path always has metadata.
    """
    path = _cache_path(runtime_dir) if runtime_dir else None

    if path and path.exists() and not refresh:
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - blob.get("fetched_at", 0) < ttl_seconds:
                insts = {k: Instrument(**v) for k, v in blob["instruments"].items()
                         if not symbols or k in symbols}
                if insts:
                    return InstrumentCache(insts, source="cache",
                                           fetched_at=blob.get("fetched_at", 0))
        except Exception as exc:  # noqa: BLE001 - corrupt cache is non-fatal
            log.warning("trading212 instrument cache unreadable (%s); refetching", exc)

    if client is not None:
        try:
            fetched = {i.symbol: i for i in client.get_instruments(symbols or None)}
            if fetched:
                cache = InstrumentCache(fetched, source="demo", fetched_at=time.time())
                if path:
                    _write_cache(path, cache)
                return cache
        except Exception as exc:  # noqa: BLE001 - network/keys missing -> fall back
            log.warning("trading212 instrument fetch failed (%s); using fallback", exc)

    if path and path.exists():
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            insts = {k: Instrument(**v) for k, v in blob["instruments"].items()
                     if not symbols or k in symbols}
            if insts:
                return InstrumentCache(insts, source="cache",
                                       fetched_at=blob.get("fetched_at", 0))
        except Exception:  # noqa: BLE001
            pass

    return InstrumentCache(synthetic_instruments(symbols), source="synthetic",
                           fetched_at=time.time())


def _write_cache(path: Path, cache: InstrumentCache) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    blob = {"fetched_at": cache.fetched_at,
            "instruments": {k: v.model_dump() for k, v in cache.instruments.items()}}
    path.write_text(json.dumps(blob, default=str), encoding="utf-8")
