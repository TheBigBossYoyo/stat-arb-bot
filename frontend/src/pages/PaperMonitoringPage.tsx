import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, ApiError } from "../lib/api";
import type { PaperMonitor, PaperAlert } from "../lib/monitorTypes";
import { CLASS_TONE, SEVERITY_TONE } from "../lib/monitorTypes";
import { Card, Badge, Button, EmptyState, PageHeader, SectionHeader } from "../components/ui";
import MetricCard from "../components/MetricCard";
import { ChartCard, MultiLineChart, ContributionChart } from "../components/charts";
import { NotLiveBanner, Loader } from "../components/Banners";
import { Icons } from "../components/icons";
import { useControls } from "../lib/useControls";
import { useUi } from "../store/ui";
import { fmtPct, fmtTs } from "../lib/formatters";

const PRODUCT = "long_only_t212";

export default function PaperMonitoringPage() {
  const qc = useQueryClient();
  const controls = useControls();
  const toast = useUi((s) => s.toast);
  const [resolving, setResolving] = useState<PaperAlert | null>(null);

  const q = useQuery({
    queryKey: ["paper-health", PRODUCT],
    queryFn: () => apiGet<PaperMonitor>(`/api/paper/health?product=${PRODUCT}`),
    refetchInterval: 20000,
  });

  const resolveMut = useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      apiPost(`/api/paper/alerts/${id}/resolve?product=${PRODUCT}`, { reason: note }),
    onSuccess: () => {
      toast("success", "Alert resolved (recorded in the audit trail).");
      setResolving(null);
      qc.invalidateQueries({ queryKey: ["paper-health", PRODUCT] });
    },
    onError: (e) =>
      toast("error", e instanceof ApiError ? e.message : "Could not resolve alert"),
  });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Paper Monitoring"
        description="Health score, alerts and quality control for the forward supervised paper period. Updates after every daily run."
        badges={<Badge tone="red" dot>NOT LIVE ELIGIBLE</Badge>}
        updatedAt={q.dataUpdatedAt ? `updated ${fmtTs(new Date(q.dataUpdatedAt).toISOString())}` : undefined}
      />
      <NotLiveBanner />

      <Loader data={q.data} error={q.error} isLoading={q.isLoading}>
        {(m) => {
          if (!m.active) {
            return <EmptyState text={String(m.metrics?.message ?? "No active paper session")}
              hint="start one from Supervised Paper" />;
          }
          const hs = m.health_score;
          const met = m.metrics;
          const active = m.alerts.filter((a) => !a.resolved);
          const resolved = m.alerts.filter((a) => a.resolved);
          const snaps = m.snapshots ?? [];
          const stopState = String((m.health?.stop_rules as { state?: string } | undefined)?.state ?? "OK");

          return (
            <>
              {/* Health score hero. */}
              <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
                <Card title="Health score" icon={<Icons.pulse size={15} />}>
                  <div className="flex flex-col items-center py-2">
                    <div className="text-5xl font-bold mono text-zinc-100">{hs.score}
                      <span className="text-xl text-zinc-500">/100</span></div>
                    <div className="mt-2"><Badge tone={CLASS_TONE[hs.classification]} dot>
                      {hs.classification.toUpperCase()}</Badge></div>
                    {hs.overrides.length > 0 && (
                      <ul className="mt-3 w-full space-y-1 text-xs text-red-300">
                        {hs.overrides.map((o) => <li key={o}>⚠ {o}</li>)}
                      </ul>
                    )}
                  </div>
                  <div className="mt-1 rounded-lg border border-zinc-800 bg-zinc-950/40 px-3 py-2 text-xs text-zinc-300">
                    <span className="font-semibold text-zinc-200">Next action: </span>
                    {m.suggested_next_action}
                  </div>
                </Card>

                <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <MetricCard label="Session" value={<span className="text-sm">{m.session_id}</span>} accent="muted" sub={met.mode} />
                  <MetricCard label="Days completed" value={met.forward_days_completed} accent="ok"
                    sub={`expected ${met.expected_trading_days}`} />
                  <MetricCard label="Missed days" value={met.missed_days}
                    accent={met.missed_days > 0 ? "warn" : "ok"} />
                  <MetricCard label="To 30-day min" value={met.days_remaining_to_min} accent="info" />
                  <MetricCard label="To 90-day target" value={met.days_remaining_to_target} accent="info" />
                  <MetricCard label="Last run" value={<span className="text-sm">{met.last_run_date ?? "—"}</span>}
                    accent={met.ran_today ? "ok" : "warn"} sub={met.ran_today ? "done today" : `next ${met.next_expected_run}`} />
                  <MetricCard label="Paper PnL" value={fmtPct(met.paper_pnl_pct)} />
                  <MetricCard label="Benchmark PnL" value={fmtPct(met.benchmark_pnl_pct)} />
                  <MetricCard label="Excess" value={met.excess_return_pct != null ? `${met.excess_return_pct}ppt` : "—"}
                    accent={(met.excess_return_pct ?? 0) >= 0 ? "ok" : "warn"} />
                  <MetricCard label="Drawdown" value={fmtPct(met.current_drawdown_pct)}
                    accent={Math.abs(met.current_drawdown_pct ?? 0) > 20 ? "danger" : "info"} />
                  <MetricCard label="Concentration" value={fmtPct((met.concentration_top_weight ?? 0) * 100)}
                    accent={(met.concentration_top_weight ?? 0) > 0.25 ? "warn" : "ok"} sub="top weight (cap 25%)" />
                  <MetricCard label="Turnover" value={`${met.turnover_per_year ?? 0}x/yr`} accent="muted" />
                  <MetricCard label="Cash drag" value={met.cash_drag_pct != null ? fmtPct(met.cash_drag_pct) : "—"} accent="muted" />
                  <MetricCard label="Tracking error" value={met.tracking_error_pct_daily != null ? `${met.tracking_error_pct_daily}%` : "—"} accent="muted" />
                  <MetricCard label="Stop rules" value={<Badge tone={stopState === "OK" ? "green" : stopState === "FAILED" ? "red" : "yellow"}>{stopState}</Badge>}
                    accent={stopState === "OK" ? "ok" : "warn"} sub={`pvb: ${met.paper_vs_backtest_status}`} />
                </div>
              </div>

              {/* Score component breakdown. */}
              <Card title="Health score components" subtitle="why the score is what it is"
                icon={<Icons.layers size={15} />}>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-zinc-800 text-left text-[11px] uppercase tracking-wider text-zinc-500">
                        <th className="px-2 py-2">component</th><th className="px-2 py-2 text-right">score</th>
                        <th className="px-2 py-2 text-right">weight</th><th className="px-2 py-2">detail</th>
                      </tr>
                    </thead>
                    <tbody>
                      {hs.components.map((c) => (
                        <tr key={c.name} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                          <td className="px-2 py-1.5 text-zinc-300">{c.name.replace(/_/g, " ")}</td>
                          <td className="px-2 py-1.5 text-right mono">
                            <span className={c.score >= 80 ? "text-emerald-400" : c.score >= 50 ? "text-amber-400" : "text-red-400"}>{c.score}</span>
                          </td>
                          <td className="px-2 py-1.5 text-right mono text-zinc-500">{c.weight}</td>
                          <td className="px-2 py-1.5 text-zinc-500">{c.detail}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Card>

              {/* Charts. */}
              <div className="grid gap-4 lg:grid-cols-2">
                <ChartCard title="Health score over time" height={200} empty={snaps.length < 2}>
                  <MultiLineChart data={snaps} xKey="date" height={200} yDomain={[0, 100]}
                    series={[{ key: "score", label: "score", color: "#38bdf8" }]} />
                </ChartCard>
                <ChartCard title="Paper vs benchmark PnL (%)" height={200} empty={snaps.length < 2}>
                  <MultiLineChart data={snaps} xKey="date" height={200} unit="%"
                    series={[
                      { key: "paper_pnl_pct", label: "paper", color: "#10b981" },
                      { key: "benchmark_pnl_pct", label: "benchmark", color: "#a78bfa" },
                    ]} />
                </ChartCard>
                <ChartCard title="Concentration over time" height={200} empty={snaps.length < 2}>
                  <MultiLineChart data={snaps} xKey="date" height={200}
                    series={[{ key: "concentration_top_weight", label: "top weight", color: "#f59e0b" }]} />
                </ChartCard>
                <ChartCard title="Alerts over time" height={200} empty={snaps.length < 2}>
                  <MultiLineChart data={snaps} xKey="date" height={200}
                    series={[
                      { key: "critical_alerts", label: "critical", color: "#ef4444" },
                      { key: "warning_alerts", label: "warning", color: "#f59e0b" },
                    ]} />
                </ChartCard>
              </div>

              {/* Active alerts. */}
              <Card title={`Active alerts (${active.length})`} icon={<Icons.alert size={15} />}>
                {active.length === 0 ? (
                  <EmptyState text="No active alerts — the session is clean" icon={<Icons.check size={26} />} />
                ) : (
                  <div className="space-y-2">
                    {active.map((a) => (
                      <AlertRow key={a.alert_id} alert={a} controls={controls}
                        onResolve={() => setResolving(a)} />
                    ))}
                  </div>
                )}
              </Card>

              {/* Resolved history. */}
              {resolved.length > 0 && (
                <Card title={`Resolved alerts (${resolved.length})`} icon={<Icons.list size={15} />}>
                  <div className="space-y-1.5">
                    {resolved.slice().reverse().slice(0, 25).map((a) => (
                      <div key={a.alert_id} className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm text-zinc-400">
                        <Badge tone={SEVERITY_TONE[a.severity]}>{a.severity}</Badge>
                        <span className="truncate">{a.title}</span>
                        <span className="ml-auto truncate text-xs text-zinc-600">{a.resolution_note}</span>
                      </div>
                    ))}
                  </div>
                </Card>
              )}

              {/* Daily history (snapshots). */}
              <Card title="Daily run history" subtitle="one row per recorded day" icon={<Icons.clipboard size={15} />}>
                {snaps.length === 0 ? <EmptyState text="No snapshots yet" /> : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-zinc-800 text-left text-[11px] uppercase tracking-wider text-zinc-500">
                          <th className="px-2 py-2">date</th><th className="px-2 py-2 text-right">score</th>
                          <th className="px-2 py-2">class</th><th className="px-2 py-2 text-right">paper%</th>
                          <th className="px-2 py-2 text-right">dd%</th><th className="px-2 py-2 text-right">conc</th>
                          <th className="px-2 py-2 text-right">alerts</th>
                        </tr>
                      </thead>
                      <tbody>
                        {snaps.slice().reverse().map((s) => (
                          <tr key={s.date} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                            <td className="px-2 py-1.5 mono">{s.date}</td>
                            <td className="px-2 py-1.5 text-right mono">{s.score}</td>
                            <td className="px-2 py-1.5"><Badge tone={CLASS_TONE[s.classification]}>{s.classification}</Badge></td>
                            <td className="px-2 py-1.5 text-right mono">{fmtPct(s.paper_pnl_pct)}</td>
                            <td className="px-2 py-1.5 text-right mono">{fmtPct(s.drawdown_pct)}</td>
                            <td className="px-2 py-1.5 text-right mono">{s.concentration_top_weight ?? "—"}</td>
                            <td className="px-2 py-1.5 text-right mono">{s.active_alerts}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>

              <SectionHeader title="Paper vs backtest behaviour"
                description={`verdict: ${m.paper_vs_backtest.verdict}`} />
              <ContributionChart
                data={hs.components.map((c) => ({ label: c.name.replace(/_/g, " "), value: c.score }))}
                height={220} unit="" />

              <NotLiveBanner />
            </>
          );
        }}
      </Loader>

      {resolving && (
        <ResolveModal alert={resolving} controls={controls}
          busy={resolveMut.isPending}
          onClose={() => setResolving(null)}
          onConfirm={(note) => resolveMut.mutate({ id: resolving.alert_id, note })} />
      )}
    </div>
  );
}

function AlertRow({ alert, controls, onResolve }: {
  alert: PaperAlert; controls: boolean; onResolve: () => void;
}) {
  const isCritical = alert.severity === "critical";
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="flex items-center gap-2">
        <Badge tone={SEVERITY_TONE[alert.severity]} dot>{alert.severity}</Badge>
        <span className="text-sm font-semibold text-zinc-200">{alert.title}</span>
        <span className="ml-auto text-xs text-zinc-600">{alert.category}</span>
      </div>
      <div className="mt-1 text-sm text-zinc-400">{alert.message}</div>
      {alert.suggested_action && (
        <div className="mt-1 text-xs text-zinc-500">→ {alert.suggested_action}</div>
      )}
      <div className="mt-2 flex items-center gap-2">
        <Button size="sm" tone={isCritical ? "secondary" : "default"} disabled={!controls || isCritical}
          onClick={onResolve} icon={<Icons.check size={13} />}
          title={isCritical ? "Critical alerts must be fixed at the source, not dismissed" : undefined}>
          {isCritical ? "Fix the underlying issue" : "Resolve…"}
        </Button>
        {!controls && <span className="text-xs text-zinc-600">read-only — enable controls to resolve</span>}
      </div>
    </div>
  );
}

function ResolveModal({ alert, controls, busy, onClose, onConfirm }: {
  alert: PaperAlert; controls: boolean; busy: boolean;
  onClose: () => void; onConfirm: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-md rounded-xl border border-zinc-700 bg-zinc-900 p-5 shadow-2xl">
        <div className="text-base font-semibold text-zinc-100">Resolve alert</div>
        <p className="mt-2 text-sm text-zinc-400">{alert.title}</p>
        <label className="mt-4 block text-xs text-zinc-400">
          Resolution note (recorded in the audit trail)
          <input autoFocus value={note} onChange={(e) => setNote(e.target.value)}
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-sky-500" />
        </label>
        <p className="mt-2 text-xs text-zinc-600">
          Resolving does not delete the alert — it stays in history. A critical alert
          whose condition is still active will be refused by the server.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button tone="primary" disabled={!controls || !note.trim() || busy}
            onClick={() => onConfirm(note.trim())}>
            {busy ? "Resolving…" : "Resolve"}
          </Button>
        </div>
      </div>
    </div>
  );
}
