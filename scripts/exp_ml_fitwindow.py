"""Capacity test: does a doubled training panel rescue orthogonal features?

Section 7b's negative (orthogonal features: Sharpe 0.84 -> 0.05) was read as
a model-capacity limit: ~16 ranked features on a fit_window-300 panel
(~170 train dates x 50 names). A fit_window of 600 doubles the panel without
new data. Costs of the test: the strategy adapts slower and the traded span
shrinks to ~650 bars (~2.6y), so variants are compared WITHIN this script at
fit_window 600, not against the 300-bar numbers.
"""

from __future__ import annotations

from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
from app.config.settings import get_settings
from app.data.market_data import build_price_matrix
from app.data.storage import Storage
from app.data.universe import get_universe
from app.strategies.ml_alpha import MLAlphaConfig, MLAlphaWeights

CFG = BasketConfig(interval="1d", fit_window=600, rebalance_every=1,
                   cost_bps=5.0, bars_per_year=252.0)

ML_BASE = dict(horizons=[5, 10, 21, 63, 126], vol_windows=[21, 63],
               forward_bars=5, retrain_every=21)


def main() -> None:
    storage = Storage(get_settings().database_url)
    prices = build_price_matrix(storage, get_universe("us_stocks_50"), "1d")
    close, aux = prices.close, prices.aux
    variants = {
        "A legacy features": MLAlphaConfig(**ML_BASE),
        "B + orthogonal features": MLAlphaConfig(**ML_BASE, orthogonal_features=True),
        "C + momentum neutral": MLAlphaConfig(**ML_BASE, momentum_neutral=True),
        "D orthogonal + neutral": MLAlphaConfig(**ML_BASE, orthogonal_features=True,
                                                momentum_neutral=True),
    }
    for label, cfg in variants.items():
        m = run_basket_backtest(close, MLAlphaWeights(cfg), CFG, aux=aux).metrics
        print(f"fit600 {label:<26} return={m['total_return_pct']:>7.2f}%  "
              f"sharpe={m['sharpe']:>5.2f}  maxDD={m['max_drawdown_pct']:>7.2f}%",
              flush=True)


if __name__ == "__main__":
    main()
