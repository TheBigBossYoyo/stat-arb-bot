import { useMemo, useState, type ReactNode } from "react";
import { downloadCsv } from "../lib/formatters";
import { EmptyState } from "./ui";

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
  sortValue?: (row: T) => number | string;
  align?: "left" | "right";
}

export default function DataTable<T extends Record<string, unknown>>({
  rows, columns, pageSize = 15, searchKeys, csvName, emptyText = "No data yet",
}: {
  rows: T[]; columns: Column<T>[]; pageSize?: number;
  searchKeys?: string[]; csvName?: string; emptyText?: string;
}) {
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<1 | -1>(-1);
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    let out = rows;
    if (query && searchKeys?.length) {
      const q = query.toLowerCase();
      out = rows.filter((r) =>
        searchKeys.some((k) => String(r[k] ?? "").toLowerCase().includes(q)),
      );
    }
    if (sortKey) {
      const col = columns.find((c) => c.key === sortKey);
      const value = (row: T) =>
        col?.sortValue ? col.sortValue(row) : (row[sortKey] as number | string);
      out = [...out].sort((a, b) => {
        const va = value(a);
        const vb = value(b);
        if (va === vb) return 0;
        return (va > vb ? 1 : -1) * sortDir;
      });
    }
    return out;
  }, [rows, query, sortKey, sortDir, columns, searchKeys]);

  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const visible = filtered.slice(page * pageSize, (page + 1) * pageSize);

  const toggleSort = (key: string) => {
    if (sortKey === key) setSortDir((d) => (d === 1 ? -1 : 1));
    else {
      setSortKey(key);
      setSortDir(-1);
    }
  };

  if (!rows.length) return <EmptyState text={emptyText} />;

  return (
    <div>
      <div className="mb-2 flex items-center gap-2">
        {searchKeys?.length ? (
          <input
            value={query}
            onChange={(e) => { setQuery(e.target.value); setPage(0); }}
            placeholder="Filter…"
            className="w-48 rounded-lg border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-sm outline-none focus:border-sky-600"
          />
        ) : null}
        <div className="ml-auto flex items-center gap-2 text-xs text-zinc-500">
          <span>{filtered.length} rows</span>
          {csvName && (
            <button
              onClick={() => downloadCsv(filtered as Record<string, unknown>[], csvName)}
              className="rounded border border-zinc-700 px-2 py-0.5 hover:bg-zinc-800"
            >
              CSV
            </button>
          )}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0">
            <tr className="border-b border-zinc-800 text-left text-[11px] uppercase tracking-wider text-zinc-500">
              {columns.map((c) => (
                <th
                  key={c.key}
                  onClick={() => toggleSort(c.key)}
                  className={`cursor-pointer select-none px-2 py-2 hover:text-zinc-300 ${c.align === "right" ? "text-right" : ""}`}
                >
                  {c.label}
                  {sortKey === c.key ? (sortDir === 1 ? " ↑" : " ↓") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visible.map((row, i) => (
              <tr key={i} className="border-b border-zinc-800/50 hover:bg-zinc-800/30">
                {columns.map((c) => (
                  <td key={c.key} className={`px-2 py-1.5 ${c.align === "right" ? "text-right mono" : ""}`}>
                    {c.render ? c.render(row) : String(row[c.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {pages > 1 && (
        <div className="mt-2 flex items-center justify-end gap-2 text-xs text-zinc-500">
          <button disabled={page === 0} onClick={() => setPage((p) => p - 1)}
                  className="rounded border border-zinc-700 px-2 py-0.5 disabled:opacity-30">‹</button>
          <span>{page + 1} / {pages}</span>
          <button disabled={page >= pages - 1} onClick={() => setPage((p) => p + 1)}
                  className="rounded border border-zinc-700 px-2 py-0.5 disabled:opacity-30">›</button>
        </div>
      )}
    </div>
  );
}
