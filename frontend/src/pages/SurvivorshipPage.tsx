import { useAction } from "../lib/useAction";
import { Card, Badge, Button } from "../components/ui";
import MetricCard from "../components/MetricCard";
import JobProgress from "../components/JobProgress";
import { NotLiveBanner, PageTitle } from "../components/Banners";
import { fmtNum } from "../lib/formatters";

interface SurvRow extends Record<string, unknown> { scenario?: string }

const VERDICT_TONE: Record<string, string> = { eliminated: "green", bounded: "yellow", unresolved: "red" };

export default function SurvivorshipPage() {
  const run = useAction("/api/long-only/survivorship/run");
  const res = run.job?.status === "succeeded" ? run.job.result : undefined;
  const rows = (res?.rows as SurvRow[] | undefined) ?? [];
  const verdict = String(res?.verdict ?? "");

  return (
    <div className="space-y-4">
      <PageTitle title="Survivorship Stress" subtitle="Bound how much the edge depends on the exact survivor set (random / sector / best-5 / worst-5 / bootstrap)." />
      <NotLiveBanner />

      <Card title="Run the survivorship bound">
        <div className="flex flex-wrap items-center gap-3">
          <Button tone="primary" disabled={run.busy}
                  onClick={() => run.run({ params: { strategy: "long_only_xsec_momentum", universe: "us_stocks_50" }, reason: "operator dashboard" })}>
            Run survivorship stress
          </Button>
          {verdict && <Badge tone={VERDICT_TONE[verdict] ?? "yellow"}>verdict: {verdict.toUpperCase()}</Badge>}
          <span className="text-xs text-zinc-500">Only a point-in-time constituent backtest can ELIMINATE the bias — this bounds it.</span>
        </div>
        {run.job && <div className="mt-3"><JobProgress job={run.job} /></div>}
      </Card>

      {res && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <MetricCard label="Median Sharpe" value={fmtNum(res.median_sharpe as number, 3)} />
            <MetricCard label="5th-pct Sharpe" value={fmtNum(res.sharpe_p05 as number, 3)} />
            <MetricCard label="Worst-case DD" value={`${fmtNum(res.worst_case_dd_pct as number, 1)}%`} />
            <MetricCard label="Verdict" value={verdict.toUpperCase()} tone={verdict === "bounded" ? "text-amber-400" : verdict === "eliminated" ? "text-emerald-400" : "text-red-400"} />
          </div>
          {rows.length > 0 && (
            <Card title="Scenarios">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs uppercase tracking-wider text-zinc-500">
                    <tr>{Object.keys(rows[0]).map((k) => <th key={k} className="px-2 py-1 text-left">{k}</th>)}</tr>
                  </thead>
                  <tbody>
                    {rows.map((r, i) => (
                      <tr key={i} className="border-t border-zinc-800">
                        {Object.keys(rows[0]).map((k) => <td key={k} className="px-2 py-1 text-zinc-300">{String(r[k])}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
