"""Crypto-futures ensemble (Path B).

Risk-parity blend of the futures sleeves — TSMOM, funding carry, basis carry and
funding-adjusted momentum — reusing the same `RiskParityEnsemble` (inverse-vol
allocation with a trailing-performance gate) as the equity flagship. On top of
the blend it enforces the crypto-futures-specific caps:

* **BTC/ETH beta cap** — bound the combined BTC+ETH gross so the book is not a
  levered market bet.
* **per-symbol cap** — concentration control.
* **funding concentration cap** — limit how much gross sits in the single
  richest-funding name (carry crowding risk).
"""

from __future__ import annotations

import pandas as pd

from app.strategies.basis_carry import make_basis_carry_weight_fn
from app.strategies.crypto_tsmom_futures import make_crypto_tsmom_weight_fn
from app.strategies.ensemble import EnsembleConfig, RiskParityEnsemble
from app.strategies.funding_adjusted_momentum import make_funding_adjusted_momentum
from app.strategies.funding_carry import make_funding_carry_weight_fn

FUTURES_SLEEVES = ("crypto_tsmom_futures", "funding_carry", "basis_carry",
                   "funding_adjusted_momentum")


class CryptoFuturesEnsemble:
    wants_aux = True

    def __init__(self, ensemble: RiskParityEnsemble, *, beta_assets=("BTCUSDT", "ETHUSDT"),
                 max_beta_gross: float = 0.50, max_symbol: float = 0.30,
                 max_funding_name: float = 0.34) -> None:
        self.ensemble = ensemble
        self.beta_assets = beta_assets
        self.max_beta_gross = max_beta_gross
        self.max_symbol = max_symbol
        self.max_funding_name = max_funding_name

    def __call__(self, close_window: pd.DataFrame, aux: dict | None = None) -> pd.Series:
        w = self.ensemble(close_window, aux=aux)
        w = w.clip(-self.max_symbol, self.max_symbol)            # per-symbol cap
        beta = [s for s in self.beta_assets if s in w.index]
        bg = float(w[beta].abs().sum()) if beta else 0.0
        if bg > self.max_beta_gross > 0:                        # BTC/ETH beta cap
            w[beta] = w[beta] * (self.max_beta_gross / bg)
        # funding concentration: no single name may exceed max_funding_name gross
        if (w.abs() > self.max_funding_name).any():
            w = w.clip(-self.max_funding_name, self.max_funding_name)
        return w

    def sleeve_allocations(self):
        return self.ensemble.sleeve_allocations()

    @property
    def history(self):
        return self.ensemble.history


def build_crypto_futures_ensemble(
    *, sleeves: list[str] | None = None,
    ensemble_config: EnsembleConfig | None = None,
    record_history: bool = False,
    **caps,
) -> CryptoFuturesEnsemble:
    names = sleeves or list(FUTURES_SLEEVES)
    builders = {
        "crypto_tsmom_futures": make_crypto_tsmom_weight_fn,
        "funding_carry": make_funding_carry_weight_fn,
        "basis_carry": make_basis_carry_weight_fn,
        "funding_adjusted_momentum": make_funding_adjusted_momentum,
    }
    unknown = [n for n in names if n not in builders]
    if unknown:
        raise ValueError(f"unknown futures sleeve(s) {unknown}; choose from {list(builders)}")
    fns = {n: builders[n]() for n in names}
    ens = RiskParityEnsemble(fns, ensemble_config or EnsembleConfig(cost_bps=7.0),
                             record_history=record_history)
    return CryptoFuturesEnsemble(ens, **caps)
