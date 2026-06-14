import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { DeflatedSharpe } from "../lib/productTypes";
import { Card } from "../components/ui";
import MetricCard from "../components/MetricCard";
import { fmtNum } from "../lib/formatters";
import { NotLiveBanner, PageTitle, Loader, ReportBlock } from "../components/Banners";

export default function DeflatedSharpePage() {
  const q = useQuery({ queryKey: ["deflated-sharpe"], queryFn: () => apiGet<DeflatedSharpe>("/api/deflated-sharpe") });
  return (
    <div className="space-y-4">
      <PageTitle title="Deflated Sharpe / Trial Family" subtitle="The market-neutral flagship deflated against the real ~45-config search." />
      <NotLiveBanner />
      <Loader data={q.data} error={q.error} isLoading={q.isLoading}>
        {(d) => (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <MetricCard label="Trials in family" value={d.n_trials} />
              <MetricCard label="With Sharpe" value={d.with_sharpe} />
              <MetricCard label="Best Sharpe" value={fmtNum(d.best_sharpe, 2)} />
              <MetricCard label="Mean Sharpe" value={fmtNum(d.mean_sharpe, 2)} sub={`σ ${fmtNum(d.std_sharpe, 2)}`} />
            </div>
            <Card title={`Deflated-Sharpe report — ${d.group}`}>
              {d.report ? <ReportBlock report={d.report} />
                : <p className="text-sm text-zinc-400">Run <code className="mono">statarb deflated-sharpe-report</code>.</p>}
            </Card>
          </>
        )}
      </Loader>
    </div>
  );
}
