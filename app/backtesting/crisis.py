"""Crisis-regime stress + crash-protection research (Phase 4).

The 2021-2026 research window contains the 2022 bear but no 2008/2020-scale
*momentum crash* — momentum's worst case, where beaten-down losers rocket in a
panic rebound and a winners-minus-losers book gets run over. This module injects
synthetic crisis regimes into the historical panel and re-runs a strategy
through them, so a book's tail behaviour is measured rather than assumed.

Scenarios transform the price panel (and aux) over a trailing window:

* **momentum_crash** — Daniel-Moskowitz: rally the recent losers, sell the recent
  winners (the panic-rebound reversal that detonates momentum).
* **correlation_spike** — push every name toward the cross-sectional mean (a
  broad, diversification-killing sell-off).
* **vol_spike** — scale recent returns up (volatility explosion).
* **market_gap** — a single large gap-down bar.
* **liquidity_shock** — gap-down + a fee/slippage multiplier (caller applies cost).
* **short_squeeze** — an extreme rally in the worst-trailing-return names.

Crash protection compares a book with vs without de-risking (trend filter /
market-vol scalar). A protection becomes default ONLY if it improves the crisis
outcome without destroying normal-regime OOS — the acceptance rule.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandas as pd

from app.backtesting.metrics import max_drawdown

RunFn = Callable[[pd.DataFrame, dict | None], pd.Series]   # (close, aux) -> equity


def _window_slice(n: int, frac: float) -> slice:
    k = max(5, int(n * frac))
    return slice(n - k, n)


def momentum_crash(close: pd.DataFrame, *, window_frac: float = 0.1,
                   magnitude: float = 0.5, lookback: int = 60) -> pd.DataFrame:
    """Rally recent losers / sell recent winners over the trailing window."""
    out = close.copy()
    n = len(close)
    sl = _window_slice(n, window_frac)
    k = n - sl.start
    if n <= lookback + k:
        return out
    trailing = close.iloc[sl.start - 1] / close.iloc[sl.start - 1 - lookback] - 1.0
    rank = trailing.rank(pct=True)                 # 1 = winner, 0 = loser
    # daily reversal shock: losers up, winners down, ramped over the window
    shock = (0.5 - rank) * 2.0 * magnitude / k     # per-bar fractional shock
    ramp = np.cumprod(1.0 + np.outer(np.ones(k), shock.to_numpy()), axis=0)
    out.iloc[sl] = close.iloc[sl].to_numpy() * ramp
    return out


def correlation_spike(close: pd.DataFrame, *, window_frac: float = 0.1,
                      blend: float = 0.8, drift: float = -0.03) -> pd.DataFrame:
    """Push returns toward the cross-sectional mean (everything sells together)."""
    out = close.copy()
    n = len(close)
    sl = _window_slice(n, window_frac)
    rets = close.pct_change().fillna(0.0)
    mean_ret = rets.mean(axis=1)
    blended = rets.mul(1 - blend).add(mean_ret * blend + drift / max(1, n - sl.start), axis=0)
    rebuilt = close.copy()
    base = close.iloc[sl.start - 1]
    factors = (1.0 + blended.iloc[sl]).cumprod()
    rebuilt.iloc[sl] = base.to_numpy() * factors.to_numpy()
    out.iloc[sl] = rebuilt.iloc[sl]
    return out


def vol_spike(close: pd.DataFrame, *, window_frac: float = 0.1, mult: float = 3.0) -> pd.DataFrame:
    """Amplify return magnitude over the trailing window."""
    out = close.copy()
    n = len(close)
    sl = _window_slice(n, window_frac)
    rets = close.pct_change().fillna(0.0)
    base = close.iloc[sl.start - 1]
    factors = (1.0 + rets.iloc[sl] * mult).cumprod()
    out.iloc[sl] = base.to_numpy() * factors.to_numpy()
    return out


def market_gap(close: pd.DataFrame, *, gap: float = -0.15, at_frac: float = 0.92) -> pd.DataFrame:
    """A single broad gap-down bar; subsequent prices ride off the gapped level."""
    out = close.copy()
    n = len(close)
    i = max(1, int(n * at_frac))
    out.iloc[i:] = out.iloc[i:].to_numpy() * (1.0 + gap)
    return out


def short_squeeze(close: pd.DataFrame, *, window_frac: float = 0.08,
                  magnitude: float = 0.8, lookback: int = 60) -> pd.DataFrame:
    """Extreme rally in the worst-trailing-return names (squeeze of crowded shorts)."""
    return momentum_crash(close, window_frac=window_frac, magnitude=magnitude,
                          lookback=lookback)


SCENARIOS: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {
    "momentum_crash": lambda c: momentum_crash(c),
    "correlation_spike": lambda c: correlation_spike(c),
    "vol_spike": lambda c: vol_spike(c),
    "market_gap": lambda c: market_gap(c),
    "short_squeeze": lambda c: short_squeeze(c),
}


def _crisis_metrics(equity: pd.Series, window_frac: float = 0.12) -> dict:
    eq = equity.dropna()
    if len(eq) < 5:
        return {"crisis_return_pct": None, "crisis_max_dd_pct": None, "full_return_pct": None}
    sl = _window_slice(len(eq), window_frac)
    crisis = eq.iloc[sl]
    crisis_ret = float(crisis.iloc[-1] / crisis.iloc[0] - 1.0) if len(crisis) > 1 else 0.0
    return {
        "crisis_return_pct": round(100 * crisis_ret, 2),
        "crisis_max_dd_pct": round(100 * max_drawdown(crisis), 2),
        "full_return_pct": round(100 * (eq.iloc[-1] / eq.iloc[0] - 1.0), 2),
        "full_max_dd_pct": round(100 * max_drawdown(eq), 2),
    }


def run_crisis_suite(close: pd.DataFrame, run_fn: RunFn, aux: dict | None = None,
                     scenarios: dict | None = None) -> pd.DataFrame:
    """Run `run_fn` on base data and each crisis transform; return a metrics table.

    `run_fn(close, aux) -> equity`. Scenarios transform close only (aux rides
    along unchanged — a conservative simplification)."""
    scen = scenarios or SCENARIOS
    rows = [{"scenario": "base", **_crisis_metrics(run_fn(close, aux))}]
    for name, transform in scen.items():
        stressed = transform(close)
        rows.append({"scenario": name, **_crisis_metrics(run_fn(stressed, aux))})
    return pd.DataFrame(rows).set_index("scenario")
