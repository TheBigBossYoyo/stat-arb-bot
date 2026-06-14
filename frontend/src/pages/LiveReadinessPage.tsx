import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { LiveReadiness } from "../lib/productTypes";
import { Card, Badge } from "../components/ui";
import DataTable from "../components/DataTable";
import { NotLiveBanner, PageTitle, Loader } from "../components/Banners";

export default function LiveReadinessPage() {
  const q = useQuery({ queryKey: ["live-readiness"], queryFn: () => apiGet<LiveReadiness>("/api/live-readiness") });
  return (
    <div className="space-y-4">
      <PageTitle title="Live Readiness Gate" subtitle="The gate that keeps real capital out until every condition is met." />
      <NotLiveBanner />
      <Loader data={q.data} error={q.error} isLoading={q.isLoading}>
        {(d) => (
          <>
            <Card title="Verdict">
              <div className="flex items-center gap-3">
                <Badge tone="red">LIVE ELIGIBLE: {String(d.live_eligible)}</Badge>
                <span className="text-sm text-zinc-300">{d.headline}</span>
              </div>
            </Card>
            <Card title="Per-product standing">
              <DataTable
                rows={d.products as unknown as Record<string, unknown>[]}
                csvName="live_readiness.csv"
                columns={[
                  { key: "product", label: "product" },
                  { key: "status", label: "status", render: (r) => <Badge tone={String(r.status) === "paper_candidate" ? "green" : "yellow"}>{String(r.status)}</Badge> },
                  { key: "eligible_label", label: "eligible", render: (r) => String(r.eligible_label) || "—" },
                  { key: "gates", label: "gates" },
                ]}
              />
            </Card>
          </>
        )}
      </Loader>
    </div>
  );
}
