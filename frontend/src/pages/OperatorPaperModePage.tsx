import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "../lib/api";
import type { OperatorStatus, OperatorRunResult } from "../lib/productTypes";
import { Card, Badge, Button, EmptyState } from "../components/ui";
import MetricCard from "../components/MetricCard";
import ConfirmModal from "../components/ConfirmModal";
import { fmtPct } from "../lib/formatters";
import { NotLiveBanner, PageTitle, Loader, ReportBlock } from "../components/Banners";
import { useUi } from "../store/ui";

const PRODUCT = "long_only_t212";

const STATE_TONE: Record<string, string> = {
  "NOT STARTED": "gray",
  "IN PROGRESS": "blue",
  PAUSED: "yellow",
  FAILED: "red",
  "READY FOR FINAL REVIEW": "green",
};

export default function OperatorPaperModePage() {
  const toast = useUi((s) => s.toast);
  const qc = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);

  const status = useQuery({
    queryKey: ["operator-status", PRODUCT],
    queryFn: () => apiGet<OperatorStatus>(`/api/operator/status?product=${PRODUCT}`),
    refetchInterval: 15000,
  });

  const run = useMutation({
    mutationFn: (vars: { mode: string; phrase: string }) =>
      apiPost<OperatorRunResult>(`/api/operator/run/${vars.mode}`, {
        confirm_phrase: vars.phrase,
        reason: "operator dashboard",
      }),
    onSuccess: (res) => {
      toast(res.ok ? "success" : "error", res.status_line ?? "done");
      qc.invalidateQueries({ queryKey: ["operator-status", PRODUCT] });
    },
    onError: (err) => toast("error", err instanceof Error ? err.message : String(err)),
  });

  return (
    <div className="space-y-4">
      <PageTitle title="Operator Paper Mode" subtitle="Run and supervise the daily long-only Trading 212 paper period." />
      <NotLiveBanner />

      <Loader data={status.data} error={status.error} isLoading={status.isLoading}>
        {(s) => {
          const h = s.health;
          const controls = s.controls_enabled;
          const tone = STATE_TONE[h.state] ?? "gray";
          return (
            <>
              {/* product decision */}
              <Card title="Product decision">
                <div className="space-y-1 text-sm">
                  <div className="text-zinc-200">{s.decision.headline}</div>
                  <div className="text-zinc-400">{s.decision.action}</div>
                  <div className="flex flex-wrap gap-2 pt-1">
                    <Badge tone={s.decision.status === "paper_candidate" ? "green" : "yellow"}>
                      status: {s.decision.status}
                    </Badge>
                    <Badge tone="gray">capital: {s.decision.capital_stage}</Badge>
                    <Badge tone="red">live eligible: false</Badge>
                  </div>
                </div>
              </Card>

              {/* session status */}
              <Card title="Supervised session" right={<Badge tone={tone}>{h.state}</Badge>}>
                {h.state === "NOT STARTED" ? (
                  <EmptyState text={h.message ?? "no session"} hint="statarb supervised-paper-start --product long_only_t212 --mode shadow" />
                ) : (
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    <MetricCard label="Mode" value={h.mode ?? "—"} />
                    <MetricCard label="Forward days" value={`${h.forward_days_completed ?? 0} / ${h.min_days ?? 30}`} tone="text-emerald-400" />
                    <MetricCard label="Days remaining" value={h.days_remaining ?? "—"} />
                    <MetricCard label="Last run" value={h.last_run_date ?? "—"} sub={`gap ${h.missing_days_gap ?? 0}d`} />
                  </div>
                )}
                <div className="mt-2 text-xs text-zinc-500">Next required run: {s.next_action}</div>
              </Card>

              {/* risk / performance metrics */}
              {h.state !== "NOT STARTED" && (
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  <MetricCard label="Paper PnL" value={fmtPct(h.paper_pnl_pct)} />
                  <MetricCard label="Benchmark PnL" value={fmtPct(h.benchmark_pnl_pct ?? null)} />
                  <MetricCard label="Drawdown" value={fmtPct(h.current_drawdown_pct)} />
                  <MetricCard label="Concentration" value={fmtPct((h.concentration_top_weight ?? 0) * 100)} />
                  <MetricCard label="Turnover / yr" value={`${h.turnover_per_year ?? 0}x`} />
                  <MetricCard label="Slippage (bps)" value={h.avg_slippage_bps ?? 0} />
                  <MetricCard label="Orders rejected" value={h.rejected_orders ?? 0} />
                  <MetricCard label="Broker errors" value={h.broker_errors ?? 0} tone={(h.broker_errors ?? 0) > 0 ? "text-red-400" : ""} />
                </div>
              )}

              {/* stop rules / blockers */}
              <Card title="Stop rules & blockers" right={<Badge tone={(h.stop_rules?.state ?? "OK") === "OK" ? "green" : (h.stop_rules?.state === "FAILED" ? "red" : "yellow")}>{h.stop_rules?.state ?? "OK"}</Badge>}>
                {h.stop_rules && h.stop_rules.triggered.length > 0 ? (
                  <div className="space-y-2">
                    {h.stop_rules.triggered.map((r) => (
                      <div key={r.rule} className="rounded-lg border border-zinc-800 bg-zinc-950 p-2 text-sm">
                        <div className="flex items-center gap-2">
                          <Badge tone={r.severity === "FAILED" ? "red" : "yellow"}>{r.severity}</Badge>
                          <span className="text-zinc-200">{r.rule}</span>
                        </div>
                        <div className="mt-1 text-xs text-zinc-400">{r.detail}</div>
                        <div className="text-xs text-zinc-500">remediation: {r.remediation}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-sm text-emerald-400">No stop rules triggered.</div>
                )}
                {h.stop_reason && <div className="mt-2 text-xs text-red-300">Stop reason: {h.stop_reason}</div>}
              </Card>

              {/* daily checklist */}
              <Card title="Daily checklist">
                <div className="space-y-1">
                  {s.checklist.map((c) => (
                    <div key={c.item} className="flex items-center gap-2 text-sm">
                      <Badge tone={c.done ? "green" : "yellow"}>{c.done ? "✓" : "•"}</Badge>
                      <span className="text-zinc-300">{c.item}</span>
                      {c.note && <span className="text-xs text-zinc-600">{c.note}</span>}
                    </div>
                  ))}
                </div>
              </Card>

              {/* run controls */}
              <Card title="Run a paper day" right={<Badge tone={controls ? "violet" : "gray"}>{controls ? "controls enabled" : "read-only"}</Badge>}>
                <div className="flex flex-wrap items-center gap-3">
                  <Button tone="primary" disabled={!controls || run.isPending}
                          onClick={() => run.mutate({ mode: "shadow", phrase: "" })}>
                    Run shadow day
                  </Button>
                  <Button tone="primary" disabled={!controls || run.isPending || !s.trading212.api_key_configured}
                          onClick={() => run.mutate({ mode: "demo_preview", phrase: "" })}>
                    Run demo preview day
                  </Button>
                  <Button tone="danger" disabled={!controls || run.isPending || !s.trading212.allow_demo_orders}
                          onClick={() => setConfirmOpen(true)}>
                    Run demo execute day…
                  </Button>
                  <span className="text-xs text-zinc-500">
                    No live button exists. Demo execute requires the exact phrase
                    <code className="mono"> {s.confirm_phrase_demo_execute}</code> and is re-validated server-side.
                  </span>
                </div>
                {!controls && (
                  <div className="mt-2 text-xs text-zinc-500">
                    Controls are disabled. Set <code className="mono">DASHBOARD_CONTROLS_ENABLED=true</code> (bind to 127.0.0.1)
                    or run from the CLI: <code className="mono">statarb supervised-paper-daily --product long_only_t212 --mode shadow</code>.
                  </div>
                )}
              </Card>

              {/* latest daily summary */}
              {s.latest_summary && (
                <Card title="Latest daily summary (orders planned/refused, TCA, target weights)">
                  <ReportBlock report={s.latest_summary} />
                </Card>
              )}

              <ConfirmModal
                open={confirmOpen}
                title="Run a DEMO paper day (submits to the Trading 212 DEMO account)"
                description="This runs the full daily routine in demo_execute mode. It submits orders to the DEMO environment ONLY — the live endpoint is hard-blocked — and only if the full demo execution gate passes. The action is re-validated server-side and written to the audit trail."
                phrase={s.confirm_phrase_demo_execute}
                mode="demo"
                onClose={() => setConfirmOpen(false)}
                onConfirm={(reason) => {
                  setConfirmOpen(false);
                  run.mutate({ mode: "demo_execute", phrase: s.confirm_phrase_demo_execute });
                  if (reason) toast("info", `reason: ${reason}`);
                }}
              />
            </>
          );
        }}
      </Loader>
    </div>
  );
}
