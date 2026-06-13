"""Return-concentration diagnostics and the concentration gate (Phase 1).

The flagship's single biggest validation failure is not its Sharpe — it is the
*shape* of its PnL. From FINAL_RESEARCH_REPORT: one month is 30.3% of total
PnL and the best 5% of days exceed total return. A strategy whose edge lives in
a handful of bars is indistinguishable from luck: remove the lucky month and
the alpha is gone. That fragility is exactly what this module measures.

Two layers of attribution:

* **Time** — from the equity curve alone: monthly / daily contribution, the
  best-N days, the share of return earned by the best 5% of bars, and the
  Herfindahl concentration of monthly PnL. No position data needed.
* **Cross-section** — from rebalance weights: per-asset, per-sector and (for an
  ensemble that records it) per-sleeve PnL contribution, plus their Herfindahls.

Attribution caveat: cross-sectional PnL is the *gross* close-to-close
contribution `w[t] * r[t+1] * equity[t]`, weights forward-filled from the last
rebalance and lagged one bar (no lookahead). It deliberately excludes costs and
financing — those are portfolio-level and already in the headline metrics — so
the per-asset total is gross PnL, a few percent above net. The shares are what
matter and they are robust to that gap.

The gate encodes the acceptance criteria: no month > 25% of PnL, the best 5% of
days must not exceed total return, no single asset/sector/sleeve may dominate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# Gate thresholds (acceptance criteria). Kept as module constants so the
# dashboard and reports cite the same numbers the gate enforces.
MAX_MONTH_PCT = 25.0          # no calendar month may exceed this share of PnL
MAX_BEST5PCT_SHARE = 100.0    # the best 5% of days must not exceed total return
MAX_ASSET_PCT = 40.0          # no single name may exceed this share of PnL
MAX_SECTOR_PCT = 55.0         # no single sector may exceed this share of PnL
MAX_SLEEVE_PCT = 70.0         # no single sleeve may exceed this share of PnL


def _active_weights(weights_df: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Forward-fill rebalance weights onto the full bar index and lag one bar.

    `weights_df` is indexed by the rebalance timestamps the engine recorded
    (the weights that became active at that bar). Reindexing + ffill gives the
    book held on every bar; `.shift(1)` makes bar t earn the return from the
    book held at t-1 -> t, which is the no-lookahead convention.
    """
    if weights_df.empty:
        return pd.DataFrame(0.0, index=index, columns=[])
    active = weights_df.reindex(index, method="ffill").fillna(0.0)
    return active.shift(1).fillna(0.0)


def per_asset_pnl(
    close: pd.DataFrame,
    weights_df: pd.DataFrame,
    equity: pd.Series,
) -> pd.DataFrame:
    """Gross per-asset PnL ($) per bar: w[t-1] * r[t] * equity[t-1].

    Returns a [time x asset] frame whose grand total is the gross PnL of the
    book. Used for asset / sector concentration and per-asset Herfindahl.
    """
    cols = [c for c in weights_df.columns if c in close.columns]
    if not cols:
        return pd.DataFrame(index=close.index)
    rets = close[cols].pct_change().fillna(0.0)
    active = _active_weights(weights_df[cols], close.index)
    eq_lag = equity.reindex(close.index).ffill().shift(1)
    pnl = active.mul(rets).mul(eq_lag, axis=0)
    return pnl.dropna(how="all")


def _share_table(contrib: pd.Series) -> pd.DataFrame:
    """Signed PnL per key plus its share of total *positive* PnL, sorted."""
    contrib = contrib.dropna().sort_values(ascending=False)
    pos_total = contrib[contrib > 0].sum()
    denom = pos_total if pos_total > 0 else (abs(contrib.sum()) or 1.0)
    return pd.DataFrame({
        "pnl": contrib.round(2),
        "share_pct": (100 * contrib / denom).round(1),
    })


def _herfindahl(contrib: pd.Series) -> float:
    """Herfindahl index (0..1) of positive PnL shares. 1 = one source carries
    everything; 1/N = perfectly even. Negative contributors are dropped."""
    pos = contrib[contrib > 0]
    total = pos.sum()
    if total <= 0 or len(pos) == 0:
        return 1.0
    shares = (pos / total).to_numpy()
    return float(np.square(shares).sum())


def _drawdown_contribution(equity: pd.Series) -> dict:
    """The worst drawdown and the share of *cumulative* loss it represents."""
    equity = equity.dropna()
    if len(equity) < 3:
        return {"max_drawdown_pct": None, "worst_dd_loss_share_pct": None}
    peak = equity.cummax()
    dd = equity / peak - 1.0
    max_dd = float(dd.min())
    # how much of the total down-day PnL fell inside the worst drawdown episode
    rets = equity.pct_change().fillna(0.0)
    trough = dd.idxmin()
    in_peak = equity.loc[:trough].idxmax()
    episode = rets.loc[in_peak:trough]
    down_total = rets[rets < 0].sum()
    share = float(episode[episode < 0].sum() / down_total) if down_total < 0 else None
    return {
        "max_drawdown_pct": round(100 * max_dd, 1),
        "worst_dd_loss_share_pct": round(100 * share, 1) if share is not None else None,
    }


