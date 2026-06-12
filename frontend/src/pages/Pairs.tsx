import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, ApiError } from "../lib/api";
import type { JobInfo, PairInfo } from "../lib/types";
import { fmtTs } from "../lib/formatters";
import DataTable from "../components/DataTable";
import { Badge, Button, Card, Field, inputCls } from "../components/ui";
import { useUi } from "../store/ui";

export default function Pairs() {
  const queryClient = useQueryClient();
  const toast = useUi((s) => s.toast);
  const [universe, setUniverse] = useState("crypto_top_10");
  const [interval, setInterval_] = useState("15m");
  const [lookback, setLookback] = useState(90);
  const [maxHalfLife, setMaxHalfLife] = useState<string>("");

  const { data: pairs } = useQuery({
    queryKey: ["pairs"], queryFn: () => apiGet<PairInfo[]>("/api/pairs"),
  });
  const { data: jobs } = useQuery({
    queryKey: ["jobs"], queryFn: () => apiGet<JobInfo[]>("/api/jobs"), refetchInterval: 3000,
  });

  const discover = useMutation({
    mutationFn: () =>
      apiPost<JobInfo>("/api/pairs/discover", {
        kind: "discover_pairs", universe, interval, lookback_days: lookback,
        max_half_life: maxHalfLife ? Number(maxHalfLife) : null,
      }),
    onSuccess: (job) => {
      toast("info", `Pair discovery started (job ${job.id}).`);
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
    },
    onError: (error) =>
      toast("error", error instanceof ApiError ? error.message : String(error)),
  });

  return (
    <div className="space-y-4">
      <Card title="Run pair discovery">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="universe">
            <select value={universe} onChange={(e) => setUniverse(e.target.value)} className={inputCls}>
              {["crypto_top_10", "crypto_majors", "synthetic_demo", "us_stocks_demo", "fx_majors"].map((u) => (
                <option key={u}>{u}</option>
              ))}
            </select>
          </Field>
          <Field label="interval">
            <select value={interval} onChange={(e) => setInterval_(e.target.value)} className={inputCls}>
              {["1m", "5m", "15m", "1h", "4h", "1d"].map((i) => <option key={i}>{i}</option>)}
            </select>
          </Field>
          <Field label="lookback (days)">
            <input type="number" value={lookback} onChange={(e) => setLookback(Number(e.target.value))} className={inputCls} />
          </Field>
          <Field label="max half-life (bars, optional)">
            <input value={maxHalfLife} onChange={(e) => setMaxHalfLife(e.target.value)} placeholder="100" className={inputCls} />
          </Field>
          <Button tone="primary" onClick={() => discover.mutate()}>Discover pairs</Button>
        </div>
        <p className="mt-3 text-xs text-zinc-600">
          Engle-Granger + ADF + half-life filters on stored history. Requires data
          downloaded first (statarb download-data). Looser thresholds = weaker evidence.
        </p>
      </Card>

      {(jobs ?? []).filter((j) => j.kind === "discover_pairs").slice(0, 3).map((job) => (
        <div key={job.id} className="rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-2 text-sm">
          <Badge tone={job.status === "done" ? "green" : job.status === "failed" ? "red" : "yellow"}>{job.status}</Badge>
          <span className="ml-2 text-zinc-400 mono text-xs">job {job.id}</span>
          {job.status === "done" && <span className="ml-2 text-zinc-300">{String(job.result.n_pairs)} pairs: {(job.result.pairs as string[] ?? []).join(", ")}</span>}
          {job.error && <span className="ml-2 text-red-400">{job.error}</span>}
        </div>
      ))}

      <Card title="Active pairs (all universes)">
        <DataTable
          rows={(pairs ?? []) as unknown as Record<string, unknown>[]}
          searchKeys={["symbol_a", "symbol_b", "universe", "interval"]}
          csvName="pairs.csv"
          emptyText="No pairs saved — run discovery"
          columns={[
            { key: "universe", label: "universe" },
            { key: "interval", label: "tf" },
            { key: "symbol_a", label: "pair", render: (r) => <span className="mono">{String(r.symbol_a)}|{String(r.symbol_b)}</span> },
            { key: "beta", label: "beta", align: "right", render: (r) => Number(r.beta).toFixed(3) },
            { key: "eg_pvalue", label: "EG p", align: "right", render: (r) => <PValue v={Number(r.eg_pvalue)} /> },
            { key: "adf_pvalue", label: "ADF p", align: "right", render: (r) => <PValue v={Number(r.adf_pvalue)} /> },
            { key: "half_life_bars", label: "half-life", align: "right", render: (r) => Number(r.half_life_bars).toFixed(1) },
            { key: "correlation", label: "corr", align: "right", render: (r) => Number(r.correlation).toFixed(2) },
            { key: "score", label: "score", align: "right", render: (r) => Number(r.score).toFixed(2) },
            { key: "window_end", label: "window end", render: (r) => <span className="mono text-xs">{fmtTs(String(r.window_end))}</span> },
            {
              key: "is_active", label: "tradability",
              render: (r) => (
                <Badge tone={String(r.universe) === "fx_majors" ? "gray" : "blue"}>
                  {String(r.universe) === "fx_majors" ? "research only (no FX broker)" : "paper eligible"}
                </Badge>
              ),
            },
          ]}
        />
        <p className="mt-3 text-xs text-zinc-600">
          Live eligibility requires shorting support: Binance spot and Trading 212 Invest/ISA
          cannot short, so market-neutral pairs are paper/research until margin venues
          (disabled by default) or long-only fallback mode are consciously enabled.
        </p>
      </Card>
    </div>
  );
}

function PValue({ v }: { v: number }) {
  const tone = v < 0.01 ? "text-emerald-400" : v < 0.05 ? "text-emerald-500" : v < 0.1 ? "text-amber-400" : "text-red-400";
  return <span className={`mono ${tone}`}>{v.toFixed(4)}</span>;
}
