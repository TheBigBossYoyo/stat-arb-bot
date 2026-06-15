import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { DashboardSummary } from "../lib/actionTypes";
import { Card, Badge, EmptyState } from "../components/ui";
import MetricCard from "../components/MetricCard";
import { NotLiveBanner, PageTitle, Loader } from "../components/Banners";
import { fmtPct } from "../lib/formatters";

const STATE_TONE: Record<string, string> = {
  "NOT STARTED": "gray", "IN PROGRESS": "blue", PAUSED: "yellow",
  FAILED: "red", "READY FOR FINAL REVIEW": "green", OK: "green",
};

function nextActionHref(text: string): string {
  const t = text.toLowerCase();
  if (t.includes("final-report") || t.includes("final review")) return "/supervised-paper";
  if (t.includes("supervised-paper") || t.includes("paper day") || t.includes("shadow")) return "/supervised-paper";
  if (t.includes("blocker")) return "/blockers";
  return "/supervised-paper";
}

export default function CommandCenterPage() {
  const q = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => apiGet<DashboardSummary>("/api/dashboard/summary"),
    refetchInterval: 15000,
  });

  return (
    <div className="space-y-4">
      <PageTitle title="Command Center" subtitle="Today's status and the single next safe action for the operator." />
      <NotLiveBanner />

      <Loader data={q.data} error={q.error} isLoading={q.isLoading}>
        {(s) => {
          const h = s.health;
          const tone = STATE_TONE[h.state] ?? "gray";
          return (
            <>
              {/* Today's action — the headline card */}
              <Card
                title="Today's required action"
                right={<Badge tone={s.controls_enabled ? "violet" : "gray"}>{s.controls_enabled ? "controls enabled" : "read-only"}</Badge>}
              >
                <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                  <div className="text-base text-zinc-100">{s.next_action}</div>
                  <Link
                    to={nextActionHref(s.next_action)}
                    className="rounded-lg border border-sky-600/50 bg-sky-600/20 px-3 py-1.5 text-sm font-medium text-sky-300 hover:bg-sky-600/40"
                  >
                    Go →
                  </Link>
                </div>
              </Card>

              <div className="grid gap-4 md:grid-cols-2">
                {/* Product decision */}
                <Card title="Product decision" right={<Badge tone="red">live: false</Badge>}>
                  <div className="space-y-1 text-sm">
                    <div className="text-zinc-200">{s.decision.headline}</div>
                    <div className="text-zinc-400">{s.decision.action}</div>
                    <div className="flex flex-wrap gap-2 pt-1">
                      <Badge tone={s.decision.status === "paper_candidate" ? "green" : "yellow"}>
                        {s.decision.status}
                      </Badge>
                      <Badge tone="gray">capital: {s.decision.capital_stage}</Badge>
                    </div>
                    <Link to="/product-decision" className="inline-block pt-1 text-xs text-sky-400 hover:underline">
                      view product paths →
                    </Link>
                  </div>
                </Card>

                {/* Supervised paper */}
                <Card title="Supervised paper" right={<Badge tone={tone}>{h.state}</Badge>}>
                  {h.state === "NOT STARTED" ? (
                    <EmptyState text={h.message ?? "no forward session yet"} hint="start one from Supervised Paper →" />
                  ) : (
                    <div className="grid grid-cols-2 gap-3">
                      <MetricCard label="Forward days" value={`${h.forward_days_completed ?? 0} / ${h.min_days ?? 30}`} tone="text-emerald-400" />
                      <MetricCard label="Days remaining" value={h.days_remaining ?? "—"} />
                      <MetricCard label="Paper PnL" value={fmtPct(h.paper_pnl_pct)} />
                      <MetricCard label="Drawdown" value={fmtPct(h.current_drawdown_pct)} />
                    </div>
                  )}
                  <Link to="/supervised-paper" className="inline-block pt-2 text-xs text-sky-400 hover:underline">
                    open control center →
                  </Link>
                </Card>

                {/* Broker */}
                <Card title="Trading 212 (demo)">
                  <div className="flex flex-wrap gap-2 text-sm">
                    <Badge tone={s.trading212.enabled ? "green" : "gray"}>{s.trading212.enabled ? "enabled" : "disabled"}</Badge>
                    <Badge tone="gray">mode: {s.trading212.mode}</Badge>
                    <Badge tone={s.trading212.api_key_configured ? "green" : "yellow"}>
                      keys: {s.trading212.api_key_configured ? "configured" : "missing"}
                    </Badge>
                    <Badge tone={s.trading212.allow_demo_orders ? "green" : "gray"}>
                      demo orders: {s.trading212.allow_demo_orders ? "allowed" : "blocked"}
                    </Badge>
                    <Badge tone="red">live orders: unsupported</Badge>
                  </div>
                  <Link to="/t212-setup" className="inline-block pt-2 text-xs text-sky-400 hover:underline">
                    run setup wizard →
                  </Link>
                </Card>

                {/* Safety */}
                <Card title="Risk & safety" right={<Badge tone={s.kill_switch_active ? "red" : "green"}>{s.kill_switch_active ? "KILL SWITCH ON" : "kill switch off"}</Badge>}>
                  <div className="space-y-1 text-sm text-zinc-400">
                    <div>Live trading is hard-blocked; demo orders need the full gate.</div>
                    <div className="flex gap-3 pt-1">
                      <Link to="/safety" className="text-xs text-sky-400 hover:underline">safety center →</Link>
                      <Link to="/live-readiness" className="text-xs text-sky-400 hover:underline">live readiness →</Link>
                    </div>
                  </div>
                </Card>
              </div>

              {/* Reports + recent jobs */}
              <div className="grid gap-4 md:grid-cols-2">
                <Card title="Latest reports" right={<Link to="/reports" className="text-xs text-sky-400 hover:underline">all →</Link>}>
                  {s.reports.length === 0 ? <EmptyState text="no reports yet" /> : (
                    <div className="space-y-1">
                      {s.reports.slice(0, 6).map((r) => (
                        <div key={r.id} className="flex items-center gap-2 text-sm">
                          <Badge tone="gray">{r.category}</Badge>
                          <span className="truncate text-zinc-300">{r.name}</span>
                          {r.stale && <Badge tone="yellow">stale</Badge>}
                        </div>
                      ))}
                    </div>
                  )}
                </Card>

                <Card title="Recent actions" right={<Link to="/safety" className="text-xs text-sky-400 hover:underline">audit →</Link>}>
                  {s.jobs.length === 0 ? <EmptyState text="no actions run yet" /> : (
                    <div className="space-y-1">
                      {s.jobs.slice(0, 6).map((j) => (
                        <div key={j.id} className="flex items-center gap-2 text-sm">
                          <Badge tone={j.status === "succeeded" ? "green" : j.status === "refused" || j.status === "failed" ? "red" : "blue"}>
                            {j.status}
                          </Badge>
                          <span className="truncate text-zinc-400">{j.job_type.replace(/_/g, " ")}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              </div>
            </>
          );
        }}
      </Loader>
    </div>
  );
}
