import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, ApiError } from "../lib/api";
import type { BacktestSummary, JobInfo } from "../lib/types";
import { fmtTs, pnlTone } from "../lib/formatters";
import DataTable from "../components/DataTable";
import { Badge, Button, Card, Field, inputCls } from "../components/ui";
import { useUi } from "../store/ui";

export default function Backtests() {
  const queryClient = useQueryClient();
  const toast = useUi((s) => s.toast);
  const [strategy, setStrategy] = useState("cointegration_pairs");
  const [universe, setUniverse] = useState("crypto_top_10");
  const [interval, setInterval_] = useState("15m");
  const [days, setDays] = useState<string>("");
  const [barsPerYear, setBarsPerYear] = useState<string>("");

  const { data: runs } = useQuery({
    queryKey: ["backtests"], queryFn: () => apiGet<BacktestSummary[]>("/api/backtests"),
  });
  const { data: jobs } = useQuery({
    queryKey: ["jobs"], queryFn: () => apiGet<JobInfo[]>("/api/jobs"), refetchInterval: 3000,
  });

  const run = useMutation({
    mutationFn: () =>
      apiPost<JobInfo>("/api/backtests/run", {
        kind: "backtest", strategy, universe, interval,
        days: days ? Number(days) : null,
        bars_per_year: barsPerYear ? Number(barsPerYear) : null,
      }),
    onSuccess: (job) => {
      toast("info", `Backtest started (job ${job.id}).`);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error) =>
      toast("error", error instanceof ApiError ? error.message : String(error)),
  });

  const backtestJobs = (jobs ?? []).filter((j) => j.kind === "backtest").slice(0, 3);

  return (
    <div className="space-y-4">
      <Card title="Run a backtest (event-driven, costs included, no lookahead)">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="strategy">
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)} className={inputCls}>
              {["pairs_zscore", "cointegration_pairs", "kalman_pairs"].map((s) => <option key={s}>{s}</option>)}
            </select>
          </Field>
          <Field label="universe (needs saved pairs)">
            <select value={universe} onChange={(e) => setUniverse(e.target.value)} className={inputCls}>
              {["crypto_top_10", "synthetic_demo", "us_stocks_demo", "fx_majors"].map((u) => <option key={u}>{u}</option>)}
            </select>
          </Field>
          <Field label="interval">
            <select value={interval} onChange={(e) => setInterval_(e.target.value)} className={inputCls}>
              {["1m", "5m", "15m", "1h", "4h", "1d"].map((i) => <option key={i}>{i}</option>)}
            </select>
          </Field>
          <Field label="last N days (optional)">
            <input value={days} onChange={(e) => setDays(e.target.value)} className={inputCls} placeholder="all" />
          </Field>
          <Field label="bars/year (252 for daily stocks/FX)">
            <input value={barsPerYear} onChange={(e) => setBarsPerYear(e.target.value)} className={inputCls} placeholder="auto" />
          </Field>
          <Button tone="primary" onClick={() => run.mutate()}>Run backtest</Button>
        </div>
      </Card>

      {backtestJobs.map((job) => (
        <div key={job.id} className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-2 text-sm">
          <Badge tone={job.status === "done" ? "green" : job.status === "failed" ? "red" : "yellow"}>{job.status}</Badge>
          <span className="ml-2 mono text-xs text-zinc-400">job {job.id}</span>
          {job.status === "done" && (
            <Link className="ml-2 text-sky-400 hover:underline"
                  to={`/backtests/${String(job.result.backtest_id)}`}>
              view result #{String(job.result.backtest_id)}
            </Link>
          )}
          {job.error && <span className="ml-2 text-red-400">{job.error}</span>}
        </div>
      ))}

      <Card title="Saved backtests">
        <DataTable
          rows={(runs ?? []) as unknown as Record<string, unknown>[]}
          searchKeys={["strategy", "interval"]}
          csvName="backtests.csv"
          emptyText="No backtests yet — run one above or via the CLI"
          columns={[
            { key: "id", label: "#", render: (r) => <Link className="text-sky-400 hover:underline" to={`/backtests/${r.id}`}>#{String(r.id)}</Link> },
            { key: "strategy", label: "strategy" },
            { key: "interval", label: "tf" },
            { key: "start_ts", label: "from", render: (r) => <span className="mono text-xs">{fmtTs(String(r.start_ts)).slice(0, 10)}</span> },
            { key: "end_ts", label: "to", render: (r) => <span className="mono text-xs">{fmtTs(String(r.end_ts)).slice(0, 10)}</span> },
            {
              key: "ret", label: "return %", align: "right",
              sortValue: (r) => Number((r.metrics as Record<string, unknown>)?.total_return_pct ?? 0),
              render: (r) => {
                const v = Number((r.metrics as Record<string, unknown>)?.total_return_pct ?? NaN);
                return <span className={pnlTone(v)}>{Number.isNaN(v) ? "—" : v.toFixed(2)}</span>;
              },
            },
            {
              key: "sharpe", label: "sharpe", align: "right",
              sortValue: (r) => Number((r.metrics as Record<string, unknown>)?.sharpe ?? 0),
              render: (r) => String((r.metrics as Record<string, unknown>)?.sharpe ?? "—"),
            },
            {
              key: "dd", label: "max dd %", align: "right",
              render: (r) => String((r.metrics as Record<string, unknown>)?.max_drawdown_pct ?? "—"),
            },
            {
              key: "trades", label: "trades", align: "right",
              render: (r) => String((r.metrics as Record<string, unknown>)?.n_trades ?? "—"),
            },
            { key: "created_at", label: "created", render: (r) => <span className="mono text-xs">{fmtTs(String(r.created_at))}</span> },
          ]}
        />
      </Card>
    </div>
  );
}
