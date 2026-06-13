"""Trading 212 Invest/ISA rebalancer — order planning (Path A).

Turns a target long-only weight vector into a concrete set of orders that
respect the *real* Trading 212 Invest/ISA constraints, so the gap between
backtest and a live account is visible before a single order is sent:

* no shorting (sells are capped at the held quantity),
* no margin (total buy notional <= available settled cash),
* fractional shares only when the instrument supports them, else whole shares,
* a minimum order value (tiny rebalancing trades are dropped, not sent),
* instrument tradability (a symbol not offered on Trading 212 is skipped, and
  flagged loudly),
* market-hours awareness (orders planned while the market is closed are marked
  as queued for the next open, the way Invest orders actually behave),
* limit-order preference (a marketable limit at a small offset, to bound
  slippage — Invest fills are not guaranteed price).

This is a PLANNER used by shadow/paper mode. It does NOT place live orders: the
official Public API order endpoints are only exercised against the demo
environment in the paper layer, never from here, and never via any unofficial
route.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.brokers.base import round_step
from app.brokers.models import Instrument, OrderRequest
from app.core.types import OrderType, Side


@dataclass
class RebalanceConfig:
    min_order_value: float = 1.0       # Trading 212 minimum order value (~£1/$1)
    prefer_limit: bool = True          # marketable limit to bound slippage
    limit_offset_bps: float = 10.0     # how far through the touch the limit sits
    cash_buffer: float = 0.0           # keep this fraction of equity in cash
    no_trade_band_bps: float = 25.0    # skip rebalances smaller than this drift


@dataclass
class PlannedOrder:
    request: OrderRequest
    weight_before: float
    weight_after: float
    queued_for_open: bool = False


@dataclass
class RebalancePlan:
    orders: list[PlannedOrder] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (symbol, reason)
    cash_before: float = 0.0
    cash_after: float = 0.0
    equity: float = 0.0
    notes: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        buys = [o for o in self.orders if o.request.side is Side.BUY]
        sells = [o for o in self.orders if o.request.side is Side.SELL]
        return {
            "n_orders": len(self.orders),
            "n_buys": len(buys),
            "n_sells": len(sells),
            "buy_notional": round(sum(o.request.notional for o in buys), 2),
            "sell_notional": round(sum(o.request.notional for o in sells), 2),
            "n_skipped": len(self.skipped),
            "cash_before": round(self.cash_before, 2),
            "cash_after": round(self.cash_after, 2),
        }


class Trading212Rebalancer:
    """Plan the orders that move a held book to its target long-only weights."""

    def __init__(self, instruments: dict[str, Instrument],
                 config: RebalanceConfig | None = None) -> None:
        self.instruments = instruments
        self.cfg = config or RebalanceConfig()

    def _tradable(self, symbol: str) -> tuple[bool, str]:
        inst = self.instruments.get(symbol)
        if inst is None:
            return False, "not offered on Trading 212 Invest/ISA"
        if inst.asset_class.value != "equity":
            return False, f"asset class {inst.asset_class.value} not Invest/ISA-eligible"
        return True, ""

    def _round_qty(self, symbol: str, qty: float, price: float) -> float:
        inst = self.instruments[symbol]
        if inst.fractional:
            step = inst.step_size or 0.0001     # T212 fractional granularity
            return round_step(qty, step)
        return float(int(qty))                  # whole shares only

    def plan(
        self,
        target_weights: dict[str, float],
        positions: dict[str, float],
        cash: float,
        prices: dict[str, float],
        *,
        market_open: bool = True,
    ) -> RebalancePlan:
        cfg = self.cfg
        held_value = sum(positions.get(s, 0.0) * prices.get(s, 0.0) for s in positions)
        equity = cash + held_value
        plan = RebalancePlan(cash_before=cash, equity=equity)
        if equity <= 0:
            plan.notes.append("non-positive equity — no orders")
            return plan

        investable = equity * (1.0 - cfg.cash_buffer)
        # decide target quantities, validating tradability and long-only
        target_qty: dict[str, float] = {}
        symbols = set(target_weights) | set(positions)
        for sym in symbols:
            w = max(0.0, target_weights.get(sym, 0.0))      # long-only
            price = prices.get(sym, 0.0)
            if price <= 0:
                if positions.get(sym, 0.0) > 0:
                    plan.skipped.append((sym, "no price — cannot value/trade"))
                continue
            ok, reason = self._tradable(sym)
            if not ok:
                if w > 0:
                    plan.skipped.append((sym, reason))
                # an untradable held position can still be SOLD to flatten
                if positions.get(sym, 0.0) > 0:
                    target_qty[sym] = 0.0
                continue
            target_qty[sym] = self._round_qty(sym, w * investable / price, price)

        # build sells first (free up cash), then buys within the cash budget
        sells: list[tuple[str, float]] = []
        buys: list[tuple[str, float]] = []
        for sym, tq in target_qty.items():
            cur = positions.get(sym, 0.0)
            delta = tq - cur
            price = prices[sym]
            if abs(delta) * price < cfg.min_order_value:
                continue
            drift_bps = 1e4 * abs(delta) * price / equity
            if drift_bps < cfg.no_trade_band_bps:
                continue
            if delta < 0:
                sells.append((sym, min(-delta, cur)))       # never sell more than held
            elif delta > 0:
                buys.append((sym, delta))

        # budget against the WORST-CASE limit-fill price (ref +/- the limit
        # offset), so a no-margin account never plans to spend more than its
        # settled cash: buys cost ref*(1+offset), sells realize ref*(1-offset).
        off = (cfg.limit_offset_bps / 1e4) if cfg.prefer_limit else 0.0
        available = cash + sum(q * prices[s] * (1 - off) for s, q in sells)
        buy_notional = sum(q * prices[s] * (1 + off) for s, q in buys)
        scale = 1.0
        if buy_notional > available > 0:                    # no margin: scale buys down
            scale = available / buy_notional
            plan.notes.append(f"buys scaled to {scale:.2%} of target (no margin headroom)")

        for sym, q in sells:
            plan.orders.append(self._make_order(sym, Side.SELL, q, prices[sym],
                                                positions, equity, target_weights, market_open))
        for sym, q in buys:
            q = self._round_qty(sym, q * scale, prices[sym])
            if q * prices[sym] < cfg.min_order_value:
                continue
            plan.orders.append(self._make_order(sym, Side.BUY, q, prices[sym],
                                                positions, equity, target_weights, market_open))

        spent = sum(o.request.notional for o in plan.orders if o.request.side is Side.BUY)
        got = sum(o.request.notional for o in plan.orders if o.request.side is Side.SELL)
        plan.cash_after = cash + got - spent
        if not market_open:
            plan.notes.append("market closed — orders queued for next regular open")
        return plan

    def _make_order(self, symbol, side, qty, price, positions, equity,
                    target_weights, market_open) -> PlannedOrder:
        cfg = self.cfg
        order_type = OrderType.LIMIT if cfg.prefer_limit else OrderType.MARKET
        limit_price = None
        if order_type is OrderType.LIMIT:
            off = cfg.limit_offset_bps / 1e4
            limit_price = price * (1 + off) if side is Side.BUY else price * (1 - off)
            inst = self.instruments.get(symbol)
            if inst and inst.tick_size:
                limit_price = round_step(limit_price, inst.tick_size)
        req = OrderRequest(
            broker="trading212", symbol=symbol, side=side, order_type=order_type,
            quantity=qty, limit_price=limit_price, ref_price=price,
            time_in_force="GTC",
        )
        w_before = positions.get(symbol, 0.0) * price / equity if equity else 0.0
        return PlannedOrder(request=req, weight_before=round(w_before, 4),
                            weight_after=round(target_weights.get(symbol, 0.0), 4),
                            queued_for_open=not market_open)
