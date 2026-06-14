import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { OrderPreview, Trading212Config } from "../lib/productTypes";
import { Card, Badge, Button } from "../components/ui";
import DataTable from "../components/DataTable";
import ConfirmModal from "../components/ConfirmModal";
import { fmtMoney } from "../lib/formatters";
import { NotLiveBanner, DemoOnlyBanner, ShadowBanner, PageTitle, Loader } from "../components/Banners";
import { useUi } from "../store/ui";

export default function Trading212OrderPreviewPage() {
  const toast = useUi((s) => s.toast);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const preview = useQuery({
    queryKey: ["order-preview"],
    queryFn: () => apiGet<OrderPreview>("/api/long-only-order-preview"),
  });
  const cfg = useQuery({
    queryKey: ["t212-config"],
    queryFn: () => apiGet<Trading212Config>("/api/trading212-config"),
  });

  return (
    <div className="space-y-4">
      <PageTitle title="Trading 212 Order Preview" subtitle="Today's long-only plan — shadow preview, sends nothing." />
      <NotLiveBanner />
      <ShadowBanner />
      <DemoOnlyBanner />

      <Card title="Trading 212 connection (secrets never shown)">
        <Loader data={cfg.data} error={cfg.error} isLoading={cfg.isLoading}>
          {(c) => (
            <div className="flex flex-wrap gap-2">
              <Badge tone={c.enabled ? "green" : "gray"}>enabled: {String(c.enabled)}</Badge>
              <Badge tone={c.mode === "demo" ? "green" : "red"}>mode: {c.mode}</Badge>
              <Badge tone={c.api_key_configured ? "green" : "gray"}>API key: {c.api_key_configured ? "configured" : "not set"}</Badge>
              <Badge tone={c.api_secret_configured ? "green" : "gray"}>API secret: {c.api_secret_configured ? "configured" : "not set"}</Badge>
              <Badge tone={c.allow_demo_orders ? "green" : "gray"}>demo orders: {c.allow_demo_orders ? "allowed" : "blocked"}</Badge>
              <Badge tone="red">live orders: unsupported</Badge>
              <Badge tone={c.kill_switch_active ? "red" : "green"}>kill switch: {c.kill_switch_active ? "ACTIVE" : "off"}</Badge>
            </div>
          )}
        </Loader>
      </Card>

      <Loader data={preview.data} error={preview.error} isLoading={preview.isLoading}>
        {(p) => (
          <>
            {!p.available && <Card title="Preview unavailable"><p className="text-sm text-red-300">{p.error}</p></Card>}
            {p.available && (
              <>
                <Card title="Planned orders (shadow)" right={
                  <Badge tone={p.validation?.ok ? "green" : "red"}>validation: {p.validation?.ok ? "PASS" : "FAIL"}</Badge>
                }>
                  <DataTable
                    rows={p.orders}
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
                </Card>
                <Card title="Order actions">
                  <div className="flex flex-wrap items-center gap-3">
                    <Button tone="primary" disabled={!cfg.data?.allow_demo_orders}
                            onClick={() => setConfirmOpen(true)}>
                      Execute on DEMO…
                    </Button>
                    <Button tone="danger" disabled>GO LIVE — UNAVAILABLE</Button>
                    <span className="text-xs text-zinc-500">
                      Demo execution is also gated server-side and must be run via the CLI
                      (<code className="mono">paper-trade-long-only --mode demo_execute --confirm-demo</code>).
                      Live is hard-blocked.
                    </span>
                  </div>
                </Card>
              </>
            )}
          </>
        )}
      </Loader>

      <ConfirmModal
        open={confirmOpen}
        title="Submit orders to the Trading 212 DEMO account"
        description="This would submit the plan above to the DEMO environment only. The live endpoint is hard-blocked. The backend re-validates the full demo execution gate and writes an audit event; from the dashboard this is informational — run demo_execute from the CLI."
        phrase="EXECUTE DEMO"
        mode="demo"
        onClose={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false);
          toast("info", "Demo execution is CLI-gated: run paper-trade-long-only --mode demo_execute --confirm-demo.");
        }}
      />
    </div>
  );
}
