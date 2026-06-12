"""Walk-forward validation.

Pairs are selected on each TRAIN window only, then traded on the following
TEST window with parameters frozen at train time. In-sample (train) and
out-of-sample (test) metrics are recorded per window so in-sample-only
strategies are exposed by their IS->OOS degradation.

Note: the first `lookback` bars of each test window act as signal warmup —
this burns a little test data but guarantees no information crosses the
train/test boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd

from app.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from app.core.logging import get_logger
from app.core.math_utils import safe_div
from app.data.market_data import PriceMatrix
from app.research.pair_selection import PairSelectionConfig, PairSelector, SelectedPair
from app.risk.kill_switch import KillSwitch
from app.risk.risk_manager import RiskLimits, RiskManager
from app.strategies.base import PairStrategyBase

log = get_logger(__name__)


@dataclass
class WalkForwardWindow:
    window_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    pairs: list[SelectedPair]
    is_metrics: dict
    oos_metrics: dict


@dataclass
class WalkForwardResult:
    windows: list[WalkForwardWindow]
    oos_equity: pd.Series
    summary: dict = field(default_factory=dict)


def run_walk_forward(
    prices: PriceMatrix,
    *,
    train_bars: int,
    test_bars: int,
    selection_config: PairSelectionConfig,
    strategy_factory: Callable[[SelectedPair], PairStrategyBase],
    bt_config: BacktestConfig,
    risk_limits: RiskLimits,
    step_bars: int | None = None,
) -> WalkForwardResult:
    n = len(prices.index)
    step = step_bars or test_bars
    selector = PairSelector(selection_config)
    windows: list[WalkForwardWindow] = []
    oos_segments: list[pd.Series] = []

    def fresh_engine(slice_: PriceMatrix, pairs: list[SelectedPair]) -> BacktestEngine:
        # each run gets isolated risk state and an in-memory kill switch
        risk = RiskManager(limits=risk_limits, kill_switch=KillSwitch())
        return BacktestEngine(slice_, pairs, strategy_factory, risk, bt_config)

    window_id = 0
    for start in range(0, n - train_bars - test_bars + 1, step):
        train = prices.slice(start, start + train_bars)
        test = prices.slice(start + train_bars, start + train_bars + test_bars)

        pairs = selector.select(train.log_close)
        if not pairs:
            log.info("window %d: no pairs selected — skipping", window_id)
            window_id += 1
            continue

        is_result: BacktestResult = fresh_engine(train, pairs).run()
        oos_result: BacktestResult = fresh_engine(test, pairs).run()

        windows.append(
            WalkForwardWindow(
                window_id=window_id,
                train_start=train.index[0], train_end=train.index[-1],
                test_start=test.index[0], test_end=test.index[-1],
                pairs=pairs,
                is_metrics=is_result.metrics,
                oos_metrics=oos_result.metrics,
            )
        )
        oos_segments.append(oos_result.equity / bt_config.starting_cash)
        log.info(
            "window %d: %d pairs | IS sharpe %.2f ret %.2f%% | OOS sharpe %.2f ret %.2f%%",
            window_id, len(pairs),
            is_result.metrics.get("sharpe") or 0.0, is_result.metrics.get("total_return_pct") or 0.0,
            oos_result.metrics.get("sharpe") or 0.0, oos_result.metrics.get("total_return_pct") or 0.0,
        )
        window_id += 1

    # stitch OOS segments into one compounded curve
    if oos_segments:
        stitched_parts = []
        level = 1.0
        for seg in oos_segments:
            stitched_parts.append(seg * level)
            level = float(stitched_parts[-1].iloc[-1])
        oos_equity = pd.concat(stitched_parts) * bt_config.starting_cash
    else:
        oos_equity = pd.Series(dtype=float)

    is_sharpes = [w.is_metrics.get("sharpe") or 0.0 for w in windows]
    oos_sharpes = [w.oos_metrics.get("sharpe") or 0.0 for w in windows]
    summary = {
        "n_windows": len(windows),
        "is_sharpe_mean": round(float(pd.Series(is_sharpes).mean()), 3) if windows else None,
        "oos_sharpe_mean": round(float(pd.Series(oos_sharpes).mean()), 3) if windows else None,
        "oos_total_return_pct": round(
            100 * (float(oos_equity.iloc[-1]) / bt_config.starting_cash - 1.0), 3
        ) if len(oos_equity) else None,
        "sharpe_degradation": round(
            safe_div(float(pd.Series(is_sharpes).mean()) - float(pd.Series(oos_sharpes).mean()),
                     abs(float(pd.Series(is_sharpes).mean())), default=0.0), 3
        ) if windows else None,
        "oos_windows_positive": sum(
            1 for w in windows if (w.oos_metrics.get("total_return_pct") or 0) > 0
        ),
    }
    return WalkForwardResult(windows=windows, oos_equity=oos_equity, summary=summary)
