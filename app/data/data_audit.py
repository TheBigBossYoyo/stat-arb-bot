"""Dataset auditing: is this data acceptable for research, and what biases remain?

`check_bars` (data_quality.py) validates one frame at download time. This
module audits what is actually IN STORAGE for a universe — the data research
will read — and produces a persisted, honest verdict:

* per-symbol coverage, gaps (calendar-aware for daily equity bars), duplicate
  timestamps, stale runs (flat closes), outlier returns, zero-volume share,
  dividend-adjustment coverage, last-bar staleness;
* universe-level alignment loss (how much history the youngest symbol deletes
  from everyone via intersection alignment — audit W-10);
* survivorship status from universe metadata (audit W-04) — a `static_survivor`
  universe can NEVER produce a verdict better than `research_only`.

Verdicts:
    ok               — clean and point-in-time: usable as evidence
    research_only    — usable for viability work; named biases remain
    not_acceptable   — known-broken data; do not draw conclusions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from app.core.logging import get_logger
from app.core.types import interval_minutes, utc_now
from app.data.storage import Storage
from app.data.universe import get_universe, get_universe_meta

log = get_logger(__name__)


@dataclass
class SymbolAudit:
    symbol: str
    rows: int
    first: datetime | None
    last: datetime | None
    missing_pct: float
    duplicates: int
    max_stale_run: int            # longest run of identical closes
    max_abs_return: float
    zero_volume_pct: float
    adj_coverage_pct: float       # % of bars with adj_close populated
    issues: list[str] = field(default_factory=list)


@dataclass
class UniverseAuditReport:
    universe: str
    interval: str
    source: str | None
    generated_at: datetime
    asset_class: str
    survivorship: str
    survivorship_note: str
    symbols: list[SymbolAudit]
    missing_symbols: list[str]
    aligned_start: datetime | None
    aligned_end: datetime | None
    alignment_loss_pct: float     # history deleted by intersection alignment
    adj_coverage_pct: float
    verdict: str                  # ok | research_only | not_acceptable
    verdict_reasons: list[str]

    def to_markdown(self) -> str:
        lines = [
            f"# Data audit — {self.universe} ({self.interval})",
            "",
            f"- generated: {self.generated_at:%Y-%m-%d %H:%M} UTC",
            f"- source: {self.source or 'any'}  |  asset class: {self.asset_class}",
            f"- survivorship: **{self.survivorship}** — {self.survivorship_note}",
            f"- aligned window: {self.aligned_start} → {self.aligned_end} "
            f"(alignment deletes {self.alignment_loss_pct:.1f}% of stored history)",
            f"- dividend-adjustment coverage: {self.adj_coverage_pct:.1f}%",
            f"- **verdict: {self.verdict.upper()}**",
            "",
        ]
        for reason in self.verdict_reasons:
            lines.append(f"  - {reason}")
        lines += ["", "| symbol | rows | span | missing% | stale run | max\\|ret\\| | adj% | issues |",
                  "| --- | ---: | --- | ---: | ---: | ---: | ---: | --- |"]
        for s in self.symbols:
            span = f"{s.first:%Y-%m-%d}→{s.last:%Y-%m-%d}" if s.first and s.last else "—"
            lines.append(
                f"| {s.symbol} | {s.rows} | {span} | {s.missing_pct:.1f} "
                f"| {s.max_stale_run} | {s.max_abs_return:.3f} "
                f"| {s.adj_coverage_pct:.0f} | {'; '.join(s.issues) or '—'} |"
            )
        if self.missing_symbols:
            lines += ["", f"**Missing from storage:** {', '.join(self.missing_symbols)}"]
        return "\n".join(lines) + "\n"


def _expected_bars(first: pd.Timestamp, last: pd.Timestamp, interval: str,
                   asset_class: str) -> int:
    if interval == "1d" and asset_class in ("equity", "fx", "unknown"):
        # weekday calendar; ~9 US holidays/yr are tolerated via the threshold
        return len(pd.bdate_range(first, last))
    step = pd.Timedelta(minutes=interval_minutes(interval))
    return int((last - first) / step) + 1


def audit_symbol(df: pd.DataFrame, symbol: str, interval: str, asset_class: str,
                 *, max_missing_pct: float, max_abs_return: float = 0.5,
                 max_stale_run: int = 5) -> SymbolAudit:
    """`df`: single-symbol long frame [ts, open, high, low, close, volume, adj_close]."""
    if df.empty:
        return SymbolAudit(symbol, 0, None, None, 100.0, 0, 0, 0.0, 0.0, 0.0,
                           issues=["no data in storage"])
    ts = pd.to_datetime(df["ts"])
    first, last = ts.min(), ts.max()
    duplicates = int(ts.duplicated().sum())
    expected = _expected_bars(first, last, interval, asset_class)
    missing_pct = max(0.0, 100.0 * (expected - len(df)) / expected) if expected else 0.0

    close = df.sort_values("ts")["close"].to_numpy(dtype=float)
    stale = flat = 0
    for i in range(1, len(close)):
        flat = flat + 1 if close[i] == close[i - 1] else 0
        stale = max(stale, flat)
    rets = np.abs(np.diff(np.log(np.where(close > 0, close, np.nan))))
    max_ret = float(np.nanmax(rets)) if len(rets) else 0.0
    zero_vol_pct = 100.0 * float((df["volume"] <= 0).mean())
    adj_pct = (100.0 * float(df["adj_close"].notna().mean())
               if "adj_close" in df.columns else 0.0)

    issues: list[str] = []
    if duplicates:
        issues.append(f"{duplicates} duplicate timestamps")
    if missing_pct > max_missing_pct:
        issues.append(f"missing {missing_pct:.1f}% of expected bars")
    if stale >= max_stale_run:
        issues.append(f"{stale} consecutive identical closes (stale/halted?)")
    if max_ret > max_abs_return:
        issues.append(f"outlier bar |return| {max_ret:.2f} (bad tick or unadjusted action?)")
    age_days = (utc_now().replace(tzinfo=None) - last.to_pydatetime()).days
    if age_days > 7:
        issues.append(f"last bar is {age_days} days old")
    return SymbolAudit(symbol, len(df), first.to_pydatetime(), last.to_pydatetime(),
                       missing_pct, duplicates, stale, max_ret, zero_vol_pct, adj_pct,
                       issues=issues)


def audit_universe(
    storage: Storage,
    universe: str,
    interval: str,
    source: str | None = None,
    symbols: list[str] | None = None,
) -> UniverseAuditReport:
    names = symbols or get_universe(universe)
    meta = get_universe_meta(universe)
    long_df = storage.load_bars(names, interval, source=source)
    max_missing = 6.0 if interval == "1d" else 5.0   # 1d: weekday calendar + holidays

    audits: list[SymbolAudit] = []
    missing: list[str] = []
    spans: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    for symbol in names:
        sdf = long_df[long_df["symbol"] == symbol]
        if sdf.empty:
            missing.append(symbol)
            continue
        a = audit_symbol(sdf, symbol, interval, meta.asset_class,
                         max_missing_pct=max_missing)
        audits.append(a)
        spans.append((pd.Timestamp(a.first), pd.Timestamp(a.last), a.rows))

    aligned_start = max(s[0] for s in spans) if spans else None
    aligned_end = min(s[1] for s in spans) if spans else None
    total_rows = sum(s[2] for s in spans)
    if spans and aligned_start is not None and aligned_end is not None and total_rows:
        kept = sum(
            min(rows, _expected_bars(max(lo, aligned_start), min(hi, aligned_end),
                                     interval, meta.asset_class))
            for lo, hi, rows in spans
        )
        alignment_loss = max(0.0, 100.0 * (1.0 - kept / total_rows))
    else:
        alignment_loss = 0.0
    adj_overall = (float(np.mean([a.adj_coverage_pct for a in audits]))
                   if audits else 0.0)

    reasons: list[str] = []
    verdict = "ok"
    if meta.survivorship == "static_survivor":
        verdict = "research_only"
        reasons.append(
            f"survivorship bias: {meta.selection_note} — results are viability "
            "sketches, upper bounds for momentum-style strategies")
    if meta.asset_class == "equity" and adj_overall < 99.0:
        verdict = "research_only" if verdict == "ok" else verdict
        reasons.append(
            f"dividend adjustment covers only {adj_overall:.1f}% of bars — re-run "
            "`statarb download-data` to backfill adj_close; raw-price research "
            "tilts ranks against high-yield names (audit W-05)")
    hard_broken = [a.symbol for a in audits
                   if a.missing_pct > 25.0 or a.duplicates > 0 or a.rows < 30]
    if missing:
        reasons.append(f"{len(missing)} symbols have no stored data: {missing[:8]}")
    if hard_broken:
        verdict = "not_acceptable"
        reasons.append(f"hard data problems in: {hard_broken}")
    if alignment_loss > 20.0:
        reasons.append(
            f"intersection alignment deletes {alignment_loss:.1f}% of stored history "
            "(youngest symbol truncates everyone — audit W-10)")
    soft_issues = [a for a in audits if a.issues]
    if soft_issues and verdict == "ok":
        verdict = "research_only"
        reasons.append(f"{len(soft_issues)} symbols carry data-quality warnings")

    return UniverseAuditReport(
        universe=universe, interval=interval, source=source,
        generated_at=utc_now().replace(tzinfo=None),
        asset_class=meta.asset_class, survivorship=meta.survivorship,
        survivorship_note=meta.selection_note,
        symbols=audits, missing_symbols=missing,
        aligned_start=aligned_start.to_pydatetime() if aligned_start is not None else None,
        aligned_end=aligned_end.to_pydatetime() if aligned_end is not None else None,
        alignment_loss_pct=alignment_loss, adj_coverage_pct=adj_overall,
        verdict=verdict, verdict_reasons=reasons,
    )
