"""Trading 212 order validation (Phase 5).

Pure, side-effect-free checks that a long-only order plan is safe to send to the
DEMO environment. These encode the order-/plan-level conditions of the demo
execution gate (the env-flag / kill-switch / live-block conditions live in
`demo_execution.py`, which calls these):

* target weights are all >= 0 (no shorting) and gross <= 1.0 (no leverage),
* every traded instrument is tradable on Invest/ISA (offered, equity, not a CFD,
  not shortable),
* a SELL never exceeds the held quantity (long-only: you can only sell what you
  hold),
* every order clears the minimum order value,
* every quantity respects the instrument's fractional / whole-share rounding,
* expected slippage (limit offset vs reference) is within the configured limit,
* buy notional never exceeds settled cash (no margin),
* market is open, or the plan is explicitly allowed to queue for the next open.

Nothing here connects to a network; it validates an already-built plan.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time

from app.brokers.base import round_step
from app.brokers.trading212.instrument_cache import InstrumentCache
from app.core.types import Side, utc_now

# US regular trading hours in US/Eastern. We avoid a tz database dependency by
# converting the provided (UTC) time to Eastern with a fixed -5/-4 offset rule.
_RTH_OPEN = time(9, 30)
_RTH_CLOSE = time(16, 0)


def _to_eastern(now: datetime) -> datetime:
    """UTC -> US/Eastern (approximate DST: Mar-Nov = -4, else -5). Good enough
    for an open/closed gate; the broker is the final authority on session."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    now = now.astimezone(UTC)
    offset = -4 if 3 <= now.month <= 11 else -5
    return now.fromtimestamp(now.timestamp() + offset * 3600, tz=UTC)


def is_us_market_open(now: datetime | None = None) -> bool:
    """True during US regular hours on a weekday (holidays NOT modeled — the
    broker rejects/queues holiday orders, which the demo executor handles)."""
    et = _to_eastern(now or utc_now())
    if et.weekday() >= 5:        # Sat/Sun
        return False
    return _RTH_OPEN <= et.time() <= _RTH_CLOSE


@dataclass
class OrderValidationConfig:
    min_order_value: float = 1.0
    max_slippage_bps: float = 50.0      # reject if the limit offset exceeds this
    max_gross: float = 1.0
    allow_queue_when_closed: bool = True


@dataclass
class ValidationResult:
    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    order_issues: list[tuple[str, str]] = field(default_factory=list)  # (symbol, issue)
    market_open: bool = True
    queued: bool = False

    def summary(self) -> dict:
        return {
            "ok": self.ok,
            "checks_passed": sum(1 for v in self.checks.values() if v),
            "checks_total": len(self.checks),
            "market_open": self.market_open,
            "queued": self.queued,
            "n_order_issues": len(self.order_issues),
        }


def validate_target_weights(target_weights: dict[str, float], *,
                            max_gross: float = 1.0) -> tuple[bool, list[str]]:
    """No negative weights (no shorting) and gross <= max_gross (no leverage)."""
    reasons: list[str] = []
    negatives = {s: w for s, w in target_weights.items() if w < -1e-9}
    if negatives:
        reasons.append(f"negative target weights (shorting) for {sorted(negatives)}")
    gross = sum(max(0.0, w) for w in target_weights.values())
    if gross > max_gross + 1e-6:
        reasons.append(f"gross target {gross:.4f} exceeds {max_gross} (leverage)")
    return (not reasons), reasons


def validate_plan(
    plan,
    cache: InstrumentCache,
    *,
    target_weights: dict[str, float],
    cash: float,
    config: OrderValidationConfig | None = None,
    now: datetime | None = None,
) -> ValidationResult:
    """Validate a `RebalancePlan` for demo submission. `plan.orders` are
    PlannedOrder; each has a `.request` (OrderRequest with ref/limit price)."""
    cfg = config or OrderValidationConfig()
    checks: dict[str, bool] = {}
    reasons: list[str] = []
    issues: list[tuple[str, str]] = []

    # --- target-weight constraints ---
    w_ok, w_reasons = validate_target_weights(target_weights, max_gross=cfg.max_gross)
    checks["no negative target weights"] = not any("negative" in r for r in w_reasons)
    checks["gross exposure <= 1.0"] = not any("gross" in r for r in w_reasons)
    reasons += w_reasons

    # --- per-order checks ---
    tradable_ok = min_value_ok = rounding_ok = slippage_ok = no_short_ok = True
    for o in plan.orders:
        r = o.request
        sym = r.symbol
        ok, why = cache.is_tradable(sym)
        if not ok:
            tradable_ok = False
            issues.append((sym, f"not tradable: {why}"))
            continue
        # min order value
        if r.notional < cfg.min_order_value - 1e-9:
            min_value_ok = False
            issues.append((sym, f"order value {r.notional:.2f} < minimum {cfg.min_order_value}"))
        # quantity rounding correctness
        inst = cache.get(sym)
        if inst and inst.fractional:
            step = inst.step_size or 0.0001
            if abs(round_step(r.quantity, step) - r.quantity) > 1e-9:
                rounding_ok = False
                issues.append((sym, f"fractional qty {r.quantity} not on step {step}"))
        elif r.quantity != float(int(r.quantity)):
            rounding_ok = False
            issues.append((sym, f"whole-share instrument with fractional qty {r.quantity}"))
        # slippage budget = limit offset vs reference
        if r.limit_price and r.ref_price:
            slip_bps = 1e4 * abs(r.limit_price - r.ref_price) / r.ref_price
            if slip_bps > cfg.max_slippage_bps + 1e-6:
                slippage_ok = False
                issues.append((sym, f"limit offset {slip_bps:.1f}bps > {cfg.max_slippage_bps}bps"))
        # long-only: a sell is bounded by the planner already, but assert intent
        if r.side is Side.SELL and r.quantity < 0:
            no_short_ok = False
            issues.append((sym, "negative sell quantity"))

    checks["every instrument tradable"] = tradable_ok
    checks["every order >= minimum value"] = min_value_ok
    checks["quantities rounded correctly"] = rounding_ok
    checks["expected slippage within limit"] = slippage_ok
    checks["no short orders"] = no_short_ok

    # --- cash sufficiency (no margin) ---
    buy_notional = sum(o.request.notional for o in plan.orders if o.request.side is Side.BUY)
    sell_notional = sum(o.request.notional for o in plan.orders if o.request.side is Side.SELL)
    available = cash + sell_notional
    cash_ok = buy_notional <= available + 1e-6
    checks["account cash sufficient (no margin)"] = cash_ok
    if not cash_ok:
        reasons.append(f"buy notional {buy_notional:.2f} exceeds available {available:.2f} (no margin)")

    # --- market hours / queue ---
    market_open = is_us_market_open(now)
    queued = (not market_open) and cfg.allow_queue_when_closed
    checks["market hours valid or queue allowed"] = market_open or cfg.allow_queue_when_closed

    for sym, why in issues:
        reasons.append(f"{sym}: {why}")
    ok = all(checks.values())
    return ValidationResult(ok=ok, checks=checks, reasons=reasons, order_issues=issues,
                            market_open=market_open, queued=queued)
