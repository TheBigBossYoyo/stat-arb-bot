import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { EquityPoint, PortfolioSummary, SignalInfo, SystemStatus, TradeInfo } from "../lib/types";
import { useChannel } from "../lib/ws";
import { fmtMoney, fmtPct, fmtTs, pnlTone } from "../lib/formatters";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import { Badge, Card, Skeleton, statusTone } from "../components/ui";
import { DrawdownChart, EquityChart } from "../components/charts";

export default function Dashboard() {
  const { data: polledSummary } = useQuery({
    queryKey: ["summary"], queryFn: () => apiGet<PortfolioSummary>("/api/portfolio/summary"),
  });
  const liveSummary = useChannel<PortfolioSummary>("portfolio");
  const summary = liveSummary ?? polledSummary;

  const { data: status } = useQuery({
    queryKey: ["status"], queryFn: () => apiGet<SystemStatus>("/api/status"),
  });
  const { data: equity } = useQuery({
    queryKey: ["equity"], queryFn: () => apiGet<EquityPoint[]>("/api/portfolio/equity"),
  });
  const { data: signals } = useQuery({
    queryKey: ["signals"], queryFn: () => apiGet<SignalInfo[]>("/api/signals?limit=8"),
  });
  const { data: trades } = useQuery({
    queryKey: ["trades-recent"], queryFn: () => apiGet<TradeInfo[]>("/api/trades?limit=8"),
  });

  if (!summary) return <Skeleton className="h-40" />;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8">
        <MetricCard label="Equity (paper)" value={fmtMoney(summary.equity)} sub={fmtTs(summary.as_of)} />
        <MetricCard label="Daily PnL" value={fmtMoney(summary.daily_pnl)} tone={pnlTone(summary.daily_pnl)} />
        <MetricCard label="Total PnL" value={fmtMoney(summary.total_pnl)} tone={pnlTone(summary.total_pnl)} />
        <MetricCard label="Realized PnL" value={fmtMoney(summary.realized_pnl)} tone={pnlTone(summary.realized_pnl)} />
        <MetricCard label="Gross / Net" value={`${fmtMoney(summary.gross_exposure, 0)} / ${fmtMoney(summary.net_exposure, 0)}`} />
        <MetricCard label="Open pairs" value={summary.open_pairs} />
        <MetricCard label="Drawdown" value={fmtPct(summary.current_drawdown_pct)} sub={`max ${fmtPct(summary.max_drawdown_pct)}`}
                    tone={summary.current_drawdown_pct > 2 ? "text-red-400" : ""} />
        <MetricCard label="Fees paid" value={fmtMoney(summary.fees_paid)} sub={`${summary.n_trades} trades`} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Equity curve (paper)" className="xl:col-span-2">
          {equity && equity.length > 1 ? (
            <EquityChart data={equity} />
          ) : (
            <div className="py-12 text-center text-sm text-zinc-500">
              No equity snapshots yet — start paper trading:
              <div className="mono mt-1 text-xs">statarb paper-trade --broker binance --strategy cointegration_pairs</div>
            </div>
          )}
        </Card>
        <Card title="Brokers">
          <div className="space-y-2">
            {status?.brokers.map((b) => (
              <div key={b.broker} className="flex items-center justify-between rounded-lg border border-zinc-800 px-3 py-2">
                <div>
                  <div className="text-sm text-zinc-200">{b.display_name}</div>
                  <div className="text-xs text-zinc-500">{b.mode} · keys {b.key_configured ? "configured" : "not set"}</div>
                </div>
                <Badge tone={b.enabled ? "green" : "gray"}>{b.enabled ? "enabled" : "disabled"}</Badge>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {equity && equity.length > 1 && (
        <Card title="Drawdown">
          <DrawdownChart data={equity} />
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Recent signals">
          <DataTable
            rows={(signals ?? []) as unknown as Record<string, unknown>[]}
            emptyText="No signals recorded yet"
            columns={[
              { key: "ts", label: "time", render: (r) => <span className="mono text-xs">{fmtTs(String(r.ts))}</span> },
              { key: "pair_key", label: "pair" },
              { key: "action", label: "action", render: (r) => <Badge tone={String(r.action).startsWith("enter") ? "blue" : "yellow"}>{String(r.action)}</Badge> },
              { key: "z_score", label: "z", align: "right", render: (r) => Number(r.z_score).toFixed(2) },
              { key: "accepted", label: "risk", render: (r) => <Badge tone={r.accepted ? "green" : "red"}>{r.accepted ? "accepted" : "rejected"}</Badge> },
            ]}
          />
        </Card>
        <Card title="Recent trades">
          <DataTable
            rows={(trades ?? []) as unknown as Record<string, unknown>[]}
            emptyText="No closed trades yet"
            columns={[
              { key: "exit_ts", label: "closed", render: (r) => <span className="mono text-xs">{fmtTs(String(r.exit_ts))}</span> },
              { key: "pair_key", label: "pair" },
              { key: "direction", label: "dir" },
              { key: "pnl", label: "pnl", align: "right", render: (r) => <span className={pnlTone(Number(r.pnl))}>{fmtMoney(Number(r.pnl))}</span> },
              { key: "exit_reason", label: "exit", render: (r) => <Badge tone={statusTone(String(r.exit_reason))}>{String(r.exit_reason)}</Badge> },
            ]}
          />
        </Card>
      </div>
    </div>
  );
}
