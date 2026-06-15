import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { ProductDecision } from "../lib/productTypes";
import type { CapabilitiesResp } from "../lib/actionTypes";
import { useAction } from "../lib/useAction";
import { Card, Badge, Button, PageHeader, StatusBadge } from "../components/ui";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import JobProgress from "../components/JobProgress";
import { Icons } from "../components/icons";
import { NotLiveBanner, Loader } from "../components/Banners";

export default function ProductDecisionPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["product-decision"], queryFn: () => apiGet<ProductDecision>("/api/product-decision") });
  const caps = useQuery({ queryKey: ["capabilities"], queryFn: () => apiGet<CapabilitiesResp>("/api/dashboard/capabilities") });
  const rerun = useAction("/api/product-decision/run", {
    onDone: () => qc.invalidateQueries({ queryKey: ["product-decision"] }),
  });
  const controls = caps.data?.controls_enabled ?? false;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Product Decision"
        description="What (if anything) to trade, the recommended next action, and the capital stage. Every path is non-live by construction."
        badges={<Badge tone="red" dot>NOT LIVE ELIGIBLE</Badge>}
        actions={
          <Button tone="primary" icon={<Icons.refresh size={15} />}
            disabled={rerun.busy} onClick={() => rerun.run({ reason: "operator dashboard" })}>
            Rerun product decision
          </Button>
        }
      />

      {rerun.job && <JobProgress job={rerun.job} />}

      <Loader data={q.data} error={q.error} isLoading={q.isLoading}>
        {(d) => {
          const lead = d.products.find((p) => p.product === d.recommended)
            ?? d.products.find((p) => p.status === "paper_candidate");
          const actionsAllowed = controls && lead?.status === "paper_candidate";
          return (
            <>
              <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
                <MetricCard label="Recommended path" value={d.recommended} tone="text-sky-300" accent="info" />
                <MetricCard label="Capital stage" value={d.capital_stage} />
                <MetricCard label="Lead product status"
                  value={<StatusBadge status={lead?.status ?? "not_evaluated"} />}
                  accent={lead?.status === "paper_candidate" ? "ok" : "warn"} />
                <MetricCard label="Live eligible" value="false" tone="text-red-400" accent="danger" />
              </div>

              <Card title="Decision" icon={<Icons.target size={15} />}>
                <div className="text-sm text-zinc-200">{d.headline}</div>
                <div className="mt-2 text-sm text-zinc-400"><b>Next action:</b> {d.action}</div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <Badge tone={actionsAllowed ? "green" : "yellow"} dot={actionsAllowed}>
                    dashboard actions: {actionsAllowed ? "allowed" : controls ? "product-gated" : "read-only"}
                  </Badge>
                  <span className="text-xs text-zinc-500">
                    {actionsAllowed
                      ? "Paper/demo session actions can run (subject to per-action gates)."
                      : controls
                        ? "Session actions are refused until the lead product is paper_candidate."
                        : "Set DASHBOARD_CONTROLS_ENABLED=true to enable controls."}
                  </span>
                </div>
              </Card>

              <Card title="Product paths" icon={<Icons.layers size={15} />}>
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
                    { key: "status", label: "status", render: (r) => <StatusBadge status={String(r.status)} /> },
                    { key: "risk", label: "risk" },
                    { key: "live_eligible", label: "live", render: () => <Badge tone="red">no</Badge> },
                  ]}
                />
              </Card>

              <NotLiveBanner />
            </>
          );
        }}
      </Loader>
    </div>
  );
}
