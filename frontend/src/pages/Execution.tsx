import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { OrderInfo, SignalInfo } from "../lib/types";
import { fmtMoney, fmtTs } from "../lib/formatters";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import { Badge, Card, statusTone } from "../components/ui";

export default function Execution() {
  const { data: orders } = useQuery({
    queryKey: ["orders"], queryFn: () => apiGet<OrderInfo[]>("/api/orders?limit=500"),
  });
  const { data: signals } = useQuery({
    queryKey: ["signals-all"], queryFn: () => apiGet<SignalInfo[]>("/api/signals?limit=300"),
  });

  const all = orders ?? [];
  const filled = all.filter((o) => o.status === "filled").length;
  const rejected = all.filter((o) => o.status.includes("rejected")).length;
  const rejectedSignals = (signals ?? []).filter((s) => !s.accepted).length;
  const avgSlippage = "5.0 bps (model)";

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <MetricCard label="Orders recorded" value={all.length} />
        <MetricCard label="Filled" value={filled} tone="text-emerald-400" />
        <MetricCard label="Rejected" value={rejected} tone={rejected ? "text-red-400" : ""} />
        <MetricCard label="Signals risk-rejected" value={rejectedSignals} />
        <MetricCard label="Slippage assumption" value={avgSlippage} sub="paper fills: close ± slippage" />
      </div>

      <Card title="Orders">
        <DataTable
          rows={all as unknown as Record<string, unknown>[]}
          searchKeys={["symbol", "pair_key", "status", "strategy", "broker"]}
          csvName="orders.csv"
          columns={[
            { key: "ts", label: "time", render: (r) => <span className="mono text-xs">{fmtTs(String(r.ts))}</span> },
            { key: "broker", label: "broker" },
            { key: "symbol", label: "symbol" },
            { key: "side", label: "side", render: (r) => <Badge tone={r.side === "buy" ? "green" : "red"}>{String(r.side)}</Badge> },
            { key: "order_type", label: "type" },
            { key: "quantity", label: "qty", align: "right", render: (r) => Number(r.quantity).toPrecision(5) },
            { key: "fill_price", label: "fill", align: "right", render: (r) => fmtMoney(Number(r.fill_price)) },
            { key: "notional", label: "notional", align: "right", render: (r) => fmtMoney(Number(r.notional)) },
            { key: "fee", label: "fee", align: "right", render: (r) => fmtMoney(Number(r.fee), 4) },
            { key: "status", label: "status", render: (r) => <Badge tone={statusTone(String(r.status))}>{String(r.status)}</Badge> },
            { key: "pair_key", label: "pair" },
          ]}
        />
      </Card>

      <Card title="Signal decisions (why orders did or didn't happen)">
        <DataTable
          rows={(signals ?? []) as unknown as Record<string, unknown>[]}
          searchKeys={["pair_key", "action", "strategy", "reject_reason"]}
          csvName="signals.csv"
          columns={[
            { key: "ts", label: "time", render: (r) => <span className="mono text-xs">{fmtTs(String(r.ts))}</span> },
            { key: "strategy", label: "strategy" },
            { key: "pair_key", label: "pair" },
            { key: "action", label: "action" },
            { key: "z_score", label: "z", align: "right", render: (r) => Number(r.z_score).toFixed(2) },
            { key: "hedge_ratio", label: "beta", align: "right", render: (r) => Number(r.hedge_ratio).toFixed(3) },
            { key: "accepted", label: "risk", render: (r) => <Badge tone={r.accepted ? "green" : "red"}>{r.accepted ? "accepted" : "rejected"}</Badge> },
            { key: "reject_reason", label: "reason", render: (r) => <span className="text-xs text-zinc-400">{String(r.reject_reason).slice(0, 60)}</span> },
          ]}
        />
      </Card>
    </div>
  );
}
