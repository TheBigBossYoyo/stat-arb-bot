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

from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
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


# --- basket / ensemble out-of-sample validation (audit W-01) ---------------------


@dataclass
class BasketWalkForwardResult:
    is_metrics: dict
    oos_metrics: dict
    folds: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def run_basket_holdout(
    close: pd.DataFrame,
    weight_fn_factory: Callable[[], object],
    config: BasketConfig,
    *,
    n_folds: int = 4,
    aux: dict | None = None,
    open_=None,
) -> BasketWalkForwardResult:
    """Anchored walk-forward for a stateful basket strategy.

    The flagship lives on the basket engine, which had NO out-of-sample path
    (audit W-01). Strategies already retrain inside their window, so the bias
    this exposes is CONFIG selection: a sleeve set / allocator tuned on the
    whole window will degrade on the later folds it never informed.

    We split the post-warmup span into `n_folds` contiguous test blocks. For
    each block we run the strategy on [start .. block_end] (a fresh stateful
    instance) and attribute the block's segment of the equity curve as that
    fold's OOS performance. Fold 0 (still partly warmup-bound) is reported but
    excluded from the OOS aggregate.
    """
    from app.backtesting.metrics import compute_metrics

    n = len(close)
    usable = n - config.fit_window
    if usable < n_folds * 5:
        raise ValueError(f"need >= {n_folds * 5} bars past the fit window, have {usable}")
    bounds = [config.fit_window + (usable * k) // n_folds for k in range(n_folds + 1)]

    folds: list[dict] = []
    oos_segments: list[pd.Series] = []
    is_sharpes, oos_sharpes = [], []
    for k in range(n_folds):
        end = bounds[k + 1]
        sub = close.iloc[:end]
        sub_aux = ({name: df.iloc[:end] for name, df in aux.items()} if aux else None)
        sub_open = open_.iloc[:end] if open_ is not None else None
        res = run_basket_backtest(sub, weight_fn_factory(), config,
                                  aux=sub_aux, open_=sub_open)
        eq = res.equity.dropna()
        block = eq.loc[close.index[bounds[k]]: close.index[end - 1]]
        is_sharpes.append(res.metrics.get("sharpe") or 0.0)
        fold_metrics = compute_metrics(
            block, [], interval=config.interval, starting_cash=float(block.iloc[0]),
            bars_per_year=config.bars_per_year,
        ) if len(block) > 2 else {}
        folds.append({"fold": k, "test_start": str(close.index[bounds[k]]),
                      "test_end": str(close.index[end - 1]),
                      "sharpe": fold_metrics.get("sharpe"),
                      "return_pct": fold_metrics.get("total_return_pct")})
        if k >= 1 and len(block) > 2:
            oos_sharpes.append(fold_metrics.get("sharpe") or 0.0)
            oos_segments.append(block / float(block.iloc[0]))

    full = run_basket_backtest(close, weight_fn_factory(), config, aux=aux, open_=open_)
    oos_mean = float(pd.Series(oos_sharpes).mean()) if oos_sharpes else 0.0
    is_mean = float(pd.Series(is_sharpes).mean()) if is_sharpes else 0.0
    summary = {
        "n_folds": n_folds,
        "full_sample_sharpe": full.metrics.get("sharpe"),
        "oos_sharpe_mean": round(oos_mean, 3),
        "oos_folds_positive": sum(1 for s in oos_sharpes if s > 0),
        "oos_folds": len(oos_sharpes),
        "sharpe_degradation": round(safe_div(is_mean - oos_mean, abs(is_mean), default=0.0), 3),
    }
    return BasketWalkForwardResult(
        is_metrics=full.metrics, oos_metrics={"oos_sharpe_mean": oos_mean},
        folds=folds, summary=summary,
    )
