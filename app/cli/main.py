"""Command-line interface.

    python -m app.cli.main --help
    statarb --help            (after `pip install -e .`)

Safe by default: every command works offline/paper; live trading is refused
unless every gate condition passes (and the live connectors are Phase 4/5).
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app.config.settings import get_settings
from app.core.logging import get_logger, setup_logging
from app.core.types import utc_now

app = typer.Typer(
    name="statarb",
    help="Statistical arbitrage research, backtesting and paper trading. "
    "LIVE TRADING IS DISABLED BY DEFAULT.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)
console = Console()
log = get_logger(__name__)

DEFAULT_INTERVAL = "15m"
STRATEGIES = ("pairs_zscore", "cointegration_pairs", "kalman_pairs")
BASKET_STRATEGIES = ("pca_stat_arb", "sector_stat_arb", "xsec_reversion", "tsmom",
                     "xsec_momentum", "ml_alpha")


def _bootstrap():
    settings = get_settings()
    settings.ensure_dirs()
    setup_logging(settings.log_level, settings.logs_dir)
    from app.data.storage import Storage

    return settings, Storage(settings.database_url)


def _parse_symbols(symbols: str | None, universe: str | None) -> list[str]:
    from app.data.universe import get_universe

    if symbols:
        return [s.strip().upper() for s in symbols.split(",") if s.strip()]
    return get_universe(universe or "crypto_top_10")


def _strategy_defaults(interval: str | None = None) -> dict:
    """Load strategy_defaults.yaml; on daily bars, merge the `daily:` profile.

    Every base parameter is tuned in 15m bars — applied to 1d bars the
    lookbacks are wrong by a factor of ~96 and the crypto cost model (15bps)
    overstates liquid-equity costs by ~3x. The `daily:` section overrides
    per-section keys when interval is '1d'.
    """
    import yaml

    from app.config.settings import CONFIG_DIR

    defaults = yaml.safe_load((CONFIG_DIR / "strategy_defaults.yaml").read_text(encoding="utf-8"))
    profile = defaults.pop("daily", None) or {}
    if interval == "1d":
        for section, overrides in profile.items():
            base = defaults.get(section)
            if isinstance(base, dict) and isinstance(overrides, dict):
                base.update(overrides)
            else:
                defaults[section] = overrides
    return defaults


def _bars_per_year(universe: str | None, interval: str) -> float | None:
    """252 for daily bars on an exchange calendar (stocks/FX); None = crypto 24/7."""
    if interval == "1d" and universe and not universe.startswith(("crypto", "synthetic")):
        return 252.0
    return None


def _strategy_factory(name: str, interval: str | None = None):
    """Build a fresh strategy instance per pair from strategy_defaults.yaml."""
    from app.strategies.cointegration_pairs import (
        CointegrationPairStrategy,
        CointegrationStrategyConfig,
    )
    from app.strategies.kalman_pairs import KalmanPairConfig, KalmanPairStrategy
    from app.strategies.pairs_zscore import ZScoreConfig, ZScorePairStrategy

    defaults = _strategy_defaults(interval)
    z_raw = dict(defaults.get("zscore_signal", {}))
    regime = defaults.get("regime_filter", {}) or {}
    if regime.get("enabled"):
        z_raw.update(
            use_regime_filter=True,
            regime_window=int(regime.get("window", 96)),
            regime_t_threshold=float(regime.get("t_threshold", 3.0)),
        )
    z_cfg = ZScoreConfig(**z_raw)
    if name == "pairs_zscore":
        return lambda pair: ZScorePairStrategy(pair, z_cfg)
    if name == "cointegration_pairs":
        c_raw = defaults.get("cointegration_strategy", {})
        c_cfg = CointegrationStrategyConfig(zscore=z_cfg, **c_raw)
        return lambda pair: CointegrationPairStrategy(pair, c_cfg)
    if name == "kalman_pairs":
        k_raw = dict(defaults.get("kalman_signal", {}) or {})
        if regime.get("enabled"):
            k_raw.update(
                use_regime_filter=True,
                regime_window=int(regime.get("window", 96)),
                regime_t_threshold=float(regime.get("t_threshold", 3.0)),
            )
        k_cfg = KalmanPairConfig(**k_raw)
        return lambda pair: KalmanPairStrategy(pair, k_cfg)
    raise typer.BadParameter(f"unknown strategy {name!r}; choose from {STRATEGIES}")


def _risk_manager(settings, kill_switch_file: bool = True):
    from app.brokers.base import load_capabilities
    from app.risk.kill_switch import KillSwitch
    from app.risk.risk_manager import RiskManager, load_risk_limits

    overrides = {
        "max_daily_loss_pct": settings.max_daily_loss_pct,
        "max_total_drawdown_pct": settings.max_total_drawdown_pct,
        "max_gross_exposure": settings.max_gross_exposure,
        "max_net_exposure": settings.max_net_exposure,
        "max_notional_per_trade": settings.max_notional_per_trade,
        "max_open_pairs": settings.max_open_pairs,
        "max_trades_per_day": settings.max_trades_per_day,
    }
    limits = load_risk_limits(overrides=overrides)
    switch = KillSwitch(settings.runtime_dir / "kill_switch.flag" if kill_switch_file else None)
    return RiskManager(limits=limits, kill_switch=switch, capabilities=load_capabilities())


def _load_pairs(storage, universe: str, interval: str):
    from app.research.pair_selection import SelectedPair

    rows = storage.load_active_pairs(universe=universe, interval=interval)
    return [
        SelectedPair(
            symbol_a=r.symbol_a, symbol_b=r.symbol_b, beta=r.beta, alpha=r.alpha,
            correlation=r.correlation, eg_pvalue=r.eg_pvalue, adf_pvalue=r.adf_pvalue,
            half_life=r.half_life_bars, spread_std=r.spread_std, score=r.score,
        )
        for r in rows
    ]


# --------------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------------


@app.command("init-db")
def init_db() -> None:
    """Create database tables."""
    _, storage = _bootstrap()
    storage.init_db()
    console.print(f"[green]Database initialised:[/green] {storage.database_url}")


@app.command("download-data")
def download_data(
    symbols: str | None = typer.Option(None, help="Comma-separated, e.g. BTCUSDT,ETHUSDT"),
    universe: str | None = typer.Option(None, help="Named universe (default crypto_top_10)"),
    interval: str = typer.Option(DEFAULT_INTERVAL),
    days: int = typer.Option(90, min=1),
    source: str = typer.Option("binance", help="binance | synthetic (offline demo)"),
) -> None:
    """Download historical klines into local storage (no API key needed)."""
    _, storage = _bootstrap()
    storage.init_db()
    from app.data.historical_loader import HistoricalDataLoader

    if source == "synthetic" and not symbols and not universe:
        universe = "synthetic_demo"
    syms = _parse_symbols(symbols, universe)
    summary = HistoricalDataLoader(storage).download(syms, interval, days, source=source)

    table = Table(title=f"Download summary ({source}, {interval}, {days}d)")
    table.add_column("symbol")
    table.add_column("new rows", justify="right")
    for sym, n in summary.symbols.items():
        table.add_row(sym, str(n))
    console.print(table)
    failed = [r for r in summary.reports if not r.passed]
    if failed:
        console.print(f"[yellow]{len(failed)} symbols flagged by data-quality checks "
                      f"(see logs).[/yellow]")


@app.command("discover-pairs")
def discover_pairs(
    universe: str = typer.Option("crypto_top_10"),
    interval: str = typer.Option(DEFAULT_INTERVAL),
    lookback_days: int = typer.Option(90, "--lookback-days"),
    source: str | None = typer.Option(None, help="restrict to a data source"),
    max_eg_pvalue: float | None = typer.Option(None, help="override Engle-Granger p threshold"),
    max_adf_pvalue: float | None = typer.Option(None, help="override ADF p threshold"),
    min_correlation: float | None = typer.Option(None, help="override correlation prefilter"),
    min_half_life: float | None = typer.Option(None, help="override min half-life (bars)"),
    max_half_life: float | None = typer.Option(None, help="override max half-life (bars)"),
) -> None:
    """Run cointegration pair discovery on stored data and save the results.

    Loosening the thresholds finds more pairs but with WEAKER statistical
    evidence - expect more false positives and faster model decay.
    """
    _, storage = _bootstrap()
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe
    from app.research.pair_selection import PairSelectionConfig, PairSelector

    defaults = _strategy_defaults(interval)
    raw = {k: v for k, v in (defaults.get("pair_selection") or {}).items()
           if k in PairSelectionConfig.model_fields}
    overrides = {
        "max_eg_pvalue": max_eg_pvalue, "max_adf_pvalue": max_adf_pvalue,
        "min_correlation": min_correlation, "min_half_life_bars": min_half_life,
        "max_half_life_bars": max_half_life,
    }
    raw.update({k: v for k, v in overrides.items() if v is not None})
    cfg = PairSelectionConfig(**raw)

    start = utc_now() - timedelta(days=lookback_days)
    prices = build_price_matrix(storage, get_universe(universe), interval,
                                start=start.replace(tzinfo=None), source=source)
    pairs = PairSelector(cfg).select(prices.log_close)
    if not pairs:
        console.print("[red]No tradeable pairs found.[/red] Try a longer lookback or "
                      "looser thresholds in config/strategy_defaults.yaml.")
        raise typer.Exit(1)

    storage.save_pairs(pairs, universe=universe, interval=interval,
                       window_start=prices.index[0], window_end=prices.index[-1])

    table = Table(title=f"Selected pairs ({universe}, {interval})")
    for col in ("pair", "beta", "EG p", "ADF p", "half-life", "corr", "score"):
        table.add_column(col, justify="right")
    for p in pairs:
        table.add_row(p.key, f"{p.beta:.3f}", f"{p.eg_pvalue:.4f}", f"{p.adf_pvalue:.4f}",
                      f"{p.half_life:.1f}", f"{p.correlation:.2f}", f"{p.score:.2f}")
    console.print(table)


@app.command("backtest")
def backtest(
    strategy: str = typer.Option("cointegration_pairs"),
    universe: str = typer.Option("crypto_top_10"),
    interval: str = typer.Option(DEFAULT_INTERVAL),
    days: int | None = typer.Option(None, help="restrict to the last N days of data"),
    stress: bool = typer.Option(False, help="also run the stress-test suite"),
    allocate: bool = typer.Option(False, help="inverse-vol capital allocation across pairs"),
    bars_per_year: float | None = typer.Option(
        None, "--bars-per-year",
        help="annualization override: ~252 for daily equity/FX bars (default: 24/7 crypto)",
    ),
) -> None:
    """Backtest a strategy on the saved pairs (event-driven, costs included)."""
    settings, storage = _bootstrap()
    from app.backtesting.engine import BacktestConfig, BacktestEngine
    from app.backtesting.report import render_markdown_report
    from app.backtesting.stress_tests import run_stress_suite
    from app.data.market_data import build_price_matrix

    pairs = _load_pairs(storage, universe, interval)
    if not pairs:
        console.print("[red]No saved pairs.[/red] Run `discover-pairs` first.")
        raise typer.Exit(1)

    symbols = sorted({s for p in pairs for s in (p.symbol_a, p.symbol_b)})
    start = (utc_now() - timedelta(days=days)).replace(tzinfo=None) if days else None
    prices = build_price_matrix(storage, symbols, interval, start=start)

    defaults = _strategy_defaults(interval)
    bt_raw = defaults.get("backtest", {})
    per_pair_pct = None
    if allocate:
        from app.strategies.portfolio_allocator import AllocationConfig, inverse_vol_pair_weights

        alloc_raw = defaults.get("allocation", {}) or {}
        per_pair_pct = inverse_vol_pair_weights(
            pairs, AllocationConfig(**{k: v for k, v in alloc_raw.items()
                                       if k in AllocationConfig.model_fields})
        )
        console.print(f"Allocation: { {k: round(v, 3) for k, v in per_pair_pct.items()} }")
    bt_config = BacktestConfig(
        interval=interval,
        starting_cash=float(bt_raw.get("starting_cash", 10_000)),
        target_pct_per_pair=float(bt_raw.get("target_pct_per_pair", 0.10)),
        per_pair_target_pct=per_pair_pct,
        slippage_bps=float(bt_raw.get("slippage_bps", 5)),
        commission_bps=float(bt_raw.get("commission_bps", 10)),
        allow_short=bool(bt_raw.get("allow_short", True)),
        bars_per_year=bars_per_year or _bars_per_year(universe, interval),
        min_edge_ratio=float(bt_raw.get("min_edge_ratio", 0)),
        target_spread_vol=float(bt_raw.get("target_spread_vol", 0)),
        label=strategy,
    )

    def run_one(config: BacktestConfig):
        engine = BacktestEngine(
            prices, pairs, _strategy_factory(strategy, interval),
            _risk_manager(settings, kill_switch_file=False), config,
        )
        return engine.run()

    console.print(f"Running backtest: [bold]{strategy}[/bold] on {len(pairs)} pairs, "
                  f"{len(prices.index)} bars...")
    result = run_one(bt_config)

    stress_df = None
    if stress:
        console.print("Running stress scenarios...")
        stress_df = run_stress_suite(run_one, bt_config)

    report_path = render_markdown_report(result, strategy_name=strategy,
                                         out_dir=settings.reports_dir, stress=stress_df)
    equity = result.equity.dropna()
    step = max(1, len(equity) // 500)
    equity_points = [[str(ts), round(float(v), 2)] for ts, v in equity.iloc[::step].items()]
    trade_dicts = [
        {k: (str(v) if hasattr(v, "isoformat") else v) for k, v in t.__dict__.items()}
        for t in result.trades
    ]
    storage.save_backtest_run(
        strategy=strategy, interval=interval,
        start_ts=prices.index[0], end_ts=prices.index[-1],
        params=bt_config.__dict__, metrics=result.metrics, report_path=str(report_path),
        equity_points=equity_points, trades=trade_dicts,
    )

    table = Table(title=f"Backtest metrics - {strategy}")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for key, value in result.metrics.items():
        table.add_row(key, str(value))
    console.print(table)
    if stress_df is not None:
        console.print(stress_df)
    console.print(f"\n[green]Report:[/green] {report_path}")
    console.print("[dim]Simulated results only - not a promise of profitability.[/dim]")


def _basket_weight_fn(strategy: str, defaults: dict, long_only: bool,
                      universe: str | None = None):
    """Build a basket WeightFn from strategy_defaults.yaml."""
    basket_raw = defaults.get("basket", {}) or {}
    momentum_raw = defaults.get("momentum", {}) or {}

    if strategy in ("pca_stat_arb", "sector_stat_arb"):
        from app.strategies.pca_stat_arb import PCAStatArbConfig, make_pca_weight_fn

        sectors: dict[str, str] = {}
        if strategy == "sector_stat_arb":
            from app.data.universe import get_sectors

            sectors = get_sectors(universe) if universe else {}
            if not sectors:
                raise typer.BadParameter(
                    f"sector_stat_arb needs a universe with a sector map; "
                    f"{universe!r} has none (US stock universes only)")
        return make_pca_weight_fn(PCAStatArbConfig(
            n_components=int(basket_raw.get("n_components", 3)),
            var_threshold=float(basket_raw.get("var_threshold", 0)),
            score_window=int(basket_raw.get("score_window", 60)),
            top_k=int(basket_raw.get("top_k", 2)),
            long_only=long_only,
            use_ou_scores=bool(basket_raw.get("use_ou_scores", True)),
            s_entry=float(basket_raw.get("s_entry", 1.25)),
            s_exit=float(basket_raw.get("s_exit", 0.25)),
            max_residual_half_life=float(basket_raw.get("max_residual_half_life", 40)),
            sectors=sectors,
            min_sector_size=int(basket_raw.get("min_sector_size", 3)),
        ))
    if strategy == "xsec_reversion":
        from app.strategies.cross_sectional_mean_reversion import (
            XSecReversalConfig,
            make_xsec_weight_fn,
        )

        return make_xsec_weight_fn(XSecReversalConfig(
            lookback_bars=int(basket_raw.get("xsec_lookback_bars", 12)),
            top_k=int(basket_raw.get("top_k", 2)),
            long_only=long_only,
        ))
    if strategy == "tsmom":
        from app.strategies.momentum import TSMOMConfig, make_tsmom_weight_fn

        return make_tsmom_weight_fn(TSMOMConfig(
            lookback_bars=int(momentum_raw.get("tsmom_lookback_bars", 672)),
            skip_bars=int(momentum_raw.get("tsmom_skip_bars", 12)),
            vol_window=int(momentum_raw.get("tsmom_vol_window", 96)),
            max_weight=float(momentum_raw.get("tsmom_max_weight", 0.30)),
            long_only=long_only,
        ))
    if strategy == "ml_alpha":
        from app.strategies.ml_alpha import MLAlphaConfig, make_ml_alpha_weight_fn

        ml_raw = dict(defaults.get("ml_alpha", {}) or {})
        ml_raw["long_only"] = long_only
        return make_ml_alpha_weight_fn(MLAlphaConfig(
            **{k: v for k, v in ml_raw.items() if k in MLAlphaConfig.model_fields}
        ))
    if strategy == "xsec_momentum":
        from app.strategies.momentum import XSMOMConfig, make_xsmom_weight_fn

        return make_xsmom_weight_fn(XSMOMConfig(
            lookback_bars=int(momentum_raw.get("xsmom_lookback_bars", 336)),
            skip_bars=int(momentum_raw.get("xsmom_skip_bars", 12)),
            top_k=int(momentum_raw.get("xsmom_top_k", 2)),
            top_frac=float(momentum_raw.get("xsmom_top_frac", 0)),
            long_only=long_only,
        ))
    raise typer.BadParameter(f"unknown basket strategy {strategy!r}; choose from {BASKET_STRATEGIES}")


@app.command("backtest-basket")
def backtest_basket(
    strategy: str = typer.Option("pca_stat_arb", help=" | ".join(BASKET_STRATEGIES)),
    universe: str = typer.Option("crypto_top_10"),
    interval: str = typer.Option(DEFAULT_INTERVAL),
    long_only: bool = typer.Option(False, help="long-only rotation (NOT market-neutral)"),
    rebalance_every: int | None = typer.Option(None, help="bars between rebalances"),
) -> None:
    """Backtest a cross-sectional basket strategy (PCA residuals, reversal, momentum)."""
    settings, storage = _bootstrap()
    from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe

    defaults = _strategy_defaults(interval)
    basket_raw = defaults.get("basket", {}) or {}
    weight_fn = _basket_weight_fn(strategy, defaults, long_only, universe)

    prices = build_price_matrix(storage, get_universe(universe), interval)
    config = BasketConfig(
        interval=interval,
        fit_window=int(basket_raw.get("fit_window", 1500)),
        rebalance_every=rebalance_every or int(basket_raw.get("rebalance_every", 24)),
        cost_bps=float(basket_raw.get("cost_bps", 15)),
        bars_per_year=_bars_per_year(universe, interval),
        label=strategy,
    )
    mode_note = " [yellow](long-only: NOT market-neutral)[/yellow]" if long_only else ""
    console.print(f"Basket backtest: [bold]{strategy}[/bold]{mode_note} on "
                  f"{len(prices.symbols)} assets, {len(prices.index)} bars...")
    result = run_basket_backtest(prices.close, weight_fn, config, aux=prices.aux)
    storage.save_backtest_run(
        strategy=f"basket_{strategy}{'_long_only' if long_only else ''}", interval=interval,
        start_ts=prices.index[0], end_ts=prices.index[-1],
        params={**basket_raw, "long_only": long_only}, metrics=result.metrics,
    )
    table = Table(title=f"Basket metrics - {strategy}")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for key, value in result.metrics.items():
        table.add_row(key, str(value))
    console.print(table)
    for warning in result.warnings:
        console.print(f"[dim]- {warning}[/dim]")


def _build_ensemble(sleeves: str | None, defaults: dict, long_only: bool,
                    universe: str, interval: str, leverage: float, reb_every: int):
    """Risk-parity ensemble from strategy_defaults.yaml (shared by the
    ensemble backtest and the basket paper trader)."""
    from app.core.math_utils import periods_per_year
    from app.strategies.ensemble import EnsembleConfig, RiskParityEnsemble

    basket_raw = defaults.get("basket", {}) or {}
    ens_raw = defaults.get("ensemble", {}) or {}
    names = ([s.strip() for s in sleeves.split(",") if s.strip()] if sleeves
             else list(ens_raw.get("sleeves", ["pca_stat_arb", "xsec_reversion", "tsmom"])))
    for name in names:
        if name not in BASKET_STRATEGIES:
            raise typer.BadParameter(f"unknown sleeve {name!r}; choose from {BASKET_STRATEGIES}")
    bpy = _bars_per_year(universe, interval) or periods_per_year(interval)
    ensemble = RiskParityEnsemble(
        {name: _basket_weight_fn(name, defaults, long_only, universe) for name in names},
        EnsembleConfig(
            vol_window=int(ens_raw.get("vol_window", 30)),
            min_observations=int(ens_raw.get("min_observations", 5)),
            gross_target=float(ens_raw.get("gross_target", 1.0)),
            leverage=leverage,
            max_sleeve_share=float(ens_raw.get("max_sleeve_share", 0.60)),
            min_sleeve_t=float(ens_raw.get("min_sleeve_t", -0.5)),
            cost_bps=float(basket_raw.get("cost_bps", 15)),
            target_vol_pct=float(ens_raw.get("target_vol_pct", 0)),
            rebalances_per_year=bpy / reb_every,
        ),
    )
    return names, ensemble


@app.command("backtest-ensemble")
def backtest_ensemble(
    sleeves: str | None = typer.Option(
        None, help="comma-separated basket strategies (default from strategy_defaults.yaml)"
    ),
    universe: str = typer.Option("crypto_top_10"),
    interval: str = typer.Option(DEFAULT_INTERVAL),
    long_only: bool = typer.Option(False, help="long-only sleeves (NOT market-neutral)"),
    rebalance_every: int | None = typer.Option(None, help="bars between rebalances"),
    leverage: float = typer.Option(
        1.0, help="multiply the whole book; margin/borrow costs NOT modeled "
                  "— research only"),
) -> None:
    """Backtest a risk-parity ensemble of basket strategies (multi-strat style).

    Sleeves are combined with inverse-volatility allocations estimated on each
    sleeve's own realized returns, so no single sleeve dominates portfolio risk.
    """
    settings, storage = _bootstrap()
    from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe

    defaults = _strategy_defaults(interval)
    basket_raw = defaults.get("basket", {}) or {}
    ens_raw = defaults.get("ensemble", {}) or {}
    reb_every = rebalance_every or int(basket_raw.get("rebalance_every", 24))
    names, ensemble = _build_ensemble(sleeves, defaults, long_only, universe,
                                      interval, leverage, reb_every)
    prices = build_price_matrix(storage, get_universe(universe), interval)
    config = BasketConfig(
        interval=interval,
        fit_window=int(basket_raw.get("fit_window", 1500)),
        rebalance_every=reb_every,
        cost_bps=float(basket_raw.get("cost_bps", 15)),
        bars_per_year=_bars_per_year(universe, interval),
        label="ensemble",
    )
    mode_note = " [yellow](long-only: NOT market-neutral)[/yellow]" if long_only else ""
    console.print(f"Ensemble backtest: [bold]{' + '.join(names)}[/bold]{mode_note} on "
                  f"{len(prices.symbols)} assets, {len(prices.index)} bars...")
    result = run_basket_backtest(prices.close, ensemble, config, aux=prices.aux)
    storage.save_backtest_run(
        strategy=f"ensemble_{'_'.join(names)}{'_long_only' if long_only else ''}",
        interval=interval, start_ts=prices.index[0], end_ts=prices.index[-1],
        params={**ens_raw, "sleeves": names, "long_only": long_only}, metrics=result.metrics,
    )
    table = Table(title="Ensemble metrics")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for key, value in result.metrics.items():
        table.add_row(key, str(value))
    console.print(table)
    console.print(f"Final sleeve risk shares: "
                  f"{ {k: round(v, 3) for k, v in ensemble.sleeve_allocations().items()} }")
    for warning in result.warnings:
        console.print(f"[dim]- {warning}[/dim]")


@app.command("paper-trade-basket")
def paper_trade_basket(
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    sleeves: str | None = typer.Option(
        None, help="comma-separated basket strategies (default from strategy_defaults.yaml)"
    ),
    leverage: float = typer.Option(1.0, help="book multiplier; margin costs NOT modeled"),
    source: str = typer.Option("yahoo", help="bar source: yahoo | stooq | binance"),
    starting_cash: float = typer.Option(10_000.0),
    iterations: int | None = typer.Option(None, help="polling cycles (default: run forever)"),
    poll_seconds: int | None = typer.Option(None, help="seconds between cycles (default 1800)"),
    no_refresh: bool = typer.Option(False, help="skip provider refresh; trade stored bars only"),
) -> None:
    """Paper-trade the basket ensemble (simulated fills, NO real orders).

    Runs the same risk-parity ensemble as `backtest-ensemble` against live
    end-of-day data: each new completed bar it recomputes target weights on
    the rolling fit window and rebalances a simulated portfolio through the
    risk manager. Shorting is SIMULATED — no connected stock broker can
    short, so this is a validation harness, not a path to live equity orders.
    """
    settings, storage = _bootstrap()
    from app.data.universe import get_universe
    from app.execution.basket_paper_trader import BasketPaperConfig, BasketPaperTrader

    defaults = _strategy_defaults(interval)
    basket_raw = defaults.get("basket", {}) or {}
    bt_raw = defaults.get("backtest", {}) or {}
    reb_every = int(basket_raw.get("rebalance_every", 24))
    names, ensemble = _build_ensemble(sleeves, defaults, long_only=False,
                                      universe=universe, interval=interval,
                                      leverage=leverage, reb_every=reb_every)
    config = BasketPaperConfig(
        symbols=get_universe(universe),
        interval=interval,
        fit_window=int(basket_raw.get("fit_window", 1500)),
        starting_cash=starting_cash,
        slippage_bps=float(bt_raw.get("slippage_bps", 5)),
        commission_bps=float(bt_raw.get("commission_bps", 10)),
        source=source,
        label=f"ensemble_{'_'.join(names)}",
    )
    trader = BasketPaperTrader(settings, storage, ensemble,
                               _risk_manager(settings), config,
                               refresh_data=not no_refresh)
    console.print(f"[green]Basket paper trading[/green]: {' + '.join(names)} on "
                  f"{universe} ({len(config.symbols)} symbols, {interval}). "
                  f"[bold]NO REAL ORDERS.[/bold]")
    trader.run(iterations=iterations, poll_seconds=poll_seconds)


@app.command("carry-backtest")
def carry_backtest(
    universe: str = typer.Option("crypto_top_10"),
    symbols: str | None = typer.Option(None, help="comma-separated perp symbols"),
    days: int = typer.Option(365, help="funding history window"),
    top_k: int = typer.Option(3),
    lookback_periods: int = typer.Option(30, help="trailing 8h periods (~10 days)"),
    cost_bps: float = typer.Option(30.0, help="both legs in+out per unit traded"),
    entry_apr: float = typer.Option(0.05, help="enter when trailing carry clears this"),
    exit_apr: float = typer.Option(0.0, help="hold until trailing carry decays through this"),
) -> None:
    """Research backtest of delta-neutral funding-rate carry (long spot, short perp).

    Models the FUNDING LEG ONLY — basis risk, margin interest and liquidation
    risk are not included, and no futures account is connected. Funding history
    comes from the public Binance futures REST API (no key required).
    """
    _, storage = _bootstrap()
    import pandas as pd

    from app.data.providers_binance_futures import BinanceFundingRates
    from app.research.funding_carry import CarryConfig, run_carry_backtest

    names = _parse_symbols(symbols, universe)
    client = BinanceFundingRates()
    start = (utc_now() - timedelta(days=days)).replace(tzinfo=None)
    end = utc_now().replace(tzinfo=None)
    panels: dict[str, pd.Series] = {}
    for sym in names:
        df = client.fetch_funding(sym, start, end)
        if df.empty:
            console.print(f"[yellow]no funding history for {sym} — skipped[/yellow]")
            continue
        panels[sym] = df.set_index("ts")["funding_rate"]
        console.print(f"[dim]{sym}: {len(df)} funding periods, "
                      f"avg {df['funding_rate'].mean() * 3 * 365 * 100:.1f}%/yr[/dim]")
    if len(panels) < 2:
        console.print("[red]Not enough perp funding history.[/red]")
        raise typer.Exit(1)

    funding = pd.DataFrame(panels).sort_index()
    result = run_carry_backtest(funding, CarryConfig(
        lookback_periods=lookback_periods, top_k=top_k, cost_bps=cost_bps,
        entry_apr=entry_apr, exit_apr=exit_apr,
    ))
    storage.save_backtest_run(
        strategy="funding_carry", interval="8h",
        start_ts=funding.index[0], end_ts=funding.index[-1],
        params={"top_k": top_k, "lookback_periods": lookback_periods,
                "cost_bps": cost_bps, "entry_apr": entry_apr,
                "exit_apr": exit_apr, "symbols": list(panels)},
        metrics=result.metrics,
    )
    table = Table(title="Funding-carry metrics (funding leg only)")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for key, value in result.metrics.items():
        table.add_row(key, str(value))
    console.print(table)
    for warning in result.warnings:
        console.print(f"[dim]- {warning}[/dim]")


@app.command("walk-forward")
def walk_forward(
    strategy: str = typer.Option("cointegration_pairs"),
    universe: str = typer.Option("crypto_top_10"),
    interval: str = typer.Option(DEFAULT_INTERVAL),
    train_bars: int | None = typer.Option(None),
    test_bars: int | None = typer.Option(None),
) -> None:
    """Walk-forward validation: select pairs in-sample, trade out-of-sample."""
    settings, storage = _bootstrap()
    from app.backtesting.engine import BacktestConfig
    from app.backtesting.report import render_walk_forward_report
    from app.backtesting.walk_forward import run_walk_forward
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe
    from app.research.pair_selection import PairSelectionConfig
    from app.risk.risk_manager import load_risk_limits

    defaults = _strategy_defaults(interval)
    wf_raw = defaults.get("walk_forward", {})
    sel_cfg = PairSelectionConfig(
        **{k: v for k, v in (defaults.get("pair_selection") or {}).items()
           if k in PairSelectionConfig.model_fields}
    )
    bt_raw = defaults.get("backtest", {})
    bt_config = BacktestConfig(
        interval=interval,
        starting_cash=float(bt_raw.get("starting_cash", 10_000)),
        target_pct_per_pair=float(bt_raw.get("target_pct_per_pair", 0.10)),
        slippage_bps=float(bt_raw.get("slippage_bps", 5)),
        commission_bps=float(bt_raw.get("commission_bps", 10)),
        allow_short=bool(bt_raw.get("allow_short", True)),
        bars_per_year=_bars_per_year(universe, interval),
        min_edge_ratio=float(bt_raw.get("min_edge_ratio", 0)),
        target_spread_vol=float(bt_raw.get("target_spread_vol", 0)),
    )

    prices = build_price_matrix(storage, get_universe(universe), interval)
    console.print(f"Walk-forward: {len(prices.index)} bars available")
    wf = run_walk_forward(
        prices,
        train_bars=train_bars or int(wf_raw.get("train_bars", 4000)),
        test_bars=test_bars or int(wf_raw.get("test_bars", 1000)),
        selection_config=sel_cfg,
        strategy_factory=_strategy_factory(strategy, interval),
        bt_config=bt_config,
        risk_limits=load_risk_limits(),
    )
    if not wf.windows:
        console.print("[red]Not enough data for a single walk-forward window.[/red]")
        raise typer.Exit(1)

    report_path = render_walk_forward_report(wf, strategy_name=strategy,
                                             out_dir=settings.reports_dir)
    table = Table(title="Walk-forward summary")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for key, value in wf.summary.items():
        table.add_row(key, str(value))
    console.print(table)
    console.print(f"\n[green]Report:[/green] {report_path}")


@app.command("paper-trade")
def paper_trade(
    broker: str = typer.Option("binance"),
    strategy: str = typer.Option("cointegration_pairs"),
    universe: str = typer.Option("crypto_top_10"),
    interval: str = typer.Option(DEFAULT_INTERVAL),
    iterations: int | None = typer.Option(None, help="stop after N polling cycles"),
) -> None:
    """Paper trade with live market data and simulated fills. NO REAL ORDERS."""
    settings, storage = _bootstrap()
    storage.init_db()
    if broker != "binance":
        console.print("[red]Only the Binance (crypto) paper feed is wired in this phase. "
                      "Trading 212 paper trading arrives with the Phase 5 connector.[/red]")
        raise typer.Exit(1)

    from app.execution.paper_trader import PaperTrader

    pairs = _load_pairs(storage, universe, interval)
    if not pairs:
        console.print("[red]No saved pairs.[/red] Run `discover-pairs` first.")
        raise typer.Exit(1)

    factory = _strategy_factory(strategy, interval)
    strategies = {p.key: factory(p) for p in pairs}
    risk = _risk_manager(settings)
    console.print(f"[bold green]PAPER mode[/bold green] - {len(pairs)} pairs, interval {interval}. "
                  "Simulated fills only; no orders are sent to any exchange.")
    PaperTrader(settings, storage, pairs, strategies, risk, interval=interval).run(iterations=iterations)


@app.command("live-trade")
def live_trade(
    broker: str = typer.Option(...),
    strategy: str = typer.Option("cointegration_pairs"),
    confirm_live: bool = typer.Option(False, "--confirm-live",
                                      help="Required explicit confirmation flag."),
) -> None:
    """Attempt to enable live trading. Refuses unless EVERY gate condition passes."""
    settings, storage = _bootstrap()
    checks: list[tuple[str, bool, str]] = []

    def gate(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    gate("LIVE_TRADING=true", settings.live_trading, "set in .env")
    gate("CONFIRM_LIVE_TRADING=true", settings.confirm_live_trading, "set in .env")
    gate("--confirm-live flag", confirm_live, "pass the flag explicitly")

    from app.risk.kill_switch import KillSwitch

    switch = KillSwitch(settings.runtime_dir / "kill_switch.flag")
    gate("kill switch off", not switch.is_active, switch.reason)

    last_run = storage.last_backtest_run() if Path(
        settings.database_url.replace("sqlite:///", "")
    ).exists() else None
    gate("recent backtest report exists", last_run is not None,
         last_run.report_path if last_run else "run `backtest` first")

    broker_ok = False
    detail = ""
    clock_ok = False
    clock_detail = ""
    if broker == "binance":
        try:
            from app.brokers.binance.client import BinancePublicData

            public = BinancePublicData()
            broker_ok = public.ping()
            detail = "public API reachable"
            offset = public.clock_offset_ms()
            clock_ok = abs(offset) < 2000
            clock_detail = f"local-exchange offset {offset:.0f}ms (limit 2000ms)"
        except Exception as exc:  # noqa: BLE001
            detail = detail or str(exc)
            clock_detail = "unreachable"
    elif broker == "trading212":
        detail = "demo-first connector available; enable TRADING212_ENABLED and test on demo"
    gate("broker connectivity", broker_ok, detail)
    gate("system clock synchronized", clock_ok, clock_detail)
    gate("paper-trading minimum period completed", False,
         "complete a supervised paper-trading period and review its trades first")

    table = Table(title="Live trading gate")
    table.add_column("condition")
    table.add_column("status")
    table.add_column("detail")
    for name, ok, det in checks:
        table.add_row(name, "[green]PASS[/green]" if ok else "[red]FAIL[/red]", det)
    console.print(table)

    console.print("\n[bold red]LIVE TRADING REFUSED.[/bold red] All conditions must pass - "
                  "and live order placement is not implemented in this phase. "
                  "This is intentional: paper trade first.")
    raise typer.Exit(2)


@app.command("kill-switch")
def kill_switch(
    engage: bool = typer.Option(False, "--engage"),
    disengage: bool = typer.Option(False, "--disengage"),
    reason: str = typer.Option("manual", help="reason recorded when engaging"),
) -> None:
    """Engage/disengage/inspect the global kill switch."""
    settings, _ = _bootstrap()
    from app.risk.kill_switch import KillSwitch

    switch = KillSwitch(settings.runtime_dir / "kill_switch.flag")
    if engage:
        switch.engage(reason)
        console.print("[red]Kill switch ENGAGED - all order flow halted.[/red]")
    elif disengage:
        switch.disengage()
        console.print("[green]Kill switch disengaged.[/green]")
    else:
        status = switch.status()
        color = "red" if status["active"] else "green"
        console.print(f"Kill switch: [{color}]{'ACTIVE' if status['active'] else 'off'}[/{color}] "
                      f"{status['reason']}")


@app.command("report")
def report(last_backtest: bool = typer.Option(True, "--last-backtest/--all")) -> None:
    """Show the most recent backtest run."""
    _, storage = _bootstrap()
    run = storage.last_backtest_run()
    if run is None:
        console.print("[yellow]No backtest runs recorded yet.[/yellow]")
        raise typer.Exit(1)
    console.print(f"[bold]{run.strategy}[/bold] {run.interval} "
                  f"{run.start_ts} -> {run.end_ts} (created {run.created_at})")
    metrics = json.loads(run.metrics_json)
    table = Table(title="Metrics")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for key, value in metrics.items():
        table.add_row(key, str(value))
    console.print(table)
    if run.report_path:
        console.print(f"[green]Full report:[/green] {run.report_path}")


@app.command("dashboard")
def dashboard(
    port: int = typer.Option(8000),
    host: str = typer.Option("127.0.0.1", help="keep this local unless you know what you're doing"),
) -> None:
    """Serve the control panel (FastAPI backend + built React frontend)."""
    settings, _ = _bootstrap()
    import uvicorn

    from app.dashboard.api import FRONTEND_DIST
    from app.dashboard.auth import warn_if_public

    warning = warn_if_public(host)
    if warning:
        console.print(f"[bold red]{warning}[/bold red]")
    if not FRONTEND_DIST.exists():
        console.print("[yellow]Frontend bundle not found - API only. "
                      "Build it with: cd frontend; npm install; npm run build[/yellow]")
    mode = "[red]CONTROLS ENABLED[/red]" if settings.dashboard_controls_enabled else "read-only"
    console.print(f"Control panel at http://{host}:{port}  ({mode})")
    uvicorn.run("app.dashboard.api:api", host=host, port=port)


if __name__ == "__main__":
    app()
