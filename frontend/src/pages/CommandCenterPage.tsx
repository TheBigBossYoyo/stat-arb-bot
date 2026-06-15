import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { DashboardSummary } from "../lib/actionTypes";
import type { ProductDecision, PaperFinal } from "../lib/productTypes";
import { Card, Badge, StatusBadge, EmptyState, PageHeader } from "../components/ui";
import MetricCard from "../components/MetricCard";
import ActionCard from "../components/ActionCard";
import { ChartCard, EquityChart } from "../components/charts";
import { Icons } from "../components/icons";
import { NotLiveBanner, Loader } from "../components/Banners";
import { computeTodaysAction } from "../lib/todaysAction";
import { fmtPct, fmtTs } from "../lib/formatters";

const PRODUCT = "long_only_t212";

export default function CommandCenterPage() {
  const q = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => apiGet<DashboardSummary>("/api/dashboard/summary"),
    refetchInterval: 15000,
  });
  const decision = useQuery({
    queryKey: ["product-decision"],
    queryFn: () => apiGet<ProductDecision>("/api/product-decision"),
  });
  const paper = useQuery({
    queryKey: ["paper-final", PRODUCT],
    queryFn: () => apiGet<PaperFinal>(`/api/paper-final/${PRODUCT}`),
    retry: false,
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Command Center"
        description="Your daily cockpit: the one safe action to take today, current product standing, and recent activity. No terminal required for normal operation."
        badges={<Badge tone="red" dot>NOT LIVE ELIGIBLE</Badge>}
        updatedAt={q.dataUpdatedAt ? `updated ${fmtTs(new Date(q.dataUpdatedAt).toISOString())}` : undefined}
      />

      <Loader data={q.data} error={q.error} isLoading={q.isLoading}>
        {(s) => {
          const h = s.health;
          const latestJob = s.jobs[0];
          const action = computeTodaysAction({
            controlsEnabled: s.controls_enabled,
            killSwitchActive: s.kill_switch_active,
            decisionStatus: s.decision.status,
            health: h,
            trading212: s.trading212,
            latestJobFailed: latestJob?.status === "failed",
            nextActionText: s.next_action,
          });
          const product = decision.data?.products.find((p) => p.product === s.product);
          const equity = (paper.data?.equity_curve ?? []).map((r) => ({ ts: r.date, equity: r.equity }));

          return (
            <>
              {/* The single most important thing to do right now. */}
              <ActionCard
                eyebrow={action.eyebrow}
                title={action.title}
                detail={action.detail}
                tone={action.tone}
                ctaLabel={action.ctaLabel}
                ctaHref={action.ctaHref}
                right={<Badge tone={s.controls_enabled ? "violet" : "gray"}>{s.controls_enabled ? "controls enabled" : "read-only"}</Badge>}
              />
              {action.readOnlyNote && (
                <div className="-mt-2 text-xs text-zinc-500">
                  Controls are read-only. Open the page to review; set
                  <code className="mono"> DASHBOARD_CONTROLS_ENABLED=true</code> to run the action.
                </div>
              )}

              {/* Product status grid — at-a-glance standing. */}
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
                <MetricCard label="Paper candidate"
                  value={<StatusBadge status={s.decision.status} />}
                  accent={s.decision.status === "paper_candidate" ? "ok" : "warn"}
                  sub={`capital: ${s.decision.capital_stage}`} />
                <MetricCard label="Readiness gates"
                  value={product ? `${product.gates_passed}/${product.gates_total}` : "—"}
                  accent={product && product.gates_passed === product.gates_total ? "ok" : "info"}
                  sub={product ? `risk: ${product.risk}` : "long-only T212"} />
                <MetricCard label="Concentration"
                  value={fmtPct((h.concentration_top_weight ?? 0) * 100)}
                  accent="info" sub="top-weight (EWMA)" />
                <MetricCard label="T212 demo"
                  value={<Badge tone={s.trading212.allow_demo_orders ? "violet" : "gray"}>
                    {s.trading212.enabled ? (s.trading212.allow_demo_orders ? "orders on" : "preview") : "off"}
                  </Badge>}
                  accent="muted" sub="live: hard-blocked" />
                <MetricCard label="Paper session"
                  value={<StatusBadge status={h.state} />}
                  accent={h.state === "FAILED" ? "danger" : h.state === "NOT STARTED" ? "muted" : "info"}
                  sub={h.state === "NOT STARTED" ? "not started" : `${h.forward_days_completed ?? 0}/${h.min_days ?? 30} days`} />
                <MetricCard label="Kill switch"
                  value={<Badge tone={s.kill_switch_active ? "red" : "green"} dot={s.kill_switch_active}>
                    {s.kill_switch_active ? "ENGAGED" : "off"}
                  </Badge>}
                  accent={s.kill_switch_active ? "danger" : "ok"} sub="halt control" />
              </div>

              {/* Charts + session detail. */}
              <div className="grid gap-4 lg:grid-cols-3">
                <div className="lg:col-span-2">
                  <ChartCard title="Paper equity curve" height={220} empty={equity.length < 2}
                    right={<Badge tone="gray">{equity.length} day(s)</Badge>}>
                    <EquityChart data={equity} height={220} />
                  </ChartCard>
                </div>
                <Card title="Supervised paper" icon={<Icons.clipboard size={15} />}
                  right={<StatusBadge status={h.state} />}>
                  {h.state === "NOT STARTED" ? (
                    <EmptyState text={h.message ?? "No supervised paper session yet"}
                      hint="start one from Supervised Paper"
                      action={<Link to="/supervised-paper" className="text-xs text-sky-400 hover:underline">Start session →</Link>} />
                  ) : (
                    <div className="grid grid-cols-2 gap-2.5">
                      <MetricCard label="Forward days" value={`${h.forward_days_completed ?? 0} / ${h.min_days ?? 30}`} accent="ok" />
                      <MetricCard label="Remaining" value={h.days_remaining ?? "—"} accent="info" />
                      <MetricCard label="Paper PnL" value={fmtPct(h.paper_pnl_pct)} />
                      <MetricCard label="Drawdown" value={fmtPct(h.current_drawdown_pct)} />
                    </div>
                  )}
                  <Link to="/supervised-paper" className="mt-3 inline-flex items-center gap-1 text-xs text-sky-400 hover:underline">
                    Open control center <Icons.arrowRight size={12} />
                  </Link>
                </Card>
              </div>

              {/* Recent activity. */}
              <div className="grid gap-4 md:grid-cols-2">
                <Card title="Latest reports" icon={<Icons.book size={15} />}
                  right={<Link to="/reports" className="text-xs text-sky-400 hover:underline">all →</Link>}>
                  {s.reports.length === 0 ? <EmptyState text="No reports generated yet"
                    hint="run a diagnostic to produce one" /> : (
                    <div className="space-y-1.5">
                      {s.reports.slice(0, 6).map((r) => (
                        <Link key={r.id} to="/reports" className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm hover:bg-zinc-800/40">
                          <Badge tone="gray">{r.category}</Badge>
                          <span className="truncate text-zinc-300">{r.name}</span>
                          {r.stale && <Badge tone="yellow">stale</Badge>}
                        </Link>
                      ))}
                    </div>
                  )}
                </Card>

                <Card title="Recent actions" icon={<Icons.list size={15} />}
                  right={<Link to="/safety" className="text-xs text-sky-400 hover:underline">audit →</Link>}>
                  {s.jobs.length === 0 ? <EmptyState text="No actions run yet"
                    hint="every action is audited" /> : (
                    <div className="space-y-1.5">
                      {s.jobs.slice(0, 6).map((j) => (
                        <div key={j.id} className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm">
                          <StatusBadge status={j.status} />
                          <span className="truncate text-zinc-400">{j.job_type.replace(/_/g, " ")}</span>
                          {j.refusal_reason && <span className="ml-auto truncate text-xs text-amber-300/80">{j.refusal_reason}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              </div>

              <NotLiveBanner />
            </>
          );
        }}
      </Loader>
    </div>
  );
}
