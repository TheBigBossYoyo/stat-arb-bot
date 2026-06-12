"""PCA residual stat-arb basket strategy (Phase 6, upgraded to Avellaneda-Lee).

Long the assets with the most negative residual s-scores (underperformed
their factor exposure), short the most positive — dollar-neutral by default.

Two upgrades over the naive version, both from Avellaneda & Lee,
"Statistical Arbitrage in the U.S. Equities Market" (2010):

* **OU scoring with a kappa filter** (`ou_s_scores`): each cumulative
  residual is fitted as an Ornstein-Uhlenbeck process and standardized
  against its EQUILIBRIUM distribution; residuals that do not mean-revert,
  or revert too slowly, are excluded instead of traded.
* **Entry/exit hysteresis**: positions OPEN when |s| clears `s_entry` and are
  HELD until s crosses back through `s_exit`. The naive top-k re-ranking
  rebuilt the book at every rebalance — ~2x turnover each time, which at
  15bps/unit compounded to tens of percent of cost bleed per quarter. The
  weight function is therefore stateful (the basket engine calls it in time
  order, so held positions carry across rebalances without lookahead).

For long-only accounts use long_only=True: a relative-rotation mode that is
explicitly NOT market-neutral and must be judged against stricter limits.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.backtesting.basket_engine import WeightFn, rank_weights
from app.research.pca_residuals import (
    ou_s_scores,
    pca_residual_returns,
    s_scores,
    sector_residual_returns,
)


class PCAStatArbConfig(BaseModel):
    n_components: int = 3
    # if > 0, pick components by cumulative explained variance instead of a
    # fixed count (Avellaneda-Lee use ~0.55) — scales with universe breadth
    var_threshold: float = 0.0
    score_window: int = 60
    top_k: int = 2
    gross_target: float = 1.0
    long_only: bool = False
    use_ou_scores: bool = True       # False = legacy stateless top-k re-ranking
    s_entry: float = 1.25            # open when |s| clears this (OU mode only)
    s_exit: float = 0.25             # close when s crosses back through this
    max_residual_half_life: float = 40.0  # bars; slower residuals are excluded
    # sector-relative mode (Avellaneda-Lee's ETF-factor design): when a
    # symbol->sector map is given, residuals come from a leave-one-out
    # sector regression instead of cross-sectional PCA
    sectors: dict[str, str] = {}
    min_sector_size: int = 3


class PCAStatArbWeights:
    """Stateful WeightFn with Avellaneda-Lee entry/exit hysteresis."""

    def __init__(self, config: PCAStatArbConfig | None = None) -> None:
        self.cfg = config or PCAStatArbConfig()
        self._held: dict[str, int] = {}    # symbol -> +1 long / -1 short

    def _update_book(self, scores: pd.Series) -> None:
        cfg = self.cfg
        # exits first: a position is closed when its score reverts through
        # s_exit (or the name dropped out of the mean-reverting set, score 0)
        for symbol, side in list(self._held.items()):
            s = float(scores.get(symbol, 0.0))
            if (side == 1 and s >= -cfg.s_exit) or (side == -1 and s <= cfg.s_exit):
                del self._held[symbol]

        longs = sum(1 for side in self._held.values() if side == 1)
        shorts = sum(1 for side in self._held.values() if side == -1)
        candidates = scores[~scores.index.isin(self._held)]
        for symbol, s in candidates.sort_values().items():     # most negative first
            if longs >= cfg.top_k or s > -cfg.s_entry:
                break
            self._held[symbol] = 1
            longs += 1
        if not cfg.long_only:
            for symbol, s in candidates.sort_values(ascending=False).items():
                if shorts >= cfg.top_k or s < cfg.s_entry:
                    break
                if symbol not in self._held:
                    self._held[symbol] = -1
                    shorts += 1

    def __call__(self, close_window: pd.DataFrame) -> pd.Series:
        cfg = self.cfg
        weights = pd.Series(0.0, index=close_window.columns)
        returns = np.log(close_window).diff().dropna()
        if len(returns) < cfg.score_window + 10 or returns.shape[1] <= cfg.n_components:
            self._held.clear()
            return weights
        if cfg.sectors:
            result = sector_residual_returns(returns, cfg.sectors, cfg.min_sector_size)
        else:
            result = pca_residual_returns(returns, cfg.n_components, cfg.var_threshold)
        scores = ou_s_scores(result.residual_returns, cfg.score_window,
                             max_half_life=cfg.max_residual_half_life)
        self._update_book(scores)

        longs = [s for s, side in self._held.items() if side == 1 and s in weights.index]
        shorts = [s for s, side in self._held.items() if side == -1 and s in weights.index]
        if longs:
            weights[longs] = cfg.gross_target / 2 / len(longs)
        if shorts:
            weights[shorts] = -cfg.gross_target / 2 / len(shorts)
        return weights


def make_pca_weight_fn(config: PCAStatArbConfig | None = None) -> WeightFn:
    cfg = config or PCAStatArbConfig()
    if cfg.use_ou_scores:
        return PCAStatArbWeights(cfg)

    def weight_fn(close_window: pd.DataFrame) -> pd.Series:
        returns = np.log(close_window).diff().dropna()
        if len(returns) < cfg.score_window + 10 or returns.shape[1] <= cfg.n_components:
            return pd.Series(0.0, index=close_window.columns)
        result = pca_residual_returns(returns, cfg.n_components, cfg.var_threshold)
        scores = s_scores(result.residual_returns, cfg.score_window)
        return rank_weights(scores, cfg.top_k, cfg.gross_target, cfg.long_only)

    return weight_fn
