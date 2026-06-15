import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { MarkdownReport } from "../lib/productTypes";
import { useAction } from "../lib/useAction";
import { useControls } from "../lib/useControls";
import { Card, Badge, Button, PageHeader, Tabs, EmptyState } from "../components/ui";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import JobProgress from "../components/JobProgress";
import { ChartCard, ScenarioDrawdownChart } from "../components/charts";
import { Icons } from "../components/icons";
import { NotLiveBanner, Loader, ReportBlock } from "../components/Banners";
import { fmtPct } from "../lib/formatters";
import type { Column } from "../components/DataTable";

const STRATEGY = "long_only_xsec_momentum";
const VERDICT_TONE: Record<string, string> = {
  BOUNDED: "green", "DEEP BUT SURVIVABLE": "yellow", CATASTROPHIC: "red",
};

function scenarioName(r: Record<string, unknown>): string {
  if (typeof r.index === "string") return r.index;
  if (typeof r.scenario === "string") return r.scenario;
  const firstStr = Object.values(r).find((v) => typeof v === "string");
  return String(firstStr ?? "scenario");
}

export default function CrisisLabPage() {
  const qc = useQueryClient();
  const report = useQuery({
    queryKey: ["crisis"],
    queryFn: () => apiGet<MarkdownReport>(`/api/crisis/${STRATEGY}?universe=us_stocks_50`),
  });
  const rerun = useAction("/api/long-only/crisis/run", {
    onDone: () => qc.invalidateQueries({ queryKey: ["crisis"] }),
  });
  const [tab, setTab] = useState("result");
  const controls = useControls();

  const res = rerun.job?.status === "succeeded" ? rerun.job.result : undefined;
  const scenarios = (res?.scenarios as Record<string, unknown>[] | undefined) ?? [];
  const verdict = String(res?.verdict ?? "");
  const chartData = scenarios
    .map((r) => ({ scenario: scenarioName(r), dd: Number(r.crisis_max_dd_pct ?? 0) }))
    .filter((d) => Number.isFinite(d.dd) && d.scenario !== "base");

  const cols: Column<Record<string, unknown>>[] = scenarios.length
    ? Object.keys(scenarios[0]).map((k) => ({
        key: k, label: k.replace(/_/g, " "),
        align: typeof scenarios[0][k] === "number" ? "right" : "left",
        render: (r) => typeof r[k] === "number" ? Number(r[k]).toFixed(2) : String(r[k]),
      }))
    : [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Crisis Lab"
        description="Synthetic 2008/2020-style stress for the long-only book — the live window has no real tail, so these are proxy injections that bound the downside. The regime filter is the real crash protection (regime-off worst DD ≈ −51%)."
        badges={verdict ? <Badge tone={VERDICT_TONE[verdict] ?? "yellow"}>{verdict}</Badge> : <Badge tone="red" dot>NOT LIVE ELIGIBLE</Badge>}
        actions={
          <Button tone="primary" icon={<Icons.refresh size={15} />}
            disabled={rerun.busy || !controls} title={!controls ? "controls are read-only" : undefined}
            onClick={() => { setTab("result"); rerun.run({ params: { strategy: STRATEGY, universe: "us_stocks_50" }, reason: "operator dashboard" }); }}>
            Rerun crisis test
          </Button>
        }
      />

      {rerun.job && <JobProgress job={rerun.job} />}

      {res && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <MetricCard label="Worst crisis DD" value={fmtPct(res.worst_crisis_dd_pct as number, 1)}
            accent={(res.worst_crisis_dd_pct as number) <= -45 ? "danger" : "warn"} sub={String(res.worst_scenario ?? "")} />
          <MetricCard label="Base full DD" value={fmtPct(res.base_full_dd_pct as number, 1)} />
          <MetricCard label="Bounded (> −45%)" value={<Badge tone={res.bounded ? "green" : "red"}>{String(res.bounded)}</Badge>} accent={res.bounded ? "ok" : "danger"} />
          <MetricCard label="Verdict" value={verdict} tone={verdict === "BOUNDED" ? "text-emerald-400" : verdict === "CATASTROPHIC" ? "text-red-400" : "text-amber-400"} />
        </div>
      )}

      <Tabs active={tab} onChange={setTab} tabs={[
        { id: "result", label: "Scenario drawdowns" },
        { id: "table", label: "Scenario table" },
        { id: "regime", label: "Regime filter" },
        { id: "report", label: "Last report" },
      ]} />

      {tab === "result" && (
        chartData.length > 0 ? (
          <ChartCard title="Per-scenario max drawdown (synthetic)" height={300}
            right={<Badge tone="gray">red ≤ −45%</Badge>}>
            <ScenarioDrawdownChart data={chartData} height={300} />
          </ChartCard>
        ) : (
          <Card><EmptyState icon={<Icons.flask size={28} />} text="No crisis run yet"
            hint="click “Rerun crisis test” (synthetic suite)" /></Card>
        )
      )}

      {tab === "table" && (
        <Card title="Scenario results" subtitle="Each row is a synthetic stress scenario">
          {scenarios.length === 0 ? <EmptyState text="No scenarios yet" />
            : <DataTable rows={scenarios} columns={cols} csvName="crisis_scenarios.csv" />}
        </Card>
      )}

      {tab === "regime" && (
        <Card title="Regime filter on / off" icon={<Icons.shield size={15} />}>
          <p className="text-sm text-zinc-300">
            The crisis suite above runs with the regime filter <b>ON</b> — the configuration that
            would actually trade. The filter is the book's real crash protection.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <MetricCard label="Regime ON — worst DD" value={res ? fmtPct(res.worst_crisis_dd_pct as number, 1) : "≈ −28%"} accent="ok" sub="synthetic crisis" />
            <MetricCard label="Regime OFF — worst DD" value="≈ −51%" accent="danger" sub="from research audit" />
          </div>
          <p className="mt-3 text-xs text-zinc-500">
            Regime-off figures are recorded in the research audit; the dashboard reruns only the
            regime-on (tradable) configuration.
          </p>
        </Card>
      )}

      {tab === "report" && (
        <Loader data={report.data} error={report.error} isLoading={report.isLoading}>
          {(d) => (
            <Card title={d.available ? "Long-only crisis report (SYNTHETIC)" : "No saved report"}>
              {d.available ? <ReportBlock report={d.report} />
                : <p className="text-sm text-zinc-400">{d.report}</p>}
            </Card>
          )}
        </Loader>
      )}

      <NotLiveBanner />
    </div>
  );
}
