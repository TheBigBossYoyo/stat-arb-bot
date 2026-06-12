"""Experiment: t-stat-tapered risk parity vs the binary performance gate.

Finding from exp_ml_orthogonal: ml_alpha's realized correlation with
xsec_momentum is only ~0.19 — the documented ensemble dilution (1.05 -> 0.95)
is an ALLOCATOR artifact, not a correlation problem. Inverse-vol hands the
low-vol ml sleeve a large capital share the moment its trailing t-stat clears
the binary gate, starving the Sharpe-1.11 momentum sleeve.

Here: share ∝ inv_vol * clip(t_stat / t_stat_scale, 0, 1) so funding scales
with the evidence of edge. Sweep the scale on the 3-sleeve baseline and the
4-sleeve blend with the momentum-neutral ml_alpha (variant C).
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


def sleeves(with_ml: bool) -> dict:
    out = {
        "pca": make_pca_weight_fn(PCAStatArbConfig(
            n_components=5, var_threshold=0.55, score_window=60, top_k=8,
            use_ou_scores=True, s_entry=1.25, s_exit=0.5, max_residual_half_life=20)),
        "xsmom": make_xsmom_weight_fn(XSMOMConfig(lookback_bars=252, skip_bars=21,
                                                  top_k=5, top_frac=0.10)),
        "tsmom": make_tsmom_weight_fn(TSMOMConfig(lookback_bars=252, skip_bars=21,
                                                  vol_window=63, max_weight=0.10)),
    }
    if with_ml:
        out["ml"] = MLAlphaWeights(MLAlphaConfig(
            horizons=[5, 10, 21, 63, 126], vol_windows=[21, 63], forward_bars=5,
            retrain_every=21, momentum_neutral=True))
    return out


def main() -> None:
    storage = Storage(get_settings().database_url)
    prices = build_price_matrix(storage, get_universe("us_stocks_50"), "1d")
    close, aux = prices.close, prices.aux

    for with_ml in (False, True):
        label_book = "4-sleeve (+ml C)" if with_ml else "3-sleeve        "
        for t_scale in (0.0, 0.5, 1.0, 2.0):
            ens = RiskParityEnsemble(sleeves(with_ml), EnsembleConfig(
                vol_window=60, min_observations=20, gross_target=1.0,
                max_sleeve_share=0.60, min_sleeve_t=0.0, cost_bps=5.0,
                target_vol_pct=10.0, rebalances_per_year=252.0,
                t_stat_scale=t_scale))
            m = run_basket_backtest(close, ens, CFG, aux=aux).metrics
            alloc = {k: round(v, 2) for k, v in ens.sleeve_allocations().items()}
            print(f"{label_book} t_scale={t_scale:>3}: return={m['total_return_pct']:>7.2f}%  "
                  f"sharpe={m['sharpe']:>5.2f}  maxDD={m['max_drawdown_pct']:>7.2f}%  "
                  f"end_alloc={alloc}", flush=True)


if __name__ == "__main__":
    main()
