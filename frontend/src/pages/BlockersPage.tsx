import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { Blockers } from "../lib/productTypes";
import { Card, Badge } from "../components/ui";
import DataTable from "../components/DataTable";
import { NotLiveBanner, PageTitle, Loader } from "../components/Banners";

export default function BlockersPage() {
  const q = useQuery({ queryKey: ["blockers"], queryFn: () => apiGet<Blockers>("/api/blockers") });
  return (
    <div className="space-y-4">
      <PageTitle title="Current Blockers" subtitle="What stands between today and a live conversation." />
      <NotLiveBanner />
      <Loader data={q.data} error={q.error} isLoading={q.isLoading}>
        {(d) => (
          <>
            <Card title="Global blockers" right={<Badge tone="yellow">{d.global.length}</Badge>}>
              <ul className="space-y-1.5 text-sm text-zinc-300">
                {d.global.map((b, i) => (
                  <li key={i} className="flex gap-2"><span className="text-amber-400">•</span>{b}</li>
                ))}
              </ul>
            </Card>
            <Card title="Per-product missing gates">
              <DataTable
                rows={d.per_product as unknown as Record<string, unknown>[]}
                csvName="blockers.csv"
                searchKeys={["product", "blocker"]}
                emptyText="No per-product blockers recorded"
                columns={[
                  { key: "product", label: "product", render: (r) => <Badge tone="blue">{String(r.product)}</Badge> },
                  { key: "blocker", label: "blocker" },
                ]}
              />
            </Card>
          </>
        )}
      </Loader>
    </div>
  );
}
