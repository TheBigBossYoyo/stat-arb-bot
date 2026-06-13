"""Point-in-time universe interface + survivorship perturbation (Phase 3).

The static universes are **survivorship-biased**: they are today's survivors
backtested into the past (a delisted 2021 large cap is simply absent, and the
winners that grew INTO the top-50 are present for years before they belonged).
The true fix is index-constituent history — a point-in-time membership feed.
We do not have one, so this module does two honest things:

1. defines the **interface** a PIT provider would implement, with the static
   universe explicitly flagged biased (so nothing silently treats it as PIT);
2. provides **perturbation** tools to *bound* the bias: if a strategy's result
   is stable when names are randomly dropped/swapped, its edge does not hinge on
   the exact survivor set, and the survivorship risk is bounded even without PIT
   data. That bound is reported by `survivorship-stress`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import numpy as np

from app.data.universe import get_universe, get_universe_meta


class PointInTimeProvider(Protocol):
    """A real PIT provider returns index membership AS OF a date."""

    def members_as_of(self, index: str, date: datetime) -> list[str]: ...


@dataclass
class StaticSurvivorProvider:
    """The only provider we actually have: a static, survivor-selected list.
    `members_as_of` returns the same names for every date and is flagged biased
    so callers cannot mistake it for true point-in-time membership."""

    universe: str

    @property
    def biased(self) -> bool:
        return get_universe_meta(self.universe).survivorship != "point_in_time"

    def members_as_of(self, index: str, date: datetime) -> list[str]:  # noqa: ARG002
        return get_universe(self.universe)


class UnavailablePITProvider:
    """Placeholder for an index-constituent-history provider (not integrated).
    Calling it fails loudly — we will not fake point-in-time membership."""

    def members_as_of(self, index: str, date: datetime):  # noqa: ARG002
        raise NotImplementedError(
            "No point-in-time constituent history is integrated. Survivorship is "
            "BOUNDED via perturbation (survivorship-stress), not eliminated. Wire a "
            "real constituent feed (e.g. an index-membership dataset) to remove it.")


def perturbed_universes(universe: str, n: int, drop_frac: float = 0.2,
                        seed: int = 7) -> list[list[str]]:
    """`n` random sub-universes, each dropping ~`drop_frac` of the names.

    A strategy whose performance is stable across these is not relying on the
    exact survivor set — the core of the survivorship bound."""
    names = get_universe(universe)
    rng = np.random.default_rng(seed)
    keep = max(3, int(round(len(names) * (1.0 - drop_frac))))
    out: list[list[str]] = []
    for _ in range(n):
        out.append(sorted(rng.choice(names, size=keep, replace=False).tolist()))
    return out
