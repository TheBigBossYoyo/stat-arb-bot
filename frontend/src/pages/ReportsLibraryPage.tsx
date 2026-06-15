import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { ReportMeta } from "../lib/actionTypes";
import { Card, Badge, EmptyState } from "../components/ui";
import { NotLiveBanner, PageTitle, Loader, ReportBlock } from "../components/Banners";
import { fmtTs } from "../lib/formatters";

interface ReportsResp { reports: ReportMeta[] }
interface ReportContent { id: string; name: string; content: string }

export default function ReportsLibraryPage() {
  const list = useQuery({
    queryKey: ["reports"],
    queryFn: () => apiGet<ReportsResp>("/api/reports"),
    refetchInterval: 30000,
  });
  const [selected, setSelected] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<string>("all");

  const content = useQuery({
    queryKey: ["report", selected],
    queryFn: () => apiGet<ReportContent>(`/api/reports/${selected}`),
    enabled: !!selected,
  });

  const categories = useMemo(() => {
    const set = new Set((list.data?.reports ?? []).map((r) => r.category));
    return ["all", ...Array.from(set).sort()];
  }, [list.data]);

  const filtered = (list.data?.reports ?? []).filter((r) =>
    (category === "all" || r.category === category) &&
    r.name.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="space-y-4">
      <PageTitle title="Reports Library" subtitle="Every operator-facing report — view, download, filter." />
      <NotLiveBanner />

      <Loader data={list.data} error={list.error} isLoading={list.isLoading}>
        {() => (
          <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
            <Card title={`Reports (${filtered.length})`}>
              <input
                placeholder="search…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="mb-2 w-full rounded-lg border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-200 outline-none focus:border-sky-600"
              />
              <div className="mb-2 flex flex-wrap gap-1">
                {categories.map((c) => (
                  <button
                    key={c}
                    onClick={() => setCategory(c)}
                    className={`rounded-full border px-2 py-0.5 text-xs ${
                      category === c ? "border-sky-500/50 bg-sky-500/15 text-sky-300" : "border-zinc-700 text-zinc-400 hover:text-zinc-200"
                    }`}
                  >
                    {c}
                  </button>
                ))}
              </div>
              {filtered.length === 0 ? <EmptyState text="no matching reports" /> : (
                <div className="space-y-1">
                  {filtered.map((r) => (
                    <button
                      key={r.id}
                      onClick={() => setSelected(r.id)}
                      className={`flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm ${
                        selected === r.id ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:bg-zinc-900"
                      }`}
                    >
                      <Badge tone="gray">{r.category}</Badge>
                      <span className="flex-1 truncate">{r.name}</span>
                      {r.stale && <Badge tone="yellow">stale</Badge>}
                    </button>
                  ))}
                </div>
              )}
            </Card>

            <Card
              title={selected ?? "Select a report"}
              right={selected && (
                <a href={`/api/reports/${selected}/download`}
                   className="rounded-lg border border-zinc-700 bg-zinc-800 px-2.5 py-1 text-xs text-zinc-200 hover:bg-zinc-700">
                  download
                </a>
              )}
            >
              {!selected ? (
                <EmptyState text="pick a report on the left" />
              ) : (
                <Loader data={content.data} error={content.error} isLoading={content.isLoading}>
                  {(c) => (
                    <div className="space-y-2">
                      <div className="text-xs text-zinc-500">
                        {(() => {
                          const meta = list.data?.reports.find((r) => r.id === selected);
                          return meta ? `modified ${fmtTs(new Date(meta.modified * 1000).toISOString())} · ${meta.size} bytes` : "";
                        })()}
                      </div>
                      <ReportBlock report={c.content} />
                    </div>
                  )}
                </Loader>
              )}
            </Card>
          </div>
        )}
      </Loader>
    </div>
  );
}
