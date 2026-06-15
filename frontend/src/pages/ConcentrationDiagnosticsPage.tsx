import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { MarkdownReport } from "../lib/productTypes";
import { useAction } from "../lib/useAction";
import { useControls } from "../lib/useControls";
import { Card, Badge, Button, PageHeader, Tabs, EmptyState, StatusBadge } from "../components/ui";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import JobProgress from "../components/JobProgress";
import { Icons } from "../components/icons";
import { NotLiveBanner, Loader, ReportBlock } from "../components/Banners";
import { fmtNum } from "../lib/formatters";
import type { Column } from "../components/DataTable";

const STRATEGY = "long_only_xsec_momentum";

export default function ConcentrationDiagnosticsPage() {
  const qc = useQueryClient();
  const report = useQuery({
    queryKey: ["concentration"],
    queryFn: () => apiGet<MarkdownReport>(`/api/concentration/${STRATEGY}?universe=us_stocks_50`),
  });
  const rerun = useAction("/api/long-only/concentration/run", {
    onDone: () => qc.invalidateQueries({ queryKey: ["concentration"] }),
  });
  const compare = useAction("/api/long-only/concentration/compare-fixes", {
    onDone: () => qc.invalidateQueries({ queryKey: ["concentration"] }),
  });
  const [tab, setTab] = useState("result");
  const controls = useControls();

  const res = rerun.job?.status === "succeeded" ? rerun.job.result : undefined;
  const rows = (res?.rows as Record<string, unknown>[] | undefined) ?? [];
  const gatePass = res?.gate_pass === true;
  const cols: Column<Record<string, unknown>>[] = rows.length
    ? Object.keys(rows[0]).map((k) => ({
        key: k, label: k.replace(/_/g, " "),
        render: (r) => typeof r[k] === "boolean"
          ? <Badge tone={r[k] ? "green" : "red"}>{String(r[k])}</Badge>
          : String(r[k]),
      }))
    : [];

  return (
    <div className="space-y-5">
      <PageHeader
        title="Concentration Diagnostics"
        description="How much of the edge concentrates in a few names, sectors or days — and whether the return-concentration gate passes. EWMA α=0.5 smoothing closed this gate (worst month 26.1% → 23.5%)."
        badges={res ? <StatusBadge status={gatePass ? "pass" : "failed"} label={gatePass ? "GATE PASS" : "GATE FAIL"} /> : <Badge tone="red" dot>NOT LIVE ELIGIBLE</Badge>}
        actions={
          <>
            <Button tone="primary" icon={<Icons.refresh size={15} />}
              disabled={rerun.busy || !controls} title={!controls ? "controls are read-only" : undefined}
              onClick={() => { setTab("result"); rerun.run({ params: { strategy: STRATEGY, universe: "us_stocks_50", method: "ewma" }, reason: "operator dashboard" }); }}>
              Rerun concentration
            </Button>
            <Button tone="secondary" icon={<Icons.layers size={15} />}
              disabled={compare.busy || !controls} title={!controls ? "controls are read-only" : undefined}
              onClick={() => { setTab("compare"); compare.run({ params: { strategy: STRATEGY, universe: "us_stocks_50" }, reason: "operator dashboard" }); }}>
              Compare EWMA vs unsmoothed
            </Button>
          </>
        }
      />

      {(rerun.job || compare.job) && (
        <div className="space-y-2">
          {rerun.job && <JobProgress job={rerun.job} />}
          {compare.job && <JobProgress job={compare.job} />}
        </div>
      )}

      {res && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <MetricCard label="Baseline OOS Sharpe" value={fmtNum(res.baseline_oos_sharpe as number, 3)} accent="info" />
          <MetricCard label="Smoothing" value={String(res.smoothing ?? "—")} />
          <MetricCard label="Sleeves" value={(res.sleeves as string[] | undefined)?.length ?? "—"} />
          <MetricCard label="Gate" value={<Badge tone={gatePass ? "green" : "red"}>{gatePass ? "PASS" : "FAIL"}</Badge>} accent={gatePass ? "ok" : "danger"} />
        </div>
      )}

      <Tabs active={tab} onChange={setTab} tabs={[
        { id: "result", label: "Latest run" },
        { id: "compare", label: "EWMA vs unsmoothed" },
        { id: "report", label: "Last report" },
      ]} />

      {tab === "result" && (
        <Card title="Concentration evaluation" subtitle="Per-sleeve out-of-sample concentration and the gate">
          {rows.length === 0
            ? <EmptyState icon={<Icons.chart size={28} />} text="No run yet"
                hint="click “Rerun concentration” to evaluate the gate" />
            : <DataTable rows={rows} columns={cols} csvName="concentration_rows.csv" />}
        </Card>
      )}

      {tab === "compare" && (
        <Card title="EWMA smoothing vs unsmoothed" subtitle="Does the smoothing meaningfully reduce concentration?">
          {compare.job?.status === "succeeded" ? (
            <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs text-zinc-300">
              {String(compare.job.result?.log_tail ?? "(no output)")}
            </pre>
          ) : (
            <EmptyState text="No comparison run yet"
              hint="click “Compare EWMA vs unsmoothed”" />
          )}
        </Card>
      )}

      {tab === "report" && (
        <Loader data={report.data} error={report.error} isLoading={report.isLoading}>
          {(d) => (
            <Card title={d.available ? `Report — ${d.file ?? ""}` : "No saved report"}>
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
