import { useAction } from "../lib/useAction";
import { useControls } from "../lib/useControls";
import { Card, Badge, Button, PageHeader, StatusBadge, EmptyState } from "../components/ui";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import JobProgress from "../components/JobProgress";
import { Icons } from "../components/icons";
import { NotLiveBanner } from "../components/Banners";
import { fmtNum } from "../lib/formatters";
import type { Column } from "../components/DataTable";

const STRATEGY = "long_only_xsec_momentum";

export default function SurvivorshipPage() {
  const run = useAction("/api/long-only/survivorship/run");
  const controls = useControls();
  const res = run.job?.status === "succeeded" ? run.job.result : undefined;
  const rows = (res?.rows as Record<string, unknown>[] | undefined) ?? [];
  const verdict = String(res?.verdict ?? "");

  const cols: Column<Record<string, unknown>>[] = rows.length
    ? Object.keys(rows[0]).map((k) => ({
        key: k, label: k.replace(/_/g, " "),
        align: typeof rows[0][k] === "number" ? "right" : "left",
        render: (r) => typeof r[k] === "number" ? Number(r[k]).toFixed(3) : String(r[k]),
      }))
    : [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Survivorship Stress"
        description="Bound how much of the edge depends on the exact survivor set (random / sector / best-5 / worst-5 / bootstrap perturbations). Only a point-in-time constituent backtest can ELIMINATE the bias — this bounds it."
        badges={verdict ? <StatusBadge status={verdict} label={verdict.toUpperCase()} /> : <Badge tone="red" dot>NOT LIVE ELIGIBLE</Badge>}
        actions={
          <Button tone="primary" icon={<Icons.refresh size={15} />}
            disabled={run.busy || !controls} title={!controls ? "controls are read-only" : undefined}
            onClick={() => run.run({ params: { strategy: STRATEGY, universe: "us_stocks_50" }, reason: "operator dashboard" })}>
            Rerun survivorship stress
          </Button>
        }
      />

      {run.job && <JobProgress job={run.job} />}

      {res ? (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <MetricCard label="Median Sharpe" value={fmtNum(res.median_sharpe as number, 3)} accent="info" />
            <MetricCard label="5th-pct Sharpe" value={fmtNum(res.sharpe_p05 as number, 3)} />
            <MetricCard label="Worst-case DD" value={`${fmtNum(res.worst_case_dd_pct as number, 1)}%`}
              accent={(res.worst_case_dd_pct as number) <= -45 ? "danger" : "warn"} />
            <MetricCard label="Verdict" value={verdict.toUpperCase()}
              tone={verdict === "bounded" ? "text-amber-400" : verdict === "eliminated" ? "text-emerald-400" : "text-red-400"} />
          </div>

          {rows.length > 0 && (
            <Card title="Perturbation scenarios" subtitle="Sharpe / drawdown under each survivor-set perturbation">
              <DataTable rows={rows} columns={cols} csvName="survivorship_scenarios.csv" />
            </Card>
          )}
        </>
      ) : (
        <Card><EmptyState icon={<Icons.layers size={28} />} text="No survivorship run yet"
          hint="click “Rerun survivorship stress” to bound the bias" /></Card>
      )}

      <NotLiveBanner />
    </div>
  );
}
