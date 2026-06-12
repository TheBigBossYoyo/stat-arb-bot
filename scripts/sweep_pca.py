"""PCA stat-arb diagnostics at 100-name breadth: book size x factor model."""

from __future__ import annotations

import itertools

from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
from app.config.settings import get_settings
from app.data.market_data import build_price_matrix
from app.data.storage import Storage
from app.data.universe import get_universe
from app.strategies.pca_stat_arb import PCAStatArbConfig, make_pca_weight_fn

storage = Storage(get_settings().database_url)
universe = "us_stocks_100"
prices = build_price_matrix(storage, get_universe(universe), "1d")
print(f"{'top_k':>5} {'var_thr':>7} {'return%':>8} {'sharpe':>7} {'maxDD%':>7} {'turnover':>8}")
for top_k, var_thr in itertools.product((8, 16, 32), (0.0, 0.55)):
    fn = make_pca_weight_fn(PCAStatArbConfig(
        n_components=5, var_threshold=var_thr, score_window=60, top_k=top_k,
        s_entry=1.25, s_exit=0.5, max_residual_half_life=20.0,
    ))
    cfg = BasketConfig(interval="1d", fit_window=300, rebalance_every=1,
                       cost_bps=5.0, bars_per_year=252.0)
    m = run_basket_backtest(prices.close, fn, cfg).metrics
    print(f"{top_k:>5} {var_thr:>7} {m['total_return_pct']:>8.2f} {m['sharpe']:>7.2f} "
          f"{m['max_drawdown_pct']:>7.2f} {m['turnover']:>8.1f}")
