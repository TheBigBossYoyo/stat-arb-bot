"""Long-only demo executor (Phase 5) — the three supervised order modes.

A single orchestrator the CLI and the supervised-paper loop call, with three
strictly-escalating modes:

* **shadow**       — build + validate the order plan; SEND NOTHING. No broker
                     connection at all. ("SHADOW MODE — SENDS NO ORDERS.")
* **demo_preview** — connect to the Trading 212 DEMO account (read cash,
                     positions, instruments), build + validate the plan against
                     the real demo balances, reconcile; SEND NOTHING.
* **demo_execute** — everything in demo_preview, then evaluate the full demo
                     execution gate and, only if EVERY condition holds, submit
                     the orders to the DEMO account. Requires an explicit
                     confirmation. Never the live endpoint.

Live is unreachable from here by construction (see `demo_execution`). Any mode
other than these three is refused.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.brokers.trading212.demo_execution import (
    DemoGateResult,
    Trading212DemoExecutor,
    evaluate_demo_gate,
)
from app.brokers.trading212.instrument_cache import InstrumentCache
from app.execution.long_only_order_planner import (
    LongOnlyOrderPlanner,
    PlannedLongOnlyOrders,
    expected_slippage_bps,
)
from app.execution.long_only_reconciliation import ReconciliationReport, reconcile_long_only

MODES = ("shadow", "demo_preview", "demo_execute")

BANNERS = {
    "shadow": "SHADOW MODE — SENDS NO ORDERS",
    "demo_preview": "DEMO ONLY — PREVIEW (connects to demo, sends nothing)",
    "demo_execute": "DEMO ONLY — EXECUTE (submits to the Trading 212 DEMO account)",
}


@dataclass
class DemoRunResult:
    mode: str
    banner: str
    planned: PlannedLongOnlyOrders | None = None
    account: dict | None = None
    reconciliation: ReconciliationReport | None = None
    gate: DemoGateResult | None = None
    submit: dict | None = None
    sent_orders: bool = False
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        out = {"mode": self.mode, "banner": self.banner, "sent_orders": self.sent_orders}
        if self.planned:
            out["plan"] = self.planned.summary()
            out["expected_slippage_bps"] = expected_slippage_bps(self.planned.plan)
        if self.account:
            out["account"] = {k: self.account[k] for k in ("cash", "equity", "n_positions")
                              if k in self.account}
        if self.gate:
            out["gate"] = self.gate.summary()
        if self.submit:
            out["submit"] = self.submit
        if self.reconciliation:
            out["reconciliation"] = self.reconciliation.summary()
        return out


class LongOnlyDemoExecutor:
    def __init__(self, settings, cache: InstrumentCache,
                 planner: LongOnlyOrderPlanner | None = None,
                 demo_executor: Trading212DemoExecutor | None = None) -> None:
        self.settings = settings
        self.cache = cache
        self.planner = planner or LongOnlyOrderPlanner(cache)
        self._demo = demo_executor

    def _demo_exec(self) -> Trading212DemoExecutor:
        if self._demo is None:
            self._demo = Trading212DemoExecutor(self.settings)
        return self._demo

    def run(
        self,
        mode: str,
        target_weights: dict[str, float],
        *,
        positions: dict[str, float] | None = None,
        cash: float = 0.0,
        prices: dict[str, float],
        confirm_demo: bool = False,
        paper_eligible: bool = False,
        market_data_fresh: bool = True,
        kill_switch_active: bool = False,
        market_open: bool = True,
        now=None,
    ) -> DemoRunResult:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; choose from {MODES}")
        positions = dict(positions or {})
        banner = BANNERS[mode]

        if mode == "shadow":
            planned = self.planner.plan(target_weights, positions, cash, prices,
                                        market_open=market_open, now=now)
            return DemoRunResult(mode=mode, banner=banner, planned=planned,
                                 notes=["No broker connection. Nothing was sent."])

        # demo_preview / demo_execute both connect to the DEMO account first
        demo = self._demo_exec()
        account = demo.check_connection()
        broker_positions = dict(account.get("positions", {}))
        demo_cash = float(account.get("cash", cash))
        planned = self.planner.plan(target_weights, broker_positions, demo_cash, prices,
                                    market_open=market_open, now=now)
        recon = reconcile_long_only(target_weights, broker_positions, prices, demo_cash)

        if mode == "demo_preview":
            return DemoRunResult(mode=mode, banner=banner, planned=planned, account=account,
                                 reconciliation=recon,
                                 notes=["Connected to DEMO. Plan previewed; nothing sent."])

        # demo_execute: evaluate the full gate, then submit only if it passes
        gate = evaluate_demo_gate(
            self.settings, confirm_demo=confirm_demo, kill_switch_active=kill_switch_active,
            validation=planned.validation, paper_eligible=paper_eligible,
            market_data_fresh=market_data_fresh)
        if not gate.ok:
            return DemoRunResult(mode=mode, banner=banner, planned=planned, account=account,
                                 reconciliation=recon, gate=gate, sent_orders=False,
                                 notes=["DEMO execution REFUSED — gate not satisfied.",
                                        *gate.reasons])
        submit = demo.submit_plan(planned.plan, gate)
        return DemoRunResult(mode=mode, banner=banner, planned=planned, account=account,
                             reconciliation=recon, gate=gate, submit=submit.summary(),
                             sent_orders=not submit.blocked and bool(submit.submitted),
                             notes=["DEMO orders submitted (demo endpoint only)."])