@dataclass
class ConcentrationReport:
    """Full concentration picture for one equity curve (+ optional attribution)."""

    # time-based (equity only)
    max_month_pct: float | None
    max_day_pct: float | None
    best5pct_share: float | None
    monthly_herfindahl: float | None
    n_months: int
    # cross-sectional (needs weights)
    top_asset: str | None = None
    top_asset_pct: float | None = None
    asset_herfindahl: float | None = None
    top_sector: str | None = None
    top_sector_pct: float | None = None
    top_sleeve: str | None = None
    top_sleeve_pct: float | None = None
    sleeve_herfindahl: float | None = None
    # drawdown
    max_drawdown_pct: float | None = None
    worst_dd_loss_share_pct: float | None = None
    # tables (not serialized into the flat dict)
    monthly_table: pd.DataFrame | None = field(default=None, repr=False)
    daily_top: pd.DataFrame | None = field(default=None, repr=False)
    asset_table: pd.DataFrame | None = field(default=None, repr=False)
    sector_table: pd.DataFrame | None = field(default=None, repr=False)
    sleeve_table: pd.DataFrame | None = field(default=None, repr=False)

    def concentration_score(self) -> float:
        """0 (evenly spread) .. 100 (one source carries everything). A blend of
        the worst month share, the best-5%-of-days share and the per-asset
        Herfindahl — the three failure modes the report named. Lower is better."""
        parts: list[float] = []
        if self.max_month_pct is not None:
            parts.append(min(self.max_month_pct / MAX_MONTH_PCT, 2.0) * 50.0)
        if self.best5pct_share is not None:
            parts.append(min(self.best5pct_share / MAX_BEST5PCT_SHARE, 2.0) * 50.0)
        if self.asset_herfindahl is not None:
            parts.append(min(self.asset_herfindahl * 100.0, 100.0))
        return round(float(np.mean(parts)) if parts else 0.0, 1)

    def gate(self) -> "ConcentrationGate":
        return concentration_gate(self)

    def to_flat(self) -> dict:
        return {
            "max_month_pct": self.max_month_pct,
            "max_day_pct": self.max_day_pct,
            "best5pct_share": self.best5pct_share,
            "monthly_herfindahl": self.monthly_herfindahl,
            "top_asset": self.top_asset,
            "top_asset_pct": self.top_asset_pct,
            "asset_herfindahl": self.asset_herfindahl,
            "top_sector": self.top_sector,
            "top_sector_pct": self.top_sector_pct,
            "top_sleeve": self.top_sleeve,
            "top_sleeve_pct": self.top_sleeve_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "concentration_score": self.concentration_score(),
        }


@dataclass
class ConcentrationGate:
    passed: bool
    checks: dict[str, bool]
    reasons: list[str]


def concentration_gate(report: ConcentrationReport) -> ConcentrationGate:
    """Pass/fail against the acceptance criteria. Cross-sectional checks only
    fire when the attribution was supplied (None = not measured = not failed)."""
    checks: dict[str, bool] = {}
    reasons: list[str] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks[name] = ok
        if not ok:
            reasons.append(detail)

    if report.max_month_pct is not None:
        check("no month > 25% of PnL", report.max_month_pct <= MAX_MONTH_PCT,
              f"worst month is {report.max_month_pct}% of PnL (limit {MAX_MONTH_PCT}%)")
    if report.best5pct_share is not None:
        check("best 5% days <= total return", report.best5pct_share <= MAX_BEST5PCT_SHARE,
              f"best 5% of days are {report.best5pct_share}% of total return "
              f"(limit {MAX_BEST5PCT_SHARE}%)")
    if report.top_asset_pct is not None:
        check("no asset > 40% of PnL", report.top_asset_pct <= MAX_ASSET_PCT,
              f"{report.top_asset} alone is {report.top_asset_pct}% of PnL "
              f"(limit {MAX_ASSET_PCT}%)")
    if report.top_sector_pct is not None:
        check("no sector > 55% of PnL", report.top_sector_pct <= MAX_SECTOR_PCT,
              f"sector {report.top_sector} is {report.top_sector_pct}% of PnL "
              f"(limit {MAX_SECTOR_PCT}%)")
    if report.top_sleeve_pct is not None:
        check("no sleeve > 70% of PnL", report.top_sleeve_pct <= MAX_SLEEVE_PCT,
              f"sleeve {report.top_sleeve} is {report.top_sleeve_pct}% of PnL "
              f"(limit {MAX_SLEEVE_PCT}%)")
    return ConcentrationGate(passed=all(checks.values()), checks=checks, reasons=reasons)


