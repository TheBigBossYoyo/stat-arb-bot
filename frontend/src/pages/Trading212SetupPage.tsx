import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { Trading212Config } from "../lib/productTypes";
import { useAction } from "../lib/useAction";
import { Card, Badge, Button } from "../components/ui";
import JobProgress from "../components/JobProgress";
import { NotLiveBanner, DemoOnlyBanner, PageTitle, Loader } from "../components/Banners";

interface SetupCheckRow { name: string; ok: boolean; detail: string; severity: string }

export default function Trading212SetupPage() {
  const cfg = useQuery({
    queryKey: ["t212-config"],
    queryFn: () => apiGet<Trading212Config>("/api/trading212-config"),
    refetchInterval: 20000,
  });
  const check = useAction("/api/trading212/setup-check");
  const checks = (check.job?.result?.checks as SetupCheckRow[] | undefined) ?? [];
  const verdictOk = check.job?.result?.ok === true;

  return (
    <div className="space-y-4">
      <PageTitle title="Trading 212 Setup Wizard" subtitle="Verify the DEMO environment is correctly configured. Secrets are never shown." />
      <NotLiveBanner />
      <DemoOnlyBanner />

      <Loader data={cfg.data} error={cfg.error} isLoading={cfg.isLoading}>
        {(c) => (
          <Card title="Configuration (booleans only — no secrets)">
            <div className="grid grid-cols-2 gap-2 text-sm md:grid-cols-3">
              <Status label="TRADING212_ENABLED" ok={c.enabled} />
              <Status label="mode = demo" ok={c.mode === "demo"} text={c.mode} />
              <Status label="API key configured" ok={c.api_key_configured} />
              <Status label="API secret configured" ok={c.api_secret_configured} />
              <Status label="demo orders allowed" ok={c.allow_demo_orders} />
              <Status label="live orders supported" ok={!c.live_orders_supported} text={c.live_orders_supported ? "yes" : "no (hard-blocked)"} good={!c.live_orders_supported} />
            </div>
            {!c.api_key_configured && (
              <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-200">
                <div className="font-semibold">Keys missing. In <code className="mono">.env</code> set:</div>
                <pre className="mono mt-1 whitespace-pre-wrap">{`TRADING212_ENABLED=true
TRADING212_MODE=demo
TRADING212_API_KEY=<your demo key>
TRADING212_API_SECRET=<your demo secret>
TRADING212_ALLOW_DEMO_ORDERS=false   # leave false until you are ready
TRADING212_ALLOW_LIVE_ORDERS=false   # never true`}</pre>
                <div className="mt-1">Then restart the backend. Browser secret entry is intentionally disabled.</div>
              </div>
            )}
          </Card>
        )}
      </Loader>

      <Card title="Run the demo setup check">
        <div className="flex flex-wrap items-center gap-3">
          <Button tone="primary" disabled={check.busy}
                  onClick={() => check.run({ params: { connect: true }, reason: "operator dashboard" })}>
            Run setup check (probe demo endpoints)
          </Button>
          <Button disabled={check.busy}
                  onClick={() => check.run({ params: { connect: false }, reason: "operator dashboard" })}>
            Config-only check (no connection)
          </Button>
          {check.job?.status === "succeeded" && (
            <Badge tone={verdictOk ? "green" : "yellow"}>verdict: {verdictOk ? "DEMO READY" : "not ready"}</Badge>
          )}
          <Badge tone="red">live eligible: false</Badge>
        </div>
        {check.job && <div className="mt-3"><JobProgress job={check.job} /></div>}
      </Card>

      {checks.length > 0 && (
        <Card title="Setup checklist">
          <div className="space-y-1">
            {checks.map((row, i) => (
              <div key={`${row.name}-${i}`} className="flex items-start gap-2 text-sm">
                <Badge tone={row.ok ? "green" : row.severity === "required" ? "red" : "yellow"}>
                  {row.ok ? "PASS" : row.severity === "required" ? "FAIL" : "—"}
                </Badge>
                <div>
                  <div className="text-zinc-200">{row.name}</div>
                  <div className="text-xs text-zinc-500">{row.detail}</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}

function Status({ label, ok, text, good }: { label: string; ok: boolean; text?: string; good?: boolean }) {
  const positive = good ?? ok;
  return (
    <div className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2">
      <span className="text-zinc-300">{label}</span>
      <Badge tone={positive ? "green" : "yellow"}>{text ?? (ok ? "yes" : "no")}</Badge>
    </div>
  );
}
