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
                    alloc_mode: str | None = None):
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
            alloc_mode=str(ens_raw.get("alloc_mode", "inverse_vol")),
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
