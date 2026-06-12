"""Synthetic market data generator.

Produces a universe with known cointegrated pairs so the entire pipeline
(pair discovery -> backtest -> report) can run fully offline, with no API
keys and no network. Symbols are paired (0,1), (2,3), ... as cointegrated;
any odd leftover symbol is an independent random walk.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.core.types import interval_minutes


def _ou_process(n: int, half_life: float, sigma: float, rng: np.random.Generator) -> np.ndarray:
    """Discrete Ornstein-Uhlenbeck around 0 with the given half-life in bars."""
    theta = np.log(2.0) / half_life
    phi = np.exp(-theta)
    # stationary std of the AR(1): sigma_e / sqrt(1 - phi^2)
    noise = rng.normal(0.0, sigma, n)
    s = np.empty(n)
    s[0] = noise[0]
    for t in range(1, n):
        s[t] = phi * s[t - 1] + noise[t]
    return s


def generate_synthetic_bars(
    symbols: list[str],
    n_bars: int = 6000,
    interval: str = "15m",
    seed: int = 42,
    start: pd.Timestamp | None = None,
    half_life_bars: float = 30.0,
    bar_vol: float = 0.004,
) -> pd.DataFrame:
    """Long-format OHLCV frame [symbol, ts, open, high, low, close, volume].

    Bars end at the current time by default so date-window filters
    (e.g. --lookback-days) behave the same as with real data.
    """
    rng = np.random.default_rng(seed)
    minutes = interval_minutes(interval)
    if start is None:
        end = pd.Timestamp.now(tz="UTC").tz_localize(None).floor(f"{minutes}min")
        start = end - pd.Timedelta(minutes=minutes * (n_bars - 1))
    ts = pd.date_range(start, periods=n_bars, freq=f"{minutes}min")

    log_prices: dict[str, np.ndarray] = {}
    base_levels = rng.uniform(2.0, 7.0, size=len(symbols))  # log price levels ~ e^2..e^7

    i = 0
    while i < len(symbols):
        if i + 1 < len(symbols):
            # cointegrated pair: B is a random walk, A = alpha + beta*B + OU spread
            beta = rng.uniform(0.8, 1.2)
            b = base_levels[i + 1] + np.cumsum(rng.normal(0.0, bar_vol, n_bars))
            spread = _ou_process(n_bars, half_life_bars, bar_vol * 0.6, rng)
            alpha = base_levels[i] - beta * base_levels[i + 1]
            a = alpha + beta * b + spread
            log_prices[symbols[i]] = a
            log_prices[symbols[i + 1]] = b
            i += 2
        else:
            log_prices[symbols[i]] = base_levels[i] + np.cumsum(rng.normal(0.0, bar_vol, n_bars))
            i += 1

    frames = []
    for sym, lp in log_prices.items():
        close = np.exp(lp)
        open_ = np.empty(n_bars)
        open_[0] = close[0]
        open_[1:] = close[:-1]
        jitter = np.abs(rng.normal(0.0, bar_vol / 2, n_bars))
        high = np.maximum(open_, close) * (1 + jitter)
        low = np.minimum(open_, close) * (1 - jitter)
        volume = rng.lognormal(mean=10.0, sigma=0.5, size=n_bars)
        frames.append(
            pd.DataFrame(
                {
                    "symbol": sym,
                    "ts": ts,
                    "open": open_,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)
