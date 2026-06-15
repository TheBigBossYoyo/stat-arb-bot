import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { SystemStatus, AuditEvent } from "../lib/types";
import type { JobRecord, CapabilitiesResp } from "../lib/actionTypes";
import { useAction } from "../lib/useAction";
import { Card, Badge, Button, EmptyState } from "../components/ui";
import ConfirmModal from "../components/ConfirmModal";
import { NotLiveBanner, PageTitle, Loader } from "../components/Banners";
import { fmtTs } from "../lib/formatters";

const UNSUPPORTED = [
  ["Live orders", "no live order connector exists; the flag is never consulted"],
  ["Trading 212 CFDs", "official Invest/ISA Public API only — CFDs are unreachable"],
  ["Trading 212 shorting", "long-only by design; shorting is not wired"],
  ["Trading 212 margin / leverage", "cash equities only; no margin path"],
  ["Unofficial / private endpoints", "no scraping, no reverse-engineered endpoints"],
];

export default function SafetyCenterPage() {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["status"] });
    qc.invalidateQueries({ queryKey: ["safety-audit"] });
  };

  const status = useQuery({ queryKey: ["status"], queryFn: () => apiGet<SystemStatus>("/api/status"), refetchInterval: 10000 });
  const audit = useQuery({ queryKey: ["safety-audit"], queryFn: () => apiGet<AuditEvent[]>("/api/audit?limit=50"), refetchInterval: 15000 });
  const jobs = useQuery({ queryKey: ["dashboard-jobs"], queryFn: () => apiGet<JobRecord[]>("/api/dashboard/jobs?limit=50"), refetchInterval: 10000 });
  const caps = useQuery({ queryKey: ["capabilities"], queryFn: () => apiGet<CapabilitiesResp>("/api/dashboard/capabilities") });

  const engage = useAction("/api/risk/kill-switch/engage", { onDone: refresh });
  const disengage = useAction("/api/risk/kill-switch/disengage", { onDone: refresh });
  const [modal, setModal] = useState<"engage" | "disengage" | null>(null);

  const refused = (jobs.data ?? []).filter((j) => j.status === "refused");
  const approved = (jobs.data ?? []).filter((j) => j.status !== "refused");

  return (
    <div className="space-y-4">
      <PageTitle title="Safety Center" subtitle="The halt control, what is structurally impossible, and the audit trail." />
      <NotLiveBanner />

      <Loader data={status.data} error={status.error} isLoading={status.isLoading}>
        {(s) => {
          const active = s.kill_switch.active;
          return (
            <div className="grid gap-4 md:grid-cols-2">
              <Card title="Kill switch" right={<Badge tone={active ? "red" : "green"}>{active ? "ENGAGED" : "off"}</Badge>}>
                <div className="space-y-2 text-sm">
                  <div className="text-zinc-400">{active ? `Engaged${s.kill_switch.reason ? `: ${s.kill_switch.reason}` : ""}` : "All actions can run (subject to gates)."}</div>
                  <div className="flex gap-2">
                    <Button tone="danger" disabled={active || !s.controls_enabled || engage.busy} onClick={() => setModal("engage")}>
                      Engage…
                    </Button>
                    <Button disabled={!active || !s.controls_enabled || disengage.busy} onClick={() => setModal("disengage")}>
                      Disengage…
                    </Button>
                  </div>
                  <div className="text-xs text-zinc-600">
                    Engage needs the phrase <code className="mono">ACTIVATE KILL SWITCH</code>; disengage is stricter —
                    admin + <code className="mono">DISENGAGE KILL SWITCH</code>.
                  </div>
                </div>
              </Card>

              <Card title="Status flags">
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <Flag label="live trading allowed" bad={s.live_trading_allowed} text={s.live_trading_allowed ? "YES" : "no"} />
                  <Flag label="mode" text={s.mode} />
                  <Flag label="controls enabled" text={s.controls_enabled ? "yes" : "read-only"} good={s.controls_enabled} neutral />
                  <Flag label="bot status" text={s.bot_status} neutral />
                </div>
              </Card>
            </div>
          );
        }}
      </Loader>

      <Card title="Structurally unsupported (by design)">
        <div className="space-y-1">
          {UNSUPPORTED.map(([name, why]) => (
            <div key={name} className="flex items-start gap-2 text-sm">
              <Badge tone="red">blocked</Badge>
              <div><span className="text-zinc-200">{name}</span> <span className="text-xs text-zinc-500">— {why}</span></div>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title={`Recently refused (${refused.length})`}>
          {refused.length === 0 ? <EmptyState text="no refused actions" /> : (
            <div className="space-y-1 text-sm">
              {refused.slice(0, 8).map((j) => (
                <div key={j.id} className="rounded border border-red-500/20 bg-red-500/5 px-2 py-1">
                  <div className="text-zinc-300">{j.job_type.replace(/_/g, " ")}</div>
                  <div className="text-xs text-red-300">{j.refusal_reason}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card title={`Recently approved (${approved.length})`}>
          {approved.length === 0 ? <EmptyState text="no actions yet" /> : (
            <div className="space-y-1 text-sm">
              {approved.slice(0, 8).map((j) => (
                <div key={j.id} className="flex items-center gap-2">
                  <Badge tone={j.status === "succeeded" ? "green" : j.status === "failed" ? "red" : "blue"}>{j.status}</Badge>
                  <span className="text-zinc-400">{j.job_type.replace(/_/g, " ")}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title="Confirmation policy">
        <Loader data={caps.data} error={caps.error} isLoading={caps.isLoading}>
          {(c) => (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs uppercase tracking-wider text-zinc-500">
                  <tr><th className="px-2 py-1 text-left">action</th><th className="px-2 py-1 text-left">safety</th><th className="px-2 py-1 text-left">role</th><th className="px-2 py-1 text-left">confirm</th><th className="px-2 py-1 text-left">phrase</th></tr>
                </thead>
                <tbody>
                  {c.actions.map((a) => (
                    <tr key={a.job_type} className="border-t border-zinc-800">
                      <td className="px-2 py-1 text-zinc-300">{a.job_type.replace(/_/g, " ")}</td>
                      <td className="px-2 py-1"><Badge tone={a.safety_level === "demo" ? "yellow" : a.safety_level === "danger" ? "red" : "gray"}>{a.safety_level}</Badge></td>
                      <td className="px-2 py-1 text-zinc-400">{a.min_role}</td>
                      <td className="px-2 py-1 text-zinc-400">{a.confirm_level}{a.needs_demo_env ? " +env" : ""}</td>
                      <td className="px-2 py-1 mono text-xs text-zinc-500">{a.phrase || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Loader>
      </Card>

      <Card title="Audit trail (latest 50)">
        <Loader data={audit.data} error={audit.error} isLoading={audit.isLoading}>
          {(events) => events.length === 0 ? <EmptyState text="no audit events" /> : (
            <div className="max-h-96 space-y-1 overflow-y-auto text-sm">
              {events.map((e) => (
                <div key={e.id} className="flex items-center gap-2 border-b border-zinc-900 py-1">
                  <span className="mono text-xs text-zinc-600">{fmtTs(e.ts)}</span>
                  <Badge tone={e.confirmed ? "violet" : "gray"}>{e.actor}</Badge>
                  <span className="text-zinc-300">{e.action}</span>
                  <span className="ml-auto truncate text-xs text-zinc-500">{e.result}</span>
                </div>
              ))}
            </div>
          )}
        </Loader>
      </Card>

      <ConfirmModal
        open={modal === "engage"}
        title="Engage kill switch"
        description="Immediately halts all new action flow. Persists across restarts until disengaged. Paper positions are simulated; this is the effective halt."
        phrase="ACTIVATE KILL SWITCH"
        mode="paper"
        onClose={() => setModal(null)}
        onConfirm={(reason) => { setModal(null); engage.run({ confirm_phrase: "ACTIVATE KILL SWITCH", params: { reason: reason || "dashboard" }, reason }); }}
      />
      <ConfirmModal
        open={modal === "disengage"}
        title="Disengage kill switch"
        description="Re-enables action flow. Only do this after you understand and have addressed whatever engaged it. Requires admin controls. This does NOT enable anything live."
        phrase="DISENGAGE KILL SWITCH"
        mode="paper"
        onClose={() => setModal(null)}
        onConfirm={(reason) => { setModal(null); disengage.run({ confirm_phrase: "DISENGAGE KILL SWITCH", params: { reason: reason || "dashboard" }, reason }); }}
      />
    </div>
  );
}

function Flag({ label, text, bad, good, neutral }: { label: string; text: string; bad?: boolean; good?: boolean; neutral?: boolean }) {
  const tone = neutral ? "gray" : bad ? "red" : good ? "green" : bad === undefined && good === undefined ? "gray" : "green";
  return (
    <div className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2">
      <span className="text-zinc-400">{label}</span>
      <Badge tone={tone}>{text}</Badge>
    </div>
  );
}
