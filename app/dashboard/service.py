"""Dashboard service layer: real engine data in, pydantic schemas out.

Everything reads from the same SQLite/Postgres storage, config files and
kill-switch flag the trading code uses — no mock data. Secrets never leave
this layer: settings views only report WHETHER keys are configured.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from app.brokers.base import load_capabilities
from app.config.settings import Settings
from app.core.logging import get_logger
from app.dashboard.schemas import (
    AuditEventOut,
    BacktestDetail,
    BacktestSummary,
    BrokerStatus,
    JobInfo,
    JobRequest,
    KillSwitchState,
    LogEvent,
    OrderInfo,
    PairInfo,
    PortfolioSummary,
    RiskLimitStatus,
    RiskStatus,
    SignalInfo,
    StrategyStatus,
    SystemStatus,
    TradeInfo,
)
from app.data.storage import Storage
from app.risk.kill_switch import KillSwitch
from app.risk.risk_manager import RiskLimits, load_risk_limits

log = get_logger(__name__)

STRATEGY_REGISTRY: dict[str, dict] = {
    "pairs_zscore": {"version": "1.0", "kind": "pair"},
    "cointegration_pairs": {"version": "1.0", "kind": "pair"},
    "kalman_pairs": {"version": "1.0", "kind": "pair"},
    "basket_pca_stat_arb": {"version": "1.0", "kind": "basket"},
    "basket_xsec_reversion": {"version": "1.0", "kind": "basket"},
}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DashboardService:
    def __init__(self, settings: Settings, storage: Storage) -> None:
        self.settings = settings
        self.storage = storage
        self.kill_switch = KillSwitch(Path(settings.runtime_dir) / "kill_switch.flag")
        self._paused_file = Path(settings.runtime_dir) / "paused_strategies.json"
        self._jobs: dict[str, JobInfo] = {}
        self._jobs_lock = threading.Lock()

    # -- helpers -----------------------------------------------------------------

    def _risk_limits(self) -> RiskLimits:
        s = self.settings
        return load_risk_limits(overrides={
            "max_daily_loss_pct": s.max_daily_loss_pct,
            "max_total_drawdown_pct": s.max_total_drawdown_pct,
            "max_gross_exposure": s.max_gross_exposure,
            "max_net_exposure": s.max_net_exposure,
            "max_notional_per_trade": s.max_notional_per_trade,
            "max_open_pairs": s.max_open_pairs,
            "max_trades_per_day": s.max_trades_per_day,
        })

    def paused_strategies(self) -> set[str]:
        if self._paused_file.exists():
            try:
                return set(json.loads(self._paused_file.read_text()))
            except Exception:  # noqa: BLE001
                return set()
        return set()

    def set_strategy_paused(self, name: str, paused: bool) -> set[str]:
        current = self.paused_strategies()
        if paused:
            current.add(name)
        else:
            current.discard(name)
        self._paused_file.parent.mkdir(parents=True, exist_ok=True)
        self._paused_file.write_text(json.dumps(sorted(current)))
        return current

    # -- system / brokers -------------------------------------------------------------

    def broker_statuses(self, probe: bool = False) -> list[BrokerStatus]:
        capabilities = load_capabilities()
        s = self.settings
        out: list[BrokerStatus] = []

        binance = BrokerStatus(
            broker="binance_spot",
            display_name="Binance Spot",
            enabled=s.binance_enabled,
            mode=s.binance_mode,
            asset_class="crypto_spot",
            key_configured=bool(s.binance_api_key and s.binance_api_secret),
            capabilities=capabilities["binance_spot"].model_dump(),
            detail="market data is public; account/orders need keys (testnet first)",
        )
        if probe:
            try:
                import time as _time

                from app.brokers.binance.client import BinancePublicData

                client = BinancePublicData()
                t0 = _time.perf_counter()
                client.ping()
                binance.latency_ms = round((_time.perf_counter() - t0) * 1000, 1)
                binance.connected = True
            except Exception as exc:  # noqa: BLE001
                binance.connected = False
                binance.detail = str(exc)[:200]
        out.append(binance)

        out.append(BrokerStatus(
            broker="trading212",
            display_name="Trading 212 (Invest/ISA)",
            enabled=s.trading212_enabled,
            mode=s.trading212_mode,
            asset_class="equity",
            key_configured=bool(s.trading212_api_key and s.trading212_api_secret),
            capabilities=capabilities["trading212"].model_dump(),
            detail="official Public API only; CFDs/shorting/margin unsupported by design",
        ))
        out.append(BrokerStatus(
            broker="binance_futures",
            display_name="Binance USD-M Futures",
            enabled=False,
            mode="disabled",
            asset_class="crypto_futures",
            key_configured=False,
            capabilities=capabilities["binance_futures"].model_dump(),
            detail="deliberately disabled by default (leverage/liquidation risk)",
        ))
        return out

    def system_status(self, probe: bool = False) -> SystemStatus:
        s = self.settings
        snaps = self.storage.load_equity_snapshots(mode="paper", limit=1)
        orders = self.storage.load_orders(limit=1)
        last_equity_ts = snaps["ts"].iloc[-1].to_pydatetime() if len(snaps) else None
        mode = "live" if s.live_trading_allowed else ("paper" if last_equity_ts else "research")
        kill = self.kill_switch
        bot_status = "halted" if kill.is_active else ("running" if last_equity_ts else "idle")
        return SystemStatus(
            mode=mode,
            bot_status=bot_status,
            app_env=s.app_env,
            live_trading_env=s.live_trading,
            confirm_live_env=s.confirm_live_trading,
            live_trading_allowed=s.live_trading_allowed,
            controls_enabled=s.dashboard_controls_enabled,
            kill_switch=KillSwitchState(active=kill.is_active, reason=kill.reason),
            brokers=self.broker_statuses(probe=probe),
            last_equity_ts=last_equity_ts,
            last_order_ts=orders[0].ts if orders else None,
            server_time=_utc_now(),
        )

    # -- portfolio ----------------------------------------------------------------------

    def portfolio_summary(self, mode: str = "paper") -> PortfolioSummary:
        snaps = self.storage.load_equity_snapshots(mode=mode, limit=10_000)
        trades = self.storage.load_trades(limit=10_000, mode=mode)
        realized = sum(t.pnl for t in trades)
        fees = sum(t.fees for t in trades)
        if snaps.empty:
            return PortfolioSummary(realized_pnl=realized, fees_paid=fees,
                                    n_trades=len(trades), has_data=False)
        last = snaps.iloc[-1]
        equity = float(last["equity"])
        first_equity = float(snaps["equity"].iloc[0])
        today = last["ts"].date()
        today_rows = snaps[snaps["ts"].dt.date == today]
        daily_start = float(today_rows["equity"].iloc[0]) if len(today_rows) else equity
        peak = float(snaps["equity"].cummax().iloc[-1])
        running_max = snaps["equity"].cummax()
        max_dd = float(((snaps["equity"] / running_max) - 1.0).min()) * 100
        return PortfolioSummary(
            as_of=last["ts"].to_pydatetime(),
            equity=equity,
            cash=float(last["cash"]),
            daily_pnl=equity - daily_start,
            total_pnl=equity - first_equity,
            realized_pnl=realized,
            fees_paid=fees,
            gross_exposure=float(last["gross_exposure"]),
            net_exposure=float(last["net_exposure"]),
            open_pairs=int(last["open_pairs"]),
            current_drawdown_pct=round(max(0.0, (peak - equity) / peak * 100), 4) if peak else 0.0,
            max_drawdown_pct=round(abs(max_dd), 4),
            n_trades=len(trades),
            has_data=True,
        )

    def equity_curve(self, mode: str = "paper", limit: int = 2000) -> list[dict]:
        df = self.storage.load_equity_snapshots(mode=mode, limit=limit)
        return [
            {"ts": str(r.ts), "equity": r.equity, "gross": r.gross_exposure,
             "net": r.net_exposure, "open_pairs": r.open_pairs}
            for r in df.itertuples(index=False)
        ]

    # -- risk --------------------------------------------------------------------------------

    def risk_status(self, mode: str = "paper") -> RiskStatus:
        limits = self._risk_limits()
        summary = self.portfolio_summary(mode)
        today = _utc_now().date()
        trades_today = sum(
            1 for t in self.storage.load_trades(limit=500, mode=mode)
            if t.entry_ts.date() == today
        )

        def status_of(pct: float) -> str:
            if pct >= 100.0:
                return "breached"
            if pct >= 75.0:
                return "warning"
            return "safe"

        def limit_row(name: str, current: float, limit: float) -> RiskLimitStatus:
            pct = (current / limit * 100.0) if limit else 0.0
            return RiskLimitStatus(name=name, current=round(current, 4),
                                   limit=limit, pct_used=round(pct, 2),
                                   status=status_of(pct))

        daily_loss_pct = max(0.0, -summary.daily_pnl / summary.equity * 100) if summary.equity else 0.0
        rows = [
            limit_row("daily_loss_pct", daily_loss_pct, limits.max_daily_loss_pct),
            limit_row("drawdown_pct", summary.current_drawdown_pct, limits.max_total_drawdown_pct),
            limit_row("gross_exposure", summary.gross_exposure, limits.max_gross_exposure),
            limit_row("net_exposure", abs(summary.net_exposure), limits.max_net_exposure),
            limit_row("open_pairs", summary.open_pairs, limits.max_open_pairs),
            limit_row("trades_per_day", trades_today, limits.max_trades_per_day),
            limit_row("notional_per_trade", 0.0, limits.max_notional_per_trade),
            limit_row("pair_loss", 0.0, limits.max_pair_loss),
            limit_row("slippage_bps", 0.0, limits.max_slippage_bps),
        ]
        return RiskStatus(
            kill_switch=KillSwitchState(active=self.kill_switch.is_active,
                                        reason=self.kill_switch.reason),
            limits=rows,
            as_of=_utc_now(),
        )

    # -- strategies ----------------------------------------------------------------------------

    def strategies(self) -> list[StrategyStatus]:
        from app.portfolio.performance import strategy_performance

        perf = strategy_performance(self.storage)
        signals = self.storage.load_signals(limit=500)
        last_signal: dict[str, datetime] = {}
        for sig in signals:
            last_signal.setdefault(sig.strategy, sig.ts)
        paused = self.paused_strategies()

        out: list[StrategyStatus] = []
        for name, meta in STRATEGY_REGISTRY.items():
            stats = perf.loc[name] if (not perf.empty and name in perf.index) else None
            n_trades = int(stats["n_trades"]) if stats is not None else 0
            total_pnl = float(stats["total_pnl"]) if stats is not None else 0.0
            health = "paused" if name in paused else (
                "idle" if n_trades == 0 else ("degraded" if total_pnl < 0 else "healthy")
            )
            out.append(StrategyStatus(
                name=name, version=meta["version"], kind=meta["kind"],
                paused=name in paused, health=health,
                n_trades=n_trades, total_pnl=round(total_pnl, 4),
                win_rate_pct=float(stats["win_rate_pct"]) if stats is not None else None,
                total_fees=float(stats["total_fees"]) if stats is not None else 0.0,
                last_signal_ts=last_signal.get(name),
            ))
        return out

    # -- pairs / backtests -------------------------------------------------------------------------

    def pairs(self) -> list[PairInfo]:
        rows = self.storage.load_active_pairs()
        return [PairInfo(
            id=r.id, universe=r.universe, interval=r.interval,
            symbol_a=r.symbol_a, symbol_b=r.symbol_b, beta=r.beta, alpha=r.alpha,
            correlation=r.correlation, eg_pvalue=r.eg_pvalue, adf_pvalue=r.adf_pvalue,
            half_life_bars=r.half_life_bars, spread_std=r.spread_std, score=r.score,
            is_active=r.is_active, window_start=r.window_start, window_end=r.window_end,
        ) for r in rows]

    def backtests(self, limit: int = 100) -> list[BacktestSummary]:
        return [BacktestSummary(
            id=r.id, strategy=r.strategy, interval=r.interval,
            start_ts=r.start_ts, end_ts=r.end_ts, created_at=r.created_at,
            metrics=json.loads(r.metrics_json or "{}"), report_path=r.report_path or "",
        ) for r in self.storage.list_backtest_runs(limit)]

    def backtest_detail(self, run_id: int) -> BacktestDetail | None:
        r = self.storage.get_backtest_run(run_id)
        if r is None:
            return None
        return BacktestDetail(
            id=r.id, strategy=r.strategy, interval=r.interval,
            start_ts=r.start_ts, end_ts=r.end_ts, created_at=r.created_at,
            metrics=json.loads(r.metrics_json or "{}"), report_path=r.report_path or "",
            params=json.loads(r.params_json or "{}"),
            equity=json.loads(getattr(r, "equity_json", "[]") or "[]"),
            trades=json.loads(getattr(r, "trades_json", "[]") or "[]"),
        )

    # -- orders / trades / signals / logs ----------------------------------------------------------------

    def orders(self, limit: int = 200, symbol: str | None = None,
               status: str | None = None) -> list[OrderInfo]:
        return [OrderInfo(
            id=r.id, ts=r.ts, mode=r.mode, broker=r.broker, strategy=r.strategy,
            pair_key=r.pair_key, symbol=r.symbol, side=r.side, order_type=r.order_type,
            quantity=r.quantity, ref_price=r.ref_price, notional=r.notional,
            status=r.status, fill_price=r.fill_price, fee=r.fee, error=r.error or "",
        ) for r in self.storage.load_orders(limit, symbol, status)]

    def trades(self, limit: int = 200, mode: str | None = None) -> list[TradeInfo]:
        return [TradeInfo(
            id=r.id, mode=r.mode, strategy=r.strategy, pair_key=r.pair_key,
            direction=r.direction, entry_ts=r.entry_ts, exit_ts=r.exit_ts,
            holding_bars=r.holding_bars, entry_z=r.entry_z, exit_z=r.exit_z,
            pnl=r.pnl, fees=r.fees, exit_reason=r.exit_reason,
        ) for r in self.storage.load_trades(limit, mode)]

    def signals(self, limit: int = 200) -> list[SignalInfo]:
        return [SignalInfo(
            id=r.id, ts=r.ts, mode=r.mode, strategy=r.strategy, pair_key=r.pair_key,
            action=r.action, z_score=r.z_score, hedge_ratio=r.hedge_ratio,
            accepted=r.accepted, reject_reason=r.reject_reason or "",
        ) for r in self.storage.load_signals(limit)]

    def audit_events(self, limit: int = 200) -> list[AuditEventOut]:
        return [AuditEventOut(
            id=r.id, ts=r.ts, actor=r.actor, action=r.action, mode=r.mode,
            confirmed=r.confirmed, payload=json.loads(r.payload_json or "{}"),
            result=r.result or "",
        ) for r in self.storage.load_audit_events(limit)]

    def logs(self, limit: int = 300, level: str | None = None) -> list[LogEvent]:
        path = Path(self.settings.logs_dir) / "app.log"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]
        out: list[LogEvent] = []
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if level and record.get("level", "").upper() != level.upper():
                continue
            out.append(LogEvent(
                ts=str(record.get("ts", "")), level=str(record.get("level", "INFO")),
                logger=str(record.get("logger", "")), message=str(record.get("message", "")),
            ))
            if len(out) >= limit:
                break
        return out

    # -- settings (masked) ----------------------------------------------------------------------------------

    def settings_view(self) -> dict:
        s = self.settings
        db = s.database_url
        if "@" in db:  # mask credentials in postgres URLs
            db = db.split("@")[-1]
        return {
            "app_env": s.app_env,
            "database": db,
            "live_trading": s.live_trading,
            "confirm_live_trading": s.confirm_live_trading,
            "dashboard_controls_enabled": s.dashboard_controls_enabled,
            "dashboard_token_set": bool(s.dashboard_token),
            "binance": {"enabled": s.binance_enabled, "mode": s.binance_mode,
                        "key_configured": bool(s.binance_api_key),
                        "futures": s.binance_use_futures},
            "trading212": {"enabled": s.trading212_enabled, "mode": s.trading212_mode,
                           "account_type": s.trading212_account_type,
                           "key_configured": bool(s.trading212_api_key)},
            "data_provider": s.data_provider,
            "risk_overrides": {
                "max_daily_loss_pct": s.max_daily_loss_pct,
                "max_total_drawdown_pct": s.max_total_drawdown_pct,
                "max_gross_exposure": s.max_gross_exposure,
                "max_net_exposure": s.max_net_exposure,
                "max_notional_per_trade": s.max_notional_per_trade,
                "max_open_pairs": s.max_open_pairs,
                "max_trades_per_day": s.max_trades_per_day,
            },
            "note": "Secrets are never exposed; configure keys via .env only.",
        }

    # -- background jobs (backtest / pair discovery) ------------------------------------------------------------

    def list_jobs(self) -> list[JobInfo]:
        with self._jobs_lock:
            return sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)

    def get_job(self, job_id: str) -> JobInfo | None:
        with self._jobs_lock:
            return self._jobs.get(job_id)

    def start_job(self, request: JobRequest) -> JobInfo:
        job = JobInfo(id=uuid.uuid4().hex[:12], kind=request.kind, status="running",
                      started_at=_utc_now())
        with self._jobs_lock:
            self._jobs[job.id] = job

        def run() -> None:
            try:
                if request.kind == "backtest":
                    result = self._run_backtest_job(request)
                elif request.kind == "discover_pairs":
                    result = self._run_discovery_job(request)
                else:
                    raise ValueError(f"unknown job kind {request.kind!r}")
                job.result = result
                job.status = "done"
            except Exception as exc:  # noqa: BLE001 — reported via the job record
                log.exception("dashboard job %s failed", job.id)
                job.status = "failed"
                job.error = str(exc)[:500]
            finally:
                job.finished_at = _utc_now()

        threading.Thread(target=run, daemon=True, name=f"job-{job.id}").start()
        return job

    def _run_backtest_job(self, request: JobRequest) -> dict:
        from datetime import timedelta

        from app.backtesting.engine import BacktestConfig, BacktestEngine
        from app.cli.main import _load_pairs, _strategy_factory
        from app.core.types import utc_now
        from app.data.market_data import build_price_matrix
        from app.risk.risk_manager import RiskManager

        pairs = _load_pairs(self.storage, request.universe, request.interval)
        if not pairs:
            raise ValueError(f"no saved pairs for {request.universe}/{request.interval} — "
                             "run pair discovery first")
        symbols = sorted({s for p in pairs for s in (p.symbol_a, p.symbol_b)})
        start = (utc_now() - timedelta(days=request.days)).replace(tzinfo=None) if request.days else None
        prices = build_price_matrix(self.storage, symbols, request.interval, start=start)
        config = BacktestConfig(interval=request.interval, bars_per_year=request.bars_per_year,
                                label=request.strategy)
        risk = RiskManager(limits=self._risk_limits(), kill_switch=KillSwitch())
        result = BacktestEngine(prices, pairs, _strategy_factory(request.strategy),
                                risk, config).run()
        equity = result.equity.dropna()
        step = max(1, len(equity) // 500)
        points = [[str(ts), round(float(v), 2)] for ts, v in equity.iloc[::step].items()]
        trades = [
            {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in t.__dict__.items()}
            for t in result.trades
        ]
        run_id = self.storage.save_backtest_run(
            strategy=request.strategy, interval=request.interval,
            start_ts=prices.index[0], end_ts=prices.index[-1],
            params={"universe": request.universe, "days": request.days,
                    "bars_per_year": request.bars_per_year},
            metrics=result.metrics, equity_points=points, trades=trades,
        )
        return {"backtest_id": run_id, "metrics": result.metrics}

    def _run_discovery_job(self, request: JobRequest) -> dict:
        from datetime import timedelta

        from app.core.types import utc_now
        from app.data.market_data import build_price_matrix
        from app.data.universe import get_universe
        from app.research.pair_selection import PairSelectionConfig, PairSelector

        overrides: dict = {}
        if request.max_eg_pvalue is not None:
            overrides["max_eg_pvalue"] = request.max_eg_pvalue
        if request.max_half_life is not None:
            overrides["max_half_life_bars"] = request.max_half_life
        config = PairSelectionConfig(**overrides)
        start = (utc_now() - timedelta(days=request.lookback_days)).replace(tzinfo=None)
        prices = build_price_matrix(self.storage, get_universe(request.universe),
                                    request.interval, start=start)
        pairs = PairSelector(config).select(prices.log_close)
        if pairs:
            self.storage.save_pairs(pairs, universe=request.universe, interval=request.interval,
                                    window_start=prices.index[0], window_end=prices.index[-1])
        return {"n_pairs": len(pairs), "pairs": [p.key for p in pairs]}
