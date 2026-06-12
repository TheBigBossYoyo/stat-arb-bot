import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, ApiError } from "../lib/api";
import type { BrokerStatus } from "../lib/types";
import { Badge, Button, Card } from "../components/ui";
import { useUi } from "../store/ui";

export default function Brokers() {
  const queryClient = useQueryClient();
  const toast = useUi((s) => s.toast);
  const { data: brokers } = useQuery({
    queryKey: ["brokers"], queryFn: () => apiGet<BrokerStatus[]>("/api/brokers"),
  });

  const probe = useMutation({
    mutationFn: (broker: string) => apiPost<BrokerStatus>(`/api/brokers/${broker}/reconnect`),
    onSuccess: (status) => {
      toast(status.connected ? "success" : "error",
        `${status.display_name}: ${status.connected ? `reachable (${status.latency_ms}ms)` : status.detail}`);
      queryClient.invalidateQueries({ queryKey: ["brokers"] });
    },
    onError: (error) =>
      toast("error", error instanceof ApiError ? error.message : String(error)),
  });

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-3">
        {(brokers ?? []).map((b) => (
          <Card key={b.broker} title={b.display_name}
                right={<Badge tone={b.enabled ? "green" : "gray"}>{b.enabled ? "enabled" : "disabled"}</Badge>}>
            <div className="grid grid-cols-2 gap-y-1.5 text-sm">
              <span className="text-zinc-500">mode</span><span className="mono">{b.mode}</span>
              <span className="text-zinc-500">asset class</span><span>{b.asset_class}</span>
              <span className="text-zinc-500">API keys</span>
              <span>{b.key_configured ? <Badge tone="green">configured</Badge> : <Badge tone="gray">not set</Badge>}</span>
              <span className="text-zinc-500">connectivity</span>
              <span>{b.connected === null ? <Badge tone="gray">not probed</Badge>
                : b.connected ? <Badge tone="green">reachable {b.latency_ms}ms</Badge>
                : <Badge tone="red">unreachable</Badge>}</span>
            </div>
            <p className="mt-3 text-xs text-zinc-500">{b.detail}</p>
            <div className="mt-3">
              <Button onClick={() => probe.mutate(b.broker)}>Probe connection</Button>
            </div>
          </Card>
        ))}
      </div>

      <Card title="Capability matrix (enforced before every order)">
        <CapabilityMatrix brokers={brokers ?? []} />
        <p className="mt-3 text-xs text-zinc-600">
          ✗ = unsupported and refused at order validation. Trading 212 CFDs are not part of
          the official Public API and will never be implemented via unofficial endpoints.
          Binance futures stay disabled until consciously enabled with leverage caps.
        </p>
      </Card>
    </div>
  );
}

const FEATURES: { key: string; label: string }[] = [
  { key: "market", label: "Market orders" },
  { key: "limit", label: "Limit orders" },
  { key: "stop", label: "Stop orders" },
  { key: "stop_limit", label: "Stop-limit" },
  { key: "shorting", label: "Shorting" },
  { key: "margin", label: "Margin" },
  { key: "cfd", label: "CFDs" },
  { key: "fractional", label: "Fractional" },
];

function CapabilityMatrix({ brokers }: { brokers: BrokerStatus[] }) {
  const has = (b: BrokerStatus, feature: string): boolean => {
    const caps = b.capabilities as {
      order_types?: string[]; shorting?: boolean; margin?: boolean;
      fractional?: boolean; unsupported?: string[];
    };
    if (feature === "shorting") return Boolean(caps.shorting);
    if (feature === "margin") return Boolean(caps.margin);
    if (feature === "fractional") return Boolean(caps.fractional);
    if (feature === "cfd") return false;   // no broker here supports CFDs, by design
    return (caps.order_types ?? []).includes(feature);
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-left text-[11px] uppercase tracking-wider text-zinc-500">
            <th className="px-2 py-2">Broker</th>
            {FEATURES.map((f) => <th key={f.key} className="px-2 py-2 text-center">{f.label}</th>)}
            <th className="px-2 py-2 text-center">Paper</th>
            <th className="px-2 py-2 text-center">Live</th>
          </tr>
        </thead>
        <tbody>
          {brokers.map((b) => (
            <tr key={b.broker} className="border-b border-zinc-800/50">
              <td className="px-2 py-2">{b.display_name}</td>
              {FEATURES.map((f) => (
                <td key={f.key} className="px-2 py-2 text-center">
                  {has(b, f.key)
                    ? <span className="text-emerald-400">✓</span>
                    : <span className="font-semibold text-red-400">✗</span>}
                </td>
              ))}
              <td className="px-2 py-2 text-center"><span className="text-emerald-400">✓</span></td>
              <td className="px-2 py-2 text-center"><span className="font-semibold text-red-400">✗ gated</span></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
