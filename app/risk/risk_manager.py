"""Central risk manager.

Every signal must pass `validate_pair_entry` before sizing/execution, and
every order must pass `validate_order`. The manager also watches equity and
engages the kill switch on daily-loss / drawdown breaches. Exits are always
allowed (closing risk is never blocked), but they still get logged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel

from app.brokers.base import BrokerCapabilities
from app.brokers.models import OrderRequest
from app.core.logging import audit, get_logger
from app.risk.exposure import PortfolioState
from app.risk.kill_switch import KillSwitch

log = get_logger(__name__)

RISK_LIMITS_PATH = Path(__file__).resolve().parent.parent / "config" / "risk_limits.yaml"


class RiskLimits(BaseModel):
    # global
    max_daily_loss_pct: float = 1.0
    max_total_drawdown_pct: float = 5.0
    max_gross_exposure: float = 1000.0
    max_net_exposure: float = 200.0
    max_open_positions: int = 10
    max_open_pairs: int = 3
    max_trades_per_day: int = 20
    max_notional_per_trade: float = 50.0
    max_notional_per_asset: float = 200.0
    max_notional_per_broker: float = 1000.0
    max_api_errors_per_hour: int = 30
    max_order_rejections_per_day: int = 10
    # per pair
    max_pair_notional: float = 100.0
    max_pair_loss: float = 25.0          # hard unrealized-loss stop per open pair
    max_pair_holding_bars: int = 96
    max_slippage_bps: float = 25.0
    # per order
    max_order_size_notional: float = 60.0
    max_market_order_notional: float = 60.0
    # percent-of-equity limits (0 = disabled). When set, the effective limit is
    # min(absolute, pct/100 * equity): limits scale with the account while the
    # absolute values above remain hard backstops.
    max_notional_per_trade_pct: float = 0.0
    max_pair_notional_pct: float = 0.0
    max_notional_per_asset_pct: float = 0.0
    max_gross_exposure_pct: float = 0.0
    max_net_exposure_pct: float = 0.0
    max_pair_loss_pct: float = 0.0
    max_order_size_notional_pct: float = 0.0

    @staticmethod
    def _effective(absolute: float, pct: float, equity: float) -> float:
        if pct > 0 and equity > 0:
            return min(absolute, pct / 100.0 * equity)
        return absolute

    def eff_max_notional_per_trade(self, equity: float) -> float:
        return self._effective(self.max_notional_per_trade, self.max_notional_per_trade_pct, equity)

    def eff_max_pair_notional(self, equity: float) -> float:
        return self._effective(self.max_pair_notional, self.max_pair_notional_pct, equity)

    def eff_max_notional_per_asset(self, equity: float) -> float:
        return self._effective(self.max_notional_per_asset, self.max_notional_per_asset_pct, equity)

    def eff_max_gross_exposure(self, equity: float) -> float:
        return self._effective(self.max_gross_exposure, self.max_gross_exposure_pct, equity)

    def eff_max_net_exposure(self, equity: float) -> float:
        return self._effective(self.max_net_exposure, self.max_net_exposure_pct, equity)

    def eff_max_pair_loss(self, equity: float) -> float:
        return self._effective(self.max_pair_loss, self.max_pair_loss_pct, equity)

    def eff_max_order_size_notional(self, equity: float) -> float:
        return self._effective(self.max_order_size_notional, self.max_order_size_notional_pct, equity)


def load_risk_limits(path: Path | None = None, overrides: dict | None = None) -> RiskLimits:
    """Load YAML limits and apply env/setting overrides (overrides win)."""
    raw: dict = {}
    file = path or RISK_LIMITS_PATH
    if file.exists():
        data = yaml.safe_load(file.read_text(encoding="utf-8")) or {}
        for section in ("global", "per_pair", "per_order"):
            raw.update(data.get(section, {}) or {})
    known = set(RiskLimits.model_fields)
    merged = {k: v for k, v in raw.items() if k in known}
    if overrides:
        merged.update({k: v for k, v in overrides.items() if k in known and v is not None})
    return RiskLimits(**merged)


@dataclass
class RiskCheck:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class RiskDecision:
    approved: bool
    checks: list[RiskCheck] = field(default_factory=list)

    @property
    def failures(self) -> list[RiskCheck]:
        return [c for c in self.checks if not c.passed]

    def reason(self) -> str:
        return "; ".join(f"{c.name}: {c.detail}" for c in self.failures)

    def as_dicts(self) -> list[dict]:
        return [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks]


class RiskManager:
    def __init__(
        self,
        limits: RiskLimits | None = None,
        kill_switch: KillSwitch | None = None,
        capabilities: dict[str, BrokerCapabilities] | None = None,
    ) -> None:
        self.limits = limits or RiskLimits()
        self.kill_switch = kill_switch or KillSwitch()
        self.capabilities = capabilities or {}
        self._trades_today = 0
        self._rejections_today = 0
        self._current_day: date | None = None

    # -- day/counters ----------------------------------------------------------

    def roll_day(self, ts: datetime) -> bool:
        """Advance the trading day. Returns True when a new day started."""
        day = ts.date()
        if day != self._current_day:
            self._current_day = day
            self._trades_today = 0
            self._rejections_today = 0
            return True
        return False

    def register_trade(self) -> None:
        self._trades_today += 1

    @property
    def trades_today(self) -> int:
        return self._trades_today

    # -- equity monitoring -------------------------------------------------------

    def update_equity(self, state: PortfolioState) -> list[str]:
        """Check loss limits; engage the kill switch on breach. Returns triggers."""
        triggered: list[str] = []
        if state.daily_loss_pct >= self.limits.max_daily_loss_pct:
            triggered.append(
                f"daily loss {state.daily_loss_pct:.2f}% >= {self.limits.max_daily_loss_pct}%"
            )
        if state.drawdown_pct >= self.limits.max_total_drawdown_pct:
            triggered.append(
                f"drawdown {state.drawdown_pct:.2f}% >= {self.limits.max_total_drawdown_pct}%"
            )
        if triggered and not self.kill_switch.is_active:
            self.kill_switch.engage("; ".join(triggered))
        return triggered

    # -- signal/pair validation -----------------------------------------------------

    def validate_pair_entry(
        self,
        *,
        broker: str,
        notional_a: float,
        notional_b: float,
        state: PortfolioState,
        requires_short: bool = True,
        paper_mode: bool = True,
        symbol_a: str = "",
        symbol_b: str = "",
    ) -> RiskDecision:
        checks: list[RiskCheck] = []
        limits = self.limits
        total = notional_a + notional_b

        def check(name: str, passed: bool, detail: str) -> None:
            checks.append(RiskCheck(name, passed, detail))

        check("kill_switch", not self.kill_switch.is_active,
              f"engaged: {self.kill_switch.reason}" if self.kill_switch.is_active else "off")
        check("daily_loss", state.daily_loss_pct < limits.max_daily_loss_pct,
              f"{state.daily_loss_pct:.2f}% vs limit {limits.max_daily_loss_pct}%")
        check("drawdown", state.drawdown_pct < limits.max_total_drawdown_pct,
              f"{state.drawdown_pct:.2f}% vs limit {limits.max_total_drawdown_pct}%")
        check("max_open_pairs", state.open_pairs < limits.max_open_pairs,
              f"{state.open_pairs} open vs limit {limits.max_open_pairs}")
        check("max_trades_per_day", self._trades_today < limits.max_trades_per_day,
              f"{self._trades_today} today vs limit {limits.max_trades_per_day}")
        max_trade = limits.eff_max_notional_per_trade(state.equity)
        check("max_notional_per_trade",
              max(notional_a, notional_b) <= max_trade,
              f"leg notional {max(notional_a, notional_b):.2f} vs limit {max_trade:.2f}")
        max_pair = limits.eff_max_pair_notional(state.equity)
        check("max_pair_notional", total <= max_pair,
              f"pair notional {total:.2f} vs limit {max_pair:.2f}")
        max_gross = limits.eff_max_gross_exposure(state.equity)
        check("max_gross_exposure",
              state.gross_exposure + total <= max_gross,
              f"gross after {state.gross_exposure + total:.2f} vs limit {max_gross:.2f}")
        # a balanced pair adds |notional_a - notional_b| to net exposure
        net_after = abs(state.net_exposure) + abs(notional_a - notional_b)
        max_net = limits.eff_max_net_exposure(state.equity)
        check("max_net_exposure", net_after <= max_net,
              f"net after {net_after:.2f} vs limit {max_net:.2f}")

        max_asset = limits.eff_max_notional_per_asset(state.equity)
        for symbol, notional in ((symbol_a, notional_a), (symbol_b, notional_b)):
            held = state.notional_by_symbol.get(symbol, 0.0)
            check("max_notional_per_asset",
                  held + notional <= max_asset,
                  f"{symbol or 'leg'}: {held + notional:.2f} vs limit {max_asset:.2f}")

        if requires_short and not paper_mode:
            caps = self.capabilities.get(broker)
            if caps is None:
                check("broker_capability", False, f"no capability matrix for broker '{broker}'")
            else:
                ok, why = caps.supports(shorting=True)
                check("broker_capability", ok, why or "shorting supported")

        decision = RiskDecision(approved=all(c.passed for c in checks), checks=checks)
        if not decision.approved:
            self._rejections_today += 1
            audit("risk_rejected_entry", broker=broker, pair=f"{symbol_a}|{symbol_b}",
                  reason=decision.reason())
        return decision

    # -- order validation -------------------------------------------------------------

    def validate_order(self, order: OrderRequest, state: PortfolioState) -> RiskDecision:
        checks: list[RiskCheck] = []
        limits = self.limits
        notional = order.notional

        checks.append(RiskCheck("kill_switch", not self.kill_switch.is_active,
                                self.kill_switch.reason or "off"))
        max_order = limits.eff_max_order_size_notional(state.equity)
        checks.append(RiskCheck("max_order_size", notional <= max_order,
                                f"{notional:.2f} vs limit {max_order:.2f}"))
        if order.order_type.value == "market":
            max_market = limits._effective(
                limits.max_market_order_notional, limits.max_order_size_notional_pct, state.equity
            )
            checks.append(RiskCheck("max_market_order", notional <= max_market,
                                    f"{notional:.2f} vs limit {max_market:.2f}"))
        if order.metadata.expected_slippage_bps:
            checks.append(RiskCheck(
                "max_slippage",
                order.metadata.expected_slippage_bps <= limits.max_slippage_bps,
                f"{order.metadata.expected_slippage_bps:.1f}bps vs limit {limits.max_slippage_bps}bps",
            ))
        caps = self.capabilities.get(order.broker)
        if caps is not None:
            ok, why = caps.supports(order_type=order.order_type)
            checks.append(RiskCheck("broker_capability", ok, why or "ok"))

        decision = RiskDecision(approved=all(c.passed for c in checks), checks=checks)
        if not decision.approved:
            self._rejections_today += 1
        return decision
