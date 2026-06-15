import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { ProductDecision } from "../lib/productTypes";
import type { CapabilitiesResp } from "../lib/actionTypes";
import { useAction } from "../lib/useAction";
import { Card, Badge, Button, PageHeader, EmptyState, StatusBadge } from "../components/ui";
import MetricCard from "../components/MetricCard";
import JobProgress from "../components/JobProgress";
import { Icons } from "../components/icons";
import { NotLiveBanner, Loader } from "../components/Banners";

const READINESS_STRATEGY = "long_only_ensemble";

export default function ReadinessPage() {
  const decision = useQuery({
    queryKey: ["product-decision"],
    queryFn: () => apiGet<ProductDecision>("/api/product-decision"),
  });
  const caps = useQuery({
    queryKey: ["capabilities"],
    queryFn: () => apiGet<CapabilitiesResp>("/api/dashboard/capabilities"),
  });
  const rerun = useAction("/api/long-only/readiness/run", {
    onDone: () => decision.refetch(),
  });

  const res = rerun.job?.status === "succeeded" ? rerun.job.result : undefined;
  const controls = caps.data?.controls_enabled ?? false;

  return (
    <div className="space-y-5">
      <PageHeader
        title="Long-only Readiness"
        description="The paper-readiness battery for long-only Trading 212 and its gate scorecard. Passing every gate makes the product a paper candidate — it never makes it live-eligible."
        badges={<Badge tone="red" dot>NOT LIVE ELIGIBLE</Badge>}
        actions={
          <Button tone="primary" icon={<Icons.refresh size={15} />}
            disabled={rerun.busy || !controls}
            title={!controls ? "controls are read-only" : "runs the full readiness battery (can take minutes)"}
            onClick={() => rerun.run({ params: { strategy: READINESS_STRATEGY, universe: "us_stocks_50", full: true }, reason: "operator dashboard" })}>
            Rerun long-only readiness
          </Button>
        }
      />

      <Loader data={decision.data} error={decision.error} isLoading={decision.isLoading}>
        {(d) => {
          const p = d.products.find((x) => x.product === "long_only_t212")
            ?? d.products.find((x) => x.product.includes("long_only"));
          const gatesAll = !!p && p.gates_passed === p.gates_total;
          return (
            <>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <MetricCard label="Readiness gates"
                  value={p ? `${p.gates_passed} / ${p.gates_total}` : "—"}
                  accent={gatesAll ? "ok" : "warn"}
                  sub={gatesAll ? "all gates passed" : "gates outstanding"} />
                <MetricCard label="Paper candidate"
                  value={<StatusBadge status={p?.status ?? "not_evaluated"} />}
                  accent={p?.status === "paper_candidate" ? "ok" : "warn"} />
                <MetricCard label="Risk level" value={p?.risk ?? "—"} />
                <MetricCard label="Dashboard actions"
                  value={<Badge tone={controls && p?.status === "paper_candidate" ? "green" : "yellow"}>
                    {controls ? (p?.status === "paper_candidate" ? "allowed" : "product-gated") : "read-only"}
                  </Badge>} accent="muted" />
              </div>

              <Card title="Paper-candidate verdict" icon={<Icons.check size={15} />}>
                <div className="text-sm text-zinc-200">{d.headline}</div>
                <div className="mt-1 text-sm text-zinc-400"><b>Next action:</b> {d.action}</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <StatusBadge status={p?.status ?? "not_evaluated"} />
                  <Badge tone="gray">capital: {d.capital_stage}</Badge>
                  <Badge tone="red">live eligible: false</Badge>
                </div>
              </Card>

              <div className="grid gap-4 md:grid-cols-2">
                <Card title="Outstanding gates" icon={<Icons.alert size={15} />}>
                  {p && p.missing.length > 0 ? (
                    <ul className="space-y-1.5 text-sm">
                      {p.missing.map((m) => (
                        <li key={m} className="flex items-start gap-2">
                          <Badge tone="yellow">missing</Badge>
                          <span className="text-zinc-300">{m}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <EmptyState icon={<Icons.check size={28} />} text="No outstanding readiness gates" />
                  )}
                </Card>
                <Card title="Notes" icon={<Icons.book size={15} />}>
                  {p && p.notes.length > 0 ? (
                    <ul className="space-y-1.5 text-sm text-zinc-400">
                      {p.notes.map((n) => <li key={n}>• {n}</li>)}
                    </ul>
                  ) : <EmptyState text="No notes" />}
                </Card>
              </div>
            </>
          );
        }}
      </Loader>

      <Card title="Readiness battery" subtitle="Reruns the full long-only readiness command and writes PAPER_ELIGIBILITY_REPORT.md"
        right={<Link to="/reports" className="text-xs text-sky-400 hover:underline">view latest report →</Link>}>
        {rerun.job ? <JobProgress job={rerun.job} /> : (
          <EmptyState text="Battery not run this session"
            hint={controls ? "click “Rerun long-only readiness”" : "read-only — set DASHBOARD_CONTROLS_ENABLED=true"} />
        )}
        {res && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
            <Badge tone={res.passed ? "green" : "red"}>{res.passed ? "PASSED" : `exit ${String(res.exit_code)}`}</Badge>
            {res.report_path != null && <Badge tone="gray">report written</Badge>}
            <Badge tone="red">live eligible: false</Badge>
          </div>
        )}
      </Card>

      <NotLiveBanner />
    </div>
  );
}
