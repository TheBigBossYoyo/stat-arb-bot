import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, ApiError } from "../lib/api";
import type { RiskStatus, SystemStatus } from "../lib/types";
import { useUi } from "../store/ui";
import ConfirmModal from "./ConfirmModal";
import { Button } from "./ui";

export default function KillSwitchControl({ compact = false }: { compact?: boolean }) {
  const queryClient = useQueryClient();
  const toast = useUi((s) => s.toast);
  const [modal, setModal] = useState<"activate" | "deactivate" | null>(null);

  const { data: risk } = useQuery({
    queryKey: ["risk"],
    queryFn: () => apiGet<RiskStatus>("/api/risk/status"),
    refetchInterval: 10000,
  });
  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: () => apiGet<SystemStatus>("/api/status"),
  });

  const act = useMutation({
    mutationFn: ({ action, reason }: { action: "activate" | "deactivate"; reason: string }) =>
      apiPost(`/api/risk/kill-switch/${action}`, {
        confirm_phrase: action === "activate" ? "ACTIVATE KILL SWITCH" : "DEACTIVATE KILL SWITCH",
        reason,
      }),
    onSuccess: (_, vars) => {
      toast("success", `Kill switch ${vars.action}d.`);
      queryClient.invalidateQueries();
    },
    onError: (error) => {
      toast("error", error instanceof ApiError ? error.message : String(error));
    },
  });

  const active = risk?.kill_switch.active ?? false;

  return (
    <div className={compact ? "" : "flex items-center gap-3"}>
      <div className={`mb-2 flex items-center gap-2 text-xs ${compact ? "" : "mb-0"}`}>
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${active ? "bg-red-500 animate-pulse" : "bg-emerald-500"}`} />
        <span className={active ? "font-semibold text-red-400" : "text-zinc-400"}>
          {active ? `KILL SWITCH ACTIVE${risk?.kill_switch.reason ? `: ${risk.kill_switch.reason}` : ""}` : "kill switch off"}
        </span>
      </div>
      {active ? (
        <Button tone="default" onClick={() => setModal("deactivate")}>Disengage…</Button>
      ) : (
        <Button tone="danger" onClick={() => setModal("activate")}>KILL SWITCH</Button>
      )}

      <ConfirmModal
        open={modal === "activate"}
        title="Activate kill switch"
        description="Immediately halts ALL new order flow across every strategy and broker connector. Open paper positions keep being managed (exits only). This persists across restarts until manually disengaged."
        phrase="ACTIVATE KILL SWITCH"
        mode={status?.mode ?? "?"}
        onClose={() => setModal(null)}
        onConfirm={(reason) => { setModal(null); act.mutate({ action: "activate", reason }); }}
      />
      <ConfirmModal
        open={modal === "deactivate"}
        title="Deactivate kill switch"
        description="Re-enables order flow. Only do this after you understand and have addressed whatever engaged it. Requires admin controls."
        phrase="DEACTIVATE KILL SWITCH"
        mode={status?.mode ?? "?"}
        onClose={() => setModal(null)}
        onConfirm={(reason) => { setModal(null); act.mutate({ action: "deactivate", reason }); }}
      />
    </div>
  );
}
