"""Supervised shadow / paper recording with TCA (Phase 5).

Two supervised modes that bridge backtest and live, per product path:

* **shadow** — generate the daily target orders and RECORD them with the price
  context, but execute nothing. This is the safest first step: it proves the
  pipeline produces sane, constraint-respecting orders day after day, and lets
  expected vs realized slippage be measured against the next bar.
* **paper** — additionally simulate fills against a persisted book (cash +
  positions + equity), so a real paper-PnL track record accrues over calendar
  time, with rejected-order and transaction-cost accounting.

Everything persists to JSONL under `runtime/shadow/<product>.jsonl` so a
multi-day period survives restarts. No real orders are ever sent; the futures
side is testnet/paper only and live stays blocked.

The honest point of Phase 5: a strategy earns paper-eligibility by surviving a
supervised period with sane TCA — not by a backtest number.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ShadowOrder:
    symbol: str
    side: str
    quantity: float
    ref_price: float
    limit_price: float | None
    target_weight: float
    expected_slippage_bps: float


@dataclass
class ShadowCycle:
    ts: str
    product: str
    mode: str                      # shadow | paper
    equity: float
    cash: float
    n_orders: int
    n_rejected: int
    gross_exposure: float
    orders: list[dict] = field(default_factory=list)
    rejected: list[list] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    realized_pnl: float = 0.0      # paper mode: PnL since last cycle


def _log_path(runtime_dir: Path, product: str) -> Path:
    d = runtime_dir / "shadow"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{product}.jsonl"


class ShadowRecorder:
    """Append-only JSONL recorder for shadow/paper cycles."""

    def __init__(self, runtime_dir: Path, product: str) -> None:
        self.path = _log_path(runtime_dir, product)
        self.product = product

    def record(self, cycle: ShadowCycle) -> None:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(cycle), default=str) + "\n")

    def load(self, since: datetime | None = None) -> list[dict]:
        if not self.path.exists():
            return []
        rows = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()]
        if since is not None:
            rows = [r for r in rows if datetime.fromisoformat(r["ts"]) >= since]
        return rows


@dataclass
class PaperBook:
    """Persisted simulated book for paper mode."""

    cash: float
    positions: dict[str, float] = field(default_factory=dict)

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(q * prices.get(s, 0.0) for s, q in self.positions.items())

    def apply_fill(self, symbol: str, side: str, qty: float, price: float, fee: float) -> None:
        signed = qty if side == "buy" else -qty
        self.positions[symbol] = self.positions.get(symbol, 0.0) + signed
        self.cash -= signed * price + fee
        if abs(self.positions[symbol]) < 1e-9:
            self.positions.pop(symbol, None)


def book_path(runtime_dir: Path, product: str) -> Path:
    d = runtime_dir / "shadow"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{product}_book.json"


def load_paper_book(runtime_dir: Path, product: str, starting_cash: float) -> PaperBook:
    p = book_path(runtime_dir, product)
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        return PaperBook(cash=d["cash"], positions=d.get("positions", {}))
    return PaperBook(cash=starting_cash)


def save_paper_book(runtime_dir: Path, product: str, book: PaperBook) -> None:
    book_path(runtime_dir, product).write_text(
        json.dumps({"cash": book.cash, "positions": book.positions}), encoding="utf-8")


def summarize_period(rows: list[dict]) -> dict:
    """Aggregate a shadow/paper period into TCA + readiness inputs."""
    if not rows:
        return {"cycles": 0}
    total_orders = sum(r["n_orders"] for r in rows)
    total_rejected = sum(r["n_rejected"] for r in rows)
    exp_slip = [o["expected_slippage_bps"] for r in rows for o in r["orders"]]
    realized = [r.get("realized_pnl", 0.0) for r in rows]
    equities = [r["equity"] for r in rows]
    ret_pct = (100 * (equities[-1] / equities[0] - 1.0)) if len(equities) > 1 and equities[0] else 0.0
    return {
        "cycles": len(rows),
        "first": rows[0]["ts"][:10],
        "last": rows[-1]["ts"][:10],
        "total_orders": total_orders,
        "total_rejected": total_rejected,
        "reject_rate_pct": round(100 * total_rejected / max(1, total_orders + total_rejected), 1),
        "avg_expected_slippage_bps": round(sum(exp_slip) / len(exp_slip), 2) if exp_slip else 0.0,
        "paper_return_pct": round(ret_pct, 2),
        "cumulative_realized_pnl": round(sum(realized), 2),
        "start_equity": round(equities[0], 2),
        "end_equity": round(equities[-1], 2),
    }


def paper_readiness(summary: dict, min_cycles: int = 20) -> tuple[bool, list[str]]:
    """A supervised period passes only with enough cycles, a low reject rate and
    sane TCA. Calendar time cannot be faked — `min_cycles` enforces it."""
    reasons: list[str] = []
    checks = {
        f"period length >= {min_cycles} cycles": summary.get("cycles", 0) >= min_cycles,
        "reject rate < 5%": summary.get("reject_rate_pct", 100) < 5.0,
        "expected slippage <= 25 bps": summary.get("avg_expected_slippage_bps", 999) <= 25.0,
        "paper PnL not catastrophic": summary.get("paper_return_pct", -100) > -20.0,
    }
    for name, ok in checks.items():
        if not ok:
            reasons.append(name)
    return all(checks.values()), reasons
