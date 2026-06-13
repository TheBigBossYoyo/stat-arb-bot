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


def _default_adjusted(universe: str | None, interval: str) -> bool:
    """Research on daily equity bars defaults to TOTAL-RETURN prices (audit
    W-05). Crypto/synthetic have no corporate actions — raw is fine."""
    if interval != "1d" or not universe:
        return False
    from app.data.universe import get_universe_meta

    return get_universe_meta(universe).asset_class == "equity"


def _record_experiment(storage, *, kind: str, strategy: str, universe: str = "",
                       interval: str = "", config: dict | None = None,
                       metrics: dict | None = None, prices=None,
                       seed: int | None = None, sample: str = "in_sample",
                       notes: str = "") -> None:
    """Record the run in the experiment registry and tell the researcher its
    trial number — that count is what deflates the family's best Sharpe."""
    from app.research.experiment_tracking import ExperimentTracker

    rec = ExperimentTracker(storage).record(
        kind=kind, strategy=strategy, universe=universe, interval=interval,
        config=config, metrics=metrics, prices=prices, seed=seed,
        sample=sample, notes=notes,
    )
    dirty = " [yellow](DIRTY TREE — commit before citing this run)[/yellow]" if rec.git_dirty else ""
    console.print(
        f"[dim]experiment[/dim] {rec.experiment_id} [dim]| family[/dim] {rec.family} "
        f"[dim]| trial[/dim] #{rec.trial_number}{dirty}"
    )
    if rec.trial_number >= 10:
        console.print(
            f"[yellow]{rec.trial_number} trials recorded in this family — the best "
            f"Sharpe among them is inflated by selection; judge it deflated "
            f"(see RESEARCH_WEAKNESSES.md W-02).[/yellow]"
        )


def _print_adjustment_status(prices, universe: str | None, interval: str) -> None:
    if prices.adjusted:
        note = "" if prices.adjustment_coverage >= 0.99 else (
            f" [yellow](coverage {100 * prices.adjustment_coverage:.1f}% — re-run "
            f"download-data to backfill adj_close)[/yellow]")
        console.print(f"[dim]prices: total-return adjusted[/dim]{note}")
    elif _default_adjusted(universe, interval):
        console.print("[yellow]prices: RAW (dividend-blind) — pass --adjusted or "
                      "re-download data; see audit W-05[/yellow]")


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
    adjusted: bool | None = typer.Option(
        None, "--adjusted/--raw",
        help="total-return prices (default: adjusted for daily equity universes)"),
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
    use_adjusted = adjusted if adjusted is not None else _default_adjusted(universe, interval)
    prices = build_price_matrix(storage, symbols, interval, start=start,
                                adjusted=use_adjusted)
    _print_adjustment_status(prices, universe, interval)

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
    _record_experiment(
        storage, kind="backtest", strategy=strategy, universe=universe,
        interval=interval, metrics=result.metrics, prices=prices,
        config={**{k: v for k, v in bt_config.__dict__.items()
                   if k != "per_pair_target_pct"},
                "adjusted": use_adjusted, "n_pairs": len(pairs)},
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
            crash_protect_vol_window=int(momentum_raw.get("xsmom_crash_vol_window", 0)),
            crash_protect_target_vol=float(momentum_raw.get("xsmom_crash_target_vol", 0)),
        ))
    raise typer.BadParameter(f"unknown basket strategy {strategy!r}; choose from {BASKET_STRATEGIES}")


