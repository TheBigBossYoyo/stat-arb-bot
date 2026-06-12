"""Robustness of the 4-sleeve result (pca + xsmom + tsmom + ml_alpha[C]).

exp_allocator_taper found Sharpe 1.32 / +40.7% / maxDD -7.3% for the 4-sleeve
blend with the momentum-neutral ml sleeve under the binary gate — beating the
3-sleeve baseline (1.05) on every metric. Before it becomes the default it
must survive: (a) tree-seed changes, (b) allocator vol_window perturbation.
A result that only exists at random_state=7 and vol_window=60 is noise.
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


def four_sleeves(seed: int) -> dict:
    return {
        "pca": make_pca_weight_fn(PCAStatArbConfig(
            n_components=5, var_threshold=0.55, score_window=60, top_k=8,
            use_ou_scores=True, s_entry=1.25, s_exit=0.5, max_residual_half_life=20)),
        "xsmom": make_xsmom_weight_fn(XSMOMConfig(lookback_bars=252, skip_bars=21,
                                                  top_k=5, top_frac=0.10)),
        "tsmom": make_tsmom_weight_fn(TSMOMConfig(lookback_bars=252, skip_bars=21,
                                                  vol_window=63, max_weight=0.10)),
        "ml": MLAlphaWeights(MLAlphaConfig(
            horizons=[5, 10, 21, 63, 126], vol_windows=[21, 63], forward_bars=5,
            retrain_every=21, momentum_neutral=True, random_state=seed)),
    }


def main() -> None:
    storage = Storage(get_settings().database_url)
    prices = build_price_matrix(storage, get_universe("us_stocks_50"), "1d")
    close, aux = prices.close, prices.aux

    for seed, vol_window in [(7, 60), (1, 60), (42, 60), (7, 40), (7, 80)]:
        ens = RiskParityEnsemble(four_sleeves(seed), EnsembleConfig(
            vol_window=vol_window, min_observations=20, gross_target=1.0,
            max_sleeve_share=0.60, min_sleeve_t=0.0, cost_bps=5.0,
            target_vol_pct=10.0, rebalances_per_year=252.0))
        m = run_basket_backtest(close, ens, CFG, aux=aux).metrics
        alloc = {k: round(float(v), 2) for k, v in ens.sleeve_allocations().items()}
        print(f"seed={seed:>2} vol_win={vol_window}: return={m['total_return_pct']:>7.2f}%  "
              f"sharpe={m['sharpe']:>5.2f}  maxDD={m['max_drawdown_pct']:>7.2f}%  "
              f"end_alloc={alloc}", flush=True)


if __name__ == "__main__":
    main()
