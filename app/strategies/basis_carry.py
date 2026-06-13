"""Basis carry (cash-and-carry) as a futures weight function (Path B).

When a perp trades rich to spot (positive basis), short the perp and collect the
convergence as it pulls back toward index; when it trades cheap (negative basis),
go long. Enter when annualized basis clears a threshold, exit when it normalizes
(hysteresis), and model convergence risk by sizing inversely to basis volatility.

Consumes the basis panel via `aux["basis"]` (fractional perp-vs-spot basis,
windowed to the engine's close window).
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel


class BasisCarryConfig(BaseModel):
    entry_bps: float = 30.0            # |annualized basis| to enter (bps)
    exit_bps: float = 10.0             # basis through which to exit (hysteresis)
    bars_per_year: float = 365.0
    top_k: int = 3
    gross_target: float = 1.0
    max_weight: float = 0.34
    vol_window: int = 20               # basis-vol window for convergence-risk sizing


class BasisCarry:
    wants_aux = True

    def __init__(self, config: BasisCarryConfig | None = None) -> None:
        self.cfg = config or BasisCarryConfig()
        self._held: dict[str, int] = {}

    def __call__(self, close_window: pd.DataFrame, aux: dict | None = None) -> pd.Series:
        cfg = self.cfg
        zero = pd.Series(0.0, index=close_window.columns)
        if not aux or "basis" not in aux or aux["basis"] is None:
            return zero
        basis = aux["basis"]
        if len(basis) < cfg.vol_window + 1:
            return zero
        latest = basis.iloc[-1] * cfg.bars_per_year * 1e4      # annualized bps
        latest = latest.reindex(close_window.columns)
        basis_vol = (basis.iloc[-cfg.vol_window:].std() * cfg.bars_per_year * 1e4).replace(0.0, pd.NA)
        # hysteresis: hold while |basis| > exit; (re)enter when |basis| > entry
        held = {s for s, d in self._held.items()
                if s in latest.index and abs(float(latest.get(s, 0) or 0)) > cfg.exit_bps}
        candidates = latest.dropna().abs().sort_values(ascending=False)
        for sym in candidates.index:
            if len(held) >= cfg.top_k:
                break
            if abs(float(latest[sym])) > cfg.entry_bps:
                held.add(sym)
        w = pd.Series(0.0, index=close_window.columns)
        for sym in held:
            # short rich basis (positive), long cheap basis (negative);
            # size inversely to basis vol (convergence-risk control)
            sign = -1.0 if float(latest[sym]) > 0 else 1.0
            vol = float(basis_vol.get(sym, 1.0) or 1.0)
            w[sym] = sign / max(vol, 1.0)
        self._held = {s: 1 for s in held}
        gross = float(w.abs().sum())
        if gross == 0:
            return zero
        w = (w / gross * cfg.gross_target).clip(-cfg.max_weight, cfg.max_weight)
        g = float(w.abs().sum())
        return w * (cfg.gross_target / g) if g > 0 else w


def make_basis_carry_weight_fn(config: BasisCarryConfig | None = None) -> BasisCarry:
    return BasisCarry(config)
