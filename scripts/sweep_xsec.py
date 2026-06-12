"""Parameter sweep: xsec_reversion lookback x rebalance on stored real data."""

from __future__ import annotations

import itertools

from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
from app.config.settings import get_settings
from app.data.market_data import build_price_matrix
from app.data.storage import Storage
from app.data.universe import get_universe
from app.strategies.cross_sectional_mean_reversion import XSecReversalConfig, make_xsec_weight_fn

settings = get_settings()
storage = Storage(settings.database_url)
prices = build_price_matrix(storage, get_universe("crypto_top_10"), "15m")

print(f"{'lookback':>8} {'rebal':>6} {'top_k':>5} {'return%':>8} {'sharpe':>8} {'turnover':>9}")
for lookback, rebal, top_k in itertools.product((12, 24, 48, 96), (12, 24, 48), (2, 3)):
    fn = make_xsec_weight_fn(XSecReversalConfig(lookback_bars=lookback, top_k=top_k))
    cfg = BasketConfig(interval="15m", fit_window=1500, rebalance_every=rebal, cost_bps=15.0)
    result = run_basket_backtest(prices.close, fn, cfg)
    m = result.metrics
    print(f"{lookback:>8} {rebal:>6} {top_k:>5} {m['total_return_pct']:>8.2f} "
          f"{m['sharpe']:>8.2f} {m['turnover']:>9.1f}")
