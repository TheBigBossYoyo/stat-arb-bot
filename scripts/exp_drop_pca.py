"""Does the flagship need the pca sleeve at all?

Flat pca is negative standalone on the current window (-6.8%) and ends the
period at zero allocation — but the gate may still fund it in stretches
where it carries the book (e.g. the 2022 momentum drawdown). Compare the
4-sleeve flagship against xsmom+tsmom+ml with pca removed.
"""

from __future__ import annotations

from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
from app.config.settings import get_settings
from app.data.market_data import build_price_matrix
from app.data.storage import Storage
from app.data.universe import get_universe
from app.strategies.ensemble import EnsembleConfig, RiskParityEnsemble
from app.strategies.ml_alpha import MLAlphaConfig, MLAlphaWeights
from app.strategies.momentum import (
    TSMOMConfig,
    XSMOMConfig,
    make_tsmom_weight_fn,
    make_xsmom_weight_fn,
)
from app.strategies.pca_stat_arb import PCAStatArbConfig, make_pca_weight_fn

CFG = BasketConfig(interval="1d", fit_window=300, rebalance_every=1,
                   cost_bps=5.0, bars_per_year=252.0)


def sleeves(with_pca: bool) -> dict:
    out = {}
    if with_pca:
        out["pca"] = make_pca_weight_fn(PCAStatArbConfig(
            n_components=5, var_threshold=0.55, score_window=60, top_k=8,
            use_ou_scores=True, s_entry=1.25, s_exit=0.5,
            max_residual_half_life=20))
    out["xsmom"] = make_xsmom_weight_fn(XSMOMConfig(lookback_bars=252, skip_bars=21,
                                                    top_k=5, top_frac=0.10))
    out["tsmom"] = make_tsmom_weight_fn(TSMOMConfig(lookback_bars=252, skip_bars=21,
                                                    vol_window=63, max_weight=0.10))
    out["ml"] = MLAlphaWeights(MLAlphaConfig(
        horizons=[5, 10, 21, 63, 126], vol_windows=[21, 63], forward_bars=5,
        retrain_every=21, momentum_neutral=True))
    return out


def main() -> None:
    storage = Storage(get_settings().database_url)
    prices = build_price_matrix(storage, get_universe("us_stocks_50"), "1d")
    for with_pca, label in ((True, "4-sleeve flagship (with pca)"),
                            (False, "3-sleeve: xsmom+tsmom+ml (no pca)")):
        ens = RiskParityEnsemble(sleeves(with_pca), EnsembleConfig(
            vol_window=60, min_observations=20, gross_target=1.0,
            max_sleeve_share=0.60, min_sleeve_t=0.0, cost_bps=5.0,
            target_vol_pct=10.0, rebalances_per_year=252.0))
        m = run_basket_backtest(prices.close, ens, CFG, aux=prices.aux).metrics
        print(f"{label:<36} return={m['total_return_pct']:>7.2f}%  "
              f"sharpe={m['sharpe']:>5.2f}  maxDD={m['max_drawdown_pct']:>7.2f}%",
              flush=True)


if __name__ == "__main__":
    main()
