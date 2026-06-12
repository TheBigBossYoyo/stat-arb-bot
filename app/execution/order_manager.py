"""Order lifecycle manager.

Single choke point between strategies and any broker: every order is
risk-validated, capability-checked, normalized to instrument precision,
audited, persisted, and only then submitted. Used by paper and (later) live
paths so they share identical safety behaviour.
"""

from __future__ import annotations

from app.brokers.base import BrokerBase
from app.brokers.models import Order, OrderRequest
from app.core.exceptions import OrderRejectedError, RiskViolationError
from app.core.logging import audit, get_logger
from app.core.types import OrderStatus, TradingMode, utc_now
from app.data.storage import Storage
from app.risk.exposure import PortfolioState
from app.risk.risk_manager import RiskManager

log = get_logger(__name__)


class OrderManager:
    def __init__(
        self,
        broker: BrokerBase,
        risk: RiskManager,
        storage: Storage | None = None,
        mode: TradingMode = TradingMode.PAPER,
    ) -> None:
        self.broker = broker
        self.risk = risk
        self.storage = storage
        self.mode = mode

    def _record(self, request: OrderRequest, status: str, *, fill_price: float = 0.0,
                fee: float = 0.0, error: str = "", risk_checks: list | None = None) -> None:
        if self.storage is None:
            return
        self.storage.record_order(
            ts=utc_now().replace(tzinfo=None), mode=self.mode.value, broker=request.broker,
            strategy=request.metadata.strategy, pair_key=request.pair_key,
            symbol=request.symbol, side=request.side.value,
            order_type=request.order_type.value, quantity=request.quantity,
            ref_price=request.ref_price, notional=request.notional, status=status,
            fill_price=fill_price, fee=fee,
            signal_json=request.metadata.model_dump(), risk_checks_json=risk_checks or [],
            error=error,
        )

    def submit(self, request: OrderRequest, state: PortfolioState) -> Order:
        """Validate then submit. Raises RiskViolationError / broker errors."""
        decision = self.risk.validate_order(request, state)
        if not decision.approved:
            reason = decision.reason()
            self._record(request, "risk_rejected", error=reason,
                         risk_checks=decision.as_dicts())
            audit("order_risk_rejected", symbol=request.symbol, reason=reason)
            raise RiskViolationError(f"order rejected by risk: {reason}")

        audit("order_submit", broker=request.broker, symbol=request.symbol,
              side=request.side.value, qty=request.quantity,
              order_type=request.order_type.value, mode=self.mode.value)
        try:
            order = self.broker.place_order(request)
        except OrderRejectedError as exc:
            self._record(request, "broker_rejected", error=str(exc),
                         risk_checks=decision.as_dicts())
            raise
        self._record(
            request, order.status.value,
            fill_price=order.avg_fill_price, fee=order.fee,
            risk_checks=decision.as_dicts(),
        )
        return order

    def cancel(self, order_id: str, symbol: str | None = None) -> Order:
        audit("order_cancel", order_id=order_id, symbol=symbol)
        return self.broker.cancel_order(order_id, symbol)

    def status(self, order_id: str, symbol: str | None = None) -> Order:
        return self.broker.get_order_status(order_id, symbol)

    def confirm_filled(self, order: Order) -> bool:
        """Never assume a fill: re-query the broker until terminal status."""
        if order.status in (OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.REJECTED):
            return order.status is OrderStatus.FILLED
        fresh = self.status(order.order_id, order.request.symbol)
        return fresh.status is OrderStatus.FILLED
