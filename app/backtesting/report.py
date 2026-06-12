"""Markdown backtest report generator."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app.backtesting.engine import BacktestResult
from app.backtesting.walk_forward import WalkForwardResult


def _metrics_table(metrics: dict) -> str:
    lines = ["| metric | value |", "| --- | --- |"]
    for key, value in metrics.items():
        lines.append(f"| {key} | {value} |")
    return "\n".join(lines)


def render_markdown_report(
    result: BacktestResult,
    *,
    strategy_name: str,
    out_dir: Path,
    stress: pd.DataFrame | None = None,
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"backtest_{strategy_name}_{stamp}.md"

    eq = result.equity.dropna()
    lines: list[str] = []
    lines.append(f"# Backtest report — {strategy_name}")
    lines.append("")
    lines.append(f"Generated: {datetime.now(UTC).isoformat()} (UTC)")
    lines.append(f"Period: **{eq.index[0]} → {eq.index[-1]}**  |  interval: **{result.config.interval}**")
    lines.append("")
    lines.append("> ⚠️ Backtests are simulations. Past or simulated performance does not "
                 "predict real results. Costs, slippage and shorting assumptions below.")
    lines.append("")

    lines.append("## Configuration")
    cfg = result.config
    lines.append(
        f"- starting cash: {cfg.starting_cash}\n"
        f"- target % per pair: {cfg.target_pct_per_pair:.0%}\n"
        f"- commission: {cfg.commission_bps} bps | slippage: {cfg.slippage_bps} bps\n"
        f"- entry delay: {cfg.entry_delay_bars} bars | synthetic shorting: {cfg.allow_short}"
    )
    lines.append("")

    lines.append("## Pairs traded")
    lines.append("| pair | beta | EG p | ADF p | half-life (bars) | corr | score |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for p in result.pairs:
        lines.append(
            f"| {p.key} | {p.beta:.3f} | {p.eg_pvalue:.4f} | {p.adf_pvalue:.4f} "
            f"| {p.half_life:.1f} | {p.correlation:.2f} | {p.score:.2f} |"
        )
    lines.append("")

    lines.append("## Performance")
    lines.append(_metrics_table(result.metrics))
    lines.append("")

    trades_df = result.trades_df
    if not trades_df.empty:
        lines.append("## Per-pair breakdown")
        grouped = trades_df.groupby("pair_key").agg(
            n=("pnl", "size"), pnl=("pnl", "sum"), avg_pnl=("pnl", "mean"),
            win_rate=("pnl", lambda s: 100.0 * (s > 0).mean()),
            avg_holding_bars=("holding_bars", "mean"), fees=("fees", "sum"),
        ).round(3)
        lines.append(grouped.to_markdown())
        lines.append("")

        lines.append("## Best / worst trades")
        cols = ["pair_key", "direction", "entry_ts", "exit_ts", "holding_bars",
                "entry_z", "exit_z", "pnl", "exit_reason"]
        best = trades_df.nlargest(5, "pnl")[cols]
        worst = trades_df.nsmallest(5, "pnl")[cols]
        lines.append("**Best 5**\n")
        lines.append(best.to_markdown(index=False))
        lines.append("\n**Worst 5**\n")
        lines.append(worst.to_markdown(index=False))
        lines.append("")

        lines.append("## Exit reasons")
        lines.append(trades_df["exit_reason"].value_counts().to_markdown())
        lines.append("")

    if stress is not None and not stress.empty:
        lines.append("## Stress scenarios")
        lines.append(stress.to_markdown())
        lines.append("")

    if result.kill_events:
        lines.append("## Risk events (kill switch triggers)")
        for event in result.kill_events[:20]:
            lines.append(f"- {event['ts']}: {'; '.join(event['triggers'])}")
        lines.append("")

    lines.append("## Warnings & caveats")
    for w in result.warnings:
        lines.append(f"- {w}")
    lines.append("- Lookahead protection: signals at bar close, fills at next bar open.")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def render_walk_forward_report(
    wf: WalkForwardResult, *, strategy_name: str, out_dir: Path
) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"walkforward_{strategy_name}_{stamp}.md"

    lines = [f"# Walk-forward report — {strategy_name}", ""]
    lines.append("## Summary")
    lines.append(_metrics_table(wf.summary))
    lines.append("")
    lines.append("## Windows")
    lines.append("| # | train | test | pairs | IS sharpe | OOS sharpe | IS ret % | OOS ret % |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for w in wf.windows:
        lines.append(
            f"| {w.window_id} | {w.train_start:%Y-%m-%d}→{w.train_end:%Y-%m-%d} "
            f"| {w.test_start:%Y-%m-%d}→{w.test_end:%Y-%m-%d} | {len(w.pairs)} "
            f"| {w.is_metrics.get('sharpe')} | {w.oos_metrics.get('sharpe')} "
            f"| {w.is_metrics.get('total_return_pct')} | {w.oos_metrics.get('total_return_pct')} |"
        )
    lines.append("")
    lines.append("A strategy that looks good in-sample but degrades sharply out-of-sample "
                 "is overfit — do not trade it.")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
