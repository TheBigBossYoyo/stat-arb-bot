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


def covid_crash_rebound(close: pd.DataFrame, *, crash: float = -0.34, rebound: float = 0.25,
                        at_frac: float = 0.82, crash_bars: int = 20,
                        rebound_bars: int = 40) -> pd.DataFrame:
    """A 2020-style V: a fast broad crash over `crash_bars`, then a sharp rebound
    over `rebound_bars`. Tests both the drawdown AND the long-only book's ability
    to get re-invested into the recovery (the regime filter's whipsaw risk)."""
    out = close.copy()
    n = len(close)
    start = max(1, int(n * at_frac))
    end_crash = min(n, start + crash_bars)
    end_reb = min(n, end_crash + rebound_bars)
    if end_crash <= start:
        return out
    crash_path = np.linspace(0.0, crash, end_crash - start)
    out.iloc[start:end_crash] = close.iloc[start:end_crash].to_numpy() * (1.0 + crash_path)[:, None]
    floor = out.iloc[end_crash - 1]
    if end_reb > end_crash:
        reb_path = np.linspace(0.0, rebound, end_reb - end_crash)
        out.iloc[end_crash:end_reb] = floor.to_numpy() * (1.0 + reb_path)[:, None]
        tail = out.iloc[end_reb - 1] / close.iloc[end_reb - 1] if end_reb < n else None
        if tail is not None:
            out.iloc[end_reb:] = close.iloc[end_reb:].to_numpy() * tail.to_numpy()
    return out


def sustained_bear(close: pd.DataFrame, *, total: float = -0.45,
                   window_frac: float = 0.25) -> pd.DataFrame:
    """A 2008-style grinding bear: a deep, sustained drawdown spread over a long
    trailing window (not a single gap), the regime in which a long book bleeds."""
    out = close.copy()
    n = len(close)
    sl = _window_slice(n, window_frac)
    k = n - sl.start
    path = np.linspace(0.0, total, k)
    out.iloc[sl] = close.iloc[sl].to_numpy() * (1.0 + path)[:, None]
    out.iloc[sl.stop:] = close.iloc[sl.stop:].to_numpy() * (1.0 + total) if sl.stop < n else out.iloc[sl.stop:]
    return out


def vol_whipsaw(close: pd.DataFrame, *, window_frac: float = 0.12,
                amp: float = 0.06, period: int = 4) -> pd.DataFrame:
    """Alternating large up/down bars (a whipsaw that punishes a slow-to-react,
    smoothed book and churns a fast one)."""
    out = close.copy()
    n = len(close)
    sl = _window_slice(n, window_frac)
    k = n - sl.start
    osc = amp * np.sign(np.sin(np.arange(k) * 2 * np.pi / period))
    base = close.iloc[sl.start - 1]
    factors = np.cumprod(1.0 + np.outer(osc, np.ones(close.shape[1])), axis=0)
    out.iloc[sl] = base.to_numpy() * factors
    return out


def gap_up_after_crash(close: pd.DataFrame, *, crash: float = -0.18,
                       gap_up: float = 0.10, at_frac: float = 0.86) -> pd.DataFrame:
    """A short crash then a gap UP (a relief rally a de-risked book can miss)."""
    out = market_gap(close, gap=crash, at_frac=at_frac)
    n = len(out)
    j = min(n - 1, int(n * (at_frac + 0.06)))
    out.iloc[j:] = out.iloc[j:].to_numpy() * (1.0 + gap_up)
    return out


def sector_shock(close: pd.DataFrame, members: list[str], *, window_frac: float = 0.1,
                 magnitude: float = -0.35) -> pd.DataFrame:
    """Crash a single sector's names (e.g. a tech-sector blow-up) over the window,
    leaving the rest of the universe alone — tests concentration in one sector."""
    out = close.copy()
    n = len(close)
    sl = _window_slice(n, window_frac)
    k = n - sl.start
    hit = [m for m in members if m in close.columns]
    if not hit or k <= 0:
        return out
    path = np.linspace(0.0, magnitude, k)
    out.loc[out.index[sl], hit] = close.loc[close.index[sl], hit].to_numpy() * (1.0 + path)[:, None]
    out.loc[out.index[sl.stop:], hit] = (
        close.loc[close.index[sl.stop:], hit].to_numpy() * (1.0 + magnitude)
        if sl.stop < n else out.loc[out.index[sl.stop:], hit])
    return out


SCENARIOS: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = {
    "momentum_crash": lambda c: momentum_crash(c),
    "correlation_spike": lambda c: correlation_spike(c),
    "vol_spike": lambda c: vol_spike(c),
    "market_gap": lambda c: market_gap(c),
    "short_squeeze": lambda c: short_squeeze(c),
}


def long_only_scenarios(sectors: dict[str, str] | None = None) -> dict:
    """The expanded crisis suite for a long-only book: the base scenarios plus a
    synthetic 2008 grinding bear, a 2020 COVID crash/rebound, a vol whipsaw, a
    gap-up-after-crash relief rally, and (when sectors are known) a tech-sector
    crash and a broad sector-rotation shock."""
    scen: dict[str, Callable[[pd.DataFrame], pd.DataFrame]] = dict(SCENARIOS)
    scen.update({
        "covid_crash_rebound": lambda c: covid_crash_rebound(c),
        "sustained_bear_2008": lambda c: sustained_bear(c),
        "vol_whipsaw": lambda c: vol_whipsaw(c),
        "gap_up_after_crash": lambda c: gap_up_after_crash(c),
    })
    if sectors:
        by_sector: dict[str, list[str]] = {}
        for sym, sec in sectors.items():
            by_sector.setdefault(sec, []).append(sym)
        tech = by_sector.get("tech") or by_sector.get("technology")
        if tech:
            scen["tech_sector_crash"] = lambda c, m=tech: sector_shock(c, m)
        biggest = max(by_sector.values(), key=len) if by_sector else None
        if biggest:
            scen["sector_rotation_shock"] = lambda c, m=biggest: sector_shock(
                c, m, window_frac=0.12, magnitude=-0.25)
    return scen


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
