"""Capital allocation across pairs (Phase 6).

Inverse-spread-volatility weighting: quieter spreads get more capital, capped
per pair so no single relationship dominates. Output feeds the backtest
engine's per-pair target percentages.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.research.pair_selection import SelectedPair


class AllocationConfig(BaseModel):
    total_target_pct: float = 0.30   # gross capital fraction across all pairs
    max_per_pair_pct: float = 0.10
    min_per_pair_pct: float = 0.02


def inverse_vol_pair_weights(
    pairs: list[SelectedPair],
    config: AllocationConfig | None = None,
) -> dict[str, float]:
    """pair_key -> target fraction of equity (per leg sizing input).

    Weights are proportional to 1/spread_std, scaled to the total target,
    then clipped to [min, max] per pair. After clipping the total may be
    below target (never above) — capital is deliberately left on the table
    rather than concentrated.
    """
    cfg = config or AllocationConfig()
    if not pairs:
        return {}
    inverse_vol = {p.key: 1.0 / max(p.spread_std, 1e-6) for p in pairs}
    total = sum(inverse_vol.values())
    raw = {k: v / total * cfg.total_target_pct for k, v in inverse_vol.items()}
    return {
        k: float(min(max(v, cfg.min_per_pair_pct), cfg.max_per_pair_pct))
        for k, v in raw.items()
    }
