"""Robustness / stress suite.

Re-runs a backtest under conservative assumptions: higher fees, higher
slippage, delayed entries. A strategy that only survives the base scenario
should never be allowed near live trading.

Two engines are covered: the pairs engine (`run_stress_suite`) and the basket/
ensemble engine (`run_basket_stress_suite`) — the latter closed an audit gap
(W-01): the flagship lives on the basket engine and had no stress path at all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pandas as pd

from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
from app.backtesting.engine import BacktestConfig, BacktestResult

SCENARIOS: dict[str, dict] = {
    "base": {},
    "fees_x2": {"commission_bps_mult": 2.0},
    "slippage_x3": {"slippage_bps_mult": 3.0},
    "entry_delay_1": {"entry_delay_bars": 1},
    "entry_delay_2": {"entry_delay_bars": 2},
    "fees_x2_slip_x2_delay_1": {
        "commission_bps_mult": 2.0, "slippage_bps_mult": 2.0, "entry_delay_bars": 1,
    },
}


def _apply(config: BacktestConfig, scenario: dict) -> BacktestConfig:
    return replace(
        config,
        commission_bps=config.commission_bps * scenario.get("commission_bps_mult", 1.0),
        slippage_bps=config.slippage_bps * scenario.get("slippage_bps_mult", 1.0),
        entry_delay_bars=scenario.get("entry_delay_bars", config.entry_delay_bars),
        label=f"{config.label}",
    )


def run_stress_suite(
    run_backtest: Callable[[BacktestConfig], BacktestResult],
    base_config: BacktestConfig,
) -> pd.DataFrame:
    """`run_backtest` must build a FRESH engine per call (strategies are stateful)."""
    rows = []
    for name, scenario in SCENARIOS.items():
        result = run_backtest(_apply(base_config, scenario))
        m = result.metrics
        rows.append({
            "scenario": name,
            "total_return_pct": m.get("total_return_pct"),
            "sharpe": m.get("sharpe"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "n_trades": m.get("n_trades"),
            "total_fees": m.get("total_fees"),
        })
    return pd.DataFrame(rows).set_index("scenario")


# --- basket / ensemble stress suite (audit W-01) ---------------------------------

BASKET_SCENARIOS: dict[str, dict] = {
    "base": {},
    "costs_x2": {"cost_mult": 2.0},
    "costs_x3": {"cost_mult": 3.0},
    "borrow_x3": {"borrow_mult": 3.0},
    "same_close_fill": {"fill": "same_close"},   # diagnostic: timing optimism
    "next_open_delay": {"extra_rebalance": True},  # one-bar slower reaction
}


def run_basket_stress_suite(
    close: pd.DataFrame,
    weight_fn_factory: Callable[[], object],
    base_config: BasketConfig,
    *,
    aux: dict | None = None,
    open_=None,
) -> pd.DataFrame:
    """`weight_fn_factory` must return a FRESH weight fn per call (sleeves are
    stateful). Runs each scenario and returns a metrics table."""
    rows = []
    for name, scenario in BASKET_SCENARIOS.items():
        cfg = replace(
            base_config,
            cost_bps=base_config.cost_bps * scenario.get("cost_mult", 1.0),
            borrow_bps_annual=base_config.borrow_bps_annual * scenario.get("borrow_mult", 1.0),
            fill=scenario.get("fill", base_config.fill),
            rebalance_every=(base_config.rebalance_every + 1
                             if scenario.get("extra_rebalance") else base_config.rebalance_every),
            label=f"{base_config.label}_{name}",
        )
        res = run_basket_backtest(close, weight_fn_factory(), cfg, aux=aux, open_=open_)
        m = res.metrics
        rows.append({
            "scenario": name,
            "total_return_pct": m.get("total_return_pct"),
            "sharpe": m.get("sharpe"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "total_fees": m.get("total_fees"),
            "financing_cost": m.get("financing_cost"),
        })
    return pd.DataFrame(rows).set_index("scenario")


def return_concentration(equity: pd.Series) -> dict:
    """Concentration checks from the acceptance criteria: a strategy whose PnL
    rides on one month or a handful of days is fragile. Returns the worst
    single-month and single-day share of total positive PnL."""
    equity = equity.dropna()
    if len(equity) < 3:
        return {"max_month_pct": None, "max_day_pct": None, "best5pct_share": None}
    rets = equity.pct_change().dropna()
    pnl = rets * equity.shift(1).reindex(rets.index)
    total = pnl.sum()
    if total == 0:
        return {"max_month_pct": None, "max_day_pct": None, "best5pct_share": None}
    monthly = pnl.groupby(pnl.index.to_period("M")).sum()
    max_month = float(monthly.max() / total) if len(monthly) else None
    # share of total return from the best 5% of bars
    k = max(1, int(0.05 * len(pnl)))
    best5 = float(pnl.nlargest(k).sum() / total)
    max_day = float(pnl.max() / total)
    return {
        "max_month_pct": round(100 * max_month, 1) if max_month is not None else None,
        "max_day_pct": round(100 * max_day, 1),
        "best5pct_share": round(100 * best5, 1),
    }
