import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, ApiError } from "../lib/api";
import type { StrategyStatus } from "../lib/types";
import { fmtMoney, fmtTs, pnlTone } from "../lib/formatters";
import { Badge, Button, Card, statusTone } from "../components/ui";
import { useUi } from "../store/ui";

export default function Strategies() {
  const queryClient = useQueryClient();
  const toast = useUi((s) => s.toast);
  const { data: strategies } = useQuery({
    queryKey: ["strategies"], queryFn: () => apiGet<StrategyStatus[]>("/api/strategies"),
  });

  const toggle = useMutation({
    mutationFn: ({ name, paused }: { name: string; paused: boolean }) =>
      apiPost(`/api/strategies/${name}/${paused ? "resume" : "pause"}`),
    onSuccess: (_, vars) => {
      toast("success", `${vars.name} ${vars.paused ? "resumed" : "paused"}.`);
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
    },
    onError: (error) =>
      toast("error", error instanceof ApiError ? error.message : String(error)),
  });

  return (
    <div className="space-y-4">
      <p className="text-xs text-zinc-500">
        Pausing a strategy stops NEW paper entries on the next polling cycle (the paper
        trader reads runtime/paused_strategies.json); open pairs keep being managed to exit.
        Requires dashboard controls to be enabled.
      </p>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(strategies ?? []).map((s) => (
          <Card
            key={s.name}
            title={<span className="mono">{s.name} <span className="text-zinc-600">v{s.version}</span></span>}
            right={<Badge tone={statusTone(s.health)}>{s.health}</Badge>}
          >
            <div className="grid grid-cols-2 gap-y-1.5 text-sm">
              <span className="text-zinc-500">kind</span><span>{s.kind}</span>
              <span className="text-zinc-500">trades</span><span className="mono">{s.n_trades}</span>
              <span className="text-zinc-500">total pnl</span>
              <span className={`mono ${pnlTone(s.total_pnl)}`}>{fmtMoney(s.total_pnl)}</span>
              <span className="text-zinc-500">win rate</span>
              <span className="mono">{s.win_rate_pct === null ? "—" : `${s.win_rate_pct}%`}</span>
              <span className="text-zinc-500">fees</span><span className="mono">{fmtMoney(s.total_fees)}</span>
              <span className="text-zinc-500">last signal</span>
              <span className="mono text-xs">{fmtTs(s.last_signal_ts)}</span>
            </div>
            <div className="mt-4">
              <Button
                tone={s.paused ? "primary" : "default"}
                onClick={() => toggle.mutate({ name: s.name, paused: s.paused })}
              >
                {s.paused ? "Resume (paper)" : "Pause new entries"}
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
