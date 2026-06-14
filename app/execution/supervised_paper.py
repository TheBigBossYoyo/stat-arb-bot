"""Supervised paper/shadow PERIOD workflow (Phase 6).

Phase 5 records individual shadow/paper cycles. Phase 6 wraps them in a
calendar-aware SESSION so a real 30-90 day supervised period can be run, tracked
and judged honestly:

* a `PaperSession` pins the product, mode, start date and a minimum number of
  CALENDAR days; it persists across restarts;
* each day appends to seven record tables — daily reports, orders,
  reconciliations, TCA, risk snapshots, benchmark snapshots (and the session
  itself) — under `runtime/paper/<product>/`;
* the final report aggregates the period and recommends pass/fail, but it
  NEVER claims the period "passed" on replayed bars: distinct FORWARD calendar
  days are counted separately from replay days, and a session that has not
  accrued `min_days` of forward time cannot pass.

The honest framing: after setup a product is "ELIGIBLE TO BEGIN a supervised
paper/shadow period" — it earns "period passed" only once the calendar days
actually elapse. Live is never in scope here.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.core.types import utc_now

TABLES = ("daily_reports", "orders", "reconciliations", "tca",
          "risk_snapshots", "benchmark_snapshots")


@dataclass
class PaperSession:
    session_id: str
    product: str
    mode: str                 # shadow | demo_preview | demo_execute
    started_at: str           # ISO date the session began
    min_days: int
    starting_cash: float
    status: str = "active"    # active | stopped
    stop_reason: str = ""
    created_at: str = ""
    human_interventions: list[str] = field(default_factory=list)

    @staticmethod
    def new(product: str, mode: str, *, min_days: int, starting_cash: float) -> PaperSession:
        now = utc_now().replace(tzinfo=None)
        return PaperSession(
            session_id=f"PS-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}",
            product=product, mode=mode, started_at=now.date().isoformat(),
            min_days=min_days, starting_cash=starting_cash,
            created_at=now.isoformat())


class SupervisedPaperStore:
    """Per-product persistence: one session + seven append-only JSONL tables."""

    def __init__(self, runtime_dir: Path, product: str) -> None:
        self.base = Path(runtime_dir) / "paper" / product
        self.base.mkdir(parents=True, exist_ok=True)
        self.product = product

    # -- session ---------------------------------------------------------------

    @property
    def _session_path(self) -> Path:
        return self.base / "session.json"

    def current_session(self) -> PaperSession | None:
        if not self._session_path.exists():
            return None
        return PaperSession(**json.loads(self._session_path.read_text(encoding="utf-8")))

    def save_session(self, session: PaperSession) -> None:
        self._session_path.write_text(json.dumps(asdict(session), default=str), encoding="utf-8")

    def start_session(self, session: PaperSession) -> None:
        self.save_session(session)

    def stop_session(self, reason: str) -> PaperSession | None:
        s = self.current_session()
        if s is None:
            return None
        s.status = "stopped"
        s.stop_reason = reason
        self.save_session(s)
        return s

    # -- tables ----------------------------------------------------------------

    def _table_path(self, table: str) -> Path:
        if table not in TABLES:
            raise ValueError(f"unknown table {table!r}; choose from {TABLES}")
        return self.base / f"{table}.jsonl"

    def append(self, table: str, row: dict) -> None:
        with self._table_path(table).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, default=str) + "\n")

    def load(self, table: str) -> list[dict]:
        p = self._table_path(table)
        if not p.exists():
            return []
        return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def reset(self) -> None:
        """Delete the session + all tables (start a fresh period)."""
        for table in TABLES:
            p = self._table_path(table)
            if p.exists():
                p.unlink()
        if self._session_path.exists():
            self._session_path.unlink()


def _distinct_days(rows: list[dict], *, replay: bool | None = None) -> list[str]:
    days = set()
    for r in rows:
        if replay is not None and bool(r.get("replay", False)) != replay:
            continue
        d = str(r.get("date", ""))[:10]
        if d:
            days.add(d)
    return sorted(days)


def supervised_status(store: SupervisedPaperStore) -> dict:
    s = store.current_session()
    if s is None:
        return {"active": False, "message": "no session — run supervised-paper-start"}
    daily = store.load("daily_reports")
    forward_days = _distinct_days(daily, replay=False)
    replay_days = _distinct_days(daily, replay=True)
    last = daily[-1] if daily else {}
    return {
        "active": s.status == "active",
        "session_id": s.session_id,
        "product": s.product,
        "mode": s.mode,
        "status": s.status,
        "started_at": s.started_at,
        "min_days": s.min_days,
        "forward_days_completed": len(forward_days),
        "replay_days_recorded": len(replay_days),
        "cycles": len(daily),
        "last_date": last.get("date"),
        "last_equity": last.get("equity"),
        "stop_reason": s.stop_reason,
    }


def _max_drawdown(equities: list[float]) -> float:
    peak = -1e18
    mdd = 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            mdd = min(mdd, e / peak - 1.0)
    return mdd


def final_report(store: SupervisedPaperStore, *, min_days: int = 30,
                 max_drawdown_policy_pct: float = 25.0) -> dict:
    """Aggregate the period and recommend pass/fail. A period only PASSES with
    >= `min_days` distinct FORWARD calendar days (replay days never satisfy it)."""
    s = store.current_session()
    daily = store.load("daily_reports")
    orders = store.load("orders")
    recon = store.load("reconciliations")
    tca = store.load("tca")
    risk = store.load("risk_snapshots")
    bench = store.load("benchmark_snapshots")

    forward_days = _distinct_days(daily, replay=False)
    replay_days = _distinct_days(daily, replay=True)
    equities = [float(r["equity"]) for r in daily if r.get("equity") is not None]
    start_eq = equities[0] if equities else (s.starting_cash if s else 0.0)
    end_eq = equities[-1] if equities else start_eq
    paper_return = (100 * (end_eq / start_eq - 1.0)) if start_eq else 0.0
    dd = 100 * _max_drawdown(equities) if equities else 0.0

    sent = sum(int(r.get("demo_orders_sent", 0)) for r in daily)
    rejected = sum(int(r.get("n_rejected", 0)) for r in daily)
    broker_errors = sum(int(r.get("broker_errors", 0)) for r in daily)
    slippage = [float(t["realized_slippage_bps"]) for t in tca
                if t.get("realized_slippage_bps") is not None]
    fees = sum(float(t.get("fees", 0.0)) for t in tca)
    risk_breaches = sum(1 for r in risk if r.get("breach"))
    data_quality_events = sum(int(r.get("data_quality_events", 0)) for r in daily)
    interventions = list(s.human_interventions) if s else []

    bench_return = None
    if bench:
        b0, b1 = bench[0], bench[-1]
        if b0.get("spy_equity") and b1.get("spy_equity"):
            bench_return = round(100 * (b1["spy_equity"] / b0["spy_equity"] - 1.0), 2)

    max_drift = max((float(r.get("total_abs_drift", 0.0)) for r in recon), default=0.0)
    n_short = max((int(r.get("n_short_positions", 0)) for r in recon), default=0)
    max_conc = max((float(r.get("top_weight", 0.0)) for r in daily), default=0.0)

    # pass/fail recommendation
    checks = {
        f"forward calendar days >= {min_days}": len(forward_days) >= min_days,
        "no short positions ever": n_short == 0,
        "reject rate < 5%": (rejected / max(1, sent + rejected) * 100) < 5.0
                            if (sent + rejected) else True,
        "no broker errors": broker_errors == 0,
        "drawdown within policy": abs(dd) <= max_drawdown_policy_pct,
        "no risk breaches": risk_breaches == 0,
        "paper PnL not catastrophic": paper_return > -20.0,
    }
    recommendation = "PASS" if all(checks.values()) else "FAIL"
    replay_only = len(forward_days) < min_days and len(replay_days) > 0

    return {
        "session_id": s.session_id if s else None,
        "product": s.product if s else store.product,
        "mode": s.mode if s else None,
        "status": s.status if s else None,
        "days_completed_forward": len(forward_days),
        "days_recorded_replay": len(replay_days),
        "signals_generated": len(daily),
        "orders_planned": len(orders),
        "demo_orders_sent": sent,
        "orders_rejected": rejected,
        "broker_errors": broker_errors,
        "avg_realized_slippage_bps": round(sum(slippage) / len(slippage), 2) if slippage else 0.0,
        "fees": round(fees, 2),
        "paper_pnl_pct": round(paper_return, 2),
        "benchmark_pnl_pct": bench_return,
        "tracking_vs_backtest": "see long-only-readiness backtest Sharpe/return for comparison",
        "max_concentration_top_weight": round(max_conc, 4),
        "max_drawdown_pct": round(dd, 2),
        "max_drift_from_target": round(max_drift, 4),
        "risk_breaches": risk_breaches,
        "data_quality_events": data_quality_events,
        "human_interventions": interventions,
        "checks": checks,
        "recommendation": recommendation,
        "replay_only_not_forward": replay_only,
        "verdict": (
            "REPLAY ONLY — pipeline validated but NOT a forward calendar period; "
            "not eligible to claim 'period passed'." if replay_only else
            ("SUPERVISED PERIOD PASSED (forward) — recommend proceeding to the next "
             "governance stage. LIVE REMAINS BLOCKED." if recommendation == "PASS" else
             "SUPERVISED PERIOD INCOMPLETE/FAILED — see failed checks. LIVE REMAINS BLOCKED.")),
        "live_eligible": False,
    }
