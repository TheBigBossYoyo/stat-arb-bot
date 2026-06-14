import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { PaperStatus, PaperFinal } from "../lib/productTypes";
import { Card, Badge, EmptyState } from "../components/ui";
import MetricCard from "../components/MetricCard";
import { EquityChart } from "../components/charts";
import { fmtMoney, fmtPct } from "../lib/formatters";
import { NotLiveBanner, PageTitle, Loader } from "../components/Banners";

export default function SupervisedPaperMonitorPage() {
  const product = "long_only_t212";
  const status = useQuery({
    queryKey: ["paper-status", product],
    queryFn: () => apiGet<PaperStatus>(`/api/paper-status/${product}`),
    refetchInterval: 15000,
  });
  const final = useQuery({
    queryKey: ["paper-final", product],
    queryFn: () => apiGet<PaperFinal>(`/api/paper-final/${product}?min_days=30`),
  });

  return (
    <div className="space-y-4">
      <PageTitle title="Supervised Paper Monitor" subtitle="Forward vs replay days, equity, drift, and the pass/fail recommendation." />
      <NotLiveBanner />

      <Loader data={status.data} error={status.error} isLoading={status.isLoading}>
        {(s) => (!s.active && !s.session_id ? (
          <Card title="No session"><EmptyState text={s.message ?? "no session"} hint="statarb supervised-paper-start --product long_only_t212 --mode shadow" /></Card>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <MetricCard label="Mode" value={s.mode ?? "—"} />
              <MetricCard label="Forward days" value={`${s.forward_days_completed ?? 0} / ${s.min_days ?? 30}`}
                          tone="text-emerald-400" />
              <MetricCard label="Replay days" value={s.replay_days_recorded ?? 0} sub="not forward time" />
              <MetricCard label="Last equity" value={fmtMoney(s.last_equity)} sub={s.last_date} />
            </div>
            <Card title="Session"><div className="flex flex-wrap gap-2">
              <Badge tone={s.active ? "green" : "gray"}>{s.status ?? "—"}</Badge>
              <Badge tone="blue">{s.session_id}</Badge>
              <Badge tone="gray">started {s.started_at}</Badge>
            </div></Card>
          </>
        ))}
      </Loader>

      <Loader data={final.data} error={final.error} isLoading={final.isLoading}>
        {(f) => (!f.available ? (
          <Card title="Final report"><EmptyState text={f.message ?? "no data"} /></Card>
        ) : (
          <>
            {f.equity_curve && f.equity_curve.length > 1 && (
              <Card title="Paper equity curve">
                <EquityChart data={f.equity_curve.map((p) => ({ ts: p.date, equity: p.equity }))} />
              </Card>
            )}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <MetricCard label="Paper PnL" value={fmtPct(f.paper_pnl_pct)} />
              <MetricCard label="Benchmark PnL" value={fmtPct(f.benchmark_pnl_pct ?? null)} />
              <MetricCard label="Max drawdown" value={fmtPct(f.max_drawdown_pct)} />
              <MetricCard label="Recommendation"
                          value={f.recommendation ?? "—"}
                          tone={f.recommendation === "PASS" ? "text-emerald-400" : "text-amber-400"} />
            </div>
            <Card title="Verdict">
              <div className="text-sm text-zinc-200">{f.verdict}</div>
              {f.replay_only_not_forward && (
                <div className="mt-2"><Badge tone="yellow">REPLAY ONLY — not a forward calendar period</Badge></div>
              )}
              <div className="mt-1"><Badge tone="red">live eligible: {String(f.live_eligible ?? false)}</Badge></div>
            </Card>
            <Card title="Checks">
              <div className="space-y-1">
                {Object.entries(f.checks ?? {}).map(([name, ok]) => (
                  <div key={name} className="flex items-center gap-2 text-sm">
                    <Badge tone={ok ? "green" : "red"}>{ok ? "PASS" : "FAIL"}</Badge>
                    <span className="text-zinc-300">{name}</span>
                  </div>
                ))}
              </div>
            </Card>
          </>
        ))}
      </Loader>
    </div>
  );
}
