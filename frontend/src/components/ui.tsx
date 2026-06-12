import type { ReactNode } from "react";

export function Card({ title, right, children, className = "" }: {
  title?: ReactNode; right?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <div className={`rounded-xl border border-zinc-800 bg-zinc-900/60 ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2.5">
          <div className="text-sm font-semibold text-zinc-300">{title}</div>
          <div>{right}</div>
        </div>
      )}
      <div className="p-4">{children}</div>
    </div>
  );
}

const TONES: Record<string, string> = {
  green: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  red: "bg-red-500/15 text-red-400 border-red-500/30",
  yellow: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  blue: "bg-sky-500/15 text-sky-400 border-sky-500/30",
  gray: "bg-zinc-500/15 text-zinc-400 border-zinc-500/30",
  violet: "bg-violet-500/15 text-violet-400 border-violet-500/30",
};

export function Badge({ tone = "gray", children }: { tone?: string; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${TONES[tone] ?? TONES.gray}`}>
      {children}
    </span>
  );
}

export const statusTone = (status: string): string =>
  ({
    safe: "green", healthy: "green", filled: "green", running: "green", done: "green",
    connected: "green", warning: "yellow", degraded: "yellow", idle: "gray",
    paused: "gray", disabled: "gray", breached: "red", rejected: "red", failed: "red",
    risk_rejected: "red", halted: "red", error: "red", canceled: "gray",
  })[status.toLowerCase()] ?? "blue";

export function Skeleton({ className = "h-6 w-full" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-zinc-800 ${className}`} />;
}

export function EmptyState({ text, hint }: { text: string; hint?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 py-10 text-center">
      <div className="text-sm text-zinc-400">{text}</div>
      {hint && <div className="text-xs text-zinc-600 mono">{hint}</div>}
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

export function Button({ children, onClick, tone = "default", disabled = false, type = "button" }: {
  children: ReactNode; onClick?: () => void; tone?: "default" | "danger" | "primary";
  disabled?: boolean; type?: "button" | "submit";
}) {
  const styles = {
    default: "border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-zinc-200",
    danger: "border-red-600/50 bg-red-600/20 hover:bg-red-600/40 text-red-300",
    primary: "border-sky-600/50 bg-sky-600/20 hover:bg-sky-600/40 text-sky-300",
  }[tone];
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${styles}`}
    >
      {children}
    </button>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-zinc-400">
      {label}
      {children}
    </label>
  );
}

export const inputCls =
  "rounded-lg border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-200 outline-none focus:border-sky-600";
