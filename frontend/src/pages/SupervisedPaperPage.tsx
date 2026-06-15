import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { OperatorStatus } from "../lib/productTypes";
import { useAction } from "../lib/useAction";
import { Card, Badge, Button, EmptyState, Field, inputCls, PageHeader } from "../components/ui";
import MetricCard from "../components/MetricCard";
import JobProgress from "../components/JobProgress";
import ConfirmModal from "../components/ConfirmModal";
import { DemoOnlyBanner, Loader } from "../components/Banners";
import { fmtPct } from "../lib/formatters";

const PRODUCT = "long_only_t212";
const STATE_TONE: Record<string, string> = {
  "NOT STARTED": "gray", "IN PROGRESS": "blue", PAUSED: "yellow",
  FAILED: "red", "READY FOR FINAL REVIEW": "green",
};

export default function SupervisedPaperPage() {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["operator-status", PRODUCT] });
    qc.invalidateQueries({ queryKey: ["dashboard-summary"] });
  };

  const status = useQuery({
    queryKey: ["operator-status", PRODUCT],
    queryFn: () => apiGet<OperatorStatus>(`/api/operator/status?product=${PRODUCT}`),
    refetchInterval: 15000,
  });

  const [mode, setMode] = useState("shadow");
  const [minDays, setMinDays] = useState(30);
  const [cash, setCash] = useState(10000);
  const [confirm, setConfirm] = useState<"demo_execute" | "stop" | null>(null);

  const start = useAction("/api/paper/start", { onDone: refresh });
  const daily = useAction("/api/paper/daily", { onDone: refresh });
  const stop = useAction("/api/paper/stop", { onDone: refresh });
  const final = useAction("/api/paper/final-report", { onDone: refresh });
  const anyJob = daily.job ?? start.job ?? final.job ?? stop.job;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Supervised Paper — Control Center"
        description="Start, run, monitor and close the long-only Trading 212 supervised paper period. There is no live path — every mode is paper or demo and re-validated server-side."
        badges={<Badge tone="red" dot>NOT LIVE ELIGIBLE</Badge>}
      />

      <Loader data={status.data} error={status.error} isLoading={status.isLoading}>
        {(s) => {
          const h = s.health;
          const controls = s.controls_enabled;
          const tone = STATE_TONE[h.state] ?? "gray";
          const notStarted = h.state === "NOT STARTED";
          const phrase = s.confirm_phrase_demo_execute;
          return (
            <>
              {/* session header */}
              <Card title="Session" right={<Badge tone={tone}>{h.state}</Badge>}>
                {notStarted ? (
                  <EmptyState text={h.message ?? "no forward session yet"} hint="start one below — a forward day a trading day (a cron, not a loop)" />
                ) : (
                  <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                    <MetricCard label="Mode" value={h.mode ?? "—"} />
                    <MetricCard label="Forward days" value={`${h.forward_days_completed ?? 0} / ${h.min_days ?? 30}`} tone="text-emerald-400" />
                    <MetricCard label="Days remaining" value={h.days_remaining ?? "—"} sub="until 30-day minimum" />
                    <MetricCard label="Last run" value={h.last_run_date ?? "—"} sub={`gap ${h.missing_days_gap ?? 0}d`} />
                  </div>
                )}
                <div className="mt-2 text-xs text-zinc-500">Next: {s.next_action}</div>
              </Card>

              {/* metrics */}
              {!notStarted && (
                <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                  <MetricCard label="Paper PnL" value={fmtPct(h.paper_pnl_pct)} />
                  <MetricCard label="Benchmark PnL" value={fmtPct(h.benchmark_pnl_pct ?? null)} />
                  <MetricCard label="Drawdown" value={fmtPct(h.current_drawdown_pct)} />
                  <MetricCard label="Concentration" value={fmtPct((h.concentration_top_weight ?? 0) * 100)} />
                  <MetricCard label="Turnover / yr" value={`${h.turnover_per_year ?? 0}x`} />
                  <MetricCard label="Slippage (bps)" value={h.avg_slippage_bps ?? 0} />
                  <MetricCard label="Orders rejected" value={h.rejected_orders ?? 0} />
                  <MetricCard label="Risk breaches" value={h.risk_breaches ?? 0} tone={(h.risk_breaches ?? 0) > 0 ? "text-red-400" : ""} />
                </div>
              )}

              {/* start / setup */}
              {notStarted && (
                <Card title="Start a supervised paper session">
                  <div className="flex flex-wrap items-end gap-3">
                    <Field label="Mode">
                      <select className={inputCls} value={mode} onChange={(e) => setMode(e.target.value)}>
                        <option value="shadow">shadow (no broker)</option>
                        <option value="demo_preview">demo_preview (connect, send nothing)</option>
                        <option value="demo_execute">demo_execute (submit demo orders)</option>
                      </select>
                    </Field>
                    <Field label="Min forward days">
                      <input type="number" className={inputCls} value={minDays} onChange={(e) => setMinDays(Number(e.target.value))} />
                    </Field>
                    <Field label="Starting cash">
                      <input type="number" className={inputCls} value={cash} onChange={(e) => setCash(Number(e.target.value))} />
                    </Field>
                    <Button tone="primary" disabled={!controls || start.busy}
                            onClick={() => start.run({ params: { product: PRODUCT, mode, min_days: minDays, starting_cash: cash }, reason: "operator dashboard" })}>
                      Start session
                    </Button>
                  </div>
                  <div className="mt-2 text-xs text-zinc-500">
                    Mode descriptions — <b>shadow</b>: simulated only. <b>demo_preview</b>: connects to the Trading 212 DEMO API and validates, but submits nothing. <b>demo_execute</b>: may submit DEMO orders only when the full gate passes. Replay days never count as forward days.
                  </div>
                </Card>
              )}

              {/* run a day */}
              {!notStarted && (
                <Card title="Run a paper day" right={<Badge tone={controls ? "violet" : "gray"}>{controls ? "controls enabled" : "read-only"}</Badge>}>
                  <div className="flex flex-wrap items-center gap-3">
                    <Button tone="primary" disabled={!controls || daily.busy}
                            onClick={() => daily.run({ params: { product: PRODUCT, mode: "shadow" }, reason: "operator dashboard" })}>
                      Run shadow day
                    </Button>
                    <Button tone="primary" disabled={!controls || daily.busy || !s.trading212.api_key_configured}
                            onClick={() => daily.run({ params: { product: PRODUCT, mode: "demo_preview" }, reason: "operator dashboard" })}>
                      Run demo preview day
                    </Button>
                    <Button tone="danger" disabled={!controls || daily.busy || !s.trading212.allow_demo_orders}
                            onClick={() => setConfirm("demo_execute")}>
                      Run demo execute day…
                    </Button>
                  </div>
                  <div className="mt-2 text-xs text-zinc-500">
                    No live button exists. Demo execute requires the exact phrase <code className="mono">{phrase}</code>,
                    admin controls and <code className="mono">TRADING212_ALLOW_DEMO_ORDERS=true</code> — all re-checked server-side.
                  </div>
                </Card>
              )}

              {/* close-out */}
              {!notStarted && (
                <Card title="Close out">
                  <div className="flex flex-wrap items-center gap-3">
                    <Button tone="primary" disabled={!controls || final.busy}
                            onClick={() => final.run({ params: { product: PRODUCT, min_days: h.min_days ?? 30 }, reason: "operator dashboard" })}>
                      Generate final report
                    </Button>
                    <Button tone="danger" disabled={!controls || stop.busy}
                            onClick={() => setConfirm("stop")}>
                      Stop session…
                    </Button>
                    <span className="text-xs text-zinc-500">
                      The final report refuses to PASS before {h.min_days ?? 30} forward days. Stopping needs the phrase <code className="mono">STOP PAPER SESSION</code>.
                    </span>
                  </div>
                  {final.job?.status === "succeeded" && (
                    <div className="mt-3 flex flex-wrap gap-2 text-sm">
                      <Badge tone={String(final.job.result.recommendation) === "PASS" ? "green" : "yellow"}>
                        recommendation: {String(final.job.result.recommendation ?? "—")}
                      </Badge>
                      <Badge tone="gray">verdict: {String(final.job.result.verdict ?? "—")}</Badge>
                      <Badge tone="red">live eligible: false</Badge>
                    </div>
                  )}
                </Card>
              )}

              {/* live job progress */}
              {anyJob && <JobProgress job={anyJob} />}

              {/* stop rules */}
              <Card title="Stop rules" right={<Badge tone={(h.stop_rules?.state ?? "OK") === "OK" ? "green" : h.stop_rules?.state === "FAILED" ? "red" : "yellow"}>{h.stop_rules?.state ?? "OK"}</Badge>}>
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
              </Card>

              <DemoOnlyBanner />

              <ConfirmModal
                open={confirm === "demo_execute"}
                title="Run a DEMO paper day"
                description="Runs the full daily routine in demo_execute mode. Submits orders to the Trading 212 DEMO account ONLY (live is hard-blocked) and only if the full demo gate passes. Re-validated server-side and audited."
                phrase={phrase}
                mode="demo_execute"
                onClose={() => setConfirm(null)}
                onConfirm={(reason) => {
                  setConfirm(null);
                  daily.run({ params: { product: PRODUCT, mode: "demo_execute" }, confirm_phrase: phrase, reason: reason || "operator dashboard" });
                }}
              />
              <ConfirmModal
                open={confirm === "stop"}
                title="Stop the supervised paper session"
                description="Ends the active forward period and records the reason. You will need to start a new session (with reset) to resume. This does not enable anything live."
                phrase="STOP PAPER SESSION"
                mode="paper"
                onClose={() => setConfirm(null)}
                onConfirm={(reason) => {
                  setConfirm(null);
                  stop.run({ params: { product: PRODUCT, reason: reason || "stopped from dashboard" }, confirm_phrase: "STOP PAPER SESSION", reason: reason || "operator dashboard" });
                }}
              />
            </>
          );
        }}
      </Loader>
    </div>
  );
}
