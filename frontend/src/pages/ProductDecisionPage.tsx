import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { ProductDecision } from "../lib/productTypes";
import { Card, Badge } from "../components/ui";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import { NotLiveBanner, PageTitle, Loader } from "../components/Banners";

const statusTone: Record<string, string> = {
  paper_candidate: "green", testnet_candidate: "green",
  not_yet: "yellow", do_not_trade: "red", not_evaluated: "gray",
};

export default function ProductDecisionPage() {
  const q = useQuery({ queryKey: ["product-decision"], queryFn: () => apiGet<ProductDecision>("/api/product-decision") });
  return (
    <div className="space-y-4">
      <PageTitle title="Product Decision" subtitle="What (if anything) to trade — never live." />
      <NotLiveBanner />
      <Loader data={q.data} error={q.error} isLoading={q.isLoading}>
        {(d) => (
          <>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <MetricCard label="Recommended path" value={d.recommended}
                          tone="text-sky-300" />
              <MetricCard label="Capital stage" value={d.capital_stage} />
              <MetricCard label="Live eligible" value="false" tone="text-red-400" />
            </div>
            <Card title="Decision">
              <div className="text-sm text-zinc-200">{d.headline}</div>
              <div className="mt-2 text-sm text-zinc-400"><b>Next action:</b> {d.action}</div>
            </Card>
            <Card title="Product paths">
              <DataTable
                rows={d.products as unknown as Record<string, unknown>[]}
                csvName="product_decision.csv"
                searchKeys={["product", "status"]}
                columns={[
                  { key: "product", label: "product" },
                  { key: "venue", label: "venue", render: (r) => <span className="text-xs">{String(r.venue)}</span> },
                  { key: "shorting", label: "short?", render: (r) => (r.shorting ? "yes" : "no") },
                  { key: "leverage", label: "lev?", render: (r) => (r.leverage ? "yes" : "no") },
                  { key: "venue_wired", label: "venue wired", render: (r) => <Badge tone={r.venue_wired ? "green" : "red"}>{r.venue_wired ? "yes" : "no"}</Badge> },
                  { key: "gates", label: "gates", sortValue: (r) => Number(r.gates_passed), render: (r) => `${r.gates_passed}/${r.gates_total}` },
                  { key: "status", label: "status", render: (r) => <Badge tone={statusTone[String(r.status)] ?? "blue"}>{String(r.status)}</Badge> },
                  { key: "risk", label: "risk" },
                  { key: "live_eligible", label: "live", render: () => <Badge tone="red">no</Badge> },
                ]}
              />
            </Card>
          </>
        )}
      </Loader>
    </div>
  );
}
