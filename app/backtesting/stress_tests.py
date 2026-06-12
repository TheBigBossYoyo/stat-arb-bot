"""Robustness / stress suite.

Re-runs a backtest under conservative assumptions: higher fees, higher
slippage, delayed entries. A strategy that only survives the base scenario
should never be allowed near live trading.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pandas as pd

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
