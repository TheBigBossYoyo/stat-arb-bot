"""Pair discovery: correlation prefilter -> cointegration tests -> ranking."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.core.logging import get_logger
from app.research.cointegration import CointegrationResult, cointegration_test

log = get_logger(__name__)


class PairSelectionConfig(BaseModel):
    min_correlation: float = 0.75
    max_eg_pvalue: float = 0.05
    max_adf_pvalue: float = 0.05
    min_half_life_bars: float = 3.0
    max_half_life_bars: float = 100.0
    min_spread_std: float = 0.0015
    min_observations: int = 500
    max_pairs: int = 10
    max_missing_pct: float = 5.0


@dataclass
class SelectedPair:
    symbol_a: str
    symbol_b: str
    beta: float
    alpha: float
    correlation: float
    eg_pvalue: float
    adf_pvalue: float
    half_life: float
    spread_std: float
    score: float

    @property
    def key(self) -> str:
        return f"{self.symbol_a}|{self.symbol_b}"


def _score(result: CointegrationResult, cfg: PairSelectionConfig) -> float:
    """Rank pairs: stronger stationarity and a half-life near the sweet spot win.

    -log10(p) rewards stationarity strength; the half-life term peaks in the
    middle of the allowed band (too fast = noise/costs, too slow = capital drag).
    """
    stat_strength = -np.log10(max(result.eg_pvalue, 1e-12)) - np.log10(max(result.adf_pvalue, 1e-12))
    hl_mid = (cfg.min_half_life_bars + cfg.max_half_life_bars) / 2
    hl_span = (cfg.max_half_life_bars - cfg.min_half_life_bars) / 2
    hl_score = max(0.0, 1.0 - abs(result.half_life - hl_mid) / hl_span) if hl_span > 0 else 0.0
    return float(stat_strength + 2.0 * hl_score)


class PairSelector:
    def __init__(self, config: PairSelectionConfig | None = None) -> None:
        self.config = config or PairSelectionConfig()

    def select(self, log_close: pd.DataFrame) -> list[SelectedPair]:
        """Find tradeable pairs in a wide log-price frame (columns = symbols)."""
        cfg = self.config

        # drop symbols with too much missing data, then align
        keep = [
            c for c in log_close.columns
            if log_close[c].isna().mean() * 100 <= cfg.max_missing_pct
        ]
        data = log_close[keep].dropna(how="any")
        if len(data) < cfg.min_observations:
            log.warning(
                "only %d aligned observations (< %d) — pair selection skipped",
                len(data), cfg.min_observations,
            )
            return []

        returns = data.diff().dropna()
        corr = returns.corr()

        candidates: list[tuple[str, str, float]] = []
        for sym_a, sym_b in combinations(data.columns, 2):
            rho = float(corr.loc[sym_a, sym_b])
            if rho >= cfg.min_correlation:
                candidates.append((sym_a, sym_b, rho))
        log.info("correlation prefilter: %d candidate pairs (rho >= %.2f)",
                 len(candidates), cfg.min_correlation)

        selected: list[SelectedPair] = []
        for sym_a, sym_b, rho in candidates:
            # EG is asymmetric: test both orientations, keep the stronger one.
            best: tuple[str, str, CointegrationResult] | None = None
            for a, b in ((sym_a, sym_b), (sym_b, sym_a)):
                try:
                    result = cointegration_test(data[a].to_numpy(), data[b].to_numpy())
                except ValueError:
                    continue
                if best is None or result.eg_pvalue < best[2].eg_pvalue:
                    best = (a, b, result)
            if best is None:
                continue
            a, b, result = best
            if not result.is_tradeable(
                max_eg_pvalue=cfg.max_eg_pvalue,
                max_adf_pvalue=cfg.max_adf_pvalue,
                min_half_life=cfg.min_half_life_bars,
                max_half_life=cfg.max_half_life_bars,
                min_spread_std=cfg.min_spread_std,
            ):
                continue
            selected.append(
                SelectedPair(
                    symbol_a=a,
                    symbol_b=b,
                    beta=result.beta,
                    alpha=result.alpha,
                    correlation=rho,
                    eg_pvalue=result.eg_pvalue,
                    adf_pvalue=result.adf_pvalue,
                    half_life=result.half_life,
                    spread_std=result.spread_std,
                    score=_score(result, cfg),
                )
            )

        selected.sort(key=lambda p: p.score, reverse=True)
        if len(selected) > cfg.max_pairs:
            selected = selected[: cfg.max_pairs]
        log.info("selected %d pairs: %s", len(selected), [p.key for p in selected])
        return selected
