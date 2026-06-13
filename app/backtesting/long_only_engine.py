"""Long-only backtest engine + benchmark comparison (Path A).

Mechanically the long-only book runs through the same vectorized basket engine
(next-open fills, per-unit costs) — the difference is the *constraints* and the
*benchmark*. A long-only book must clear a higher bar than a market-neutral one:
it is not enough to make money, it has to beat simply buying the index, because
buying SPY is the free alternative an Invest/ISA holder always has.

So this module:

* runs the book with a hard long-only guard (no negative weight, gross <= 1,
  no borrow, no margin — the Trading 212 Invest/ISA reality),
* builds buy-and-hold benchmarks (SPY, QQQ, equal-weight universe),
* computes benchmark-relative metrics: annualized alpha & beta vs SPY, the
  information ratio, tracking error, and the cash-drag the long-only constraint
  imposes.

A long-only variant is only interesting if it beats buy-and-hold on a
RISK-ADJUSTED basis (higher Sharpe / positive alpha), not merely on total
return in a bull market — that is the gate `long-only-readiness` enforces.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.basket_engine import BasketConfig, BasketResult, run_basket_backtest


def _long_only_guard(weight_fn, max_position: float, gross_cap: float):
    """Wrap a weight fn so the executed book is always long-only and un-levered.
    A belt-and-braces guard: the long-only strategies already produce >=0 books,
    but the engine must never execute a short or a levered weight on a no-short,
    no-margin venue regardless of what a sleeve emits."""
    wants_aux = bool(getattr(weight_fn, "wants_aux", False))

    def guarded(close_window, aux=None):
        w = weight_fn(close_window, aux=aux) if wants_aux else weight_fn(close_window)
        w = w.clip(lower=0.0, upper=max_position)
        gross = float(w.sum())
        if gross > gross_cap > 0:
            w = w * (gross_cap / gross)
        return w

    guarded.wants_aux = wants_aux
    return guarded


def _ann_sharpe(returns: pd.Series, ppy: float) -> float:
    r = returns.dropna()
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * math.sqrt(ppy))


def _buy_hold(price: pd.Series, index: pd.DatetimeIndex, starting_cash: float) -> pd.Series:
    """Buy-and-hold equity curve for one instrument aligned to `index`."""
    p = price.reindex(index).ffill().dropna()
    if p.empty:
        return pd.Series(dtype=float)
    return (starting_cash * p / p.iloc[0]).reindex(index).ffill()


def _equal_weight_buy_hold(close: pd.DataFrame, index: pd.DatetimeIndex,
                           starting_cash: float) -> pd.Series:
    """Equal-weight, buy-and-hold the whole universe (the naive diversification
    benchmark a long-only book must beat to justify its turnover)."""
    sub = close.reindex(index).ffill().dropna(how="any")
    if sub.empty:
        return pd.Series(dtype=float)
    norm = sub / sub.iloc[0]
    return (starting_cash * norm.mean(axis=1)).reindex(index).ffill()


@dataclass
class LongOnlyResult:
    book: BasketResult
    benchmarks: dict[str, pd.Series]
    comparison: dict
    bars_per_year: float
    warnings: list[str] = field(default_factory=list)

    @property
    def equity(self) -> pd.Series:
        return self.book.equity

    @property
    def metrics(self) -> dict:
        return self.book.metrics


def run_long_only_backtest(
    close: pd.DataFrame,
    weight_fn,
    config: BasketConfig,
    *,
    aux: dict | None = None,
    open_: pd.DataFrame | None = None,
    benchmarks: dict[str, pd.Series] | None = None,
    max_position: float = 0.20,
    gross_cap: float = 1.0,
) -> LongOnlyResult:
    """Run the long-only book and compare it to buy-and-hold benchmarks.

    `benchmarks` maps name -> raw price series (e.g. {"SPY": spy_close}). The
    equal-weight-universe benchmark is always added. Financing is forced to zero
    (a long-only Invest/ISA book pays neither borrow nor margin)."""
    cfg = config
    # enforce the no-borrow / no-margin reality regardless of what was passed
    if cfg.borrow_bps_annual or cfg.margin_bps_annual:
        cfg = BasketConfig(**{**cfg.__dict__, "borrow_bps_annual": 0.0, "margin_bps_annual": 0.0})

    guarded = _long_only_guard(weight_fn, max_position, gross_cap)
    book = run_basket_backtest(close, guarded, cfg, aux=aux, open_=open_)
    equity = book.equity.dropna()
    # trim the leading flat warmup (equity == starting_cash before the first
    # rebalance) so the book and benchmarks are compared over the SAME active
    # window — otherwise the book is flat while SPY moves and its relative
    # Sharpe/alpha are understated.
    moved = equity[equity != cfg.starting_cash]
    if len(moved):
        equity = equity.loc[moved.index[0]:]
    idx = equity.index
    ppy = cfg.bars_per_year or 252.0
    start_cash = cfg.starting_cash

    curves: dict[str, pd.Series] = {}
    for name, price in (benchmarks or {}).items():
        bh = _buy_hold(price, idx, start_cash)
        if not bh.empty:
            curves[name] = bh
    curves["equal_weight"] = _equal_weight_buy_hold(close, idx, start_cash)

    book_ret = equity.pct_change().dropna()
    comparison: dict = {
        "book_sharpe": round(_ann_sharpe(book_ret, ppy), 3),
        "book_total_return_pct": book.metrics.get("total_return_pct"),
        "book_max_dd_pct": book.metrics.get("max_drawdown_pct"),
        "avg_gross_exposure_pct": book.metrics.get("avg_gross_exposure_pct"),
        "cash_drag_pct": round(100 - float(book.metrics.get("avg_gross_exposure_pct", 0)), 2),
        "benchmarks": {},
    }
    # primary benchmark for alpha/beta is SPY when present, else equal_weight
    primary = "SPY" if "SPY" in curves else "equal_weight"
    for name, curve in curves.items():
        bret = curve.pct_change().reindex(book_ret.index).dropna()
        common = book_ret.reindex(bret.index).dropna()
        bret = bret.reindex(common.index)
        beta = alpha_ann = info_ratio = None
        if len(common) > 5 and bret.std(ddof=1) > 0:
            cov = float(np.cov(common, bret, ddof=1)[0, 1])
            beta = round(cov / float(bret.var(ddof=1)), 3)
            active = common - bret
            te = float(active.std(ddof=1)) * math.sqrt(ppy)
            info_ratio = round(float(active.mean() * ppy) / te, 3) if te > 0 else None
            alpha_ann = round(float(active.mean()) * ppy * 100, 3)
        comparison["benchmarks"][name] = {
            "total_return_pct": round(100 * (curve.iloc[-1] / curve.iloc[0] - 1), 3)
            if len(curve) else None,
            "sharpe": round(_ann_sharpe(curve.pct_change(), ppy), 3),
            "beta": beta,
            "alpha_ann_pct_vs_this": alpha_ann,
            "info_ratio": info_ratio,
            "is_primary": name == primary,
        }
    comparison["primary_benchmark"] = primary
    bench = comparison["benchmarks"].get(primary, {})
    comparison["beats_benchmark_sharpe"] = bool(
        (comparison["book_sharpe"] or 0) > (bench.get("sharpe") or 0))
    comparison["positive_alpha"] = bool((bench.get("alpha_ann_pct_vs_this") or 0) > 0)

    warnings = [
        "Long-only book: NOT market-neutral. Direction risk is the dominant risk.",
        "Financing forced to 0 (Invest/ISA: no borrow, no margin).",
        f"Cash drag: book averaged {comparison['avg_gross_exposure_pct']}% invested.",
    ]
    return LongOnlyResult(book=book, benchmarks=curves, comparison=comparison,
                          bars_per_year=ppy, warnings=warnings)