def analyze_concentration(
    equity: pd.Series,
    *,
    close: pd.DataFrame | None = None,
    weights_df: pd.DataFrame | None = None,
    sectors: dict[str, str] | None = None,
    sleeve_pnl: pd.DataFrame | None = None,
    top_n_days: int = 10,
) -> ConcentrationReport:
    """Build the full concentration report.

    `equity` is required (time-based diagnostics). Pass `close` + `weights_df`
    to add per-asset / per-sector attribution, and `sleeve_pnl` (a [time x
    sleeve] PnL frame, e.g. from `attribute_sleeves`) for per-sleeve attribution.
    """
    equity = equity.dropna()
    rets = equity.pct_change().dropna()
    pnl = rets * equity.shift(1).reindex(rets.index)
    total = float(pnl.sum())

    # --- time-based ---
    max_month_pct = max_day_pct = best5pct_share = monthly_herfindahl = None
    monthly_table = daily_top = None
    n_months = 0
    if total != 0 and len(pnl) >= 3:
        monthly = pnl.groupby(pnl.index.to_period("M")).sum()
        n_months = int(len(monthly))
        max_month_pct = round(100 * float(monthly.max() / total), 1)
        monthly_herfindahl = round(_herfindahl(monthly), 3)
        monthly_table = pd.DataFrame({
            "pnl": monthly.round(2),
            "share_pct": (100 * monthly / total).round(1),
        })
        monthly_table.index = monthly_table.index.astype(str)
        k = max(1, int(0.05 * len(pnl)))
        best5pct_share = round(100 * float(pnl.nlargest(k).sum() / total), 1)
        max_day_pct = round(100 * float(pnl.max() / total), 1)
        top = pnl.nlargest(top_n_days)
        daily_top = pd.DataFrame({
            "date": [str(d.date()) for d in top.index],
            "pnl": top.round(2).to_numpy(),
            "share_pct": (100 * top / total).round(1).to_numpy(),
        })

    report = ConcentrationReport(
        max_month_pct=max_month_pct, max_day_pct=max_day_pct,
        best5pct_share=best5pct_share, monthly_herfindahl=monthly_herfindahl,
        n_months=n_months, monthly_table=monthly_table, daily_top=daily_top,
        **_drawdown_contribution(equity),
    )

    # --- cross-sectional (asset / sector) ---
    if close is not None and weights_df is not None and not weights_df.empty:
        asset_pnl = per_asset_pnl(close, weights_df, equity)
        if not asset_pnl.empty:
            asset_contrib = asset_pnl.sum()
            report.asset_table = _share_table(asset_contrib)
            report.asset_herfindahl = round(_herfindahl(asset_contrib), 3)
            if not report.asset_table.empty:
                report.top_asset = str(report.asset_table.index[0])
                report.top_asset_pct = float(report.asset_table["share_pct"].iloc[0])
            if sectors:
                sec = asset_contrib.groupby(
                    lambda s: sectors.get(s, "other")).sum()
                report.sector_table = _share_table(sec)
                if not report.sector_table.empty:
                    report.top_sector = str(report.sector_table.index[0])
                    report.top_sector_pct = float(report.sector_table["share_pct"].iloc[0])

    # --- per-sleeve ---
    if sleeve_pnl is not None and not sleeve_pnl.empty:
        sleeve_contrib = sleeve_pnl.sum()
        report.sleeve_table = _share_table(sleeve_contrib)
        report.sleeve_herfindahl = round(_herfindahl(sleeve_contrib), 3)
        if not report.sleeve_table.empty:
            report.top_sleeve = str(report.sleeve_table.index[0])
            report.top_sleeve_pct = float(report.sleeve_table["share_pct"].iloc[0])

    return report


def attribute_sleeves(
    history: list[tuple[pd.Timestamp, dict[str, pd.Series]]],
    close: pd.DataFrame,
    equity: pd.Series,
) -> pd.DataFrame:
    """Per-sleeve gross PnL ($) per bar from an ensemble's recorded history.

    `history` is the list of `(timestamp, {sleeve: contribution_weights})` an
    ensemble accumulates when `record_history=True` — contribution weights are
    `allocation[sleeve] * sleeve_weights`, so they sum across sleeves to the
    portfolio book. Each sleeve is attributed exactly like `per_asset_pnl`.
    """
    if not history:
        return pd.DataFrame()
    names = sorted({n for _, d in history for n in d})
    # build a per-sleeve weight panel indexed by rebalance ts
    frames: dict[str, pd.DataFrame] = {}
    for name in names:
        rows = {ts: d[name] for ts, d in history if name in d}
        frames[name] = pd.DataFrame(rows).T.reindex(columns=close.columns).fillna(0.0)
    eq_lag = equity.reindex(close.index).ffill().shift(1)
    rets = close.pct_change().fillna(0.0)
    out = {}
    for name, wdf in frames.items():
        active = _active_weights(wdf, close.index)
        out[name] = active.mul(rets).sum(axis=1).mul(eq_lag)
    return pd.DataFrame(out).dropna(how="all")