@app.command("backtest-basket")
def backtest_basket(
    strategy: str = typer.Option("pca_stat_arb", help=" | ".join(BASKET_STRATEGIES)),
    universe: str = typer.Option("crypto_top_10"),
    interval: str = typer.Option(DEFAULT_INTERVAL),
    long_only: bool = typer.Option(False, help="long-only rotation (NOT market-neutral)"),
    rebalance_every: int | None = typer.Option(None, help="bars between rebalances"),
    adjusted: bool | None = typer.Option(
        None, "--adjusted/--raw",
        help="total-return prices (default: adjusted for daily equity universes)"),
    fill: str = typer.Option("next_open", help="next_open (honest) | same_close (legacy)"),
) -> None:
    """Backtest a cross-sectional basket strategy (PCA residuals, reversal, momentum)."""
    settings, storage = _bootstrap()
    from app.backtesting.basket_engine import BasketConfig, run_basket_backtest
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe

    defaults = _strategy_defaults(interval)
    basket_raw = defaults.get("basket", {}) or {}
    bt_raw = defaults.get("backtest", {}) or {}
    weight_fn = _basket_weight_fn(strategy, defaults, long_only, universe)

    use_adjusted = adjusted if adjusted is not None else _default_adjusted(universe, interval)
    prices = build_price_matrix(storage, get_universe(universe), interval,
                                adjusted=use_adjusted)
    _print_adjustment_status(prices, universe, interval)
    config = BasketConfig(
        interval=interval,
        fit_window=int(basket_raw.get("fit_window", 1500)),
        rebalance_every=rebalance_every or int(basket_raw.get("rebalance_every", 24)),
        cost_bps=float(basket_raw.get("cost_bps", 15)),
        bars_per_year=_bars_per_year(universe, interval),
        fill=fill,
        borrow_bps_annual=float(bt_raw.get("borrow_bps_annual", 0)),
        margin_bps_annual=float(bt_raw.get("margin_bps_annual", 0)),
        label=strategy,
    )
    mode_note = " [yellow](long-only: NOT market-neutral)[/yellow]" if long_only else ""
    console.print(f"Basket backtest: [bold]{strategy}[/bold]{mode_note} on "
                  f"{len(prices.symbols)} assets, {len(prices.index)} bars...")
    result = run_basket_backtest(prices.close, weight_fn, config, aux=prices.aux,
                                 open_=prices.open)
    storage.save_backtest_run(
        strategy=f"basket_{strategy}{'_long_only' if long_only else ''}", interval=interval,
        start_ts=prices.index[0], end_ts=prices.index[-1],
        params={**basket_raw, "long_only": long_only}, metrics=result.metrics,
    )
    _record_experiment(
        storage, kind="basket", strategy=strategy, universe=universe,
        interval=interval, metrics=result.metrics, prices=prices,
        config={**basket_raw, "long_only": long_only, "adjusted": use_adjusted,
                "rebalance_every": config.rebalance_every},
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
                    universe: str, interval: str, leverage: float, reb_every: int,
                    alloc_mode: str | None = None, config_overrides: dict | None = None,
                    record_history: bool = False):
    """Risk-parity ensemble from strategy_defaults.yaml (shared by the
    ensemble backtest and the basket paper trader)."""
    from app.core.math_utils import periods_per_year
    from app.strategies.ensemble import EnsembleConfig, RiskParityEnsemble

    basket_raw = defaults.get("basket", {}) or {}
    ens_raw = dict(defaults.get("ensemble", {}) or {})
    if alloc_mode:
        ens_raw["alloc_mode"] = alloc_mode
    names = ([s.strip() for s in sleeves.split(",") if s.strip()] if sleeves
             else list(ens_raw.get("sleeves", ["pca_stat_arb", "xsec_reversion", "tsmom"])))
    for name in names:
        if name not in BASKET_STRATEGIES:
            raise typer.BadParameter(f"unknown sleeve {name!r}; choose from {BASKET_STRATEGIES}")
    bpy = _bars_per_year(universe, interval) or periods_per_year(interval)
    cfg_kwargs = dict(
        vol_window=int(ens_raw.get("vol_window", 30)),
        min_observations=int(ens_raw.get("min_observations", 5)),
        gross_target=float(ens_raw.get("gross_target", 1.0)),
        leverage=leverage,
        max_sleeve_share=float(ens_raw.get("max_sleeve_share", 0.60)),
        min_sleeve_t=float(ens_raw.get("min_sleeve_t", -0.5)),
        cost_bps=float(basket_raw.get("cost_bps", 15)),
        target_vol_pct=float(ens_raw.get("target_vol_pct", 0)),
        rebalances_per_year=bpy / reb_every,
        alloc_mode=str(ens_raw.get("alloc_mode", "inverse_vol")),
    )
    if config_overrides:
        cfg_kwargs.update(config_overrides)
    ensemble = RiskParityEnsemble(
        {name: _basket_weight_fn(name, defaults, long_only, universe) for name in names},
        EnsembleConfig(**cfg_kwargs),
        record_history=record_history,
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
    adjusted: bool | None = typer.Option(
        None, "--adjusted/--raw",
        help="total-return prices (default: adjusted for daily equity universes)"),
    fill: str = typer.Option("next_open", help="next_open (honest) | same_close (legacy)"),
    borrow_bps: float | None = typer.Option(
        None, help="annual borrow cost on short notional (overrides config)"),
    margin_bps: float | None = typer.Option(
        None, help="annual margin interest on leverage above 1x (overrides config)"),
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
    bt_raw = defaults.get("backtest", {}) or {}
    ens_raw = defaults.get("ensemble", {}) or {}
    reb_every = rebalance_every or int(basket_raw.get("rebalance_every", 24))
    names, ensemble = _build_ensemble(sleeves, defaults, long_only, universe,
                                      interval, leverage, reb_every)
    use_adjusted = adjusted if adjusted is not None else _default_adjusted(universe, interval)
    prices = build_price_matrix(storage, get_universe(universe), interval,
                                adjusted=use_adjusted)
    _print_adjustment_status(prices, universe, interval)
    config = BasketConfig(
        interval=interval,
        fit_window=int(basket_raw.get("fit_window", 1500)),
        rebalance_every=reb_every,
        cost_bps=float(basket_raw.get("cost_bps", 15)),
        bars_per_year=_bars_per_year(universe, interval),
        fill=fill,
        borrow_bps_annual=(borrow_bps if borrow_bps is not None
                           else float(bt_raw.get("borrow_bps_annual", 0))),
        margin_bps_annual=(margin_bps if margin_bps is not None
                           else float(bt_raw.get("margin_bps_annual", 0))),
        label="ensemble",
    )
    if leverage > 1.0 and config.margin_bps_annual == 0:
        console.print("[yellow]leverage > 1x with margin_bps=0: financing NOT modeled "
                      "(audit W-07). Pass --margin-bps for an honest levered result.[/yellow]")
    mode_note = " [yellow](long-only: NOT market-neutral)[/yellow]" if long_only else ""
    console.print(f"Ensemble backtest: [bold]{' + '.join(names)}[/bold]{mode_note} on "
                  f"{len(prices.symbols)} assets, {len(prices.index)} bars...")
    result = run_basket_backtest(prices.close, ensemble, config, aux=prices.aux,
                                 open_=prices.open)
    storage.save_backtest_run(
        strategy=f"ensemble_{'_'.join(names)}{'_long_only' if long_only else ''}",
        interval=interval, start_ts=prices.index[0], end_ts=prices.index[-1],
        params={**ens_raw, "sleeves": names, "long_only": long_only}, metrics=result.metrics,
    )
    _record_experiment(
        storage, kind="ensemble", strategy=f"ensemble_{'_'.join(sorted(names))}",
        universe=universe, interval=interval, metrics=result.metrics, prices=prices,
        config={**ens_raw, "sleeves": names, "long_only": long_only,
                "leverage": leverage, "adjusted": use_adjusted,
                "rebalance_every": reb_every},
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


def _ensemble_price_setup(storage, sleeves, universe, interval, long_only,
                          leverage, alloc_mode):
    """Shared setup for the validation commands: build prices + a fresh-ensemble
    factory + config (sleeves are stateful — each run needs its own instance)."""
    from app.backtesting.basket_engine import BasketConfig
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe

    defaults = _strategy_defaults(interval)
    basket_raw = defaults.get("basket", {}) or {}
    bt_raw = defaults.get("backtest", {}) or {}
    reb_every = int(basket_raw.get("rebalance_every", 24))
    use_adjusted = _default_adjusted(universe, interval)
    prices = build_price_matrix(storage, get_universe(universe), interval, adjusted=use_adjusted)
    _print_adjustment_status(prices, universe, interval)

    def factory():
        _, ens = _build_ensemble(sleeves, defaults, long_only, universe,
                                 interval, leverage, reb_every, alloc_mode=alloc_mode)
        return ens

    names, _ = _build_ensemble(sleeves, defaults, long_only, universe, interval,
                               leverage, reb_every, alloc_mode=alloc_mode)
    config = BasketConfig(
        interval=interval, fit_window=int(basket_raw.get("fit_window", 1500)),
        rebalance_every=reb_every, cost_bps=float(basket_raw.get("cost_bps", 15)),
        bars_per_year=_bars_per_year(universe, interval), fill="next_open",
        borrow_bps_annual=float(bt_raw.get("borrow_bps_annual", 0)),
        margin_bps_annual=float(bt_raw.get("margin_bps_annual", 0)),
        label="ensemble",
    )
    return prices, factory, config, names


@app.command("validate-ensemble")
def validate_ensemble(
    sleeves: str | None = typer.Option(None),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    n_folds: int = typer.Option(4),
    alloc_mode: str | None = typer.Option(None, help="inverse_vol|erc|hrp|equal|min_variance"),
) -> None:
    """Out-of-sample validation for the basket ensemble (audit W-01): anchored
    walk-forward, stress suite, return concentration, and deflated Sharpe vs the
    family's recorded trial count. This is the gate the flagship had no path to."""
    settings, storage = _bootstrap()
    from app.backtesting.basket_engine import run_basket_backtest
    from app.backtesting.stress_tests import (
        return_concentration,
        run_basket_stress_suite,
    )
    from app.backtesting.walk_forward import run_basket_holdout
    from app.core.math_utils import periods_per_year
    from app.research.deflated_sharpe import deflated_sharpe_from_trials
    from app.research.experiment_tracking import ExperimentTracker

    prices, factory, config, names = _ensemble_price_setup(
        storage, sleeves, universe, interval, False, 1.0, alloc_mode)
    console.print(f"Validating ensemble [bold]{' + '.join(names)}[/bold] "
                  f"(alloc={alloc_mode or 'inverse_vol'})...")

    wf = run_basket_holdout(prices.close, factory, config, n_folds=n_folds,
                            aux=prices.aux, open_=prices.open)
    console.print("\n[bold]Anchored walk-forward[/bold]")
    for key, value in wf.summary.items():
        console.print(f"  {key}: {value}")

    stress = run_basket_stress_suite(prices.close, factory, config,
                                     aux=prices.aux, open_=prices.open)
    console.print("\n[bold]Stress suite[/bold]")
    console.print(stress)

    full = run_basket_backtest(prices.close, factory(), config,
                               aux=prices.aux, open_=prices.open)
    conc = return_concentration(full.equity)
    console.print(f"\n[bold]Concentration[/bold]: {conc}")

    ppy = _bars_per_year(universe, interval) or periods_per_year(interval)
    rets = full.equity.dropna().pct_change().dropna().to_numpy()
    family = ExperimentTracker.make_family(f"ensemble_{'_'.join(sorted(names))}",
                                           universe, interval)
    trial_sharpes = storage.experiment_family_sharpes(family)
    dsr = deflated_sharpe_from_trials(rets, trial_sharpes or [], periods_per_year=ppy)
    console.print("\n[bold]Deflated Sharpe[/bold]")
    console.print(f"  {dsr.summary()}")
    console.print(f"  family '{family}' has {len(trial_sharpes)} recorded trials")

    # honest pass/fail against acceptance criteria
    checks = {
        "OOS folds majority positive": wf.summary.get("oos_folds_positive", 0) * 2
        >= wf.summary.get("oos_folds", 1),
        "survives costs_x2 (positive)": float(stress.loc["costs_x2", "total_return_pct"] or 0) > 0,
        "no month > 25% of PnL": (conc.get("max_month_pct") or 0) <= 25.0,
        "deflated Sharpe P>0.95": dsr.passed,
    }
    console.print("\n[bold]Acceptance checks[/bold]")
    for name, ok in checks.items():
        console.print(f"  [{'green' if ok else 'red'}]{'PASS' if ok else 'FAIL'}[/] {name}")
    out = settings.reports_dir / f"validate_ensemble_{universe}_{interval}.md"
    _write_validation_report(out, names, universe, interval, wf, stress, conc, dsr, checks)
    console.print(f"\n[green]Report:[/green] {out}")


def _write_validation_report(path, names, universe, interval, wf, stress, conc, dsr, checks):
    lines = [
        f"# Ensemble validation — {' + '.join(names)} ({universe}, {interval})",
        "", "## Anchored walk-forward (audit W-01)",
        *(f"- {k}: {v}" for k, v in wf.summary.items()),
        "", "## Stress suite", "", stress.to_markdown(),
        "", "## Return concentration", *(f"- {k}: {v}" for k, v in conc.items()),
        "", "## Deflated Sharpe", f"- {dsr.summary()}",
        "", "## Acceptance checks",
        *(f"- {'PASS' if ok else 'FAIL'} — {name}" for name, ok in checks.items()),
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


@app.command("capacity-report")
def capacity_report(
    strategy: str = typer.Option("xsec_momentum"),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    capital_grid: str = typer.Option("10000,50000,250000,1000000,5000000,25000000"),
    impact_coeff: float = typer.Option(10.0, help="bps per sqrt(participation)"),
) -> None:
    """Capacity curve: net Sharpe vs capital with square-root market impact (W-09)."""
    settings, storage = _bootstrap()
    from app.backtesting.basket_engine import BasketConfig
    from app.backtesting.capacity import run_capacity_analysis
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe

    defaults = _strategy_defaults(interval)
    basket_raw = defaults.get("basket", {}) or {}
    weight_fn = _basket_weight_fn(strategy, defaults, False, universe)
    use_adjusted = _default_adjusted(universe, interval)
    prices = build_price_matrix(storage, get_universe(universe), interval, adjusted=use_adjusted)
    grid = [float(x) for x in capital_grid.split(",")]
    config = BasketConfig(
        interval=interval, fit_window=int(basket_raw.get("fit_window", 1500)),
        rebalance_every=int(basket_raw.get("rebalance_every", 24)),
        cost_bps=float(basket_raw.get("cost_bps", 15)),
        bars_per_year=_bars_per_year(universe, interval), fill="next_open", label=strategy,
    )
    if prices.volume is None:
        console.print("[yellow]No volume data — impact cannot be estimated; "
                      "capacity curve will be flat (uninformative).[/yellow]")
    curve = run_capacity_analysis(prices.close, weight_fn, config, grid,
                                  aux=prices.aux, open_=prices.open,
                                  volume=prices.volume, impact_coeff=impact_coeff)
    console.print(f"Capacity — [bold]{strategy}[/bold] on {universe}")
    console.print(curve.to_frame())
    console.print(f"Liquidity bottlenecks: {curve.bottleneck_symbols}")
    console.print(f"Capacity at 80% Sharpe floor: "
                  f"${curve.capacity_at_sharpe_floor():,.0f}")


@app.command("compare-allocators")
def compare_allocators(
    sleeves: str | None = typer.Option(None),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    modes: str = typer.Option("equal,inverse_vol,erc,hrp"),
) -> None:
    """Compare allocation modes for the ensemble on the SAME data (audit W-11).

    A new mode must beat inverse_vol here (and out-of-sample, via
    validate-ensemble) before it should become the configured default."""
    _, storage = _bootstrap()
    from app.backtesting.basket_engine import run_basket_backtest

    rows = []
    for mode in [m.strip() for m in modes.split(",") if m.strip()]:
        prices, factory, config, names = _ensemble_price_setup(
            storage, sleeves, universe, interval, False, 1.0, mode)
        res = run_basket_backtest(prices.close, factory(), config,
                                  aux=prices.aux, open_=prices.open)
        rows.append({"mode": mode, "return_pct": res.metrics.get("total_return_pct"),
                     "sharpe": res.metrics.get("sharpe"),
                     "max_dd_pct": res.metrics.get("max_drawdown_pct"),
                     "turnover": res.metrics.get("turnover")})
    import pandas as pd

    table = pd.DataFrame(rows).set_index("mode")
    console.print(f"Allocator comparison — {' + '.join(names)} ({universe})")
    console.print(table)
    best = table["sharpe"].astype(float).idxmax()
    iv = table.loc["inverse_vol", "sharpe"] if "inverse_vol" in table.index else None
    console.print(f"Best Sharpe: [bold]{best}[/bold]"
                  + (f" (inverse_vol: {iv})" if iv is not None else ""))
    console.print("[dim]In-sample only — confirm OOS with validate-ensemble before "
                  "changing the default (acceptance criteria).[/dim]")


def _concentration_setup(storage, sleeves, universe, interval):
    """Prices + base BasketConfig + rebalance cadence for the concentration
    commands (mirrors _ensemble_price_setup but exposes the raw pieces)."""
    from app.backtesting.basket_engine import BasketConfig
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe

    defaults = _strategy_defaults(interval)
    basket_raw = defaults.get("basket", {}) or {}
    bt_raw = defaults.get("backtest", {}) or {}
    reb_every = int(basket_raw.get("rebalance_every", 24))
    use_adjusted = _default_adjusted(universe, interval)
    prices = build_price_matrix(storage, get_universe(universe), interval, adjusted=use_adjusted)
    _print_adjustment_status(prices, universe, interval)
    config = BasketConfig(
        interval=interval, fit_window=int(basket_raw.get("fit_window", 1500)),
        rebalance_every=reb_every, cost_bps=float(basket_raw.get("cost_bps", 15)),
        bars_per_year=_bars_per_year(universe, interval), fill="next_open",
        borrow_bps_annual=float(bt_raw.get("borrow_bps_annual", 0)),
        margin_bps_annual=float(bt_raw.get("margin_bps_annual", 0)),
        label="ensemble",
    )
    return defaults, prices, config, reb_every


def _fix_factory(spec, defaults, sleeves, universe, interval, reb_every, *,
                 record_history=False):
    """Return (factory, names) where factory() builds a FRESH ensemble (sleeves
    are stateful) with `spec`'s config overrides and transforms applied."""
    from app.backtesting.concentration_fixes import WrappedWeightFn
    from app.data.universe import get_sectors

    ctx = {"sectors": get_sectors(universe)}

    def factory():
        names, ens = _build_ensemble(
            sleeves, defaults, False, universe, interval, 1.0, reb_every,
            config_overrides=spec.config_overrides, record_history=record_history)
        transforms = spec.transforms(ctx)
        return (WrappedWeightFn(ens, transforms) if transforms else ens), names

    fn, names = factory()
    return (lambda: factory()[0]), names


@app.command("concentration-report")
def concentration_report_cmd(
    strategy: str = typer.Option("ensemble", help="ensemble (only basket form supported)"),
    sleeves: str | None = typer.Option(None),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    fix: str = typer.Option("none", help="apply a named concentration fix first"),
) -> None:
    """Full return-concentration diagnostics for the ensemble (Phase 1).

    Monthly/daily contribution, the best 5% of days, per-asset / per-sector /
    per-sleeve attribution, Herfindahl indices, a 0-100 concentration score and
    the pass/fail gate (no month > 25% of PnL, etc). This is the gate the
    flagship currently fails."""
    settings, storage = _bootstrap()
    from app.backtesting.basket_engine import run_basket_backtest
    from app.backtesting.concentration import analyze_concentration, attribute_sleeves
    from app.backtesting.concentration_fixes import WrappedWeightFn, default_fix_specs
    from app.data.universe import get_sectors

    specs = default_fix_specs(get_sectors(universe))
    if fix not in specs:
        raise typer.BadParameter(f"unknown fix {fix!r}; choose from {list(specs)}")
    defaults, prices, config, reb_every = _concentration_setup(
        storage, sleeves, universe, interval)
    factory, names = _fix_factory(specs[fix], defaults, sleeves, universe,
                                  interval, reb_every, record_history=True)
    fn = factory()
    console.print(f"Concentration report: [bold]{' + '.join(names)}[/bold] "
                  f"(fix={fix}) on {universe}...")
    result = run_basket_backtest(prices.close, fn, config, aux=prices.aux, open_=prices.open)
    ensemble = getattr(fn, "inner", fn)
    sleeve_pnl = attribute_sleeves(getattr(ensemble, "history", []),
                                   prices.close, result.equity)
    rep = analyze_concentration(
        result.equity, close=prices.close, weights_df=result.weights,
        sectors=get_sectors(universe),
        sleeve_pnl=sleeve_pnl if not sleeve_pnl.empty else None)
    _print_concentration(rep)
    out = settings.reports_dir / f"concentration_{strategy}_{universe}_{interval}_{fix}.md"
    out.write_text(_concentration_markdown(rep, names, universe, interval, fix),
                   encoding="utf-8")
    console.print(f"\n[green]Report:[/green] {out}")


def _print_concentration(rep) -> None:
    gate = rep.gate()
    console.print(f"\n[bold]Concentration score[/bold]: {rep.concentration_score()}/100 "
                  f"(lower is better)")
    flat = rep.to_flat()
    table = Table(title="Concentration metrics")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for key in ("max_month_pct", "max_day_pct", "best5pct_share", "monthly_herfindahl",
                "top_asset", "top_asset_pct", "asset_herfindahl", "top_sector",
                "top_sector_pct", "top_sleeve", "top_sleeve_pct", "max_drawdown_pct"):
        table.add_row(key, str(flat.get(key)))
    console.print(table)
    if rep.monthly_table is not None:
        worst = rep.monthly_table.sort_values("share_pct", ascending=False).head(5)
        console.print("\n[bold]Top months by PnL share[/bold]")
        console.print(worst)
    if rep.daily_top is not None:
        console.print("\n[bold]Top days by PnL share[/bold]")
        console.print(rep.daily_top.head(5).to_string(index=False))
    console.print("\n[bold]Gate[/bold]")
    for name, ok in gate.checks.items():
        console.print(f"  [{'green' if ok else 'red'}]{'PASS' if ok else 'FAIL'}[/] {name}")
    verdict = "[green]PASS[/green]" if gate.passed else "[red]FAIL[/red]"
    console.print(f"verdict: {verdict}")
    for reason in gate.reasons:
        console.print(f"  [yellow]- {reason}[/yellow]")


def _concentration_markdown(rep, names, universe, interval, fix) -> str:
    gate = rep.gate()
    lines = [
        f"# Return concentration — {' + '.join(names)} ({universe}, {interval})",
        f"\nFix applied: **{fix}**  |  concentration score: "
        f"**{rep.concentration_score()}/100** (lower is better)",
        f"\nGate verdict: **{'PASS' if gate.passed else 'FAIL'}**", "",
        "## Metrics", "",
        *(f"- {k}: {v}" for k, v in rep.to_flat().items()), "",
    ]
    if rep.monthly_table is not None:
        lines += ["## Monthly PnL contribution", "", rep.monthly_table.to_markdown(), ""]
    if rep.daily_top is not None:
        lines += ["## Top days by PnL share", "",
                  rep.daily_top.to_markdown(index=False), ""]
    if rep.asset_table is not None:
        lines += ["## Per-asset PnL contribution (top 15)", "",
                  rep.asset_table.head(15).to_markdown(), ""]
    if rep.sector_table is not None:
        lines += ["## Per-sector PnL contribution", "", rep.sector_table.to_markdown(), ""]
    if rep.sleeve_table is not None:
        lines += ["## Per-sleeve PnL contribution", "", rep.sleeve_table.to_markdown(), ""]
    lines += ["## Gate checks", ""]
    lines += [f"- {'PASS' if ok else 'FAIL'} — {name}" for name, ok in gate.checks.items()]
    if gate.reasons:
        lines += ["", "### Failures"] + [f"- {r}" for r in gate.reasons]
    return "\n".join(lines) + "\n"


@app.command("concentration-fix-backtest")
def concentration_fix_backtest(
    fix: str = typer.Option("combo", help="named fix (see compare-concentration-fixes)"),
    sleeves: str | None = typer.Option(None),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    n_folds: int = typer.Option(3),
) -> None:
    """Backtest one concentration fix: full-window concentration + OOS Sharpe.

    A fix is only worth keeping if it lowers concentration WITHOUT breaking the
    out-of-sample Sharpe — both are reported here side by side with the baseline."""
    settings, storage = _bootstrap()
    from app.backtesting.basket_engine import run_basket_backtest
    from app.backtesting.concentration import analyze_concentration
    from app.backtesting.concentration_fixes import default_fix_specs
    from app.backtesting.walk_forward import run_basket_holdout
    from app.data.universe import get_sectors

    specs = default_fix_specs(get_sectors(universe))
    if fix not in specs:
        raise typer.BadParameter(f"unknown fix {fix!r}; choose from {list(specs)}")
    defaults, prices, config, reb_every = _concentration_setup(
        storage, sleeves, universe, interval)

    rows = []
    for spec_name in ("none", fix) if fix != "none" else ("none",):
        spec = specs[spec_name]
        factory, names = _fix_factory(spec, defaults, sleeves, universe, interval, reb_every)
        full = run_basket_backtest(prices.close, factory(), config,
                                   aux=prices.aux, open_=prices.open)
        rep = analyze_concentration(full.equity, close=prices.close,
                                    weights_df=full.weights, sectors=get_sectors(universe))
        wf = run_basket_holdout(prices.close, factory, config, n_folds=n_folds,
                                aux=prices.aux, open_=prices.open)
        rows.append({
            "fix": spec_name,
            "return_pct": full.metrics.get("total_return_pct"),
            "sharpe": full.metrics.get("sharpe"),
            "max_dd_pct": full.metrics.get("max_drawdown_pct"),
            "turnover": full.metrics.get("turnover"),
            "max_month_pct": rep.max_month_pct,
            "best5pct_share": rep.best5pct_share,
            "conc_score": rep.concentration_score(),
            "gate": "PASS" if rep.gate().passed else "FAIL",
            "oos_sharpe": wf.summary.get("oos_sharpe_mean"),
        })
    import pandas as pd

    df = pd.DataFrame(rows).set_index("fix")
    console.print(f"\nFix backtest — {' + '.join(names)} ({universe})")
    console.print(df)
    console.print("[dim]Keep a fix only if conc_score drops and oos_sharpe holds.[/dim]")


@app.command("compare-concentration-fixes")
def compare_concentration_fixes(
    sleeves: str | None = typer.Option(None),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    n_folds: int = typer.Option(3),
) -> None:
    """Run every concentration fix and rank them by (gate pass, OOS Sharpe).

    Picks the best fix that passes the concentration gate while preserving
    out-of-sample Sharpe — the Phase 1 acceptance test. Writes a report and
    prints the recommended fix (or 'none survive' if the edge is too concentrated
    to repair without destroying it)."""
    settings, storage = _bootstrap()
    import pandas as pd

    from app.backtesting.basket_engine import run_basket_backtest
    from app.backtesting.concentration import analyze_concentration
    from app.backtesting.concentration_fixes import default_fix_specs
    from app.backtesting.walk_forward import run_basket_holdout
    from app.data.universe import get_sectors

    specs = default_fix_specs(get_sectors(universe))
    defaults, prices, config, reb_every = _concentration_setup(
        storage, sleeves, universe, interval)

    rows = []
    names: list[str] = []
    base_oos = None
    for name, spec in specs.items():
        factory, names = _fix_factory(spec, defaults, sleeves, universe, interval, reb_every)
        full = run_basket_backtest(prices.close, factory(), config,
                                   aux=prices.aux, open_=prices.open)
        rep = analyze_concentration(full.equity, close=prices.close,
                                    weights_df=full.weights, sectors=get_sectors(universe))
        wf = run_basket_holdout(prices.close, factory, config, n_folds=n_folds,
                                aux=prices.aux, open_=prices.open)
        oos = wf.summary.get("oos_sharpe_mean")
        if name == "none":
            base_oos = oos
        rows.append({
            "fix": name, "return_pct": full.metrics.get("total_return_pct"),
            "sharpe": full.metrics.get("sharpe"),
            "max_dd_pct": full.metrics.get("max_drawdown_pct"),
            "max_month_pct": rep.max_month_pct, "best5pct_share": rep.best5pct_share,
            "conc_score": rep.concentration_score(),
            "gate_pass": rep.gate().passed, "oos_sharpe": oos,
        })
        console.print(f"  [dim]{name}: score {rep.concentration_score()}, "
                      f"gate {'PASS' if rep.gate().passed else 'FAIL'}, oos {oos}[/dim]")

    df = pd.DataFrame(rows).set_index("fix")
    console.print(f"\nConcentration-fix comparison — {' + '.join(names)} ({universe})")
    console.print(df)

    # acceptance: gate passes AND OOS Sharpe within 15% of baseline (no edge destruction)
    floor = (float(base_oos) * 0.85) if base_oos else 0.0
    base_score = float(df.loc["none", "conc_score"]) if "none" in df.index else None
    oos_ok = df["oos_sharpe"].astype(float) >= floor
    survivors = df[(df["gate_pass"]) & oos_ok]
    survivors = survivors[survivors.index != "none"]
    # best MITIGATION: lowers concentration vs baseline without hurting OOS, even
    # if the absolute gate (e.g. best-5%-days < total return) is structurally
    # unreachable for a daily strategy. Honest middle ground between PASS and "no fix".
    mitig = df[oos_ok & (df.index != "none")]
    if base_score is not None:
        mitig = mitig[mitig["conc_score"].astype(float) < base_score - 1.0]
    best_mitig = mitig["conc_score"].astype(float).idxmin() if len(mitig) else None

    recommended = None
    if len(survivors):
        recommended = survivors["oos_sharpe"].astype(float).idxmax()
        console.print(f"\n[green]Recommended fix (passes gate):[/green] [bold]{recommended}[/bold] "
                      f"(OOS Sharpe {survivors.loc[recommended, 'oos_sharpe']} >= floor {floor:.2f})")
    elif best_mitig:
        console.print(f"\n[yellow]No fix fully clears the absolute gate[/yellow] (the "
                      f"'best-5%-of-days < total return' bar is structurally hard for a "
                      f"daily strategy). Best MITIGATION: [bold]{best_mitig}[/bold] — "
                      f"conc score {df.loc[best_mitig, 'conc_score']} vs baseline {base_score}, "
                      f"OOS Sharpe {df.loc[best_mitig, 'oos_sharpe']} (>= floor {floor:.2f}). "
                      f"It reduces concentration without hurting out-of-sample return.")
    else:
        console.print("\n[red]No fix reduces concentration while preserving OOS Sharpe — "
                      "the edge is too concentrated to repair. Honest negative result; "
                      "do not force a fix.[/red]")
    out = settings.reports_dir / f"concentration_fixes_{universe}_{interval}.md"
    lines = [f"# Concentration-fix comparison — {' + '.join(names)} ({universe}, {interval})",
             "", df.to_markdown(), "",
             f"OOS Sharpe floor (85% of baseline {base_oos}): {floor:.3f}",
             f"Baseline concentration score: {base_score}", ""]
    if recommended:
        lines.append(f"**Recommended fix (passes gate): {recommended}**")
    elif best_mitig:
        lines += [f"**No fix clears the absolute gate; best mitigation: {best_mitig}**",
                  "", "The 'best 5% of days < total return' criterion is structurally hard "
                  "for a daily directional strategy; the recommended mitigation lowers the "
                  "concentration score and best-5%-share without reducing OOS Sharpe."]
    else:
        lines.append("**No fix survives — edge too concentrated; keep researching.**")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[green]Report:[/green] {out}")


# --------------------------------------------------------------------------------
# Path A — long-only Trading 212 Invest/ISA product
# --------------------------------------------------------------------------------

LONG_ONLY_STRATEGIES = ("long_only_xsec_momentum", "long_only_tsmom",
                        "long_only_ml_alpha", "long_only_ensemble")


def _long_only_configs(defaults: dict):
    """Map the tuned daily momentum/ML config onto the long-only sleeve configs
    so Path A inherits the flagship's calibration (252-day momentum, etc.)."""
    from app.strategies.long_only_momentum import LongOnlyTSMOMConfig, LongOnlyXSMOMConfig
    from app.strategies.ml_alpha import MLAlphaConfig

    mom = defaults.get("momentum", {}) or {}
    ml_raw = dict(defaults.get("ml_alpha", {}) or {})
    xs = LongOnlyXSMOMConfig(
        lookback_bars=int(mom.get("xsmom_lookback_bars", 252)),
        skip_bars=int(mom.get("xsmom_skip_bars", 21)),
        top_k=int(mom.get("xsmom_top_k", 5)),
        top_frac=float(mom.get("xsmom_top_frac", 0.10)),
        max_weight=0.20,
    )
    ts = LongOnlyTSMOMConfig(
        lookback_bars=int(mom.get("tsmom_lookback_bars", 252)),
        skip_bars=int(mom.get("tsmom_skip_bars", 21)),
        vol_window=int(mom.get("tsmom_vol_window", 63)),
        max_weight=0.20,
    )
    ml = MLAlphaConfig(**{k: v for k, v in ml_raw.items() if k in MLAlphaConfig.model_fields})
    return xs, ts, ml


def _regime_cfg(enabled: bool, risk_off_exposure: float, ma_window: int = 200):
    from app.strategies.long_only_momentum import RegimeFilterConfig

    return RegimeFilterConfig(enabled=enabled, risk_off_exposure=risk_off_exposure,
                              ma_window=ma_window)


def _build_long_only(strategy: str, defaults: dict, universe: str, interval: str,
                     regime, reb_every: int, record_history: bool = False):
    """Return (weight_fn, names). `weight_fn` is the long-only book to backtest."""
    from app.core.math_utils import periods_per_year
    from app.strategies.ensemble import EnsembleConfig
    from app.strategies.long_only_ensemble import build_long_only_ensemble
    from app.strategies.long_only_ml_alpha import make_long_only_ml_alpha
    from app.strategies.long_only_momentum import (
        make_long_only_tsmom_weight_fn,
        make_long_only_xsmom_weight_fn,
    )

    xs, ts, ml = _long_only_configs(defaults)
    if strategy == "long_only_xsec_momentum":
        return make_long_only_xsmom_weight_fn(xs.model_copy(update={"regime": regime})), [strategy]
    if strategy == "long_only_tsmom":
        return make_long_only_tsmom_weight_fn(ts.model_copy(update={"regime": regime})), [strategy]
    if strategy == "long_only_ml_alpha":
        return make_long_only_ml_alpha(ml, regime=regime), [strategy]
    if strategy == "long_only_ensemble":
        ens_raw = defaults.get("ensemble", {}) or {}
        bpy = _bars_per_year(universe, interval) or periods_per_year(interval)
        ens_cfg = EnsembleConfig(
            vol_window=int(ens_raw.get("vol_window", 60)),
            min_observations=int(ens_raw.get("min_observations", 20)),
            gross_target=1.0, max_sleeve_share=float(ens_raw.get("max_sleeve_share", 0.60)),
            min_sleeve_t=float(ens_raw.get("min_sleeve_t", 0.0)), cost_bps=5.0,
            target_vol_pct=float(ens_raw.get("target_vol_pct", 10)),
            rebalances_per_year=bpy / reb_every, alloc_mode="inverse_vol",
        )
        ens = build_long_only_ensemble(
            xsmom=xs, tsmom=ts, ml=ml, ensemble_config=ens_cfg, regime=regime,
            gross_cap=1.0, max_position=0.20, record_history=record_history)
        return ens, list(ens.ensemble.sleeves)
    raise typer.BadParameter(f"unknown long-only strategy {strategy!r}; "
                             f"choose from {LONG_ONLY_STRATEGIES}")


def _load_benchmarks(storage, interval: str, names=("SPY", "QQQ")):
    """Total-return benchmark close series from storage; {} if none stored."""
    from app.data.market_data import build_price_matrix

    out = {}
    for sym in names:
        try:
            pm = build_price_matrix(storage, [sym], interval, adjusted=True, min_rows=50)
            out[sym] = pm.close[sym]
        except Exception:  # noqa: BLE001 - missing benchmark is non-fatal
            pass
    return out


def _long_only_setup(storage, universe, interval, reb_every_override=None):
    from app.backtesting.basket_engine import BasketConfig
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe

    defaults = _strategy_defaults(interval)
    basket_raw = defaults.get("basket", {}) or {}
    # long-only momentum rebalances WEEKLY by default (5 daily bars): the
    # signals use 252-day lookbacks, so the flagship's daily cadence only
    # churns turnover/costs for no extra edge.
    reb_every = reb_every_override or 5
    prices = build_price_matrix(storage, get_universe(universe), interval, adjusted=True)
    _print_adjustment_status(prices, universe, interval)
    config = BasketConfig(
        interval=interval, fit_window=int(basket_raw.get("fit_window", 300)),
        rebalance_every=reb_every, cost_bps=float(basket_raw.get("cost_bps", 5)),
        bars_per_year=_bars_per_year(universe, interval), fill="next_open",
        borrow_bps_annual=0.0, margin_bps_annual=0.0, label="long_only",
    )
    return defaults, prices, config, reb_every


@app.command("backtest-long-only")
def backtest_long_only(
    strategy: str = typer.Option("long_only_ensemble", help=" | ".join(LONG_ONLY_STRATEGIES)),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    rebalance_every: int | None = typer.Option(None, help="bars between rebalances"),
    regime: bool = typer.Option(True, "--regime/--no-regime",
                                help="risk-off cash filter (market below its 200d MA)"),
    risk_off_exposure: float = typer.Option(0.0, help="gross when risk-off (0 = full cash)"),
) -> None:
    """Backtest a long-only book against buy-and-hold benchmarks (Path A).

    A long-only Invest/ISA book must beat simply holding SPY on a RISK-ADJUSTED
    basis, not just in a bull market — that comparison is the whole point here.
    NOT market-neutral: direction risk is the dominant risk."""
    settings, storage = _bootstrap()
    from app.backtesting.long_only_engine import run_long_only_backtest

    defaults, prices, config, reb_every = _long_only_setup(
        storage, universe, interval, rebalance_every)
    regime_cfg = _regime_cfg(regime, risk_off_exposure)
    fn, names = _build_long_only(strategy, defaults, universe, interval, regime_cfg, reb_every)
    benchmarks = _load_benchmarks(storage, interval)
    console.print(f"Long-only backtest: [bold]{strategy}[/bold] ({' + '.join(names)}) on "
                  f"{universe}, regime={'on' if regime else 'off'}...")
    result = run_long_only_backtest(prices.close, fn, config, aux=prices.aux,
                                    open_=prices.open, benchmarks=benchmarks)
    _record_experiment(
        storage, kind="long_only", strategy=strategy, universe=universe,
        interval=interval, metrics=result.metrics, prices=prices,
        config={"strategy": strategy, "regime": regime,
                "risk_off_exposure": risk_off_exposure, "rebalance_every": reb_every},
        notes="long-only directional book (Trading 212 Invest/ISA); NOT market-neutral",
    )
    table = Table(title=f"Long-only metrics — {strategy}")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for key, value in result.metrics.items():
        table.add_row(key, str(value))
    console.print(table)
    _print_long_only_comparison(result.comparison)
    for warning in result.warnings:
        console.print(f"[dim]- {warning}[/dim]")


def _print_long_only_comparison(comp: dict) -> None:
    console.print(f"\n[bold]Book vs benchmarks[/bold] (primary: {comp['primary_benchmark']})")
    table = Table()
    for col in ("series", "total_return%", "sharpe", "beta", "alpha_ann%", "info_ratio"):
        table.add_column(col, justify="right")
    table.add_row("[bold]long-only book[/bold]",
                  str(comp["book_total_return_pct"]), str(comp["book_sharpe"]), "—", "—", "—")
    for name, m in comp["benchmarks"].items():
        mark = " *" if m.get("is_primary") else ""
        table.add_row(name + mark, str(m["total_return_pct"]), str(m["sharpe"]),
                      str(m["beta"]), str(m["alpha_ann_pct_vs_this"]), str(m["info_ratio"]))
    console.print(table)
    verdict_c = "green" if comp["beats_benchmark_sharpe"] else "red"
    console.print(f"beats primary benchmark Sharpe: [{verdict_c}]{comp['beats_benchmark_sharpe']}[/] "
                  f"| positive alpha: [{verdict_c}]{comp['positive_alpha']}[/] "
                  f"| cash drag {comp['cash_drag_pct']}%")


@app.command("compare-long-only")
def compare_long_only(
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    benchmark: str = typer.Option("SPY", help="primary benchmark symbol"),
    rebalance_every: int | None = typer.Option(None),
) -> None:
    """Compare every long-only variant + market-neutral flagship + benchmarks.

    One table: each long-only sleeve, the long-only ensemble, the market-neutral
    ensemble (for reference — it cannot trade on Invest/ISA), and buy-and-hold
    SPY/QQQ/equal-weight. Answers: does any tradable long-only book beat just
    buying the index, risk-adjusted?"""
    settings, storage = _bootstrap()
    import pandas as pd

    from app.backtesting.basket_engine import run_basket_backtest
    from app.backtesting.long_only_engine import run_long_only_backtest

    defaults, prices, config, reb_every = _long_only_setup(
        storage, universe, interval, rebalance_every)
    benchmarks = _load_benchmarks(storage, interval, names=(benchmark, "QQQ"))
    regime_cfg = _regime_cfg(True, 0.0)
    rows = []
    for strat in LONG_ONLY_STRATEGIES:
        fn, _ = _build_long_only(strat, defaults, universe, interval, regime_cfg, reb_every)
        res = run_long_only_backtest(prices.close, fn, config, aux=prices.aux,
                                     open_=prices.open, benchmarks=benchmarks)
        c = res.comparison
        rows.append({"book": strat, "total_return_pct": res.metrics.get("total_return_pct"),
                     "sharpe": c["book_sharpe"], "max_dd_pct": res.metrics.get("max_drawdown_pct"),
                     "turnover": res.metrics.get("turnover"),
                     "beats_bench": c["beats_benchmark_sharpe"], "alpha+": c["positive_alpha"]})
    # benchmarks row(s)
    last = res.comparison["benchmarks"]
    for name, m in last.items():
        rows.append({"book": f"[bench] {name}", "total_return_pct": m["total_return_pct"],
                     "sharpe": m["sharpe"], "max_dd_pct": None, "turnover": None,
                     "beats_bench": None, "alpha+": None})
    df = pd.DataFrame(rows).set_index("book")
    console.print(f"\nLong-only comparison — {universe} (primary benchmark {benchmark})")
    console.print(df)
    out = settings.reports_dir / f"compare_long_only_{universe}_{interval}.md"
    out.write_text(f"# Long-only comparison — {universe} ({interval})\n\n"
                   + df.to_markdown() + "\n", encoding="utf-8")
    console.print(f"[green]Report:[/green] {out}")


@app.command("long-only-readiness")
def long_only_readiness(
    strategy: str = typer.Option("long_only_ensemble"),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    n_folds: int = typer.Option(3),
    rebalance_every: int | None = typer.Option(None),
) -> None:
    """Long-only paper-readiness gate (Path A). NEVER asserts live eligibility.

    Runs the full battery — beats-benchmark, walk-forward OOS, cost stress,
    concentration gate, turnover — and prints PASS/FAIL plus the paper-trading
    plan. The best a long-only book can earn here is 'paper-trading eligible'."""
    settings, storage = _bootstrap()
    from app.backtesting.basket_engine import run_basket_backtest
    from app.backtesting.concentration import analyze_concentration
    from app.backtesting.long_only_engine import _long_only_guard, run_long_only_backtest
    from app.backtesting.stress_tests import run_basket_stress_suite
    from app.backtesting.walk_forward import run_basket_holdout
    from app.data.universe import get_sectors

    defaults, prices, config, reb_every = _long_only_setup(
        storage, universe, interval, rebalance_every)
    regime_cfg = _regime_cfg(True, 0.0)
    benchmarks = _load_benchmarks(storage, interval)

    def factory():
        fn, _ = _build_long_only(strategy, defaults, universe, interval, regime_cfg, reb_every)
        return _long_only_guard(fn, 0.20, 1.0)

    console.print(f"Long-only readiness: [bold]{strategy}[/bold] on {universe}...")
    fn, names = _build_long_only(strategy, defaults, universe, interval, regime_cfg, reb_every)
    result = run_long_only_backtest(prices.close, fn, config, aux=prices.aux,
                                    open_=prices.open, benchmarks=benchmarks)
    conc = analyze_concentration(result.equity, close=prices.close,
                                 weights_df=result.book.weights, sectors=get_sectors(universe))
    wf = run_basket_holdout(prices.close, factory, config, n_folds=n_folds,
                            aux=prices.aux, open_=prices.open)
    stress = run_basket_stress_suite(prices.close, factory, config,
                                     aux=prices.aux, open_=prices.open)

    c = result.comparison
    turnover = float(result.metrics.get("turnover") or 0)
    checks = {
        "beats primary benchmark (Sharpe)": c["beats_benchmark_sharpe"],
        "positive alpha vs benchmark": c["positive_alpha"],
        "OOS walk-forward Sharpe > 0.3": float(wf.summary.get("oos_sharpe_mean") or 0) > 0.3,
        "survives costs x2 (positive)": float(stress.loc["costs_x2", "total_return_pct"] or 0) > 0,
        "survives costs x3 (positive)": float(stress.loc["costs_x3", "total_return_pct"] or 0) > 0,
        "concentration: no month > 25%": (conc.max_month_pct or 0) <= 25.0,
        "turnover acceptable (< 50x/yr)": turnover < 50.0,
    }
    _print_long_only_comparison(c)
    console.print(f"\n[bold]Walk-forward[/bold]: OOS Sharpe {wf.summary.get('oos_sharpe_mean')}, "
                  f"{wf.summary.get('oos_folds_positive')}/{wf.summary.get('oos_folds')} folds positive")
    console.print(f"[bold]Concentration score[/bold]: {conc.concentration_score()}/100 "
                  f"(max month {conc.max_month_pct}%)")
    console.print(f"[bold]Turnover[/bold]: {turnover}x/yr")
    console.print("\n[bold]Readiness gate[/bold]")
    for name, ok in checks.items():
        console.print(f"  [{'green' if ok else 'red'}]{'PASS' if ok else 'FAIL'}[/] {name}")
    passed = sum(1 for v in checks.values() if v)
    eligible = all(checks.values())
    verdict = ("[green]PAPER-TRADING ELIGIBLE[/green]" if eligible
               else f"[yellow]NOT YET PAPER-ELIGIBLE ({passed}/{len(checks)} gates)[/yellow]")
    console.print(f"\nVerdict: {verdict}")
    console.print("[bold red]NOT LIVE ELIGIBLE[/bold red] — paper/shadow only; no Invest/ISA "
                  "order endpoint is wired and a supervised paper period must pass first.")
    out = settings.reports_dir / f"long_only_readiness_{strategy}_{universe}.md"
    lines = [f"# Long-only readiness — {strategy} ({universe}, {interval})", "",
             f"Verdict: **{'PAPER-TRADING ELIGIBLE' if eligible else 'NOT YET PAPER-ELIGIBLE'}** "
             f"({passed}/{len(checks)} gates)", "", "**NOT LIVE ELIGIBLE.**", "",
             "## Gate checks", ""]
    lines += [f"- {'PASS' if ok else 'FAIL'} — {n}" for n, ok in checks.items()]
    lines += ["", "## Book vs benchmarks", "",
              f"- book Sharpe {c['book_sharpe']}, return {c['book_total_return_pct']}%",
              f"- primary benchmark {c['primary_benchmark']}: "
              f"{c['benchmarks'].get(c['primary_benchmark'], {})}",
              f"- walk-forward OOS Sharpe {wf.summary.get('oos_sharpe_mean')}",
              f"- concentration score {conc.concentration_score()}/100", ""]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[green]Report:[/green] {out}")
    if not eligible:
        raise typer.Exit(1)


def _synthetic_trading212_instruments(symbols: list[str]) -> dict:
    """Offline Invest/ISA instrument stubs for shadow planning: every name is an
    equity, fractional, penny tick. The live demo connector (Phase 5) replaces
    this with the broker's real instrument list."""
    from app.brokers.models import Instrument
    from app.core.types import AssetClass

    return {s: Instrument(broker="trading212", symbol=s, asset_class=AssetClass.EQUITY,
                          tick_size=0.01, step_size=0.0001, min_notional=1.0,
                          fractional=True, shortable=False) for s in symbols}


@app.command("paper-trade-long-only")
def paper_trade_long_only(
    strategy: str = typer.Option("long_only_ensemble"),
    broker: str = typer.Option("trading212"),
    mode: str = typer.Option("shadow", help="shadow (plan only) | demo (Phase 5 demo connector)"),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    starting_cash: float = typer.Option(10_000.0),
) -> None:
    """Shadow-plan today's long-only orders for Trading 212 Invest/ISA (Path A).

    Computes target weights on the latest bar and turns them into a concrete
    Trading 212 order plan (no short, no margin, fractional shares, limit-order
    preference, market-hours awareness) — WITHOUT sending anything. The full
    supervised paper/demo loop with simulated fills + TCA is the Phase 5 layer."""
    settings, storage = _bootstrap()
    if broker != "trading212":
        raise typer.BadParameter("Path A targets Trading 212 Invest/ISA only.")
    if mode == "demo":
        console.print("[yellow]Demo-connector paper trading is the Phase 5 layer "
                      "(shadow-start/paper-start). Running SHADOW plan instead.[/yellow]")
    from app.execution.trading212_rebalancer import RebalanceConfig, Trading212Rebalancer

    defaults, prices, config, reb_every = _long_only_setup(storage, universe, interval)
    regime_cfg = _regime_cfg(True, 0.0)
    fn, names = _build_long_only(strategy, defaults, universe, interval, regime_cfg, reb_every)
    window = prices.close.iloc[-config.fit_window:]
    aux_window = {k: v.iloc[-config.fit_window:] for k, v in prices.aux.items()}
    weights = (fn(window, aux=aux_window) if getattr(fn, "wants_aux", False)
               else fn(window))
    weights = weights.clip(lower=0.0)
    last_prices = {s: float(prices.close[s].iloc[-1]) for s in prices.symbols}

    instruments = _synthetic_trading212_instruments(prices.symbols)
    reb = Trading212Rebalancer(instruments, RebalanceConfig())
    plan = reb.plan({s: float(w) for s, w in weights.items()}, positions={},
                    cash=starting_cash, prices=last_prices, market_open=False)
    console.print(f"[bold green]SHADOW plan[/bold green] — {strategy} on {universe} "
                  f"({broker}). [bold]NO REAL ORDERS.[/bold]")
    console.print(f"target names: {int((weights > 0).sum())}, "
                  f"gross {float(weights.sum()):.2%}, cash buffer {plan.summary()}")
    table = Table(title="Planned orders (shadow)")
    for col in ("symbol", "side", "type", "qty", "limit", "notional", "tgt_wt"):
        table.add_column(col, justify="right")
    for o in sorted(plan.orders, key=lambda x: -x.request.notional)[:25]:
        r = o.request
        table.add_row(r.symbol, r.side.value, r.order_type.value, f"{r.quantity:.4f}",
                      f"{r.limit_price:.2f}" if r.limit_price else "—",
                      f"{r.notional:.2f}", f"{o.weight_after:.2%}")
    console.print(table)
    for sym, reason in plan.skipped[:10]:
        console.print(f"[dim]skipped {sym}: {reason}[/dim]")
    for note in plan.notes:
        console.print(f"[dim]- {note}[/dim]")


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
    _record_experiment(
        storage, kind="carry", strategy="funding_carry", universe=universe,
        interval="8h", metrics=result.metrics,
        config={"top_k": top_k, "lookback_periods": lookback_periods,
                "cost_bps": cost_bps, "entry_apr": entry_apr,
                "exit_apr": exit_apr, "symbols": list(panels)},
        notes="funding leg only — basis/margin/liquidation unmodeled",
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
    adjusted: bool | None = typer.Option(
        None, "--adjusted/--raw",
        help="total-return prices (default: adjusted for daily equity universes)"),
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

    use_adjusted = adjusted if adjusted is not None else _default_adjusted(universe, interval)
    prices = build_price_matrix(storage, get_universe(universe), interval,
                                adjusted=use_adjusted)
    _print_adjustment_status(prices, universe, interval)
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
    _record_experiment(
        storage, kind="walk_forward", strategy=strategy, universe=universe,
        interval=interval, metrics=wf.summary, prices=prices, sample="walk_forward",
        config={"train_bars": train_bars or int(wf_raw.get("train_bars", 4000)),
                "test_bars": test_bars or int(wf_raw.get("test_bars", 1000)),
                "adjusted": use_adjusted},
    )
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


@app.command("data-audit")
def data_audit(
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    source: str | None = typer.Option(None, help="restrict to one bar source"),
    symbols: str | None = typer.Option(None, help="comma-separated symbols (overrides universe)"),
) -> None:
    """Audit stored data for a universe: coverage, gaps, staleness, outliers,
    dividend-adjustment coverage, survivorship status — with an honest verdict."""
    settings, storage = _bootstrap()
    from app.data.data_audit import audit_universe

    names = ([s.strip().upper() for s in symbols.split(",") if s.strip()]
             if symbols else None)
    rep = audit_universe(storage, universe, interval, source=source, symbols=names)

    color = {"ok": "green", "research_only": "yellow", "not_acceptable": "red"}[rep.verdict]
    console.print(f"\n[bold]Data audit — {universe} ({interval})[/bold]")
    console.print(f"survivorship: [bold]{rep.survivorship}[/bold] — {rep.survivorship_note}")
    console.print(f"aligned window: {rep.aligned_start} → {rep.aligned_end} "
                  f"(alignment loss {rep.alignment_loss_pct:.1f}%)")
    console.print(f"dividend-adjustment coverage: {rep.adj_coverage_pct:.1f}%")
    console.print(f"verdict: [{color}][bold]{rep.verdict.upper()}[/bold][/{color}]")
    for reason in rep.verdict_reasons:
        console.print(f"  - {reason}")
    flagged = [a for a in rep.symbols if a.issues]
    if flagged:
        table = Table(title=f"{len(flagged)} symbols with issues")
        table.add_column("symbol")
        table.add_column("issues")
        for a in flagged:
            table.add_row(a.symbol, "; ".join(a.issues))
        console.print(table)
    out = settings.reports_dir / f"data_audit_{universe}_{interval}.md"
    out.write_text(rep.to_markdown(), encoding="utf-8")
    console.print(f"[green]Report:[/green] {out}")
    if rep.verdict == "not_acceptable":
        raise typer.Exit(1)


@app.command("data-coverage")
def data_coverage(
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
) -> None:
    """Per-symbol stored-bar coverage for a universe."""
    _, storage = _bootstrap()
    from app.data.universe import get_universe

    table = Table(title=f"Coverage — {universe} ({interval})")
    for col in ("symbol", "rows", "first", "last"):
        table.add_column(col)
    for symbol in get_universe(universe):
        lo, hi, n = storage.bar_coverage(symbol, interval)
        table.add_row(symbol, str(n), str(lo or "—"), str(hi or "—"))
    console.print(table)


@app.command("experiments")
def experiments(
    family: str | None = typer.Option(None, help="filter by trial family"),
    strategy: str | None = typer.Option(None),
    limit: int = typer.Option(30),
) -> None:
    """List recorded experiments (every research run is a counted trial)."""
    _, storage = _bootstrap()
    rows = storage.list_experiments(family=family, strategy=strategy, limit=limit)
    if not rows:
        console.print("[yellow]No experiments recorded yet.[/yellow]")
        return
    table = Table(title="Experiments (newest first)")
    for col in ("id", "created", "kind", "family", "sample", "sharpe", "ret%", "git", "trial info"):
        table.add_column(col)
    for r in rows:
        m = json.loads(r.metrics_json or "{}")
        n_trials = storage.count_experiment_trials(r.family) if r.family else 0
        table.add_row(
            r.experiment_id, f"{r.created_at:%m-%d %H:%M}", r.kind, r.family, r.sample,
            str(m.get("sharpe", m.get("oos_sharpe_mean", "—"))),
            str(m.get("total_return_pct", m.get("oos_total_return_pct", "—"))),
            (r.git_commit[:7] + ("*" if r.git_dirty else "")) or "—",
            f"family has {n_trials} trials",
        )
    console.print(table)
    console.print("[dim]* = dirty working tree. Best-of-family Sharpe is inflated "
                  "by the family's trial count (W-02).[/dim]")


@app.command("trial-backfill")
def trial_backfill_cmd(
    manifest: str | None = typer.Option(None, help="override research_trials.yaml path"),
) -> None:
    """Back-fill the documented historical research trials into the registry.

    The deflated Sharpe needs the REAL number of configs searched (~50), not the
    ~1 the tracker saw before it existed. This imports every cited trial from
    app/config/research_trials.yaml. Idempotent — safe to re-run."""
    _, storage = _bootstrap()
    from pathlib import Path

    from app.research.trial_backfill import backfill_trials

    res = backfill_trials(storage, Path(manifest) if manifest else None)
    console.print(f"[green]Trial backfill[/green]: inserted {res['inserted']}, "
                  f"skipped {res['skipped']} (already present), "
                  f"manifest total {res['total_manifest_trials']}")
    table = Table(title="Trials per selection group")
    table.add_column("group")
    table.add_column("manifest trials", justify="right")
    for group, n in res["by_group"].items():
        table.add_row(group, str(n))
    console.print(table)


@app.command("trial-family-report")
def trial_family_report() -> None:
    """Selection groups and trial families with counts + Sharpe distributions."""
    _, storage = _bootstrap()
    from app.research.trial_backfill import all_groups, backfill_trials, group_stats

    backfill_trials(storage)            # idempotent: ensure the record is populated
    groups = all_groups(storage)
    if not groups:
        console.print("[yellow]No grouped trials. Run `trial-backfill` first.[/yellow]")
        return
    table = Table(title="Selection groups (trial families for deflation)")
    for col in ("group", "trials", "with Sharpe", "best", "mean", "std"):
        table.add_column(col, justify="right")
    for g in groups:
        s = group_stats(storage, g)
        table.add_row(g, str(s.n_trials), str(len(s.sharpes)),
                      f"{s.best_sharpe:.2f}" if s.best_sharpe is not None else "—",
                      f"{s.mean_sharpe:.2f}" if s.mean_sharpe is not None else "—",
                      f"{s.std_sharpe:.2f}" if s.std_sharpe is not None else "—")
    console.print(table)
    console.print("[dim]The trial count + Sharpe std deflate the best-of-group result "
                  "(deflated-sharpe-report).[/dim]")


@app.command("deflated-sharpe-report")
def deflated_sharpe_report(
    sleeves: str | None = typer.Option(None, help="flagship sleeves (default config)"),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
    group: str = typer.Option("equity_daily_book_selection",
                              help="selection group to deflate against"),
) -> None:
    """Deflate the flagship's Sharpe against the TRUE trial count (Phase 2).

    Re-runs the flagship book for its realized returns, then computes the
    deflated Sharpe twice: naive (1 trial, what the tracker saw) and honest (the
    full selection-group trial count). Reports whether the flagship remains
    research-eligible — and does not hide it if the verdict worsens."""
    settings, storage = _bootstrap()
    from app.backtesting.basket_engine import run_basket_backtest
    from app.core.math_utils import periods_per_year
    from app.research.deflated_sharpe import deflated_sharpe_ratio
    from app.research.trial_backfill import backfill_trials, group_stats

    backfill_trials(storage)
    stats = group_stats(storage, group)
    if stats.n_trials == 0:
        console.print(f"[red]No trials in group {group!r}.[/red]")
        raise typer.Exit(1)

    prices, factory, config, names = _ensemble_price_setup(
        storage, sleeves, universe, interval, False, 1.0, None)
    console.print(f"Re-running flagship [bold]{' + '.join(names)}[/bold] for realized "
                  f"returns (deflating against group '{group}')...")
    full = run_basket_backtest(prices.close, factory(), config, aux=prices.aux, open_=prices.open)
    import numpy as np

    rets = full.equity.dropna().pct_change().dropna().to_numpy()
    ppy = _bars_per_year(universe, interval) or periods_per_year(interval)
    std_per_period = (stats.std_sharpe / np.sqrt(ppy)) if stats.std_sharpe else None

    naive = deflated_sharpe_ratio(rets, n_trials=1, periods_per_year=ppy)
    honest = deflated_sharpe_ratio(rets, n_trials=stats.n_trials,
                                   periods_per_year=ppy, trial_sharpe_std=std_per_period)
    console.print(f"\n[bold]Selection group[/bold]: {stats.summary()}")
    console.print("\n[bold]Deflated Sharpe — naive (1 trial)[/bold]")
    console.print(f"  {naive.summary()}")
    console.print(f"\n[bold]Deflated Sharpe — honest ({stats.n_trials} trials)[/bold]")
    console.print(f"  {honest.summary()}")
    verdict_c = "green" if honest.passed else "red"
    console.print(f"\nVerdict (honest): [{verdict_c}]{'RESEARCH-ELIGIBLE' if honest.passed else 'FAILS DEFLATED SHARPE'}[/]")
    if not honest.passed:
        console.print("[yellow]After correcting for the real search, P(true Sharpe > "
                      "E[max of noise]) is below 0.95. This is the honest, harsher "
                      "verdict the audit demanded — the flagship is a plausible but "
                      "UNPROVEN candidate, not an established edge.[/yellow]")
    out = settings.reports_dir / f"deflated_sharpe_{group}.md"
    out.write_text(
        f"# Deflated Sharpe — {' + '.join(names)} vs group '{group}'\n\n"
        f"- {stats.summary()}\n"
        f"- naive (1 trial): {naive.summary()}\n"
        f"- honest ({stats.n_trials} trials): {honest.summary()}\n"
        f"- verdict: {'RESEARCH-ELIGIBLE' if honest.passed else 'FAILS DEFLATED SHARPE'}\n",
        encoding="utf-8")
    console.print(f"[green]Report:[/green] {out}")


@app.command("multiple-testing-report")
def multiple_testing_report(
    group: str = typer.Option("equity_daily_book_selection"),
    fdr_alpha: float = typer.Option(0.10),
) -> None:
    """Family-wise / FDR correction + overfitting warning across a group.

    Converts each trial's annualized Sharpe to an approximate t-stat / p-value
    (t ≈ Sharpe·√years), then applies Bonferroni and Benjamini-Hochberg, and
    flags probability-of-backtest-overfitting risk by comparing the best
    observed Sharpe to E[max] of pure-noise trials."""
    settings, storage = _bootstrap()
    import numpy as np
    from scipy import stats as sps

    from app.research.deflated_sharpe import expected_max_sharpe
    from app.research.multiple_testing import benjamini_hochberg, bonferroni
    from app.research.trial_backfill import backfill_trials, group_stats

    backfill_trials(storage)
    gs = group_stats(storage, group)
    if not gs.sharpes:
        console.print(f"[yellow]No recorded Sharpes in group {group!r}.[/yellow]")
        raise typer.Exit(1)
    years = 3.8                          # the daily research window length
    sharpes = np.array(gs.sharpes)
    tstats = sharpes * np.sqrt(years)
    pvalues = [float(1.0 - sps.norm.cdf(t)) for t in tstats]   # one-sided H0: SR<=0
    bonf = bonferroni(pvalues, alpha=0.05)
    bh = benjamini_hochberg(pvalues, alpha=fdr_alpha)
    best = float(sharpes.max())
    emax_ann = expected_max_sharpe(gs.n_trials, gs.std_sharpe / 1.0) if gs.std_sharpe else 0.0

    console.print(f"[bold]Multiple-testing — group '{group}'[/bold] "
                  f"({gs.n_trials} trials, {len(gs.sharpes)} with Sharpe)")
    console.print(f"  best Sharpe {best:.2f} | Bonferroni discoveries "
                  f"{sum(bonf)}/{len(bonf)} | BH(FDR {fdr_alpha}) discoveries {sum(bh)}/{len(bh)}")
    console.print(f"  E[max Sharpe] of {gs.n_trials} pure-noise trials "
                  f"(dispersion {gs.std_sharpe:.2f}): {emax_ann:.2f}")
    pbo_risk = "HIGH" if best <= emax_ann * 1.2 else ("MODERATE" if best <= emax_ann * 1.8 else "LOW")
    color = {"HIGH": "red", "MODERATE": "yellow", "LOW": "green"}[pbo_risk]
    console.print(f"  overfitting (PBO) risk: [{color}]{pbo_risk}[/] — best Sharpe is "
                  f"{best / emax_ann:.1f}x the noise-max" if emax_ann > 0 else
                  "  overfitting risk: indeterminate (no dispersion)")
    if sum(bonf) == 0:
        console.print("[yellow]No trial survives Bonferroni — individually, no single "
                      "config is significant after family-wise correction.[/yellow]")
    out = settings.reports_dir / f"multiple_testing_{group}.md"
    out.write_text(
        f"# Multiple-testing — group '{group}'\n\n"
        f"- trials: {gs.n_trials} ({len(gs.sharpes)} with Sharpe)\n"
        f"- best Sharpe: {best:.2f}\n"
        f"- Bonferroni discoveries (a=0.05): {sum(bonf)}/{len(bonf)}\n"
        f"- Benjamini-Hochberg discoveries (FDR {fdr_alpha}): {sum(bh)}/{len(bh)}\n"
        f"- E[max Sharpe] of noise: {emax_ann:.2f}\n"
        f"- PBO risk: {pbo_risk}\n", encoding="utf-8")
    console.print(f"[green]Report:[/green] {out}")


@app.command("product-decision")
def product_decision() -> None:
    """Decide what (if anything) to trade across all paths (Phase 6).

    Synthesizes the readiness of the market-neutral flagship, the long-only
    equity book and the crypto-futures book into one operator decision: lead
    product, tradability, missing gates, next action, risk level and capital
    stage. Reads the readiness reports; run those first for a current verdict."""
    settings, storage = _bootstrap()
    from app.research.product_decision import evaluate_products

    decision = evaluate_products(settings, storage)
    table = Table(title="Product paths")
    for col in ("product", "venue", "short?", "lev?", "venue wired", "gates", "status", "risk"):
        table.add_column(col)
    for p in decision.products:
        gates = f"{p.gates_passed}/{p.gates_total}" if p.gates_total else "—"
        scolor = {"do_not_trade": "red", "not_yet": "yellow",
                  "paper_candidate": "green", "testnet_candidate": "green"}.get(p.status, "dim")
        table.add_row(p.product_id, p.venue[:38], "yes" if p.requires_short else "no",
                      "yes" if p.requires_leverage else "no",
                      "[green]yes[/green]" if p.venue_connected else "[red]no[/red]",
                      gates, f"[{scolor}]{p.status}[/{scolor}]", p.risk_level)
    console.print(table)
    console.print(f"\n[bold]Decision[/bold]: {decision.headline}")
    console.print(f"[bold]Recommended path[/bold]: {decision.recommended}")
    console.print(f"[bold]Next action[/bold]: {decision.action}")
    console.print(f"[bold]Capital stage[/bold]: {decision.capital_stage}")
    console.print("[bold red]NOTHING IS LIVE ELIGIBLE.[/bold red]")
    out = settings.reports_dir / "product_decision.md"
    lines = ["# Product decision", "", f"**{decision.headline}**", "",
             f"- recommended path: {decision.recommended}",
             f"- next action: {decision.action}",
             f"- capital stage: {decision.capital_stage}",
             "- **NOTHING IS LIVE ELIGIBLE.**", "", "## Paths", ""]
    for p in decision.products:
        lines += [f"### {p.product_id} — {p.status}",
                  f"- {p.name}", f"- venue: {p.venue} (wired: {p.venue_connected})",
                  f"- gates: {p.gates_passed}/{p.gates_total}; risk: {p.risk_level}",
                  f"- missing: {', '.join(p.missing) or 'none'}",
                  *[f"- note: {n}" for n in p.notes], ""]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[green]Report:[/green] {out}")


# --------------------------------------------------------------------------------
# Path B — Binance USDT-perp crypto futures (research / paper / testnet only)
# --------------------------------------------------------------------------------

FUTURES_STRATEGIES = ("crypto_tsmom_futures", "funding_carry", "basis_carry",
                      "funding_adjusted_momentum", "crypto_futures_ensemble")


def _load_futures_prices(storage, universe, interval):
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe

    return build_price_matrix(storage, get_universe(universe), interval,
                              source="binance_futures", adjusted=False, min_rows=60)


def _build_funding_aux(symbols, index, *, quiet=False):
    """(raw 8h panel for engine P&L, bar-mean panel for signals). Network fetch;
    returns (None, None) on failure so funding sleeves idle gracefully."""
    import numpy as np

    from app.data.funding import build_funding_panel

    try:
        start = index[0].to_pydatetime()
        end = index[-1].to_pydatetime()
        raw = build_funding_panel(list(symbols), start, end)
    except Exception as exc:  # noqa: BLE001
        if not quiet:
            console.print(f"[yellow]funding fetch failed ({exc}); funding sleeves idle[/yellow]")
        return None, None
    if raw.empty:
        return None, None
    bins = index
    pos = np.searchsorted(bins.values, raw.index.values, side="right") - 1
    pos = np.clip(pos, 0, len(bins) - 1)
    bar_mean = raw.groupby(bins[pos]).mean().reindex(index=index, columns=symbols).ffill()
    return raw, bar_mean


def _futures_strategy(strategy: str, record_history: bool = False):
    from app.strategies.basis_carry import make_basis_carry_weight_fn
    from app.strategies.crypto_futures_ensemble import build_crypto_futures_ensemble
    from app.strategies.crypto_tsmom_futures import make_crypto_tsmom_weight_fn
    from app.strategies.ensemble import EnsembleConfig
    from app.strategies.funding_adjusted_momentum import make_funding_adjusted_momentum
    from app.strategies.funding_carry import make_funding_carry_weight_fn

    if strategy == "crypto_tsmom_futures":
        return make_crypto_tsmom_weight_fn()
    if strategy == "funding_carry":
        return make_funding_carry_weight_fn()
    if strategy == "basis_carry":
        return make_basis_carry_weight_fn()
    if strategy == "funding_adjusted_momentum":
        return make_funding_adjusted_momentum()
    if strategy == "crypto_futures_ensemble":
        return build_crypto_futures_ensemble(
            ensemble_config=EnsembleConfig(vol_window=20, min_observations=5, cost_bps=7.0),
            record_history=record_history)
    raise typer.BadParameter(f"unknown futures strategy {strategy!r}; choose from {FUTURES_STRATEGIES}")


@app.command("download-futures-data")
def download_futures_data(
    universe: str = typer.Option("crypto_top_20"),
    interval: str = typer.Option("1d"),
    days: int = typer.Option(1095, min=1),
) -> None:
    """Download Binance USDT-perp futures klines (public, no key). Research only."""
    _, storage = _bootstrap()
    storage.init_db()
    from app.data.futures import BinanceFuturesData
    from app.data.universe import get_universe

    syms = get_universe(universe)
    console.print(f"Downloading futures klines: {len(syms)} symbols, {interval}, {days}d...")
    counts = BinanceFuturesData().download(storage, syms, interval, days)
    table = Table(title=f"Futures download ({interval}, {days}d)")
    table.add_column("symbol")
    table.add_column("rows", justify="right")
    for sym, n in counts.items():
        table.add_row(sym, str(n))
    console.print(table)


def _futures_config(interval, universe):
    from app.backtesting.futures_engine import FuturesConfig

    return FuturesConfig(
        interval=interval, fit_window=150, rebalance_every=1,
        taker_fee_bps=4.0, slippage_bps=3.0, leverage=1.0, max_leverage=2.0,
        bars_per_year=365.0, apply_funding=True, label="futures")


@app.command("backtest-futures")
def backtest_futures(
    strategy: str = typer.Option("crypto_futures_ensemble", help=" | ".join(FUTURES_STRATEGIES)),
    universe: str = typer.Option("crypto_top_20"),
    interval: str = typer.Option("1d"),
) -> None:
    """Backtest a crypto-futures strategy with fees + funding + leverage cap.

    Research only — no account, no live orders. Funding is fetched from the
    public API; the basis sleeve idles unless spot data is present."""
    settings, storage = _bootstrap()
    from app.backtesting.futures_engine import run_futures_backtest

    prices = _load_futures_prices(storage, universe, interval)
    raw_funding, funding_aux = _build_funding_aux(prices.symbols, prices.index)
    fn = _futures_strategy(strategy)
    aux = dict(prices.aux)
    if funding_aux is not None:
        aux["funding"] = funding_aux
    config = _futures_config(interval, universe)
    console.print(f"Futures backtest: [bold]{strategy}[/bold] on {len(prices.symbols)} perps, "
                  f"{len(prices.index)} bars (funding {'on' if raw_funding is not None else 'OFF'})...")
    result = run_futures_backtest(prices.close, fn, config, funding=raw_funding,
                                  aux=aux, open_=prices.open)
    _record_experiment(storage, kind="futures", strategy=strategy, universe=universe,
                       interval=interval, metrics=result.metrics, prices=prices,
                       config={"strategy": strategy, "leverage": config.leverage},
                       notes="crypto futures research; paper/testnet only")
    table = Table(title=f"Futures metrics — {strategy}")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for key, value in result.metrics.items():
        table.add_row(key, str(value))
    console.print(table)
    console.print(f"funding paid (net): {result.funding_paid:.2f} | "
                  f"liquidation breaches: {result.n_liquidation_breaches} | "
                  f"min liq distance: {result.min_liquidation_distance}")
    for w in result.warnings:
        console.print(f"[dim]- {w}[/dim]")


@app.command("funding-report")
def funding_report(
    universe: str = typer.Option("crypto_top_20"),
    days: int = typer.Option(365),
) -> None:
    """Trailing funding-rate APR per perp (the carry landscape)."""
    _, storage = _bootstrap()
    from app.data.funding import build_funding_panel, funding_summary
    from app.data.universe import get_universe

    start = (utc_now() - timedelta(days=days)).replace(tzinfo=None)
    end = utc_now().replace(tzinfo=None)
    panel = build_funding_panel(get_universe(universe), start, end)
    if panel.empty:
        console.print("[red]No funding history fetched.[/red]")
        raise typer.Exit(1)
    summary = funding_summary(panel)
    console.print(f"Funding report — {universe} ({days}d)")
    console.print(summary)


@app.command("basis-report")
def basis_report(
    universe: str = typer.Option("crypto_top_20"),
    interval: str = typer.Option("1d"),
) -> None:
    """Perp-vs-spot basis per symbol (cash-and-carry landscape)."""
    settings, storage = _bootstrap()
    from app.data.basis import basis_summary, compute_basis
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe

    syms = get_universe(universe)
    try:
        fut = _load_futures_prices(storage, universe, interval).close
        spot = build_price_matrix(storage, syms, interval, source="binance",
                                  adjusted=False, min_rows=60).close
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]basis needs both futures and spot bars stored: {exc}[/yellow]")
        raise typer.Exit(1) from exc
    basis = compute_basis(fut, spot)
    if basis.empty:
        console.print("[yellow]No overlapping futures+spot symbols for basis.[/yellow]")
        raise typer.Exit(1)
    console.print(f"Basis report — {universe} ({interval})")
    console.print(basis_summary(basis))


@app.command("futures-stress")
def futures_stress(
    strategy: str = typer.Option("crypto_futures_ensemble"),
    universe: str = typer.Option("crypto_top_20"),
    interval: str = typer.Option("1d"),
) -> None:
    """Stress the futures book: higher fees, funding shock, vol spike, leverage."""
    settings, storage = _bootstrap()
    import pandas as pd

    from app.backtesting.futures_engine import run_futures_backtest

    prices = _load_futures_prices(storage, universe, interval)
    raw_funding, funding_aux = _build_funding_aux(prices.symbols, prices.index)
    aux = dict(prices.aux)
    if funding_aux is not None:
        aux["funding"] = funding_aux

    scenarios = {
        "base": {},
        "fees_x3": {"taker_fee_bps": 12.0, "slippage_bps": 9.0},
        "funding_x2": {"funding_mult": 2.0},
        "leverage_2x": {"leverage": 2.0},
        "vol_spike": {"return_shock": True},
    }
    rows = []
    for name, sc in scenarios.items():
        cfg = _futures_config(interval, universe)
        cfg.taker_fee_bps = sc.get("taker_fee_bps", cfg.taker_fee_bps)
        cfg.slippage_bps = sc.get("slippage_bps", cfg.slippage_bps)
        cfg.leverage = sc.get("leverage", cfg.leverage)
        fund = raw_funding * sc["funding_mult"] if (raw_funding is not None and "funding_mult" in sc) else raw_funding
        close = prices.close
        if sc.get("return_shock"):     # widen all returns 2x (vol spike proxy)
            close = (prices.close.pct_change().fillna(0) * 2.0 + 1.0).cumprod() * prices.close.iloc[0]
        res = run_futures_backtest(close, _futures_strategy(strategy), cfg,
                                   funding=fund, aux=aux, open_=prices.open)
        rows.append({"scenario": name, "return_pct": res.metrics.get("total_return_pct"),
                     "sharpe": res.metrics.get("sharpe"),
                     "max_dd_pct": res.metrics.get("max_drawdown_pct"),
                     "liq_breaches": res.n_liquidation_breaches,
                     "min_liq_dist": res.min_liquidation_distance})
    df = pd.DataFrame(rows).set_index("scenario")
    console.print(f"Futures stress — {strategy} ({universe})")
    console.print(df)
    out = settings.reports_dir / f"futures_stress_{strategy}_{universe}.md"
    out.write_text(f"# Futures stress — {strategy} ({universe})\n\n{df.to_markdown()}\n",
                   encoding="utf-8")
    console.print(f"[green]Report:[/green] {out}")


@app.command("futures-paper")
def futures_paper(
    strategy: str = typer.Option("crypto_futures_ensemble"),
    broker: str = typer.Option("binance"),
    mode: str = typer.Option("testnet", help="paper | testnet (live is blocked)"),
    universe: str = typer.Option("crypto_top_20"),
    interval: str = typer.Option("1d"),
    starting_cash: float = typer.Option(10_000.0),
) -> None:
    """Shadow/paper plan today's futures orders (testnet/paper only; live blocked)."""
    settings, storage = _bootstrap()
    if broker != "binance":
        raise typer.BadParameter("Path B targets Binance futures only.")
    from app.brokers.binance.futures_testnet_execution import (
        FuturesExecutionConfig,
        FuturesTestnetExecutor,
    )

    prices = _load_futures_prices(storage, universe, interval)
    _raw, funding_aux = _build_funding_aux(prices.symbols, prices.index, quiet=True)
    fn = _futures_strategy(strategy)
    window = prices.close.iloc[-_futures_config(interval, universe).fit_window:]
    aux = {k: v.iloc[-len(window):] for k, v in prices.aux.items()}
    if funding_aux is not None:
        aux["funding"] = funding_aux.iloc[-len(window):]
    weights = fn(window, aux=aux) if getattr(fn, "wants_aux", False) else fn(window)
    marks = {s: float(prices.close[s].iloc[-1]) for s in prices.symbols}
    executor = FuturesTestnetExecutor(FuturesExecutionConfig(mode=mode))
    report = executor.execute_target({s: float(w) for s, w in weights.items()},
                                     positions={}, equity=starting_cash, mark_prices=marks)
    console.print(f"[bold green]{mode.upper()} futures plan[/bold green] — {strategy} on "
                  f"{universe}. [bold]NO LIVE ORDERS.[/bold] {len(report.fills)} simulated fills.")
    table = Table(title=f"Simulated futures fills ({mode})")
    for col in ("symbol", "side", "qty", "price", "fee"):
        table.add_column(col, justify="right")
    for f in sorted(report.fills, key=lambda x: -x.quantity * x.price)[:25]:
        table.add_row(f.symbol, f.side.value, f"{f.quantity:.4f}", f"{f.price:.2f}", f"{f.fee:.2f}")
    console.print(table)
    for sym, reason in report.rejected[:10]:
        console.print(f"[dim]rejected {sym}: {reason}[/dim]")


@app.command("futures-readiness")
def futures_readiness(
    strategy: str = typer.Option("crypto_futures_ensemble"),
    universe: str = typer.Option("crypto_top_20"),
    interval: str = typer.Option("1d"),
    n_folds: int = typer.Option(3),
) -> None:
    """Crypto-futures testnet/paper-readiness gate (Path B). Live stays blocked."""
    settings, storage = _bootstrap()
    from app.backtesting.concentration import analyze_concentration
    from app.backtesting.futures_engine import run_futures_backtest

    prices = _load_futures_prices(storage, universe, interval)
    raw_funding, funding_aux = _build_funding_aux(prices.symbols, prices.index)
    aux = dict(prices.aux)
    if funding_aux is not None:
        aux["funding"] = funding_aux
    cfg = _futures_config(interval, universe)
    res = run_futures_backtest(prices.close, _futures_strategy(strategy), cfg,
                               funding=raw_funding, aux=aux, open_=prices.open)
    conc = analyze_concentration(res.equity, close=prices.close, weights_df=res.weights)
    # simple holdout: split the series, compare first/second half Sharpe
    eq = res.equity.dropna()
    half = len(eq) // 2
    import numpy as np

    def _sh(s):
        r = s.pct_change().dropna().to_numpy()
        return float(np.mean(r) / np.std(r) * np.sqrt(365)) if len(r) > 2 and np.std(r) > 0 else 0.0
    oos_sharpe = _sh(eq.iloc[half:])

    checks = {
        "positive net return": (res.metrics.get("total_return_pct") or 0) > 0,
        "Sharpe > 0.5": (res.metrics.get("sharpe") or 0) > 0.5,
        "2nd-half (OOS) Sharpe > 0": oos_sharpe > 0,
        "no liquidation breaches at 1x": res.n_liquidation_breaches == 0,
        "liquidation buffer healthy": res.min_liquidation_distance > 0.3,
        "concentration: no month > 25%": (conc.max_month_pct or 0) <= 25.0,
    }
    console.print(f"Futures readiness — [bold]{strategy}[/bold] ({universe})")
    table = Table(title="Futures metrics")
    table.add_column("metric")
    table.add_column("value", justify="right")
    for k in ("total_return_pct", "sharpe", "max_drawdown_pct", "ann_vol_pct"):
        table.add_row(k, str(res.metrics.get(k)))
    table.add_row("2nd-half OOS sharpe", f"{oos_sharpe:.3f}")
    table.add_row("funding_paid", f"{res.funding_paid:.2f}")
    table.add_row("liq_breaches", str(res.n_liquidation_breaches))
    console.print(table)
    console.print("\n[bold]Readiness gate[/bold]")
    for name, ok in checks.items():
        console.print(f"  [{'green' if ok else 'red'}]{'PASS' if ok else 'FAIL'}[/] {name}")
    eligible = all(checks.values())
    n_pass = sum(1 for v in checks.values() if v)
    verdict = ("[green]TESTNET/PAPER ELIGIBLE[/green]" if eligible
               else f"[yellow]NOT YET TESTNET/PAPER ELIGIBLE ({n_pass}/{len(checks)})[/yellow]")
    console.print(f"\nVerdict: {verdict}")
    console.print("[bold red]LIVE BLOCKED[/bold red] — Binance futures mainnet trading is "
                  "refused; testnet/paper only, and a supervised period must pass first.")
    out = settings.reports_dir / f"futures_readiness_{strategy}_{universe}.md"
    lines = [f"# Futures readiness — {strategy} ({universe}, {interval})", "",
             f"Verdict: **{'TESTNET/PAPER ELIGIBLE' if eligible else 'NOT YET ELIGIBLE'}** "
             f"({n_pass}/{len(checks)}). **LIVE BLOCKED.**", "", "## Gates", ""]
    lines += [f"- {'PASS' if ok else 'FAIL'} — {n}" for n, ok in checks.items()]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[green]Report:[/green] {out}")


# --------------------------------------------------------------------------------
# Phase 4 — crisis-regime + crash-protection testing
# --------------------------------------------------------------------------------

def _crisis_equity_runner(strategy, universe, interval, *, regime=True):
    """Build (run_fn, label) for the crisis suite over the equity basket engine.
    run_fn(close, aux) -> equity. A fresh weight fn per call (sleeves stateful)."""
    settings, storage = _bootstrap()
    from app.backtesting.basket_engine import BasketConfig, run_basket_backtest

    defaults = _strategy_defaults(interval)
    basket_raw = defaults.get("basket", {}) or {}
    reb_every = 5 if strategy.startswith("long_only") else int(basket_raw.get("rebalance_every", 1))
    config = BasketConfig(
        interval=interval, fit_window=int(basket_raw.get("fit_window", 300)),
        rebalance_every=reb_every, cost_bps=float(basket_raw.get("cost_bps", 5)),
        bars_per_year=_bars_per_year(universe, interval), fill="same_close", label="crisis")

    def build_fn():
        if strategy.startswith("long_only"):
            from app.backtesting.long_only_engine import _long_only_guard
            rc = _regime_cfg(regime, 0.0)
            fn, _ = _build_long_only(strategy, defaults, universe, interval, rc, reb_every)
            return _long_only_guard(fn, 0.20, 1.0)
        _, ens = _build_ensemble(None, defaults, False, universe, interval, 1.0, reb_every)
        return ens

    def run_fn(close, aux):
        return run_basket_backtest(close, build_fn(), config, aux=aux,
                                   open_=close).equity
    return run_fn, config


@app.command("crisis-test")
def crisis_test(
    strategy: str = typer.Option("long_only_xsec_momentum",
                                 help="long_only_* | ensemble (market-neutral)"),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
) -> None:
    """Run a strategy through synthetic crisis regimes (Phase 4, blocker #10).

    Injects momentum-crash / correlation-spike / vol-spike / gap / squeeze
    scenarios into the historical panel and reports the crisis-window outcome —
    the 2008/2020-style tail the 2021-2026 window never exercised."""
    settings, storage = _bootstrap()
    from app.backtesting.crisis import run_crisis_suite
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe

    prices = build_price_matrix(storage, get_universe(universe), interval, adjusted=True)
    run_fn, _ = _crisis_equity_runner(strategy, universe, interval)
    console.print(f"Crisis test: [bold]{strategy}[/bold] on {universe}...")
    table = run_crisis_suite(prices.close, run_fn, aux=prices.aux)
    console.print(table)
    base_dd = table.loc["base", "full_max_dd_pct"]
    worst = table["crisis_max_dd_pct"].astype(float).min()
    console.print(f"[bold]Worst crisis drawdown[/bold]: {worst}% (base full DD {base_dd}%)")
    out = settings.reports_dir / f"crisis_{strategy}_{universe}.md"
    out.write_text(f"# Crisis test — {strategy} ({universe}, {interval})\n\n"
                   f"{table.to_markdown()}\n\nWorst crisis DD: {worst}%\n", encoding="utf-8")
    console.print(f"[green]Report:[/green] {out}")


@app.command("crash-protection-backtest")
def crash_protection_backtest(
    strategy: str = typer.Option("long_only_xsec_momentum"),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
) -> None:
    """Compare a momentum book WITH vs WITHOUT crash protection (regime filter).

    Acceptance: protection becomes default only if it improves the crisis
    outcome WITHOUT destroying the normal-regime full-window return."""
    settings, storage = _bootstrap()
    import pandas as pd

    from app.backtesting.crisis import run_crisis_suite
    from app.data.market_data import build_price_matrix
    from app.data.universe import get_universe

    prices = build_price_matrix(storage, get_universe(universe), interval, adjusted=True)
    rows = []
    for label, regime in (("protection_off", False), ("protection_on", True)):
        run_fn, _ = _crisis_equity_runner(strategy, universe, interval, regime=regime)
        tbl = run_crisis_suite(prices.close, run_fn, aux=prices.aux)
        rows.append({"variant": label,
                     "normal_full_return_pct": tbl.loc["base", "full_return_pct"],
                     "momentum_crash_return_pct": tbl.loc["momentum_crash", "crisis_return_pct"],
                     "momentum_crash_dd_pct": tbl.loc["momentum_crash", "crisis_max_dd_pct"],
                     "vol_spike_dd_pct": tbl.loc["vol_spike", "crisis_max_dd_pct"]})
    df = pd.DataFrame(rows).set_index("variant")
    console.print(f"Crash protection — {strategy} ({universe})")
    console.print(df)
    on, off = df.loc["protection_on"], df.loc["protection_off"]
    helps = float(on["momentum_crash_dd_pct"]) > float(off["momentum_crash_dd_pct"])
    keeps = float(on["normal_full_return_pct"]) >= float(off["normal_full_return_pct"]) * 0.85
    verdict = ("[green]ADOPT[/green]" if helps and keeps
               else "[yellow]DO NOT default[/yellow]")
    console.print(f"protection improves crash DD: {helps} | preserves normal return: {keeps} "
                  f"-> {verdict}")
    out = settings.reports_dir / f"crash_protection_{strategy}_{universe}.md"
    out.write_text(f"# Crash protection — {strategy} ({universe})\n\n{df.to_markdown()}\n\n"
                   f"Adopt as default: {helps and keeps}\n", encoding="utf-8")
    console.print(f"[green]Report:[/green] {out}")


@app.command("crisis-report")
def crisis_report(
    strategy: str = typer.Option("long_only_xsec_momentum"),
    universe: str = typer.Option("us_stocks_50"),
    interval: str = typer.Option("1d"),
) -> None:
    """Crisis-test + crash-protection summary in one report."""
    crisis_test(strategy=strategy, universe=universe, interval=interval)
    crash_protection_backtest(strategy=strategy, universe=universe, interval=interval)


registry_app = typer.Typer(no_args_is_help=True, help="Alpha registry: list, promote, reject, retire.")
app.add_typer(registry_app, name="alpha-registry")


@registry_app.command("list")
def registry_list(status: str | None = typer.Option(None)) -> None:
    """All alphas with status, venues and last transition."""
    from app.research.alpha_registry import AlphaRegistry

    table = Table(title="Alpha registry")
    for col in ("id", "status", "asset class", "short?", "venues", "last transition"):
        table.add_column(col)
    for a in AlphaRegistry().list(status=status):
        last = a.history[-1] if a.history else {}
        color = {"rejected": "red", "retired": "dim",
                 "paper": "cyan"}.get(a.status, "yellow" if a.status in
                                      ("idea", "research") else "green")
        table.add_row(
            a.alpha_id, f"[{color}]{a.status}[/{color}]", a.asset_class,
            "yes" if a.requires_short else "no",
            ", ".join(a.executable_venues) or "[red]none[/red]",
            f"{last.get('ts', '')[:10]} {last.get('reason', '')[:60]}",
        )
    console.print(table)


@registry_app.command("show")
def registry_show(alpha_id: str = typer.Argument(...)) -> None:
    """Full record for one alpha, including promotion history."""
    from app.research.alpha_registry import AlphaRegistry, RegistryError

    try:
        a = AlphaRegistry().get(alpha_id)
    except RegistryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[bold]{a.name}[/bold]  (status: {a.status})")
    console.print(f"hypothesis: {a.hypothesis}")
    console.print(f"universe: {a.universe}  horizon: {a.horizon}  rebalance: {a.rebalance}")
    console.print(f"requires_short={a.requires_short} requires_leverage={a.requires_leverage} "
                  f"venues={a.executable_venues or 'NONE'}")
    if a.known_risks:
        console.print("known risks: " + "; ".join(a.known_risks))
    if a.experiment_ids:
        console.print(f"experiments: {', '.join(a.experiment_ids[-10:])}")
    table = Table(title="History")
    for col in ("ts", "from", "to", "by", "reason"):
        table.add_column(col)
    for h in a.history:
        table.add_row(str(h.get("ts", ""))[:19], str(h.get("from")), h.get("to", ""),
                      h.get("by", ""), h.get("reason", ""))
    console.print(table)


@registry_app.command("promote")
def registry_promote(
    alpha_id: str = typer.Argument(...),
    to: str = typer.Option(..., "--to"),
    reason: str = typer.Option("", help="required: cite experiment IDs"),
) -> None:
    """Promote one stage forward (live stages are blocked until governance gates exist)."""
    from app.research.alpha_registry import AlphaRegistry, RegistryError

    try:
        a = AlphaRegistry().promote(alpha_id, to, reason=reason)
        console.print(f"[green]{alpha_id} -> {a.status}[/green]")
    except RegistryError as exc:
        console.print(f"[red]REFUSED:[/red] {exc}")
        raise typer.Exit(1) from exc


@registry_app.command("reject")
def registry_reject(
    alpha_id: str = typer.Argument(...),
    reason: str = typer.Option(..., help="why this alpha is rejected"),
) -> None:
    """Reject an alpha (terminal; the record is kept on purpose)."""
    from app.research.alpha_registry import AlphaRegistry, RegistryError

    try:
        AlphaRegistry().reject(alpha_id, reason=reason)
        console.print(f"[red]{alpha_id} rejected[/red]: {reason}")
    except RegistryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@registry_app.command("retire")
def registry_retire(
    alpha_id: str = typer.Argument(...),
    reason: str = typer.Option(..., help="why this alpha is retired"),
) -> None:
    """Retire an alpha (terminal)."""
    from app.research.alpha_registry import AlphaRegistry, RegistryError

    try:
        AlphaRegistry().retire(alpha_id, reason=reason)
        console.print(f"[dim]{alpha_id} retired[/dim]: {reason}")
    except RegistryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@app.command("governance-report")
def governance_report(
    alpha_id: str = typer.Argument(...),
    to: str = typer.Option(..., "--to", help="the stage you want to promote into"),
) -> None:
    """Show the promotion-gate report for an alpha entering `to`.

    Evidence is read from the alpha's latest validate-ensemble report and data
    audit where available; missing evidence fails the gate that needs it (that
    is the point — unproven claims do not pass). This NEVER promotes; use
    `alpha-registry promote` (structural) once gates are green."""
    settings, storage = _bootstrap()
    from app.governance.gates import evaluate_gates
    from app.research.alpha_registry import AlphaRegistry, RegistryError

    try:
        alpha = AlphaRegistry().get(alpha_id)
    except RegistryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    evidence = _collect_governance_evidence(settings, storage, alpha)
    report = evaluate_gates(to, evidence, stage_from=alpha.status)
    console.print(f"[bold]Governance gates: {alpha_id} ({alpha.status} -> {to})[/bold]")
    for r in report.results:
        color = "green" if r.passed else ("red" if r.blocking else "yellow")
        console.print(f"  [{color}]{r.status}[/{color}] {r.name}: {r.detail}")
    verdict = "[green]APPROVED[/green]" if report.approved else "[red]BLOCKED[/red]"
    console.print(f"verdict: {verdict}")
    if not report.approved:
        console.print("[dim]Unproven gates fail by design — run validate-ensemble / "
                      "data-audit to generate the missing evidence.[/dim]")


def _collect_governance_evidence(settings, storage, alpha) -> dict:
    """Best-effort evidence assembly from recorded artifacts. Conservative:
    anything not found stays absent and its gate fails."""
    import re

    evidence: dict = {
        "executable_venues": alpha.executable_venues,
        "requires_short": alpha.requires_short,
        "requires_leverage": alpha.requires_leverage,
    }
    # data verdict from the latest data audit report for the alpha's universe
    audit_md = settings.reports_dir / f"data_audit_{alpha.universe}_1d.md"
    if audit_md.exists():
        text = audit_md.read_text(encoding="utf-8")
        m = re.search(r"verdict:\s*\*?\*?(\w+)", text, re.IGNORECASE)
        if m:
            evidence["data_verdict"] = m.group(1).lower()
    # validation summary, if a validate-ensemble report exists
    val_md = settings.reports_dir / f"validate_ensemble_{alpha.universe}_1d.md"
    if val_md.exists():
        text = val_md.read_text(encoding="utf-8")
        for key, pat in (("oos_sharpe", r"oos_sharpe_mean:\s*([-\d.]+)"),
                         ("oos_sharpe_degradation", r"sharpe_degradation:\s*([-\d.]+)"),
                         ("max_month_pct", r"max_month_pct:\s*([-\d.]+)")):
            m = re.search(pat, text)
            if m:
                evidence[key] = float(m.group(1))
        evidence["survives_costs_x2"] = "costs_x2" in text
    return evidence


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
