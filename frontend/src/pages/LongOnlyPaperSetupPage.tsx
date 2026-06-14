import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { ProductDecision, Trading212Config } from "../lib/productTypes";
import { Card, Badge } from "../components/ui";
import MetricCard from "../components/MetricCard";
import { NotLiveBanner, DemoOnlyBanner, PageTitle, Loader } from "../components/Banners";

export default function LongOnlyPaperSetupPage() {
  const dec = useQuery({ queryKey: ["product-decision"], queryFn: () => apiGet<ProductDecision>("/api/product-decision") });
  const cfg = useQuery({ queryKey: ["t212-config"], queryFn: () => apiGet<Trading212Config>("/api/trading212-config") });

  return (
    <div className="space-y-4">
      <PageTitle title="Long-only T212 Paper Setup" subtitle="Eligibility, broker config, and how to begin a supervised paper period." />
      <NotLiveBanner />
      <DemoOnlyBanner />

      <Loader data={dec.data} error={dec.error} isLoading={dec.isLoading}>
        {(d) => {
          const lo = d.products.find((p) => p.product === "long_only_equity");
          const eligible = lo?.status === "paper_candidate";
          return (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
              <MetricCard label="Readiness gates" value={lo ? `${lo.gates_passed}/${lo.gates_total}` : "—"} />
              <MetricCard label="Paper eligibility"
                          value={eligible ? "ELIGIBLE TO BEGIN" : "not yet"}
                          tone={eligible ? "text-emerald-400" : "text-amber-400"} />
              <MetricCard label="Live eligible" value="false" tone="text-red-400" />
            </div>
          );
        }}
      </Loader>

      <Card title="Broker configuration (booleans only — no secrets)">
        <Loader data={cfg.data} error={cfg.error} isLoading={cfg.isLoading}>
          {(c) => (
            <div className="flex flex-wrap gap-2">
              <Badge tone={c.enabled ? "green" : "gray"}>TRADING212_ENABLED: {String(c.enabled)}</Badge>
              <Badge tone={c.mode === "demo" ? "green" : "red"}>MODE: {c.mode}</Badge>
              <Badge tone={c.api_key_configured ? "green" : "gray"}>API key: {c.api_key_configured ? "set" : "not set"}</Badge>
              <Badge tone={c.allow_demo_orders ? "green" : "gray"}>ALLOW_DEMO_ORDERS: {String(c.allow_demo_orders)}</Badge>
              <Badge tone="red">live: hard-blocked</Badge>
            </div>
          )}
        </Loader>
      </Card>

      <Card title="How to begin the supervised period">
        <ol className="list-decimal space-y-1.5 pl-5 text-sm text-zinc-300">
          <li>(optional) configure Trading 212 <b>demo</b> keys, then <code className="mono">statarb trading212-check --mode demo</code></li>
          <li>preview orders: <code className="mono">statarb long-only-order-preview --mode demo_preview</code></li>
          <li>start the period (run daily — a cron, not a loop): <code className="mono">statarb supervised-paper-start --product long_only_t212 --mode shadow</code></li>
          <li>after ≥30 forward days: <code className="mono">statarb supervised-paper-final-report --min-days 30</code></li>
        </ol>
        <p className="mt-3 text-xs text-zinc-600">
          Replayed bars validate the pipeline but never count as forward calendar days.
          See <code className="mono">docs/long_only_t212_paper_plan.md</code>.
        </p>
      </Card>
    </div>
  );
}
