"""Paper trading for basket/ensemble strategies on daily bar data.

The validated daily flagship (xsec_momentum + tsmom + momentum-neutral
ml_alpha) is a WEIGHT function, not a pair-signal stream, so it cannot run
through the pairs PaperTrader. This trader closes that research->execution
gap: on each completed bar it refreshes data, recomputes target weights on
the same rolling window the backtest used, and rebalances a simulated
portfolio through the risk manager. NO REAL ORDERS - fills are simulated at
the latest close +/- slippage.

Notes on honesty:
* Shorting is SIMULATED (margin account semantics). No connected stock
  broker can short (T212 Invest/ISA is long-only), so this remains a
  research/validation harness until a shorting venue exists.
* The book lives in memory like the pairs paper trader: restarting the
  process restarts the paper portfolio (orders/equity history persist in
  the database for inspection).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.backtesting.broker_simulator import SimulatedBroker
from app.backtesting.commissions import PercentCommission
from app.backtesting.slippage import FixedBpsSlippage
from app.brokers.models import OrderRequest, SignalMetadata
from app.config.settings import Settings
from app.core.exceptions import DataQualityError, OrderRejectedError
from app.core.logging import audit, get_logger
from app.core.types import Side, TradingMode
from app.data.storage import Storage
from app.risk.exposure import PortfolioState
from app.risk.risk_manager import RiskManager

log = get_logger(__name__)


@dataclass
class BasketPaperConfig:
    symbols: list[str]
    interval: str = "1d"
    fit_window: int = 300            # bars of history handed to the weight fn
    starting_cash: float = 10_000.0
    slippage_bps: float = 3.0        # daily-profile equity costs
    commission_bps: float = 2.0
    min_trade_notional_pct: float = 0.0005  # skip dust orders < 0.05% of equity
    source: str | None = "yahoo"     # restrict storage loads to one bar source
    refresh_days: int = 14           # incremental provider fetch window
    label: str = "basket_ensemble"


class BasketPaperTrader:
    """Rebalance a simulated portfolio to a basket weight function's targets."""

    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        weight_fn,
        risk: RiskManager,
        config: BasketPaperConfig,
        refresh_data: bool = True,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.weight_fn = weight_fn
        self.risk = risk
        self.cfg = config
        self.refresh_data = refresh_data
        self.broker = SimulatedBroker(
            starting_cash=config.starting_cash,
            slippage=FixedBpsSlippage(config.slippage_bps),
            commission=PercentCommission(config.commission_bps),
            allow_short=True,   # simulated margin account — see module docstring
        )
        self.daily_start = config.starting_cash
        self.peak = config.starting_cash
        self._last_ts: pd.Timestamp | None = None
        self._backfilled = False

    # -- data -----------------------------------------------------------------

    def _refresh(self, days: int) -> None:
        from app.data.historical_loader import HistoricalDataLoader

        if self.cfg.source in (None, "synthetic"):
            return
        HistoricalDataLoader(self.storage).download(
            self.cfg.symbols, self.cfg.interval, days, source=self.cfg.source,
        )

    def _backfill_days(self) -> int:
        """Calendar days needed to cover fit_window bars (~252 trading days
        per 365 calendar days for stocks, plus slack for holidays)."""
        return int(self.cfg.fit_window * 1.6) + 30

    def _load_window(self):
        from app.data.market_data import build_price_matrix

        try:
            prices = build_price_matrix(
                self.storage, self.cfg.symbols, self.cfg.interval,
                source=self.cfg.source, min_rows=1,
            )
        except DataQualityError as exc:
            log.warning("no usable price window: %s", exc)
            return None
        n = len(prices.index)
        if n < self.cfg.fit_window:
            log.warning(
                "only %d bars of stored history; need fit_window=%d "
                "(run `statarb download-data --source %s --interval %s` or let "
                "the trader backfill)", n, self.cfg.fit_window,
                self.cfg.source, self.cfg.interval,
            )
            return None
        return prices.slice(n - self.cfg.fit_window, n)

    # -- trading cycle ----------------------------------------------------------

    def step(self) -> bool:
        """One polling cycle. Returns True if a new bar was processed."""
        if self.refresh_data:
            try:
                self._refresh(self.cfg.refresh_days)
            except Exception as exc:  # noqa: BLE001 — keep stale data usable
                log.warning("data refresh failed (continuing on stored bars): %s", exc)
        window = self._load_window()
        if window is None and self.refresh_data and not self._backfilled:
            # stored history is shorter than the fit window (fresh database):
            # backfill once instead of refusing forever
            self._backfilled = True
            days = self._backfill_days()
            log.info("backfilling %d calendar days of %s history...", days,
                     self.cfg.interval)
            try:
                self._refresh(days)
            except Exception as exc:  # noqa: BLE001
                log.warning("backfill failed: %s", exc)
            window = self._load_window()
        if window is None:
            return False
        bar_ts = window.index[-1]
        if self._last_ts is not None and bar_ts <= self._last_ts:
            return False
        ts = bar_ts.to_pydatetime()

        marks = {s: float(window.close[s].iloc[-1]) for s in window.close.columns}
        self.broker.set_market(marks, ts)
        if self.risk.roll_day(ts):
            self.daily_start = self.broker.equity()
        equity = self.broker.equity(marks)
        self.peak = max(self.peak, equity)
        gross, net = self.broker.exposures()
        state = PortfolioState(
            equity=equity, cash=self.broker.cash, daily_start_equity=self.daily_start,
            peak_equity=self.peak, gross_exposure=gross, net_exposure=net,
            open_pairs=0, open_positions=len(self.broker.positions),
            trades_today=self.risk.trades_today,
            notional_by_symbol={s: abs(q) * marks.get(s, 0.0)
                                for s, q in self.broker.positions.items()},
            ts=ts,
        )
        self.risk.update_equity(state)   # may auto-engage the kill switch
        self.storage.record_equity_snapshot(
            ts=ts, mode=TradingMode.PAPER.value, equity=equity, cash=self.broker.cash,
            gross_exposure=gross, net_exposure=net, open_pairs=0,
        )

        targets = self._target_weights(window)
        filled, rejected = self._rebalance(targets, marks, state)
        self._last_ts = bar_ts
        log.info("bar %s | equity %.2f | %d positions | %d fills %d rejects | kill=%s",
                 bar_ts.date(), equity, len(self.broker.positions), filled, rejected,
                 self.risk.kill_switch.is_active)
        audit("basket_paper_bar", ts=str(bar_ts), equity=equity, fills=filled,
              rejects=rejected, kill=self.risk.kill_switch.is_active)
        return True

    def _target_weights(self, window) -> pd.Series:
        if getattr(self.weight_fn, "wants_aux", False):
            raw = self.weight_fn(window.close, aux=window.aux)
        else:
            raw = self.weight_fn(window.close)
        return raw.reindex(window.close.columns).fillna(0.0)

    # -- rebalancing ----------------------------------------------------------

    def _rebalance(self, targets: pd.Series, marks: dict[str, float],
                   state: PortfolioState) -> tuple[int, int]:
        """Trade the difference between target and held quantities.

        Sells run before buys so freed cash funds the new longs. Orders below
        the dust threshold are skipped — a daily-rebalanced ensemble nudges
        weights constantly and trading every nudge is pure cost bleed.
        """
        equity = state.equity
        min_notional = self.cfg.min_trade_notional_pct * equity
        deltas: list[tuple[str, float, float]] = []   # symbol, delta_qty, price
        symbols = set(targets.index) | set(self.broker.positions)
        for symbol in sorted(symbols):
            price = marks.get(symbol, 0.0)
            if price <= 0:
                continue
            target_qty = float(targets.get(symbol, 0.0)) * equity / price
            delta = target_qty - self.broker.position(symbol)
            if abs(delta) * price < min_notional:
                continue
            deltas.append((symbol, delta, price))

        filled = rejected = 0
        deltas.sort(key=lambda d: d[1])               # most negative first = sells first
        for symbol, delta, price in deltas:
            if self.risk.kill_switch.is_active:
                log.warning("kill switch active — rebalance halted at %s", symbol)
                break
            side = Side.BUY if delta > 0 else Side.SELL
            qty = abs(delta)
            request = OrderRequest(
                broker="paper(simulated)", symbol=symbol, side=side, quantity=qty,
                ref_price=price,
                metadata=SignalMetadata(strategy=self.cfg.label, action="rebalance",
                                        expected_slippage_bps=self.cfg.slippage_bps),
            )
            decision = self.risk.validate_order(request, state)
            status, fill_price, fee, reject = "rejected", 0.0, 0.0, decision.reason()
            if decision.approved:
                try:
                    fill = self.broker.execute_market(symbol, side, qty, ref_price=price)
                    status, fill_price, fee, reject = "filled", fill.price, fill.fee, ""
                    self.risk.register_trade()
                    filled += 1
                except OrderRejectedError as exc:
                    reject = str(exc)
                    rejected += 1
            else:
                rejected += 1
            self.storage.record_order(
                ts=state.ts, mode=TradingMode.PAPER.value, broker="paper(simulated)",
                strategy=self.cfg.label, pair_key="", symbol=symbol, side=side.value,
                order_type="market", quantity=qty, ref_price=price,
                notional=qty * price, status=status, fill_price=fill_price, fee=fee,
                signal_json={"target_weight": float(targets.get(symbol, 0.0)),
                             "reject": reject},
                risk_checks_json=decision.as_dicts(),
            )
        return filled, rejected

    # -- loop -------------------------------------------------------------------

    def run(self, iterations: int | None = None, poll_seconds: int | None = None) -> None:
        import time

        poll = poll_seconds or 1800   # daily bars: check twice an hour
        log.info("basket paper trading started: %d symbols, interval %s, poll %ds "
                 "— NO REAL ORDERS", len(self.cfg.symbols), self.cfg.interval, poll)
        count = 0
        while iterations is None or count < iterations:
            try:
                self.step()
            except KeyboardInterrupt:  # pragma: no cover
                log.info("basket paper trading stopped by user")
                break
            except Exception as exc:  # noqa: BLE001 — keep the loop alive
                log.exception("basket paper cycle failed: %s", exc)
            count += 1
            if iterations is None or count < iterations:
                time.sleep(poll)
