"""Decile-spec check: xsec_momentum top_k at 100-name breadth on daily data."""

from __future__ import annotations

from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
from app.config.settings import get_settings
from app.data.market_data import build_price_matrix
from app.data.storage import Storage
from app.data.universe import get_universe
from app.strategies.momentum import XSMOMConfig, make_xsmom_weight_fn

storage = Storage(get_settings().database_url)
prices = build_price_matrix(storage, get_universe("us_stocks_100"), "1d")
for k in (5, 10, 15):
    fn = make_xsmom_weight_fn(XSMOMConfig(lookback_bars=252, skip_bars=21, top_k=k))
    cfg = BasketConfig(interval="1d", fit_window=300, rebalance_every=1,
                       cost_bps=5.0, bars_per_year=252.0)
    m = run_basket_backtest(prices.close, fn, cfg).metrics
    print(f"top_k={k:>2}  return={m['total_return_pct']:>7.2f}%  "
          f"sharpe={m['sharpe']:>5.2f}  maxDD={m['max_drawdown_pct']:>7.2f}%")
