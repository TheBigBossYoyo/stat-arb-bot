"""Event-driven pair backtest engine.

Lookahead is prevented structurally:
  * at bar i a strategy sees prices[0..i] only,
  * orders generated at bar i are filled at bar i+1's OPEN (plus optional
    extra delay), with slippage and fees,
  * equity is marked at each bar's close.

Every signal passes the RiskManager before it can become an execution; the
kill switch and exposure limits behave exactly as they would in paper/live.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from app.backtesting.broker_simulator import SimulatedBroker
from app.backtesting.commissions import PercentCommission
from app.backtesting.metrics import compute_metrics
from app.backtesting.slippage import FixedBpsSlippage
from app.core.exceptions import RiskViolationError
from app.core.logging import get_logger
from app.core.types import Side, SignalAction
from app.data.market_data import PriceMatrix
from app.research.pair_selection import SelectedPair
from app.risk.exposure import PortfolioState
from app.risk.risk_manager import RiskManager
from app.risk.sizing import size_pair
from app.risk.stops import pair_loss_stop_triggered, unrealized_pair_pnl
from app.strategies.base import PairSignal, PairStrategyBase, PositionContext

log = get_logger(__name__)


@dataclass
class BacktestConfig:
    interval: str = "15m"
    starting_cash: float = 10_000.0
    target_pct_per_pair: float = 0.10
    per_pair_target_pct: dict[str, float] | None = None  # allocator output, by pair key
    slippage_bps: float = 5.0
    commission_bps: float = 10.0
    entry_delay_bars: int = 0      # extra bars between signal and fill (stress testing)
    allow_short: bool = True       # synthetic shorting (paper). False = spot long-only
    reset_kill_switch_daily: bool = True   # backtest convention: resume next day
    bars_per_year: float | None = None     # annualization override (252 for daily equity/FX)
    min_edge_ratio: float = 0.0    # entry gate: expected reversion >= ratio * round-trip cost (0 = off)
    target_spread_vol: float = 0.0  # de-risk pairs whose rolling spread std exceeds this (0 = off)
    label: str = ""


@dataclass
class OpenPair:
    pair_key: str
    direction: int                 # +1 long spread, -1 short spread
    qty_a: float
    qty_b: float
    symbol_a: str
    symbol_b: str
    entry_i: int
    entry_ts: datetime
    entry_price_a: float
    entry_price_b: float
    entry_z: float
    beta: float
    fees: float = 0.0
    closing: bool = False          # an exit has been scheduled; don't schedule another


@dataclass
class PairTradeRecord:
    pair_key: str
    direction: str
    entry_ts: datetime
    exit_ts: datetime
    holding_bars: int
    qty_a: float
    qty_b: float
    entry_price_a: float
    entry_price_b: float
    exit_price_a: float
    exit_price_b: float
    entry_z: float
    exit_z: float
    beta: float
    pnl: float
    fees: float
    exit_reason: str


@dataclass
class _Pending:
    signal: PairSignal
    qty_a: float = 0.0
    qty_b: float = 0.0


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: list[PairTradeRecord]
    signals: list[dict]
    metrics: dict
    config: BacktestConfig
    pairs: list[SelectedPair]
    warnings: list[str] = field(default_factory=list)
    kill_events: list[dict] = field(default_factory=list)

    @property
    def trades_df(self) -> pd.DataFrame:
        return pd.DataFrame([t.__dict__ for t in self.trades])


class BacktestEngine:
    def __init__(
        self,
        prices: PriceMatrix,
        pairs: list[SelectedPair],
        strategy_factory: Callable[[SelectedPair], PairStrategyBase],
        risk_manager: RiskManager,
        config: BacktestConfig | None = None,
    ) -> None:
        self.prices = prices
        self.pairs = [p for p in pairs if p.symbol_a in prices.symbols and p.symbol_b in prices.symbols]
        dropped = len(pairs) - len(self.pairs)
        if dropped:
            log.warning("%d pairs dropped: symbols missing from the price matrix", dropped)
        self.strategies: dict[str, PairStrategyBase] = {
            p.key: strategy_factory(p) for p in self.pairs
        }
        self.risk = risk_manager
        self.config = config or BacktestConfig()

    def run(self) -> BacktestResult:
        cfg = self.config
        idx = self.prices.index
        n = len(idx)
        close = self.prices.close
        open_ = self.prices.open
        log_close = {s: np.log(close[s].to_numpy()) for s in self.prices.symbols}
        close_np = {s: close[s].to_numpy() for s in self.prices.symbols}
        open_np = {s: open_[s].to_numpy() for s in self.prices.symbols}

        broker = SimulatedBroker(
            starting_cash=cfg.starting_cash,
            slippage=FixedBpsSlippage(cfg.slippage_bps),
            commission=PercentCommission(cfg.commission_bps),
            allow_short=cfg.allow_short,
        )

        open_pairs: dict[str, OpenPair] = {}
        pending: dict[int, list[_Pending]] = {}
        equity = np.full(n, np.nan)
        trades: list[PairTradeRecord] = []
        signals: list[dict] = []
        kill_events: list[dict] = []
        traded_notional = 0.0
        gross_sum = 0.0

        daily_start = cfg.starting_cash
        peak = cfg.starting_cash
        last_equity = cfg.starting_cash
        drawdown_halt = False

        for i in range(n):
            ts = idx[i].to_pydatetime()

            if self.risk.roll_day(ts):
                daily_start = last_equity
                if cfg.reset_kill_switch_daily and self.risk.kill_switch.is_active and not drawdown_halt:
                    self.risk.kill_switch.disengage()

            # 1) execute actions scheduled for this bar at its OPEN
            for action in pending.pop(i, []):
                fills_notional = self._execute(action, i, broker, open_np, open_pairs, trades, idx)
                traded_notional += fills_notional

            # 2) mark to market at the close
            marks = {s: close_np[s][i] for s in close_np}
            broker.set_market(marks, ts)
            eq = broker.equity(marks)
            equity[i] = eq
            last_equity = eq
            peak = max(peak, eq)
            gross, net = broker.exposures()
            gross_sum += gross

            state = PortfolioState(
                equity=eq, cash=broker.cash, daily_start_equity=daily_start, peak_equity=peak,
                gross_exposure=gross, net_exposure=net, open_pairs=len(open_pairs),
                open_positions=len(broker.positions), trades_today=self.risk.trades_today,
                notional_by_symbol={s: abs(q) * marks.get(s, 0.0) for s, q in broker.positions.items()},
                ts=ts,
            )
            triggers = self.risk.update_equity(state)
            if triggers:
                kill_events.append({"ts": ts, "triggers": triggers})
                if any("drawdown" in t for t in triggers):
                    drawdown_halt = True

            # 2b) hard money stop per open pair — fires regardless of the model
            if i + 1 < n:
                for key, op in open_pairs.items():
                    if op.closing:
                        continue
                    unrealized = unrealized_pair_pnl(
                        direction=op.direction, qty_a=op.qty_a, qty_b=op.qty_b,
                        entry_price_a=op.entry_price_a, entry_price_b=op.entry_price_b,
                        mark_a=marks[op.symbol_a], mark_b=marks[op.symbol_b],
                        entry_fees=op.fees,
                    )
                    max_pair_loss = self.risk.limits.eff_max_pair_loss(eq)
                    if pair_loss_stop_triggered(unrealized, max_pair_loss):
                        op.closing = True
                        stop_sig = PairSignal(
                            ts=ts, pair_key=key, action=SignalAction.PAIR_LOSS_STOP,
                            z_score=float("nan"), hedge_ratio=op.beta, alpha=0.0,
                            spread=float("nan"), spread_mean=float("nan"),
                            spread_std=float("nan"),
                            reason=f"unrealized {unrealized:.2f} < -max_pair_loss "
                                   f"{max_pair_loss:.2f}",
                        )
                        pending.setdefault(i + 1, []).append(_Pending(signal=stop_sig))
                        signals.append({
                            "ts": ts, "pair_key": key, "action": stop_sig.action.value,
                            "z_score": float("nan"), "hedge_ratio": op.beta,
                            "spread": float("nan"), "spread_mean": float("nan"),
                            "spread_std": float("nan"), "accepted": True,
                            "reject_reason": "", "reason": stop_sig.reason,
                        })

            # 3) signals for the NEXT bar (none on the final bar — nothing can fill)
            if i >= n - 1:
                continue
            for pair in self.pairs:
                strat = self.strategies[pair.key]
                if strat.disabled and pair.key not in open_pairs:
                    continue
                op = open_pairs.get(pair.key)
                ctx = PositionContext(
                    position=op.direction if op else 0,
                    bars_held=(i - op.entry_i) if op else 0,
                )
                sig = strat.on_bar(i, log_close[pair.symbol_a], log_close[pair.symbol_b], ts, ctx)
                if sig is None:
                    continue
                self._handle_signal(
                    sig, pair, i, n, state, marks, open_pairs, pending, signals
                )

        # force-close anything still open at the final close
        final_marks = {s: close_np[s][n - 1] for s in close_np}
        broker.set_market(final_marks, idx[n - 1].to_pydatetime())
        for key in list(open_pairs):
            traded_notional += self._close_pair(
                open_pairs.pop(key), n - 1, broker, close_np, trades, idx,
                exit_z=float("nan"), exit_reason="end_of_data",
            )
        equity[n - 1] = broker.equity(final_marks)

        equity_series = pd.Series(equity, index=idx, name="equity")
        extras = {
            "total_fees": broker.fees_paid,
            "traded_notional": traded_notional,
            "avg_gross_exposure": gross_sum / n if n else 0.0,
        }
        metrics = compute_metrics(
            equity_series, trades, interval=cfg.interval,
            starting_cash=cfg.starting_cash, extras=extras,
            bars_per_year=cfg.bars_per_year,
        )

        warnings = [
            "Universe selected with knowledge of today's listings — survivorship bias possible.",
            f"Costs assumed: {cfg.commission_bps}bps commission + {cfg.slippage_bps}bps slippage per fill.",
        ]
        if cfg.allow_short:
            warnings.append(
                "Synthetic shorting enabled (paper convention). A real Binance SPOT account "
                "cannot short — live market-neutral execution would require margin/futures "
                "(disabled by default) or the long-only fallback mode."
            )

        return BacktestResult(
            equity=equity_series, trades=trades, signals=signals, metrics=metrics,
            config=cfg, pairs=self.pairs, warnings=warnings, kill_events=kill_events,
        )

    # -- internals ---------------------------------------------------------------

    def _passes_edge_gate(self, sig: PairSignal) -> bool:
        """Pre-trade cost filter: the move we expect to capture (revert from the
        current z to the mean, in log terms ~ |z| * spread_std on leg-A notional)
        must exceed `min_edge_ratio` times the full round-trip cost of 4 fills
        across both legs. Entries that cannot beat costs are never worth taking."""
        cfg = self.config
        if cfg.min_edge_ratio <= 0:
            return True
        if not (np.isfinite(sig.z_score) and np.isfinite(sig.spread_std) and sig.spread_std > 0):
            return True  # no basis to judge — leave it to the strategy/risk checks
        capture_bps = abs(sig.z_score) * sig.spread_std * 10_000.0
        cost_bps = 2.0 * (cfg.commission_bps + cfg.slippage_bps) * (1.0 + max(sig.hedge_ratio, 0.0))
        return capture_bps >= cfg.min_edge_ratio * cost_bps

    def _handle_signal(
        self,
        sig: PairSignal,
        pair: SelectedPair,
        i: int,
        n: int,
        state: PortfolioState,
        marks: dict[str, float],
        open_pairs: dict[str, OpenPair],
        pending: dict[int, list[_Pending]],
        signals: list[dict],
    ) -> None:
        cfg = self.config
        accepted = False
        reject_reason = ""

        if sig.action.is_entry and pair.key not in open_pairs:
            exec_i = i + 1 + cfg.entry_delay_bars
            if exec_i >= n:
                reject_reason = "no bars left to execute"
            elif not self._passes_edge_gate(sig):
                reject_reason = (
                    f"expected reversion below {cfg.min_edge_ratio:.1f}x round-trip cost "
                    f"(z={sig.z_score:.2f}, spread_std={sig.spread_std:.5f})"
                )
            else:
                price_a, price_b = marks[pair.symbol_a], marks[pair.symbol_b]
                target_pct = (cfg.per_pair_target_pct or {}).get(
                    pair.key, cfg.target_pct_per_pair
                )
                try:
                    sizing = size_pair(
                        equity=state.equity, target_pct=target_pct,
                        beta=sig.hedge_ratio, price_a=price_a, price_b=price_b,
                        max_notional_per_trade=self.risk.limits.eff_max_notional_per_trade(state.equity),
                        spread_std=sig.spread_std if np.isfinite(sig.spread_std) else None,
                        target_spread_vol=cfg.target_spread_vol or None,
                    )
                except RiskViolationError as exc:
                    reject_reason = str(exc)
                    sizing = None
                if sizing is not None:
                    decision = self.risk.validate_pair_entry(
                        broker="binance_spot",
                        notional_a=sizing.notional_a, notional_b=sizing.notional_b,
                        state=state, requires_short=True, paper_mode=True,
                        symbol_a=pair.symbol_a, symbol_b=pair.symbol_b,
                    )
                    if decision.approved:
                        pending.setdefault(exec_i, []).append(
                            _Pending(signal=sig, qty_a=sizing.qty_a, qty_b=sizing.qty_b)
                        )
                        accepted = True
                    else:
                        reject_reason = decision.reason()
        elif sig.action.is_exit and pair.key in open_pairs:
            # exits are always allowed; schedule for next bar open
            if open_pairs[pair.key].closing:
                reject_reason = "exit already scheduled"
            elif i + 1 < n:
                open_pairs[pair.key].closing = True
                pending.setdefault(i + 1, []).append(_Pending(signal=sig))
                accepted = True
            else:
                reject_reason = "end of data"
        elif sig.action is SignalAction.DISABLE_PAIR:
            accepted = True
        else:
            reject_reason = f"signal {sig.action.value} not applicable to current position state"

        signals.append({
            "ts": sig.ts, "pair_key": sig.pair_key, "action": sig.action.value,
            "z_score": sig.z_score, "hedge_ratio": sig.hedge_ratio, "spread": sig.spread,
            "spread_mean": sig.spread_mean, "spread_std": sig.spread_std,
            "accepted": accepted, "reject_reason": reject_reason, "reason": sig.reason,
        })

    def _execute(
        self,
        action: _Pending,
        i: int,
        broker: SimulatedBroker,
        open_np: dict[str, np.ndarray],
        open_pairs: dict[str, OpenPair],
        trades: list[PairTradeRecord],
        idx: pd.DatetimeIndex,
    ) -> float:
        sig = action.signal
        key = sig.pair_key
        symbol_a, symbol_b = key.split("|")
        ts = idx[i].to_pydatetime()
        broker.set_market({symbol_a: open_np[symbol_a][i], symbol_b: open_np[symbol_b][i]}, ts)

        if sig.action.is_entry:
            if key in open_pairs:
                return 0.0
            direction = 1 if sig.action is SignalAction.ENTER_LONG_SPREAD else -1
            side_a = Side.BUY if direction == 1 else Side.SELL
            side_b = Side.SELL if direction == 1 else Side.BUY
            fill_a = broker.execute_market(symbol_a, side_a, action.qty_a)
            fill_b = broker.execute_market(symbol_b, side_b, action.qty_b)
            open_pairs[key] = OpenPair(
                pair_key=key, direction=direction, qty_a=action.qty_a, qty_b=action.qty_b,
                symbol_a=symbol_a, symbol_b=symbol_b, entry_i=i, entry_ts=ts,
                entry_price_a=fill_a.price, entry_price_b=fill_b.price,
                entry_z=sig.z_score, beta=sig.hedge_ratio,
                fees=fill_a.fee + fill_b.fee,
            )
            self.risk.register_trade()
            return fill_a.notional + fill_b.notional

        if sig.action.is_exit and key in open_pairs:
            return self._close_pair(
                open_pairs.pop(key), i, broker,
                {symbol_a: open_np[symbol_a], symbol_b: open_np[symbol_b]},
                trades, idx, exit_z=sig.z_score, exit_reason=sig.action.value,
            )
        return 0.0

    def _close_pair(
        self,
        op: OpenPair,
        i: int,
        broker: SimulatedBroker,
        price_arrays: dict[str, np.ndarray],
        trades: list[PairTradeRecord],
        idx: pd.DatetimeIndex,
        exit_z: float,
        exit_reason: str,
    ) -> float:
        ts = idx[i].to_pydatetime()
        broker.set_market(
            {op.symbol_a: price_arrays[op.symbol_a][i], op.symbol_b: price_arrays[op.symbol_b][i]}, ts
        )
        side_a = Side.SELL if op.direction == 1 else Side.BUY
        side_b = Side.BUY if op.direction == 1 else Side.SELL
        fill_a = broker.execute_market(op.symbol_a, side_a, op.qty_a)
        fill_b = broker.execute_market(op.symbol_b, side_b, op.qty_b)

        signed_a = op.direction * op.qty_a
        signed_b = -op.direction * op.qty_b
        fees = op.fees + fill_a.fee + fill_b.fee
        pnl = (
            signed_a * (fill_a.price - op.entry_price_a)
            + signed_b * (fill_b.price - op.entry_price_b)
            - fees
        )
        trades.append(
            PairTradeRecord(
                pair_key=op.pair_key,
                direction="long_spread" if op.direction == 1 else "short_spread",
                entry_ts=op.entry_ts, exit_ts=ts, holding_bars=i - op.entry_i,
                qty_a=op.qty_a, qty_b=op.qty_b,
                entry_price_a=op.entry_price_a, entry_price_b=op.entry_price_b,
                exit_price_a=fill_a.price, exit_price_b=fill_b.price,
                entry_z=op.entry_z, exit_z=exit_z,
                beta=op.beta, pnl=pnl, fees=fees, exit_reason=exit_reason,
            )
        )
        return fill_a.notional + fill_b.notional
