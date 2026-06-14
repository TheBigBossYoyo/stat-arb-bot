import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { MarkdownReport } from "../lib/productTypes";
import { Card } from "../components/ui";
import { NotLiveBanner, PageTitle, Loader, ReportBlock } from "../components/Banners";

export default function CrisisLabPage() {
  const q = useQuery({
    queryKey: ["crisis"],
    queryFn: () => apiGet<MarkdownReport>("/api/crisis/long_only_xsec_momentum?universe=us_stocks_50"),
  });
  return (
    <div className="space-y-4">
      <PageTitle title="Crisis Lab" subtitle="Synthetic 2008/2020-style stress for the long-only book (no real tail in the sample)." />
      <NotLiveBanner />
      <Loader data={q.data} error={q.error} isLoading={q.isLoading}>
        {(d) => (
          <Card title={d.available ? "Long-only crisis report (SYNTHETIC)" : "Not generated"}>
            {d.available
              ? <ReportBlock report={d.report} />
              : <p className="text-sm text-zinc-400">{d.report}</p>}
            <p className="mt-3 text-xs text-zinc-600">
              Worst synthetic crisis DD −28% (bounded). The regime filter is the real crash
              protection (regime-off worst DD −51%). Regenerate via
              <code className="mono"> statarb crisis-test-long-only</code>.
            </p>
          </Card>
        )}
      </Loader>
    </div>
  );
}
