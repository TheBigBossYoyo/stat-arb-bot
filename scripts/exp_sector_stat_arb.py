"""Experiment: sector-relative residual reversion (Avellaneda-Lee ETF-factor
design) vs the failed flat-PCA version.

Baselines (us_stocks_50 daily, 5 bps, docs section 5/7c):
  flat pca_stat_arb standalone   +7.7%  Sharpe 0.27
  4-sleeve flagship              +40.7% Sharpe 1.32 (pca sleeve gated to 0)

Questions:
  1. Does within-sector residual reversion clear costs where flat PCA didn't?
  2. If yes, does swapping it for (or adding it to) the pca sleeve improve
     the flagship?
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
from app.config.settings import get_settings
from app.data.market_data import build_price_matrix
from app.data.storage import Storage
from app.data.universe import get_sectors, get_universe
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


def pca_cfg(**kw) -> PCAStatArbConfig:
    base = dict(n_components=5, var_threshold=0.55, score_window=60, top_k=8,
                use_ou_scores=True, s_entry=1.25, s_exit=0.5,
                max_residual_half_life=20)
    return PCAStatArbConfig(**{**base, **kw})


def ml_fn():
    return MLAlphaWeights(MLAlphaConfig(
        horizons=[5, 10, 21, 63, 126], vol_windows=[21, 63], forward_bars=5,
        retrain_every=21, momentum_neutral=True))


def xsmom_fn():
    return make_xsmom_weight_fn(XSMOMConfig(lookback_bars=252, skip_bars=21,
                                            top_k=5, top_frac=0.10))


def tsmom_fn():
    return make_tsmom_weight_fn(TSMOMConfig(lookback_bars=252, skip_bars=21,
                                            vol_window=63, max_weight=0.10))


def run(label: str, fn, close, aux) -> pd.Series:
    result = run_basket_backtest(close, fn, CFG, aux=aux)
    m = result.metrics
    print(f"{label:<42} return={m['total_return_pct']:>7.2f}%  "
          f"sharpe={m['sharpe']:>5.2f}  maxDD={m['max_drawdown_pct']:>7.2f}%  "
          f"fees=${m.get('total_fees', 0):>6.0f}", flush=True)
    return result.equity.iloc[CFG.fit_window:].pct_change().fillna(0.0)


def ens_cfg() -> EnsembleConfig:
    return EnsembleConfig(vol_window=60, min_observations=20, gross_target=1.0,
                          max_sleeve_share=0.60, min_sleeve_t=0.0, cost_bps=5.0,
                          target_vol_pct=10.0, rebalances_per_year=252.0)


def main() -> None:
    storage = Storage(get_settings().database_url)
    prices = build_price_matrix(storage, get_universe("us_stocks_50"), "1d")
    close, aux = prices.close, prices.aux
    sectors = get_sectors("us_stocks_50")

    print("--- standalone ---", flush=True)
    pca_rets = run("flat pca (reference)", make_pca_weight_fn(pca_cfg()), close, aux)
    sec_rets = run("sector, defaults (hl=20)",
                   make_pca_weight_fn(pca_cfg(sectors=sectors)), close, aux)
    run("sector, hl=10",
        make_pca_weight_fn(pca_cfg(sectors=sectors, max_residual_half_life=10)),
        close, aux)
    run("sector, s_entry=1.5",
        make_pca_weight_fn(pca_cfg(sectors=sectors, s_entry=1.5)), close, aux)
    run("sector, top_k=5",
        make_pca_weight_fn(pca_cfg(sectors=sectors, top_k=5)), close, aux)

    mom_rets = run("xsec_momentum (reference)", xsmom_fn(), close, aux)
    print("\ncorrelations of daily sleeve returns:", flush=True)
    print(f"  sector vs flat pca        {np.corrcoef(sec_rets, pca_rets)[0, 1]:+.3f}")
    print(f"  sector vs xsec_momentum   {np.corrcoef(sec_rets, mom_rets)[0, 1]:+.3f}")

    print("\n--- ensembles ---", flush=True)
    run("4-sleeve flagship (pca+xsmom+tsmom+ml)",
        RiskParityEnsemble({"pca": make_pca_weight_fn(pca_cfg()),
                            "xsmom": xsmom_fn(), "tsmom": tsmom_fn(),
                            "ml": ml_fn()}, ens_cfg()), close, aux)
    run("4-sleeve, sector replaces pca",
        RiskParityEnsemble({"sector": make_pca_weight_fn(pca_cfg(sectors=sectors)),
                            "xsmom": xsmom_fn(), "tsmom": tsmom_fn(),
                            "ml": ml_fn()}, ens_cfg()), close, aux)
    run("5-sleeve (both pca and sector)",
        RiskParityEnsemble({"pca": make_pca_weight_fn(pca_cfg()),
                            "sector": make_pca_weight_fn(pca_cfg(sectors=sectors)),
                            "xsmom": xsmom_fn(), "tsmom": tsmom_fn(),
                            "ml": ml_fn()}, ens_cfg()), close, aux)


if __name__ == "__main__":
    main()
