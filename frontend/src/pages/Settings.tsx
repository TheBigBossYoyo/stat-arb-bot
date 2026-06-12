import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import { Badge, Card } from "../components/ui";

type SettingsView = Record<string, unknown>;

export default function Settings() {
  const { data } = useQuery({
    queryKey: ["settings"], queryFn: () => apiGet<SettingsView>("/api/settings"),
  });
  if (!data) return null;

  const binance = data.binance as Record<string, unknown>;
  const t212 = data.trading212 as Record<string, unknown>;
  const risk = data.risk_overrides as Record<string, unknown>;

  return (
    <div className="max-w-3xl space-y-4">
      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
        Configuration is READ-ONLY in the dashboard. Edit <span className="mono">.env</span> /
        the YAML files and restart. API keys are never displayed anywhere — only whether
        they are configured.
      </div>

      <Card title="Environment">
        <KV k="app_env" v={String(data.app_env)} />
        <KV k="database" v={String(data.database)} mono />
        <KV k="live_trading" v={<Flag on={Boolean(data.live_trading)} danger />} />
        <KV k="confirm_live_trading" v={<Flag on={Boolean(data.confirm_live_trading)} danger />} />
        <KV k="dashboard_controls_enabled" v={<Flag on={Boolean(data.dashboard_controls_enabled)} />} />
        <KV k="dashboard_token" v={data.dashboard_token_set ? "set (hidden)" : "not set"} />
        <KV k="data_provider" v={String(data.data_provider)} />
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Binance">
          <KV k="enabled" v={<Flag on={Boolean(binance.enabled)} />} />
          <KV k="mode" v={String(binance.mode)} mono />
          <KV k="API key" v={binance.key_configured ? "configured (hidden)" : "not set"} />
          <KV k="futures" v={<Flag on={Boolean(binance.futures)} danger />} />
        </Card>
        <Card title="Trading 212">
          <KV k="enabled" v={<Flag on={Boolean(t212.enabled)} />} />
          <KV k="mode" v={String(t212.mode)} mono />
          <KV k="account type" v={String(t212.account_type)} />
          <KV k="API key" v={t212.key_configured ? "configured (hidden)" : "not set"} />
        </Card>
      </div>

      <Card title="Risk overrides (.env > config/risk_limits.yaml)">
        {Object.entries(risk).map(([key, value]) => (
          <KV key={key} k={key} v={String(value)} mono />
        ))}
      </Card>

      <p className="text-xs text-zinc-600">{String(data.note)}</p>
    </div>
  );
}

function KV({ k, v, mono = false }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between border-b border-zinc-800/50 py-1.5 text-sm last:border-0">
      <span className="text-zinc-500">{k}</span>
      <span className={mono ? "mono text-xs text-zinc-300" : "text-zinc-200"}>{v}</span>
    </div>
  );
}

function Flag({ on, danger = false }: { on: boolean; danger?: boolean }) {
  if (on) return <Badge tone={danger ? "red" : "green"}>{danger ? "TRUE ⚠" : "true"}</Badge>;
  return <Badge tone="gray">false</Badge>;
}
