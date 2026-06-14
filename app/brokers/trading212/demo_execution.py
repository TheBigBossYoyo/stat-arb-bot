"""Trading 212 DEMO order execution (Phase 5) — official Public API, demo only.

This is the only module that submits Trading 212 orders, and it submits them to
the DEMO environment ONLY. Live is hard-blocked on multiple, independent grounds:

* the executor always constructs the client with `mode="demo", allow_live=False`,
  so the live base URL is never even reachable from here;
* the demo execution GATE refuses unless EVERY condition holds (env enabled,
  mode==demo, allow_demo_orders, an explicit per-call confirmation, kill switch
  off, the GLOBAL live-trading flag OFF, the order plan validated, the strategy
  paper-eligible and the market data fresh);
* `trading212_allow_live_orders` is intentionally NEVER consulted — a single env
  var cannot enable live; that path simply does not exist in this product.

Every connection check and order action emits an audit event.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.brokers.trading212.client import Trading212Client
from app.brokers.trading212.order_validation import ValidationResult
from app.core.exceptions import LiveTradingBlockedError
from app.core.logging import audit, get_logger

log = get_logger(__name__)


@dataclass
class DemoGateResult:
    ok: bool
    checks: dict[str, bool] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        return {"ok": self.ok,
                "passed": sum(1 for v in self.checks.values() if v),
                "total": len(self.checks),
                "blocking": self.reasons}


def evaluate_demo_gate(
    settings,
    *,
    confirm_demo: bool,
    kill_switch_active: bool,
    validation: ValidationResult | None,
    paper_eligible: bool,
    market_data_fresh: bool,
) -> DemoGateResult:
    """Evaluate EVERY demo-execution condition. Demo orders may be sent only if
    `ok` is True. Live remains blocked regardless of any flag."""
    checks: dict[str, bool] = {}
    reasons: list[str] = []

    def gate(name: str, ok: bool, why: str) -> None:
        checks[name] = bool(ok)
        if not ok:
            reasons.append(why)

    gate("TRADING212_ENABLED=true", settings.trading212_enabled,
         "TRADING212_ENABLED is not true")
    gate("TRADING212_MODE=demo", settings.trading212_mode == "demo",
         f"TRADING212_MODE is '{settings.trading212_mode}', must be 'demo'")
    gate("TRADING212_ALLOW_DEMO_ORDERS=true", settings.trading212_allow_demo_orders,
         "TRADING212_ALLOW_DEMO_ORDERS is not true")
    gate("--confirm-demo provided", confirm_demo,
         "explicit demo confirmation (--confirm-demo) not provided")
    gate("kill switch off", not kill_switch_active, "kill switch is ENGAGED")
    # Defense in depth: the GLOBAL live-trading gate must be OFF. Live for this
    # product is blocked unconditionally; this asserts no one flipped it on.
    gate("global live trading OFF", not settings.live_trading_allowed,
         "global live-trading flag is ON — refusing (this product is demo-only)")
    gate("API key + secret configured",
         bool(settings.trading212_api_key and settings.trading212_api_secret),
         "TRADING212_API_KEY / TRADING212_API_SECRET not configured")
    gate("strategy paper-eligible", paper_eligible,
         "strategy is not paper-eligible (run long-only-readiness --full)")
    gate("market data fresh", market_data_fresh, "market data is stale")
    gate("order plan validated", bool(validation and validation.ok),
         "order plan failed validation" if validation else "no validated order plan")

    return DemoGateResult(ok=all(checks.values()), checks=checks, reasons=reasons)


@dataclass
class DemoSubmitResult:
    submitted: list[dict] = field(default_factory=list)   # accepted orders
    rejected: list[dict] = field(default_factory=list)     # broker rejections / errors
    blocked: bool = False
    block_reason: str = ""

    def summary(self) -> dict:
        return {"n_submitted": len(self.submitted), "n_rejected": len(self.rejected),
                "blocked": self.blocked, "block_reason": self.block_reason}


class Trading212DemoExecutor:
    """Connects to the Trading 212 DEMO account and (only when the gate passes)
    submits long-only orders to it. Never touches the live endpoint."""

    def __init__(self, settings, client: Trading212Client | None = None) -> None:
        self.settings = settings
        self._client = client

    # -- connection ------------------------------------------------------------

    def connect(self) -> Trading212Client:
        """Build (once) a DEMO client. Refuses to construct a live client here."""
        if self._client is not None:
            return self._client
        if self.settings.trading212_mode != "demo":
            raise LiveTradingBlockedError(
                "Trading212DemoExecutor refuses any mode other than 'demo'. "
                "Live trading is not available for this product.")
        self._client = Trading212Client(
            api_key=self.settings.trading212_api_key,
            api_secret=self.settings.trading212_api_secret,
            mode="demo",                 # hard-coded: never live
            enabled=self.settings.trading212_enabled,
            allow_live=False,            # hard-coded: never live
            account_type=self.settings.trading212_account_type,
        )
        audit("trading212_demo_connect", account_type=self.settings.trading212_account_type)
        return self._client

    def check_connection(self) -> dict:
        """Read-only connectivity + account snapshot (no orders)."""
        client = self.connect()
        account = client.get_account()
        audit("trading212_demo_account_read", cash=account.cash, equity=account.equity,
              n_positions=len(account.positions))
        return {
            "broker": account.broker, "mode": "demo", "currency": account.currency,
            "cash": account.cash, "equity": account.equity,
            "n_positions": len(account.positions),
            "positions": {p.symbol: p.quantity for p in account.positions},
        }

    # -- order submission ------------------------------------------------------

    def submit_plan(self, plan, gate: DemoGateResult) -> DemoSubmitResult:
        """Submit a validated plan to the DEMO account. Refuses if the gate is
        not fully satisfied. Each order is submitted individually so one
        rejection does not abort the rest; every action is audited."""
        if not gate.ok:
            audit("trading212_demo_submit_blocked", reasons=gate.reasons)
            return DemoSubmitResult(blocked=True,
                                    block_reason="; ".join(gate.reasons) or "gate not satisfied")
        client = self.connect()
        result = DemoSubmitResult()
        for o in plan.orders:
            req = o.request
            try:
                order = client.place_order(req)
                result.submitted.append({
                    "symbol": req.symbol, "side": req.side.value, "quantity": req.quantity,
                    "order_id": order.order_id, "status": order.status.value,
                    "limit_price": req.limit_price})
                audit("trading212_demo_order_ok", symbol=req.symbol, side=req.side.value,
                      order_id=order.order_id, status=order.status.value)
            except Exception as exc:  # noqa: BLE001 - one bad order must not abort the batch
                result.rejected.append({"symbol": req.symbol, "side": req.side.value,
                                        "quantity": req.quantity, "error": str(exc)})
                audit("trading212_demo_order_rejected", symbol=req.symbol, error=str(exc))
        return result

    def poll_status(self, order_id: str) -> dict:
        client = self.connect()
        order = client.get_order_status(order_id)
        return {"order_id": order.order_id, "status": order.status.value,
                "filled_quantity": order.filled_quantity, "avg_fill_price": order.avg_fill_price}

    def cancel(self, order_id: str, symbol: str | None = None) -> dict:
        client = self.connect()
        order = client.cancel_order(order_id, symbol=symbol)
        audit("trading212_demo_order_cancel", order_id=order_id)
        return {"order_id": order.order_id, "status": order.status.value}
