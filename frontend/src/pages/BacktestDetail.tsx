import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { BacktestDetail as Detail } from "../lib/types";
import { fmtMoney, fmtTs, pnlTone } from "../lib/formatters";
import DataTable from "../components/DataTable";
import { Badge, Card, Skeleton, statusTone } from "../components/ui";
import { DrawdownChart, EquityChart, PnlBars } from "../components/charts";

export default function BacktestDetail() {
  const { id } = useParams();
  const { data: detail, error } = useQuery({
    queryKey: ["backtest", id],
    queryFn: () => apiGet<Detail>(`/api/backtests/${id}`),
  });

  if (error) return <div className="text-red-400">{String(error)}</div>;
  if (!detail) return <Skeleton className="h-60" />;

  const equity = detail.equity.map(([ts, value]) => ({ ts, equity: value }));
  const trades = detail.trades as { pnl?: number }[];
  const pnls = trades.map((t) => Number(t.pnl ?? 0));
  const warnings = qualityWarnings(detail, pnls);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold">Backtest #{detail.id} — <span className="mono">{detail.strategy}</span></h1>
        <Badge tone="blue">{detail.interval}</Badge>
        <span className="text-xs text-zinc-500 mono">
          {fmtTs(detail.start_ts).slice(0, 10)} → {fmtTs(detail.end_ts).slice(0, 10)}
        </span>
      </div>

      <Card title="Quality warnings (read before believing the numbers)">
        {warnings.length ? (
          <ul className="space-y-1.5">
            {warnings.map((w, i) => (
              <li key={i} className={`text-sm ${w.level === "red" ? "text-red-300" : "text-amber-300"}`}>
                {w.level === "red" ? "✗" : "⚠"} {w.text}
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-sm text-emerald-400">No automatic quality flags raised — still verify with walk-forward + stress.</div>
        )}
        <p className="mt-3 text-xs text-zinc-600">
          Structural protections: signals at bar close fill at next bar open (no lookahead);
          commission + slippage charged on every leg. Survivorship bias possible — the
          universe was selected with today's knowledge.
        </p>
      </Card>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
        {Object.entries(detail.metrics).map(([key, value]) => (
          <div key={key} className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">{key}</div>
            <div className="mono text-sm text-zinc-200">{value === null ? "—" : String(value)}</div>
          </div>
        ))}
      </div>

      {equity.length > 1 && (
        <div className="grid gap-4 xl:grid-cols-2">
          <Card title="Equity">{<EquityChart data={equity} />}</Card>
          <Card title="Drawdown">{<DrawdownChart data={equity} />}</Card>
        </div>
      )}

      {pnls.length > 0 && (
        <Card title="Trade PnL sequence"><PnlBars values={pnls} /></Card>
      )}

      <Card title={`Trades (${trades.length})`}>
        <DataTable
          rows={detail.trades as Record<string, unknown>[]}
          searchKeys={["pair_key", "direction", "exit_reason"]}
          csvName={`backtest_${detail.id}_trades.csv`}
          columns={[
            { key: "entry_ts", label: "entry", render: (r) => <span className="mono text-xs">{fmtTs(String(r.entry_ts))}</span> },
            { key: "exit_ts", label: "exit", render: (r) => <span className="mono text-xs">{fmtTs(String(r.exit_ts))}</span> },
            { key: "pair_key", label: "pair" },
            { key: "direction", label: "dir" },
            { key: "holding_bars", label: "bars", align: "right" },
            { key: "entry_z", label: "entry z", align: "right", render: (r) => Number(r.entry_z).toFixed(2) },
            { key: "pnl", label: "pnl", align: "right", render: (r) => <span className={pnlTone(Number(r.pnl))}>{fmtMoney(Number(r.pnl))}</span> },
            { key: "fees", label: "fees", align: "right", render: (r) => fmtMoney(Number(r.fees)) },
            { key: "exit_reason", label: "exit", render: (r) => <Badge tone={statusTone(String(r.exit_reason))}>{String(r.exit_reason)}</Badge> },
          ]}
        />
      </Card>
    </div>
  );
}

function qualityWarnings(detail: Detail, pnls: number[]): { level: "red" | "amber"; text: string }[] {
  const out: { level: "red" | "amber"; text: string }[] = [];
  const m = detail.metrics as Record<string, number | null>;
  const nTrades = Number(m.n_trades ?? 0);
  if (nTrades < 20) out.push({ level: "amber", text: `Only ${nTrades} trades — results are statistically fragile.` });
  const totalPnl = pnls.reduce((a, b) => a + b, 0);
  const best = Math.max(0, ...pnls);
  if (nTrades > 0 && totalPnl > 0 && best > 0.5 * totalPnl)
    out.push({ level: "amber", text: "More than half the profit comes from a single trade." });
  if (Number(m.max_drawdown_pct ?? 0) < -5)
    out.push({ level: "red", text: `Max drawdown ${m.max_drawdown_pct}% exceeds the 5% global limit — live trading would have been killed.` });
  if (Number(m.turnover ?? 0) > 10)
    out.push({ level: "amber", text: `Turnover ${m.turnover}x — high fee sensitivity; rerun the stress suite with 2x fees.` });
  const fees = Number(m.total_fees ?? 0);
  if (totalPnl !== 0 && fees > Math.abs(totalPnl))
    out.push({ level: "amber", text: "Fees exceed |net PnL| — the edge may not survive real costs." });
  if (Number(m.total_return_pct ?? 0) <= 0)
    out.push({ level: "red", text: "Strategy lost money in this configuration. Do not paper/live trade it." });
  return out;
}
