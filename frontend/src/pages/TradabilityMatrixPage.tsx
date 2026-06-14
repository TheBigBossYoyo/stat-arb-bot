import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { TradabilityMatrix } from "../lib/productTypes";
import { Card, Badge } from "../components/ui";
import DataTable from "../components/DataTable";
import { NotLiveBanner, PageTitle, Loader } from "../components/Banners";

export default function TradabilityMatrixPage() {
  const q = useQuery({ queryKey: ["tradability"], queryFn: () => apiGet<TradabilityMatrix>("/api/tradability-matrix") });
  return (
    <div className="space-y-4">
      <PageTitle title="Tradability Matrix" subtitle="Per-product venue + gate status. The binding column is 'live eligible' — every row is no." />
      <NotLiveBanner />
      <Loader data={q.data} error={q.error} isLoading={q.isLoading}>
        {(d) => (
          <Card title="Products">
            <DataTable
              rows={d.rows as unknown as Record<string, unknown>[]}
              csvName="tradability_matrix.csv"
              searchKeys={["product", "venue"]}
              columns={[
                { key: "product", label: "product" },
                { key: "asset_class", label: "asset class" },
                { key: "shorting", label: "needs short", render: (r) => (r.shorting ? <Badge tone="yellow">yes</Badge> : "no") },
                { key: "leverage", label: "needs lev", render: (r) => (r.leverage ? <Badge tone="yellow">yes</Badge> : "no") },
                { key: "venue_wired", label: "venue wired", render: (r) => <Badge tone={r.venue_wired ? "green" : "red"}>{r.venue_wired ? "yes" : "no"}</Badge> },
                { key: "gates", label: "gates", sortValue: (r) => Number(r.gates_passed), render: (r) => `${r.gates_passed}/${r.gates_total}` },
                { key: "eligible_label", label: "eligible", render: (r) => <Badge tone={String(r.eligible_label) === "PAPER" ? "green" : "gray"}>{String(r.eligible_label) || "—"}</Badge> },
                { key: "risk", label: "risk" },
                { key: "live", label: "live eligible", render: () => <Badge tone="red">no</Badge> },
              ]}
            />
            <p className="mt-3 text-xs text-zinc-600">live_eligible_any: {String(d.live_eligible_any)} — always false by design.</p>
          </Card>
        )}
      </Loader>
    </div>
  );
}
