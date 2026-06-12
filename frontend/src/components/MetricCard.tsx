import type { ReactNode } from "react";

export default function MetricCard({ label, value, sub, tone = "" }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: string;
}) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`mt-1 text-xl font-semibold mono ${tone || "text-zinc-100"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-zinc-500">{sub}</div>}
    </div>
  );
}
