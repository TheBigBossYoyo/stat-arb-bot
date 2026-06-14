"""Reconcile the local target book against the demo broker positions (Phase 5).

After a demo cycle the local intended book and the broker's actual positions can
diverge — partial fills, rejections, rounding, dividends, queued orders. This
module quantifies that drift so a supervised paper period can see, every day,
how faithfully the demo account tracks the strategy's targets.

Pure / offline: it takes a target-weight dict and a {symbol: quantity} snapshot
of broker positions plus prices, and returns a per-name and aggregate drift
report. It never trades.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReconciliationRow:
    symbol: str
    target_weight: float
    actual_weight: float
    target_qty: float
    actual_qty: float
    drift_weight: float       # actual - target (signed)

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "target_weight": round(self.target_weight, 4),
            "actual_weight": round(self.actual_weight, 4),
            "target_qty": round(self.target_qty, 4),
            "actual_qty": round(self.actual_qty, 4),
            "drift_weight": round(self.drift_weight, 4),
        }


@dataclass
class ReconciliationReport:
    rows: list[ReconciliationRow] = field(default_factory=list)
    equity: float = 0.0
    cash: float = 0.0
    total_abs_drift: float = 0.0          # sum |actual_w - target_w| (one-sided gross drift)
    max_name_drift: float = 0.0
    n_short_positions: int = 0            # MUST be zero on Invest/ISA
    broker_only_symbols: list[str] = field(default_factory=list)

    @property
    def in_sync(self) -> bool:
        """Within a 2% gross-weight tolerance and no shorts present."""
        return self.total_abs_drift <= 0.02 and self.n_short_positions == 0

    def summary(self) -> dict:
        return {
            "equity": round(self.equity, 2),
            "cash": round(self.cash, 2),
            "total_abs_drift": round(self.total_abs_drift, 4),
            "max_name_drift": round(self.max_name_drift, 4),
            "n_short_positions": self.n_short_positions,
            "in_sync": self.in_sync,
            "broker_only_symbols": self.broker_only_symbols,
        }


def reconcile_long_only(
    target_weights: dict[str, float],
    broker_positions: dict[str, float],
    prices: dict[str, float],
    cash: float,
) -> ReconciliationReport:
    """`broker_positions` maps symbol -> quantity from the demo account.

    Equity = cash + market value of all positions. Target quantities are implied
    by `target_weights * equity / price`. Drift is per-name actual-vs-target
    weight; a short broker position (quantity < 0) is flagged loudly — it must
    never appear on an Invest/ISA account."""
    held_value = sum(q * prices.get(s, 0.0) for s, q in broker_positions.items())
    equity = cash + held_value
    rows: list[ReconciliationRow] = []
    symbols = set(target_weights) | set(broker_positions)
    total_abs = 0.0
    max_drift = 0.0
    n_short = 0
    broker_only = []
    for sym in sorted(symbols):
        price = prices.get(sym, 0.0)
        tw = max(0.0, float(target_weights.get(sym, 0.0)))
        aq = float(broker_positions.get(sym, 0.0))
        if aq < -1e-9:
            n_short += 1
        aw = (aq * price / equity) if equity > 0 else 0.0
        tq = (tw * equity / price) if price > 0 else 0.0
        if sym not in target_weights and abs(aq) > 1e-9:
            broker_only.append(sym)
        drift = aw - tw
        total_abs += abs(drift)
        max_drift = max(max_drift, abs(drift))
        if abs(tw) > 1e-9 or abs(aq) > 1e-9:
            rows.append(ReconciliationRow(sym, tw, aw, tq, aq, drift))
    return ReconciliationReport(
        rows=rows, equity=equity, cash=cash,
        total_abs_drift=total_abs / 2.0,   # halve: gross one-sided drift
        max_name_drift=max_drift, n_short_positions=n_short,
        broker_only_symbols=broker_only)
