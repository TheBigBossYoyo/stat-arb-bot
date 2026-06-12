import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { EquityPoint, PerformanceRow, PortfolioSummary, TradeInfo } from "../lib/types";
import { fmtMoney, fmtPct, fmtTs, pnlTone } from "../lib/formatters";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import { Card, statusTone, Badge } from "../components/ui";
import { EquityChart, ExposureChart, PnlBars } from "../components/charts";

export default function Portfolio() {
  const { data: summary } = useQuery({
    queryKey: ["summary"], queryFn: () => apiGet<PortfolioSummary>("/api/portfolio/summary"),
  });
  const { data: equity } = useQuery({
    queryKey: ["equity"], queryFn: () => apiGet<EquityPoint[]>("/api/portfolio/equity"),
  });
  const { data: trades } = useQuery({
    queryKey: ["trades"], queryFn: () => apiGet<TradeInfo[]>("/api/trades?limit=500"),
  });
  const { data: perf } = useQuery({
    queryKey: ["performance"],
    queryFn: () => apiGet<{ by_strategy: PerformanceRow[]; by_pair: PerformanceRow[] }>("/api/performance"),
  });

  const pnls = (trades ?? []).map((t) => t.pnl).reverse();

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <MetricCard label="Equity" value={fmtMoney(summary?.equity)} />
        <MetricCard label="Cash" value={fmtMoney(summary?.cash)} />
        <MetricCard label="Realized PnL" value={fmtMoney(summary?.realized_pnl)} tone={pnlTone(summary?.realized_pnl)} />
        <MetricCard label="Fees" value={fmtMoney(summary?.fees_paid)} />
        <MetricCard label="Max drawdown" value={fmtPct(summary?.max_drawdown_pct)} />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Equity">{equity?.length ? <EquityChart data={equity} /> : <Empty />}</Card>
        <Card title="Exposure (gross / net)">{equity?.length ? <ExposureChart data={equity} /> : <Empty />}</Card>
      </div>

      {pnls.length > 0 && (
        <Card title="Trade PnL sequence">
          <PnlBars values={pnls} />
        </Card>
      )}

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="PnL by strategy">
          <PerfTable rows={perf?.by_strategy ?? []} keyField="strategy" />
        </Card>
        <Card title="PnL by pair">
          <PerfTable rows={perf?.by_pair ?? []} keyField="pair_key" />
        </Card>
      </div>

      <Card title="Closed trades">
        <DataTable
          rows={(trades ?? []) as unknown as Record<string, unknown>[]}
          searchKeys={["pair_key", "strategy", "exit_reason"]}
          csvName="trades.csv"
          columns={[
            { key: "exit_ts", label: "closed", render: (r) => <span className="mono text-xs">{fmtTs(String(r.exit_ts))}</span> },
            { key: "strategy", label: "strategy" },
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

function PerfTable({ rows, keyField }: { rows: PerformanceRow[]; keyField: string }) {
  return (
    <DataTable
      rows={rows as unknown as Record<string, unknown>[]}
      emptyText="No closed trades yet"
      columns={[
        { key: keyField, label: keyField.replace("_", " ") },
        { key: "n_trades", label: "trades", align: "right" },
        { key: "total_pnl", label: "pnl", align: "right", render: (r) => <span className={pnlTone(Number(r.total_pnl))}>{fmtMoney(Number(r.total_pnl))}</span> },
        { key: "win_rate_pct", label: "win %", align: "right" },
        { key: "total_fees", label: "fees", align: "right", render: (r) => fmtMoney(Number(r.total_fees)) },
      ]}
    />
  );
}

const Empty = () => (
  <div className="py-10 text-center text-sm text-zinc-500">No data yet — run the paper trader.</div>
);
