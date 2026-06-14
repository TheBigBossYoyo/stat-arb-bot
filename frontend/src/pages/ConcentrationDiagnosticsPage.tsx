import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { MarkdownReport } from "../lib/productTypes";
import { Card } from "../components/ui";
import { NotLiveBanner, PageTitle, Loader, ReportBlock } from "../components/Banners";

export default function ConcentrationDiagnosticsPage() {
  const q = useQuery({
    queryKey: ["concentration"],
    queryFn: () => apiGet<MarkdownReport>("/api/concentration/long_only_xsec_momentum?universe=us_stocks_50"),
  });
  return (
    <div className="space-y-4">
      <PageTitle title="Concentration Diagnostics" subtitle="Monthly / daily PnL contribution, Herfindahl, per-asset/sector — and the gate." />
      <NotLiveBanner />
      <Loader data={q.data} error={q.error} isLoading={q.isLoading}>
        {(d) => (
          <Card title={d.available ? `Report — ${d.file ?? ""}` : "Not generated"}>
            {d.available
              ? <ReportBlock report={d.report} />
              : <p className="text-sm text-zinc-400">{d.report}</p>}
            <p className="mt-3 text-xs text-zinc-600">
              EWMA α=0.5 smoothing closed this gate: worst month 26.1% → 23.5%.
              Regenerate via <code className="mono">statarb compare-concentration-fixes --strategy long_only_xsec_momentum</code>.
            </p>
          </Card>
        )}
      </Loader>
    </div>
  );
}
