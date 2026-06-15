import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { OrderPreviewResult, Trading212Config } from "../lib/productTypes";
import { useAction } from "../lib/useAction";
import {
  Card, Badge, Button, PageHeader, Field, inputCls, Tabs, EmptyState, StatusBadge,
} from "../components/ui";
import MetricCard from "../components/MetricCard";
import DataTable from "../components/DataTable";
import JobProgress from "../components/JobProgress";
import { Icons } from "../components/icons";
import { NotLiveBanner, Loader } from "../components/Banners";
import { fmtMoney } from "../lib/formatters";

export default function Trading212OrderPreviewPage() {
  const cfg = useQuery({
    queryKey: ["t212-config"],
    queryFn: () => apiGet<Trading212Config>("/api/trading212-config"),
  });
  const preview = useAction("/api/trading212/order-preview");
  const [cash, setCash] = useState(10000);
  const [tab, setTab] = useState("orders");

  const res = preview.job?.status === "succeeded"
    ? (preview.job.result as unknown as OrderPreviewResult) : undefined;
  const v = res?.validation;
  const sum = res?.summary;

  const generate = (mode: "shadow" | "demo_preview") =>
    preview.run({ params: { mode, starting_cash: cash }, reason: "operator dashboard" });

  return (
    <div className="space-y-5">
      <PageHeader
        title="Order Preview"
        description="See exactly what a supervised paper day would plan today — target weights, planned buys/sells, skipped orders, fees and validation. This view connects to no broker and sends nothing."
        badges={<Badge tone="red" dot>NOT LIVE ELIGIBLE</Badge>}
        actions={
          <>
            <Button tone="primary" icon={<Icons.eye size={15} />}
              disabled={preview.busy} onClick={() => generate("shadow")}>
              Generate shadow preview
            </Button>
            <Button tone="demo" icon={<Icons.eye size={15} />}
              disabled={preview.busy} onClick={() => generate("demo_preview")}>
              Generate demo preview
            </Button>
          </>
        }
      />

      {/* The one rule that governs this page. */}
      <div className="flex flex-col gap-2 rounded-xl border border-violet-500/30 bg-violet-500/10 px-4 py-3 text-sm text-violet-200 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-2">
          <Icons.lock size={16} />
          <span>Demo execution is only available inside the gated supervised paper daily run. There is no order-sending button on this page.</span>
        </div>
        <Link to="/supervised-paper" className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-violet-500/40 px-3 py-1.5 text-xs font-medium text-violet-100 hover:bg-violet-500/20">
          Go to Supervised Paper <Icons.arrowRight size={13} />
        </Link>
      </div>

      {/* Trading 212 connection — booleans only, secrets never shown. */}
      <Card title="Trading 212 connection" subtitle="Booleans only — secrets are never sent to the browser"
        icon={<Icons.broker size={15} />}>
        <Loader data={cfg.data} error={cfg.error} isLoading={cfg.isLoading}>
          {(c) => (
            <div className="flex flex-wrap gap-2">
              <Badge tone={c.enabled ? "green" : "gray"}>enabled: {String(c.enabled)}</Badge>
              <Badge tone={c.mode === "demo" ? "green" : "red"}>mode: {c.mode}</Badge>
              <Badge tone={c.api_key_configured ? "green" : "gray"}>API key: {c.api_key_configured ? "configured" : "not set"}</Badge>
              <Badge tone={c.allow_demo_orders ? "violet" : "gray"}>demo orders: {c.allow_demo_orders ? "allowed" : "blocked"}</Badge>
              <Badge tone="red">live orders: unsupported</Badge>
              <Badge tone={c.kill_switch_active ? "red" : "green"}>kill switch: {c.kill_switch_active ? "ACTIVE" : "off"}</Badge>
            </div>
          )}
        </Loader>
      </Card>

      {/* Generate controls + progress. */}
      <Card title="Generate a preview" icon={<Icons.refresh size={15} />}>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Starting cash" hint="simulated book value">
            <input type="number" className={inputCls} value={cash}
              onChange={(e) => setCash(Number(e.target.value))} />
          </Field>
          <Button tone="primary" disabled={preview.busy} onClick={() => generate("shadow")}>
            Generate shadow preview
          </Button>
          <Button tone="demo" disabled={preview.busy} onClick={() => generate("demo_preview")}>
            Generate demo preview (offline)
          </Button>
        </div>
        <p className="mt-2 text-xs text-zinc-500">
          Both previews run the exact same validated planner the supervised paper day uses and
          send nothing. The demo preview additionally reports whether the demo gate is configured.
        </p>
        {preview.job && <div className="mt-3"><JobProgress job={preview.job} /></div>}
      </Card>

      {!res && !preview.busy && (
        <Card><EmptyState icon={<Icons.list size={28} />} text="No preview generated yet"
          hint="click “Generate shadow preview” to see today’s plan" /></Card>
      )}

      {res && sum && v && (
        <>
          {/* Summary metrics. */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <MetricCard label="Planned orders" value={sum.n_orders} accent="info" />
            <MetricCard label="Buys / Sells" value={`${sum.n_buys} / ${sum.n_sells}`} />
            <MetricCard label="Skipped" value={sum.n_skipped}
              accent={sum.n_skipped > 0 ? "warn" : "muted"} />
            <MetricCard label="Cash after" value={fmtMoney(sum.cash_after)} sub={`from ${fmtMoney(sum.cash_before)}`} />
            <MetricCard label="Est. slippage" value={`${sum.expected_slippage_bps} bps`} sub="marketable-limit budget" />
            <MetricCard label="Validation"
              value={<Badge tone={v.ok ? "green" : "red"}>{v.ok ? "PASS" : "FAIL"}</Badge>}
              accent={v.ok ? "ok" : "danger"} />
          </div>

          {/* Status row. */}
          <div className="flex flex-wrap gap-2">
            <Badge tone={sum.market_open ? "green" : "yellow"}>
              market: {sum.market_open ? "open" : "closed (orders queue for open)"}
            </Badge>
            <Badge tone={res.demo_eligible ? "violet" : "gray"}>
              demo eligibility: {res.demo_eligible ? "configured" : "not enabled"}
            </Badge>
            <Badge tone="gray">{res.demo_note}</Badge>
            <Badge tone="red">live execution: hard-blocked</Badge>
          </div>

          <Tabs
            active={tab}
            onChange={setTab}
            tabs={[
              { id: "orders", label: `Planned orders (${res.orders.length})` },
              { id: "weights", label: `Target weights (${res.target_weights.length})` },
              { id: "skipped", label: `Skipped (${res.skipped.length})` },
              { id: "checks", label: "Validation checks" },
            ]}
          />

          {tab === "orders" && (
            <Card title="Planned orders" subtitle="The exact plan — nothing is sent">
              {res.orders.length === 0
                ? <EmptyState text="No orders planned (book already on target)" />
                : (
                  <DataTable
                    rows={res.orders}
                    csvName="order_preview.csv"
                    searchKeys={["symbol", "side"]}
                    columns={[
                      { key: "symbol", label: "symbol" },
                      { key: "side", label: "side", render: (r) => <Badge tone={r.side === "buy" ? "green" : "yellow"}>{String(r.side)}</Badge> },
                      { key: "type", label: "type" },
                      { key: "quantity", label: "qty", align: "right", render: (r) => Number(r.quantity).toFixed(4) },
                      { key: "limit_price", label: "limit", align: "right", render: (r) => (r.limit_price == null ? "—" : fmtMoney(Number(r.limit_price))) },
                      { key: "notional", label: "notional", align: "right", render: (r) => fmtMoney(Number(r.notional)) },
                      { key: "target_weight", label: "tgt wt", align: "right", render: (r) => `${(Number(r.target_weight) * 100).toFixed(1)}%` },
                      { key: "queued_for_open", label: "queued", render: (r) => (r.queued_for_open ? <Badge tone="yellow">open</Badge> : "—") },
                    ]}
                  />
                )}
            </Card>
          )}

          {tab === "weights" && (
            <Card title="Smoothed target weights" subtitle="EWMA-smoothed long-only targets feeding the plan">
              {res.target_weights.length === 0 ? <EmptyState text="No target weights" /> : (
                <DataTable
                  rows={res.target_weights as unknown as Record<string, unknown>[]}
                  csvName="target_weights.csv"
                  searchKeys={["symbol"]}
                  columns={[
                    { key: "symbol", label: "symbol" },
                    { key: "weight", label: "weight", align: "right", sortValue: (r) => Number(r.weight), render: (r) => `${(Number(r.weight) * 100).toFixed(2)}%` },
                  ]}
                />
              )}
            </Card>
          )}

          {tab === "skipped" && (
            <Card title="Skipped orders" subtitle="Why a target was not turned into an order">
              {res.skipped.length === 0
                ? <EmptyState icon={<Icons.check size={28} />} text="Nothing skipped — every target was tradable" />
                : (
                  <div className="space-y-1.5">
                    {res.skipped.map(([sym, reason], i) => (
                      <div key={`${sym}-${i}`} className="flex items-start gap-2 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm">
                        <Badge tone="yellow">skipped</Badge>
                        <div><span className="text-zinc-200">{sym}</span>
                          <span className="text-xs text-zinc-500"> — {reason}</span></div>
                      </div>
                    ))}
                  </div>
                )}
            </Card>
          )}

          {tab === "checks" && (
            <Card title="Risk & tradability validation" subtitle="Plan-level checks (re-run server-side before any demo send)">
              <div className="grid gap-1.5 md:grid-cols-2">
                {Object.entries(v.checks).map(([name, ok]) => (
                  <div key={name} className="flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 text-sm">
                    <StatusBadge status={ok ? "pass" : "failed"} label={ok ? "PASS" : "FAIL"} />
                    <span className="text-zinc-300">{name}</span>
                  </div>
                ))}
              </div>
              {v.issues.length > 0 && (
                <div className="mt-3 space-y-1">
                  <div className="text-xs font-semibold uppercase tracking-wider text-amber-300/80">Order issues</div>
                  {v.issues.map(([sym, issue], i) => (
                    <div key={`${sym}-${i}`} className="text-xs text-amber-200/80">{sym}: {issue}</div>
                  ))}
                </div>
              )}
            </Card>
          )}
        </>
      )}

      <NotLiveBanner />
    </div>
  );
}
