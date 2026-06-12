"""Feature engineering for the ML alpha sleeve (Phase 8).

Cross-sectional return forecasting the way systematic equity funds do it
(Gu, Kelly & Xiu, "Empirical Asset Pricing via Machine Learning", 2020):
tabular features per (date, asset), CROSS-SECTIONALLY RANKED per date so the
model learns relative ordering rather than levels, and a forward relative
return as the target. Rank transforms make the features stationary across
regimes and make tree models robust to outliers.

Two mechanisms exist to decorrelate the learned sleeve from the hand-built
momentum sleeve (its documented failure mode — standalone Sharpe 0.84 yet it
DILUTED the ensemble because it rode the same 12-1 factor):

* ORTHOGONAL FEATURES from aux OHLCV frames — abnormal volume, volume trend,
  Amihud illiquidity, the overnight/intraday return split (Lou, Polk &
  Skouras 2019: the two components carry opposite cross-sectional
  information), Parkinson range volatility, and market beta / idiosyncratic
  vol. None of these are visible to a close-only momentum signal.
* TARGET NEUTRALIZATION — the forward-return target (and, in the strategy,
  the predicted scores) is residualized per date against chosen ranked
  characteristics, so the model is trained to forecast the component of
  return that momentum does NOT explain.

Everything here is computed from the price/aux windows the basket engine
hands the strategy, so lookahead beyond the window is impossible by
construction; within the window, training rows only include dates whose
forward-return target has fully completed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class FeaturePanel:
    X: np.ndarray                 # training rows (date x asset, stacked)
    y: np.ndarray                 # forward cross-sectional return per row
    latest: np.ndarray            # one row per asset: features at the last bar
    assets: list[str]
    feature_names: list[str]
    neutralize_idx: list[int] = field(default_factory=list)  # columns of the
    # neutralization characteristics inside X/latest (for score residualization)


def _rank_cross_section(df: pd.DataFrame) -> pd.DataFrame:
    """Per-date rank in [-0.5, 0.5]; NaN-safe (NaNs stay NaN)."""
    n = df.count(axis=1)
    return df.rank(axis=1).sub(1).div((n - 1).clip(lower=1), axis=0) - 0.5


def build_feature_frames(
    close: pd.DataFrame,
    horizons: list[int],
    vol_windows: list[int],
    aux: dict[str, pd.DataFrame] | None = None,
    extended: bool = False,
) -> dict[str, pd.DataFrame]:
    """Raw (un-ranked) feature frames, one DataFrame[date x asset] each.

    `extended=False` reproduces the legacy close-only feature set exactly
    (returns, vols, price z-score, drawdown) — the configuration behind the
    documented +28.5%/Sharpe 0.84 baseline. `extended=True` adds the
    orthogonal block (beta/idio-vol and, when aux frames are present, volume,
    overnight/intraday and range-vol features). All rolling windows are
    bounded by max(horizons + vol_windows), so warmup does not grow.
    """
    aux = aux or {}
    log_close = np.log(close)
    rets = log_close.diff()
    feats: dict[str, pd.DataFrame] = {}
    for h in horizons:
        feats[f"ret_{h}"] = log_close.diff(h)
    for w in vol_windows:
        feats[f"vol_{w}"] = rets.rolling(w).std()
    w0 = vol_windows[0]
    w1 = max(vol_windows)
    ma = close.rolling(w0).mean()
    sd = close.rolling(w0).std()
    feats[f"price_z_{w0}"] = (close - ma) / sd.replace(0.0, np.nan)
    hmax = max(horizons)
    feats[f"drawdown_{hmax}"] = close / close.rolling(hmax).max() - 1.0
    if not extended:
        return feats

    # --- market-structure features (close-only, but orthogonal to momentum):
    # rolling beta to the equal-weight universe and the idiosyncratic vol
    # left after stripping that market exposure (low-beta / low-idio-vol are
    # classic cross-sectional effects distinct from 12-1 momentum)
    mkt = rets.mean(axis=1)
    mvar = mkt.rolling(w1).var()
    beta = rets.rolling(w1).cov(mkt).div(mvar.replace(0.0, np.nan), axis=0)
    feats[f"beta_{w1}"] = beta
    idio_var = rets.rolling(w1).var().sub(beta.pow(2).mul(mvar, axis=0))
    feats[f"idio_vol_{w1}"] = idio_var.clip(lower=0.0).pow(0.5)

    volume = aux.get("volume")
    if volume is not None:
        vol_pos = volume.where(volume > 0)
        log_vol = np.log(vol_pos)
        vmean = log_vol.rolling(w1, min_periods=w0).mean()
        vstd = log_vol.rolling(w1, min_periods=w0).std()
        feats[f"volume_z_{w1}"] = (log_vol - vmean) / vstd.replace(0.0, np.nan)
        # volume momentum: short-window turnover vs its own long-window level
        feats["volume_trend"] = log_vol.rolling(w0).mean() - vmean
        # Amihud (2002) illiquidity: |return| per unit of dollar volume
        feats[f"amihud_{w1}"] = (rets.abs() / (close * vol_pos)).rolling(
            w1, min_periods=w0).mean()

    open_ = aux.get("open")
    if open_ is not None:
        # overnight/intraday decomposition (Lou-Polk-Skouras 2019): a 24/7
        # market has overnight ~ 0 and the feature ranks go flat — harmless
        overnight = np.log(open_.where(open_ > 0) / close.shift(1))
        h_mid = sorted(horizons)[len(horizons) // 2]
        feats[f"overnight_{h_mid}"] = overnight.rolling(h_mid).sum()
        feats[f"intraday_{h_mid}"] = (
            feats[f"ret_{h_mid}"] if h_mid in horizons else log_close.diff(h_mid)
        ) - feats[f"overnight_{h_mid}"]

    high, low = aux.get("high"), aux.get("low")
    if high is not None and low is not None:
        hl = np.log((high / low).where((high > 0) & (low > 0)))
        park = hl.pow(2).rolling(w0).mean().div(4 * np.log(2)).pow(0.5)
        feats[f"park_vol_{w0}"] = park
        # range vol vs close-to-close vol: gap-driven names rank low,
        # intraday-churn names rank high — invisible to close-only features
        feats[f"range_ratio_{w0}"] = park / rets.rolling(w0).std().replace(0.0, np.nan)

    # a frame that never has data (e.g. FX volume from stooq is always 0)
    # would otherwise NaN-out every training row through the finite-row mask
    return {name: df for name, df in feats.items() if bool(df.notna().any().any())}


def _residualize_target(
    target: pd.DataFrame, chars: list[pd.DataFrame]
) -> pd.DataFrame:
    """Per-date cross-sectional OLS residual of `target` on ranked `chars`.

    NaN characteristics are treated as the cross-sectional median (rank 0);
    NaNs in the target stay NaN.
    """
    X = np.stack([np.nan_to_num(c.to_numpy(), nan=0.0) for c in chars], axis=-1)
    y = target.to_numpy()
    yf = np.nan_to_num(y, nan=0.0)
    gram = np.einsum("tnk,tnl->tkl", X, X)
    gram += 1e-9 * np.eye(X.shape[-1])
    rhs = np.einsum("tnk,tn->tk", X, yf)
    coef = np.linalg.solve(gram, rhs[..., None])[..., 0]
    return pd.DataFrame(y - np.einsum("tnk,tk->tn", X, coef),
                        index=target.index, columns=target.columns)


def build_panel(
    close: pd.DataFrame,
    horizons: list[int],
    vol_windows: list[int],
    forward_bars: int,
    aux: dict[str, pd.DataFrame] | None = None,
    neutralize_features: list[str] | None = None,
    extended: bool | None = None,
) -> FeaturePanel | None:
    """Stack ranked features into a training panel plus the latest live row.

    Targets are forward log returns, cross-sectionally demeaned per date —
    the model forecasts RELATIVE performance, which is what a dollar-neutral
    book trades. Training dates stop `forward_bars` before the window end so
    every target is fully realized inside the window.

    `neutralize_features` names ranked feature frames (e.g. ["ret_63",
    "ret_126"]) whose cross-sectional effect is regressed OUT of the target
    per date, so the model learns the residual the momentum sleeve cannot
    already capture. Their column indices are reported in `neutralize_idx`
    so the caller can residualize predicted scores the same way.
    """
    warmup = max(max(horizons), max(vol_windows))
    if len(close) < warmup + forward_bars + 10 or close.shape[1] < 4:
        return None
    if extended is None:
        extended = aux is not None
    frames = build_feature_frames(close, horizons, vol_windows, aux=aux,
                                  extended=extended)
    ranked = {name: _rank_cross_section(df) for name, df in frames.items()}
    feature_names = list(ranked)

    log_close = np.log(close)
    forward = log_close.shift(-forward_bars) - log_close
    target = forward.sub(forward.mean(axis=1), axis=0)

    neutralize_names = [n for n in (neutralize_features or []) if n in ranked]
    if neutralize_names:
        target = _residualize_target(target, [ranked[n] for n in neutralize_names])

    dates = close.index[warmup:]
    train_dates = dates[: -forward_bars]
    cube = np.stack([ranked[n].loc[train_dates].to_numpy() for n in feature_names], axis=-1)
    y_mat = target.loc[train_dates].to_numpy()
    X = cube.reshape(-1, len(feature_names))
    y = y_mat.reshape(-1)
    ok = np.isfinite(X).all(axis=1) & np.isfinite(y)
    if ok.sum() < 100:
        return None

    latest = np.stack(
        [ranked[n].iloc[-1].to_numpy() for n in feature_names], axis=-1
    )
    return FeaturePanel(
        X=X[ok], y=y[ok], latest=np.nan_to_num(latest, nan=0.0),
        assets=list(close.columns), feature_names=feature_names,
        neutralize_idx=[feature_names.index(n) for n in neutralize_names],
    )
