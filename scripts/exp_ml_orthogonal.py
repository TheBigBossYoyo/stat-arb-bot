"""Experiment: does an orthogonalized ml_alpha earn an ensemble slot?

Baselines from docs/strategy_research.md (us_stocks_50, 1d, 5 bps):
  ml_alpha standalone          +28.5%  Sharpe 0.84
  3-sleeve ensemble            +36.3%  Sharpe 1.05  maxDD -7.4%
  4-sleeve (old ml_alpha)      Sharpe ~0.95 (diluted -> rejected)

Variants here:
  A  ml_alpha as shipped (close-only features, no neutralization)
  B  + aux features (volume, overnight/intraday, range vol, beta/idio)
  C  + momentum neutralization (target + score residualization)
  D  B + C combined

For each: standalone metrics + correlation of sleeve daily returns with the
xsec_momentum sleeve, then the 4-sleeve ensemble with variant D.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

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

UNIVERSE = "us_stocks_50"
CFG = BasketConfig(interval="1d", fit_window=300, rebalance_every=1,
                   cost_bps=5.0, bars_per_year=252.0)

ML_BASE = dict(horizons=[5, 10, 21, 63, 126], vol_windows=[21, 63],
               forward_bars=5, retrain_every=21)


def ml_cfg(**kw) -> MLAlphaConfig:
    return MLAlphaConfig(**{**ML_BASE, **kw})


def xsmom_fn():
    return make_xsmom_weight_fn(XSMOMConfig(lookback_bars=252, skip_bars=21,
                                            top_k=5, top_frac=0.10))


def tsmom_fn():
    return make_tsmom_weight_fn(TSMOMConfig(lookback_bars=252, skip_bars=21,
                                            vol_window=63, max_weight=0.10))


def pca_fn():
    return make_pca_weight_fn(PCAStatArbConfig(
        n_components=5, var_threshold=0.55, score_window=60, top_k=8,
        use_ou_scores=True, s_entry=1.25, s_exit=0.5, max_residual_half_life=20))


def run(label: str, fn, close, aux) -> pd.Series:
    result = run_basket_backtest(close, fn, CFG, aux=aux)
    m = result.metrics
    rets = result.equity.iloc[CFG.fit_window:].pct_change().fillna(0.0)
    print(f"{label:<34} return={m['total_return_pct']:>7.2f}%  "
          f"sharpe={m['sharpe']:>5.2f}  maxDD={m['max_drawdown_pct']:>7.2f}%  "
          f"fees=${m.get('total_fees', 0):>7.0f}")
    return rets


def main() -> None:
    storage = Storage(get_settings().database_url)
    prices = build_price_matrix(storage, get_universe(UNIVERSE), "1d")
    close, aux = prices.close, prices.aux
    print(f"{UNIVERSE}: {close.shape[1]} names x {len(close)} bars "
          f"[{close.index[0].date()} .. {close.index[-1].date()}]\n")

    mom_rets = run("xsec_momentum (reference)", xsmom_fn(), close, aux)

    variants = {
        "A legacy features (baseline)": ml_cfg(),
        "B + orthogonal features": ml_cfg(orthogonal_features=True),
        "C + momentum neutral only": ml_cfg(momentum_neutral=True),
        "D orthogonal + momentum neutral": ml_cfg(orthogonal_features=True,
                                                  momentum_neutral=True),
    }
    ml_rets: dict[str, pd.Series] = {}
    for label, cfg in variants.items():
        ml_rets[label] = run(label, MLAlphaWeights(cfg), close, aux)

    print("\ncorrelation of daily sleeve returns vs xsec_momentum:")
    for label, rets in ml_rets.items():
        corr = float(np.corrcoef(rets, mom_rets)[0, 1])
        print(f"  {label:<34} {corr:+.3f}")

    print("\nensembles (daily profile gates: min_sleeve_t=0, target_vol=10%):")
    ens_cfg = EnsembleConfig(vol_window=60, min_observations=20, gross_target=1.0,
                             max_sleeve_share=0.60, min_sleeve_t=0.0, cost_bps=5.0,
                             target_vol_pct=10.0, rebalances_per_year=252.0)

    def ensemble(sleeves: dict) -> RiskParityEnsemble:
        return RiskParityEnsemble(sleeves, ens_cfg.model_copy())

    run("3-sleeve baseline (pca+xsmom+tsmom)",
        ensemble({"pca": pca_fn(), "xsmom": xsmom_fn(), "tsmom": tsmom_fn()}),
        close, aux)
    run("4-sleeve + ml_alpha variant D",
        ensemble({"pca": pca_fn(), "xsmom": xsmom_fn(), "tsmom": tsmom_fn(),
                  "ml": MLAlphaWeights(ml_cfg(orthogonal_features=True,
                                              momentum_neutral=True))}),
        close, aux)
    run("4-sleeve + ml_alpha variant A (old)",
        ensemble({"pca": pca_fn(), "xsmom": xsmom_fn(), "tsmom": tsmom_fn(),
                  "ml": MLAlphaWeights(ml_cfg())}),
        close, aux)


if __name__ == "__main__":
    main()
