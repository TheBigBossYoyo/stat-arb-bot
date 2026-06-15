import type { ReactNode } from "react";

/**
 * Compact metric tile: uppercase label, large mono value, optional sub-text and
 * a small accent stripe on the left for emphasis. `tone` is a text colour class
 * (kept for backwards compatibility with existing call sites).
 */
export default function MetricCard({ label, value, sub, tone = "", accent, icon }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: string;
  accent?: "ok" | "warn" | "danger" | "info" | "muted"; icon?: ReactNode;
}) {
  const stripe = {
    ok: "before:bg-emerald-500/70", warn: "before:bg-amber-500/70",
    danger: "before:bg-red-500/70", info: "before:bg-sky-500/70", muted: "before:bg-zinc-600",
  }[accent ?? "muted"];
  return (
    <div className={`card-elevated relative overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/60 px-4 py-3 ${accent ? `before:absolute before:left-0 before:top-0 before:h-full before:w-0.5 ${stripe}` : ""}`}>
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">{label}</div>
        {icon && <span className="text-zinc-600">{icon}</span>}
      </div>
      <div className={`mt-1 text-xl font-semibold mono ${tone || "text-zinc-100"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-zinc-500">{sub}</div>}
    </div>
  );
}
