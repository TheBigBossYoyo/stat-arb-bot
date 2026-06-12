import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, ApiError } from "../lib/api";
import type { AuditEvent, RiskStatus, SystemStatus } from "../lib/types";
import { fmtTs } from "../lib/formatters";
import DataTable from "../components/DataTable";
import ConfirmModal from "../components/ConfirmModal";
import KillSwitchControl from "../components/KillSwitch";
import { Badge, Button, Card, statusTone } from "../components/ui";
import { useUi } from "../store/ui";

export default function Risk() {
  const queryClient = useQueryClient();
  const toast = useUi((s) => s.toast);
  const [flattenOpen, setFlattenOpen] = useState(false);

  const { data: risk } = useQuery({
    queryKey: ["risk"], queryFn: () => apiGet<RiskStatus>("/api/risk/status"), refetchInterval: 10000,
  });
  const { data: status } = useQuery({
    queryKey: ["status"], queryFn: () => apiGet<SystemStatus>("/api/status"),
  });
  const { data: audit } = useQuery({
    queryKey: ["audit"], queryFn: () => apiGet<AuditEvent[]>("/api/audit?limit=50"),
  });

  const flatten = useMutation({
    mutationFn: (reason: string) =>
      apiPost("/api/risk/flatten-all", { confirm_phrase: "FLATTEN ALL", reason }),
    onError: (error) => {
      const msg = error instanceof ApiError ? error.message : String(error);
      toast(error instanceof ApiError && error.status === 501 ? "info" : "error", msg);
      queryClient.invalidateQueries({ queryKey: ["audit"] });
    },
  });

  return (
    <div className="space-y-4">
      <Card
        title="Emergency controls"
        right={<Badge tone={status?.controls_enabled ? "violet" : "gray"}>
          {status?.controls_enabled ? "controls enabled" : "read-only (DASHBOARD_CONTROLS_ENABLED=false)"}
        </Badge>}
      >
        <div className="flex flex-wrap items-center gap-4">
          <KillSwitchControl />
          <Button tone="danger" onClick={() => setFlattenOpen(true)}>Flatten all…</Button>
          <div className="text-xs text-zinc-500">
            Every action requires a typed confirmation phrase, is re-validated server-side,
            and is written to the audit trail below.
          </div>
        </div>
      </Card>

      <Card title="Risk limits">
        <div className="space-y-2">
          {(risk?.limits ?? []).map((limit) => (
            <div key={limit.name} className="flex items-center gap-3">
              <div className="w-44 shrink-0 text-sm text-zinc-300">{limit.name}</div>
              <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-zinc-800">
                <div
                  className={`h-full rounded-full transition-all ${
                    limit.status === "breached" ? "bg-red-500" : limit.status === "warning" ? "bg-amber-500" : "bg-emerald-600"
                  }`}
                  style={{ width: `${Math.min(100, limit.pct_used)}%` }}
                />
              </div>
              <div className="w-36 shrink-0 text-right text-xs mono text-zinc-400">
                {limit.current} / {limit.limit}
              </div>
              <div className="w-20 shrink-0 text-right">
                <Badge tone={statusTone(limit.status)}>{limit.pct_used.toFixed(0)}%</Badge>
              </div>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs text-zinc-600">
          Limits come from config/risk_limits.yaml with .env overrides. Per-order limits
          (notional, slippage) are enforced at validation time on every single order.
        </p>
      </Card>

      <Card title="Audit trail (dashboard actions)">
        <DataTable
          rows={(audit ?? []) as unknown as Record<string, unknown>[]}
          emptyText="No dashboard actions recorded yet"
          csvName="audit.csv"
          columns={[
            { key: "ts", label: "time", render: (r) => <span className="mono text-xs">{fmtTs(String(r.ts))}</span> },
            { key: "actor", label: "actor" },
            { key: "action", label: "action", render: (r) => <Badge tone="blue">{String(r.action)}</Badge> },
            { key: "mode", label: "mode" },
            { key: "confirmed", label: "confirmed", render: (r) => <Badge tone={r.confirmed ? "green" : "red"}>{String(r.confirmed)}</Badge> },
            { key: "result", label: "result", render: (r) => <span className="text-xs text-zinc-400">{String(r.result).slice(0, 80)}</span> },
          ]}
        />
      </Card>

      <ConfirmModal
        open={flattenOpen}
        title="Flatten all positions"
        description="Requests immediate closure of every open position. In this deployment live order connectors are gated off, so the backend will refuse with an explanation — the request is still audited. Use the kill switch to halt order flow."
        phrase="FLATTEN ALL"
        mode={status?.mode ?? "?"}
        onClose={() => setFlattenOpen(false)}
        onConfirm={(reason) => { setFlattenOpen(false); flatten.mutate(reason); }}
      />
    </div>
  );
}
