"""Live paper trading against real Binance market data.

Polls public klines (no API key needed), runs the pair strategies on each new
completed bar, validates through the risk manager and executes on the
simulated broker via the semi-atomic pair executor. Every signal/order/trade
and an equity snapshot per bar are persisted to the database and audit log.

History ACCUMULATES across cycles (bar indices are stable), so stateful
strategies like the Kalman filter behave identically to the backtest.
Fills are simulated at the latest close +/- slippage; real order endpoints
are never touched.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.backtesting.broker_simulator import SimulatedBroker
from app.brokers.binance.client import BinancePublicData
from app.brokers.binance.market_data import klines_to_dataframe
from app.config.settings import Settings
from app.core.logging import audit, get_logger
from app.core.types import Side, SignalAction, TradingMode, interval_minutes
from app.data.storage import Storage
from app.execution.pair_executor import Leg, PairExecutor
from app.execution.reconciliation import reconcile_positions
from app.research.pair_selection import SelectedPair
from app.risk.exposure import PortfolioState
from app.risk.risk_manager import RiskManager
from app.risk.sizing import size_pair
from app.risk.stops import pair_loss_stop_triggered, unrealized_pair_pnl
from app.strategies.base import PairSignal, PairStrategyBase, PositionContext

log = get_logger(__name__)

MAX_HISTORY_BARS = 20_000   # cap memory; trimming resets stateful strategies' warmup


@dataclass
class OpenPaperPair:
    direction: int
    qty_a: float
    qty_b: float
    entry_ts: pd.Timestamp
    entry_z: float
    entry_price_a: float
    entry_price_b: float
    entry_fees: float
    bars_held: int = 0


class PaperTrader:
    def __init__(
        self,
        settings: Settings,
        storage: Storage,
        pairs: list[SelectedPair],
        strategies: dict[str, PairStrategyBase],
        risk: RiskManager,
        interval: str = "15m",
        starting_cash: float = 10_000.0,
        history_bars: int = 600,
    ) -> None:
        self.settings = settings
        self.storage = storage
        self.pairs = pairs
        self.strategies = strategies
        self.risk = risk
        self.interval = interval
        self.history_bars = history_bars
        self.market = BinancePublicData()
        self.broker = SimulatedBroker(starting_cash=starting_cash)
        self.executor = PairExecutor(self.broker, kill_switch=risk.kill_switch)
        self.open_pairs: dict[str, OpenPaperPair] = {}
        self.daily_start = starting_cash
        self.peak = starting_cash
        self._history: pd.DataFrame | None = None   # wide close frame, grows per bar

    # -- data -----------------------------------------------------------------

    def _symbols(self) -> list[str]:
        symbols: set[str] = set()
        for p in self.pairs:
            symbols.update((p.symbol_a, p.symbol_b))
        return sorted(symbols)

    def _fetch_closes(self, limit: int) -> pd.DataFrame:
        frames = {}
        for symbol in self._symbols():
            raw = self.market.get_klines(symbol, self.interval, limit=limit)
            df = klines_to_dataframe(raw)
            if len(df) > 1:
                df = df.iloc[:-1]  # drop the still-forming bar
            frames[symbol] = df.set_index("ts")["close"]
        return pd.DataFrame(frames).dropna()

    def _update_history(self) -> bool:
        """Append new completed bars. Returns True if at least one was added."""
        if self._history is None:
            self._history = self._fetch_closes(self.history_bars)
            return not self._history.empty
        fresh = self._fetch_closes(10)
        if fresh.empty:
            return False
        new_rows = fresh[fresh.index > self._history.index[-1]]
        if new_rows.empty:
            return False
        self._history = pd.concat([self._history, new_rows])
        if len(self._history) > MAX_HISTORY_BARS:
            self._history = self._history.iloc[-MAX_HISTORY_BARS:]
        return True

    # -- trading cycle ----------------------------------------------------------

    def step(self) -> bool:
        """One polling cycle. Returns True if a new bar was processed."""
        if not self._update_history():
            return False
        closes = self._history
        bar_ts = closes.index[-1]
        ts = bar_ts.to_pydatetime()
        if self.risk.roll_day(ts):
            self.daily_start = self.broker.equity()

        marks = {s: float(closes[s].iloc[-1]) for s in closes.columns}
        self.broker.set_market(marks, ts)
        equity = self.broker.equity(marks)
        self.peak = max(self.peak, equity)
        gross, net = self.broker.exposures()
        state = PortfolioState(
            equity=equity, cash=self.broker.cash, daily_start_equity=self.daily_start,
            peak_equity=self.peak, gross_exposure=gross, net_exposure=net,
            open_pairs=len(self.open_pairs), open_positions=len(self.broker.positions),
            trades_today=self.risk.trades_today,
            notional_by_symbol={s: abs(q) * marks.get(s, 0.0)
                                for s, q in self.broker.positions.items()},
            ts=ts,
        )
        self.risk.update_equity(state)
        self.storage.record_equity_snapshot(
            ts=ts, mode=TradingMode.PAPER.value, equity=equity, cash=self.broker.cash,
            gross_exposure=gross, net_exposure=net, open_pairs=len(self.open_pairs),
        )

        # hard money stop, independent of strategy logic
        for key, op in list(self.open_pairs.items()):
            pair = next(p for p in self.pairs if p.key == key)
            unrealized = unrealized_pair_pnl(
                direction=op.direction, qty_a=op.qty_a, qty_b=op.qty_b,
                entry_price_a=op.entry_price_a, entry_price_b=op.entry_price_b,
                mark_a=marks[pair.symbol_a], mark_b=marks[pair.symbol_b],
                entry_fees=op.entry_fees,
            )
            if pair_loss_stop_triggered(unrealized, self.risk.limits.eff_max_pair_loss(equity)):
                stop_sig = PairSignal(
                    ts=ts, pair_key=key, action=SignalAction.PAIR_LOSS_STOP,
                    z_score=float("nan"), hedge_ratio=pair.beta, alpha=pair.alpha,
                    spread=float("nan"), spread_mean=float("nan"), spread_std=float("nan"),
                    reason=f"unrealized {unrealized:.2f} breached max_pair_loss",
                )
                self._close_pair(stop_sig, pair)

        paused = self._paused_strategies()
        log_close = {s: np.log(closes[s].to_numpy()) for s in closes.columns}
        i = len(closes) - 1
        for pair in self.pairs:
            strat = self.strategies[pair.key]
            if strat.info.name in paused and pair.key not in self.open_pairs:
                continue  # paused: no NEW entries; open pairs still managed
            op = self.open_pairs.get(pair.key)
            if op:
                op.bars_held += 1
            ctx = PositionContext(position=op.direction if op else 0,
                                  bars_held=op.bars_held if op else 0)
            sig = strat.on_bar(i, log_close[pair.symbol_a], log_close[pair.symbol_b], ts, ctx)
            if sig is None:
                continue
            self._act_on_signal(sig, pair, state, marks)

        self._reconcile()
        log.info(
            "bar %s | equity %.2f | open pairs %d | kill=%s",
            bar_ts, equity, len(self.open_pairs), self.risk.kill_switch.is_active,
        )
        return True

    def _paused_strategies(self) -> set[str]:
        """Strategies paused from the dashboard (runtime/paused_strategies.json)."""
        import json

        path = self.settings.runtime_dir / "paused_strategies.json"
        if path.exists():
            try:
                return set(json.loads(path.read_text()))
            except Exception:  # noqa: BLE001
                return set()
        return set()

    def _reconcile(self) -> None:
        """Broker book must equal the sum of open pair legs — always."""
        expected: dict[str, float] = {}
        for key, op in self.open_pairs.items():
            symbol_a, symbol_b = key.split("|")
            expected[symbol_a] = expected.get(symbol_a, 0.0) + op.direction * op.qty_a
            expected[symbol_b] = expected.get(symbol_b, 0.0) - op.direction * op.qty_b
        mismatches = reconcile_positions(expected, dict(self.broker.positions), tolerance=1e-9)
        if mismatches and not self.risk.kill_switch.is_active:
            self.risk.kill_switch.engage(
                f"paper reconciliation mismatch: {[m.symbol for m in mismatches]}"
            )

    # -- signal handling -----------------------------------------------------------

    def _act_on_signal(self, sig: PairSignal, pair: SelectedPair, state: PortfolioState,
                       marks: dict[str, float]) -> None:
        strat = self.strategies[pair.key]
        accepted = False
        reject = ""

        if sig.action.is_entry and pair.key not in self.open_pairs:
            accepted, reject = self._open_pair(sig, pair, state, marks)
        elif sig.action.is_exit and pair.key in self.open_pairs:
            self._close_pair(sig, pair)
            accepted = True

        self.storage.record_signal(
            ts=sig.ts, mode=TradingMode.PAPER.value, strategy=strat.info.name,
            strategy_version=strat.info.version, pair_key=pair.key,
            action=sig.action.value, z_score=sig.z_score, hedge_ratio=sig.hedge_ratio,
            spread=sig.spread, spread_mean=sig.spread_mean, spread_std=sig.spread_std,
            accepted=accepted, reject_reason=reject,
        )
        audit("paper_signal", pair=pair.key, action=sig.action.value, z=sig.z_score,
              accepted=accepted, reject=reject)

    def _open_pair(self, sig: PairSignal, pair: SelectedPair, state: PortfolioState,
                   marks: dict[str, float]) -> tuple[bool, str]:
        strat = self.strategies[pair.key]
        try:
            sizing = size_pair(
                equity=state.equity, target_pct=0.10, beta=sig.hedge_ratio,
                price_a=marks[pair.symbol_a], price_b=marks[pair.symbol_b],
                max_notional_per_trade=self.risk.limits.eff_max_notional_per_trade(state.equity),
            )
        except Exception as exc:  # noqa: BLE001 — sizing failures are rejections
            return False, str(exc)

        decision = self.risk.validate_pair_entry(
            broker="binance_spot", notional_a=sizing.notional_a,
            notional_b=sizing.notional_b, state=state, requires_short=True,
            paper_mode=True, symbol_a=pair.symbol_a, symbol_b=pair.symbol_b,
        )
        if not decision.approved:
            return False, decision.reason()

        direction = 1 if sig.action is SignalAction.ENTER_LONG_SPREAD else -1
        result = self.executor.execute_pair(
            pair.key,
            Leg(pair.symbol_a, Side.BUY if direction == 1 else Side.SELL, sizing.qty_a),
            Leg(pair.symbol_b, Side.SELL if direction == 1 else Side.BUY, sizing.qty_b, 1),
        )
        if not result.ok:
            return False, result.incident
        assert result.fill_a is not None and result.fill_b is not None

        self.open_pairs[pair.key] = OpenPaperPair(
            direction=direction, qty_a=sizing.qty_a, qty_b=sizing.qty_b,
            entry_ts=pd.Timestamp(sig.ts), entry_z=sig.z_score,
            entry_price_a=result.fill_a.price, entry_price_b=result.fill_b.price,
            entry_fees=result.fill_a.fee + result.fill_b.fee,
        )
        self.risk.register_trade()
        for fill in (result.fill_a, result.fill_b):
            self.storage.record_order(
                ts=fill.ts.replace(tzinfo=None) if fill.ts.tzinfo else fill.ts,
                mode=TradingMode.PAPER.value, broker="paper(binance_spot)",
                strategy=strat.info.name, pair_key=pair.key,
                symbol=fill.symbol, side=fill.side.value, order_type="market",
                quantity=fill.quantity, ref_price=fill.price,
                notional=fill.notional, status="filled",
                fill_price=fill.price, fee=fill.fee,
                signal_json={"z": sig.z_score, "beta": sig.hedge_ratio, "spread": sig.spread},
                risk_checks_json=decision.as_dicts(),
            )
        return True, ""

    def _close_pair(self, sig: PairSignal, pair: SelectedPair) -> None:
        strat = self.strategies[pair.key]
        op = self.open_pairs.pop(pair.key)
        side_a = Side.SELL if op.direction == 1 else Side.BUY
        side_b = Side.BUY if op.direction == 1 else Side.SELL
        fill_a = self.broker.execute_market(pair.symbol_a, side_a, op.qty_a)
        fill_b = self.broker.execute_market(pair.symbol_b, side_b, op.qty_b)
        fees = op.entry_fees + fill_a.fee + fill_b.fee
        pnl = (
            op.direction * op.qty_a * (fill_a.price - op.entry_price_a)
            - op.direction * op.qty_b * (fill_b.price - op.entry_price_b)
            - fees
        )
        self.storage.record_trade(
            mode=TradingMode.PAPER.value, strategy=strat.info.name, pair_key=pair.key,
            direction="long_spread" if op.direction == 1 else "short_spread",
            entry_ts=op.entry_ts.to_pydatetime(), exit_ts=sig.ts,
            holding_bars=op.bars_held, entry_z=op.entry_z, exit_z=sig.z_score,
            beta=sig.hedge_ratio, qty_a=op.qty_a, qty_b=op.qty_b,
            pnl=pnl, fees=fees, exit_reason=sig.action.value,
        )
        audit("paper_trade_closed", pair=pair.key, pnl=pnl, fees=fees,
              exit_reason=sig.action.value)

    def run(self, iterations: int | None = None, poll_seconds: int | None = None) -> None:
        poll = poll_seconds or max(30, interval_minutes(self.interval) * 60 // 4)
        log.info(
            "paper trading started: %d pairs, interval %s, poll %ds — NO REAL ORDERS",
            len(self.pairs), self.interval, poll,
        )
        count = 0
        while iterations is None or count < iterations:
            try:
                self.step()
            except KeyboardInterrupt:  # pragma: no cover
                log.info("paper trading stopped by user")
                break
            except Exception as exc:  # noqa: BLE001 — keep the loop alive
                log.exception("paper trading cycle failed: %s", exc)
            count += 1
            if iterations is None or count < iterations:
                time.sleep(poll)
