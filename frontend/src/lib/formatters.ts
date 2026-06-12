export const fmtMoney = (v: number | null | undefined, digits = 2): string =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });

export const fmtPct = (v: number | null | undefined, digits = 2): string =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : `${v.toFixed(digits)}%`;

export const fmtNum = (v: number | null | undefined, digits = 4): string =>
  v === null || v === undefined || Number.isNaN(v) ? "—" : v.toFixed(digits);

export const fmtTs = (ts: string | null | undefined): string => {
  if (!ts) return "—";
  const d = new Date(ts);
  return Number.isNaN(d.getTime()) ? String(ts).slice(0, 19) : d.toISOString().replace("T", " ").slice(0, 19);
};

export const pnlTone = (v: number | null | undefined): string =>
  v === null || v === undefined || v === 0 ? "text-zinc-300" : v > 0 ? "text-emerald-400" : "text-red-400";

export function toCsv(rows: Record<string, unknown>[]): string {
  if (!rows.length) return "";
  const cols = Object.keys(rows[0]);
  const escape = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return [cols.join(","), ...rows.map((r) => cols.map((c) => escape(r[c])).join(","))].join("\n");
}

export function downloadCsv(rows: Record<string, unknown>[], filename: string): void {
  const blob = new Blob([toCsv(rows)], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
