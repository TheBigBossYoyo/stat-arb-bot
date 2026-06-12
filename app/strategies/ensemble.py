"""Multi-strategy risk-parity ensemble (Phase 7).

What multi-strat funds actually sell is not one signal but the COMBINATION:
several lowly-correlated sleeves (mean reversion, momentum, residual
stat-arb), each allocated capital in inverse proportion to its realized
volatility, so no single sleeve dominates portfolio risk. Mean-reversion
sleeves bleed in trends exactly when momentum sleeves print — the blend has
a smoother equity curve than any component.

`RiskParityEnsemble` is a stateful basket WeightFn: the basket engine calls
it in time order at every rebalance, so it can track each sleeve's realized
returns out of its own past weights (no lookahead — weights chosen at the
previous rebalance earn the returns since then) and re-estimate sleeve vols
on the fly. Until enough sleeve history accumulates it falls back to equal
weights.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.backtesting.basket_engine import WeightFn
from app.core.logging import get_logger

log = get_logger(__name__)


class EnsembleConfig(BaseModel):
    vol_window: int = 30          # sleeve-return observations (one per rebalance)
    min_observations: int = 5     # equal-weight until each sleeve has this many
    gross_target: float = 1.0     # cap on combined gross exposure
    max_sleeve_share: float = 0.60  # no sleeve may take more than this risk share
    # performance gate: a sleeve whose trailing return t-stat falls below this
    # gets ZERO allocation until it recovers. Inverse-vol alone keeps funding a
    # consistently losing sleeve — low vol is not the same as positive edge.
    min_sleeve_t: float = -0.5    # set very negative to disable
    # continuous refinement of the same idea: scale each surviving sleeve's
    # inverse-vol share by clip(t_stat / t_stat_scale, 0, 1), so a sleeve is
    # funded in proportion to the EVIDENCE of its edge instead of jumping to
    # full size the moment its t-stat clears the gate. The binary gate funds
    # a low-vol sleeve fully at t = 0.01 and lets it starve a Sharpe-1 sleeve
    # of capital. 0 disables (binary gate only).
    t_stat_scale: float = 0.0
    # sleeve returns are tracked NET of this turnover cost; gross-of-cost
    # tracking made a high-churn sleeve look profitable while its costs were
    # quietly paid by the portfolio (match the basket engine's cost_bps)
    cost_bps: float = 15.0
    # portfolio-level volatility targeting: when the ensemble's own realized
    # vol (annualized) exceeds the target, the whole book is scaled DOWN.
    # It never levers up beyond gross_target — de-risking only. 0 disables.
    target_vol_pct: float = 0.0
    rebalances_per_year: float = 0.0  # annualization of per-rebalance returns
    # multiplies the whole book (sleeves are built around gross 1.0, so the
    # cap alone cannot lever). RESEARCH ONLY: margin and borrow costs are not
    # modeled; turnover costs do scale with it.
    leverage: float = 1.0


class RiskParityEnsemble:
    """Combine sleeve weight functions with inverse-volatility allocations."""

    # accept aux frames from the engine and forward them to sleeves that ask
    wants_aux = True

    def __init__(self, sleeves: dict[str, WeightFn], config: EnsembleConfig | None = None) -> None:
        if not sleeves:
            raise ValueError("ensemble needs at least one sleeve")
        self.sleeves = sleeves
        self.cfg = config or EnsembleConfig()
        self._returns: dict[str, deque[float]] = {
            name: deque(maxlen=self.cfg.vol_window) for name in sleeves
        }
        self._last_weights: dict[str, pd.Series] | None = None
        self._last_ts: pd.Timestamp | None = None
        self._pending_cost: dict[str, float] = dict.fromkeys(sleeves, 0.0)
        self._portfolio_returns: deque[float] = deque(maxlen=self.cfg.vol_window)
        self._last_combined: pd.Series | None = None
        self._pending_portfolio_cost = 0.0

    def sleeve_allocations(self) -> dict[str, float]:
        """Current inverse-vol risk shares among sleeves passing the trailing
        performance gate. Sums to 1 (equal until warmed up) — or to 0 when every
        sleeve is bleeding, in which case the ensemble stands aside in cash."""
        cfg = self.cfg
        names = list(self.sleeves)
        if any(len(self._returns[n]) < cfg.min_observations for n in names):
            return {n: 1.0 / len(names) for n in names}
        inv_vol = {}
        for n in names:
            rets = np.fromiter(self._returns[n], dtype=float)
            vol = float(np.std(rets, ddof=1))
            if vol <= 1e-12:
                inv_vol[n] = 0.0
                continue
            t_stat = float(rets.mean()) / (vol / np.sqrt(len(rets)))
            if t_stat < cfg.min_sleeve_t:
                inv_vol[n] = 0.0
            elif cfg.t_stat_scale > 0:
                inv_vol[n] = (1.0 / vol) * min(max(t_stat, 0.0) / cfg.t_stat_scale, 1.0)
            else:
                inv_vol[n] = 1.0 / vol
        total = sum(inv_vol.values())
        if total <= 0:
            return {n: 0.0 for n in names}     # nothing has edge: hold cash
        shares = {n: v / total for n, v in inv_vol.items()}
        # cap any sleeve's share and re-normalize the remainder
        capped = {n: min(s, cfg.max_sleeve_share) for n, s in shares.items()}
        total = sum(capped.values())
        return {n: s / total for n, s in capped.items()}

    def _update_sleeve_returns(self, close_window: pd.DataFrame) -> None:
        """Realize each sleeve's return since the previous rebalance using the
        weights it held over that span (decided then — no lookahead)."""
        if self._last_weights is None or self._last_ts is None:
            return
        if self._last_ts not in close_window.index:
            return  # window slid past the last rebalance (gap); skip this sample
        period = close_window.loc[self._last_ts:]
        if len(period) < 2:
            return
        asset_returns = period.iloc[-1] / period.iloc[0] - 1.0
        for name, weights in self._last_weights.items():
            sleeve_ret = float((weights * asset_returns.reindex(weights.index).fillna(0.0)).sum())
            self._returns[name].append(sleeve_ret - self._pending_cost[name])
        if self._last_combined is not None:
            w = self._last_combined
            port_ret = float((w * asset_returns.reindex(w.index).fillna(0.0)).sum())
            self._portfolio_returns.append(port_ret - self._pending_portfolio_cost)

    def __call__(
        self, close_window: pd.DataFrame, aux: dict[str, pd.DataFrame] | None = None
    ) -> pd.Series:
        self._update_sleeve_returns(close_window)

        sleeve_weights: dict[str, pd.Series] = {}
        for name, fn in self.sleeves.items():
            if getattr(fn, "wants_aux", False) and aux is not None:
                raw = fn(close_window, aux=aux)
            else:
                raw = fn(close_window)
            w = raw.reindex(close_window.columns).fillna(0.0)
            old = (self._last_weights or {}).get(name)
            turnover = float((w - old).abs().sum()) if old is not None else float(w.abs().sum())
            self._pending_cost[name] = turnover * self.cfg.cost_bps / 10_000.0
            sleeve_weights[name] = w
        self._last_weights = sleeve_weights
        self._last_ts = close_window.index[-1]

        allocations = self.sleeve_allocations()
        combined = pd.Series(0.0, index=close_window.columns)
        for name, w in sleeve_weights.items():
            combined = combined.add(allocations[name] * w, fill_value=0.0)

        combined *= self._vol_target_scalar() * self.cfg.leverage
        gross = float(combined.abs().sum())
        max_gross = self.cfg.gross_target * self.cfg.leverage
        if gross > max_gross and gross > 0:
            combined *= max_gross / gross
        old = self._last_combined
        turnover = float((combined - old).abs().sum()) if old is not None else float(combined.abs().sum())
        self._pending_portfolio_cost = turnover * self.cfg.cost_bps / 10_000.0
        self._last_combined = combined.copy()
        return combined

    def _vol_target_scalar(self) -> float:
        """<= 1.0 multiplier bringing realized ensemble vol down to the target."""
        cfg = self.cfg
        if cfg.target_vol_pct <= 0 or cfg.rebalances_per_year <= 0:
            return 1.0
        if len(self._portfolio_returns) < cfg.min_observations:
            return 1.0
        vol = float(np.std(np.fromiter(self._portfolio_returns, dtype=float), ddof=1))
        if vol <= 1e-12:
            return 1.0
        target = cfg.target_vol_pct / 100.0 / np.sqrt(cfg.rebalances_per_year)
        return float(min(1.0, target / vol))
