import type { ReactNode } from "react";
import { Icons } from "./icons";

/* ------------------------------------------------------------------ surfaces */

export function Card({ title, subtitle, right, children, className = "", icon, noPad = false }: {
  title?: ReactNode; subtitle?: ReactNode; right?: ReactNode; children: ReactNode;
  className?: string; icon?: ReactNode; noPad?: boolean;
}) {
  return (
    <div className={`card-elevated rounded-xl border border-zinc-800 bg-zinc-900/60 transition-colors hover:border-zinc-700/80 ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between gap-3 border-b border-zinc-800 px-4 py-2.5">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
              {icon && <span className="text-zinc-500">{icon}</span>}
              <span className="truncate">{title}</span>
            </div>
            {subtitle && <div className="mt-0.5 text-xs text-zinc-500">{subtitle}</div>}
          </div>
          {right && <div className="shrink-0">{right}</div>}
        </div>
      )}
      <div className={noPad ? "" : "p-4"}>{children}</div>
    </div>
  );
}

/** Page header: title, plain-English description, status badges, primary action. */
export function PageHeader({ title, description, badges, actions, updatedAt }: {
  title: string; description?: string; badges?: ReactNode; actions?: ReactNode; updatedAt?: ReactNode;
}) {
  return (
    <div className="fade-in flex flex-col gap-3 border-b border-zinc-800/80 pb-4 md:flex-row md:items-start md:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight text-zinc-100">{title}</h1>
          {badges}
        </div>
        {description && <p className="mt-1 max-w-2xl text-sm text-zinc-500">{description}</p>}
      </div>
      {(actions || updatedAt) && (
        <div className="flex shrink-0 flex-col items-start gap-1 md:items-end">
          {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
          {updatedAt && <div className="text-[11px] text-zinc-600">{updatedAt}</div>}
        </div>
      )}
    </div>
  );
}

/** A labelled sub-section header inside a page (lighter than a Card title). */
export function SectionHeader({ title, description, right }: {
  title: string; description?: string; right?: ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-3">
      <div>
        <h2 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">{title}</h2>
        {description && <p className="mt-0.5 text-xs text-zinc-500">{description}</p>}
      </div>
      {right}
    </div>
  );
}

/* -------------------------------------------------------------------- badges */

const TONES: Record<string, string> = {
  green: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
  red: "bg-red-500/15 text-red-300 border-red-500/30",
  yellow: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  amber: "bg-amber-500/15 text-amber-300 border-amber-500/30",
  blue: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  sky: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  gray: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
  violet: "bg-violet-500/15 text-violet-300 border-violet-500/30",
  emerald: "bg-emerald-500/15 text-emerald-300 border-emerald-500/30",
};

export function Badge({ tone = "gray", children, dot = false }: {
  tone?: string; children: ReactNode; dot?: boolean;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${TONES[tone] ?? TONES.gray}`}>
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current opacity-80" />}
      {children}
    </span>
  );
}

/**
 * Semantic status badge — maps a known status/keyword to a tone + label so the
 * same concept always renders the same way across pages. Falls back to a neutral
 * pill (with the raw text) for unknown values.
 */
const STATUS_MAP: Record<string, { tone: string; label?: string; dot?: boolean }> = {
  // job / action lifecycle
  queued: { tone: "gray", dot: true }, running: { tone: "blue", dot: true },
  succeeded: { tone: "green" }, completed: { tone: "green" }, failed: { tone: "red" },
  refused: { tone: "yellow" }, cancelled: { tone: "gray" },
  // product / readiness
  paper_candidate: { tone: "green", label: "PAPER CANDIDATE" },
  testnet_candidate: { tone: "green", label: "TESTNET CANDIDATE" },
  not_yet: { tone: "yellow", label: "NOT YET" },
  do_not_trade: { tone: "red", label: "DO NOT TRADE" },
  not_evaluated: { tone: "gray", label: "NOT EVALUATED" },
  // paper session states
  "not started": { tone: "gray" }, "in progress": { tone: "blue", dot: true },
  paused: { tone: "yellow" }, "ready for final review": { tone: "green" },
  ok: { tone: "green" },
  // verdicts
  pass: { tone: "green" }, bounded: { tone: "yellow" }, eliminated: { tone: "green" },
  unresolved: { tone: "red" }, catastrophic: { tone: "red" },
};

export function StatusBadge({ status, label }: { status: string; label?: string }) {
  const key = String(status ?? "").toLowerCase();
  const m = STATUS_MAP[key] ?? { tone: "blue" };
  return <Badge tone={m.tone} dot={m.dot}>{label ?? m.label ?? String(status)}</Badge>;
}

export const statusTone = (status: string): string =>
  ({
    safe: "green", healthy: "green", filled: "green", running: "green", done: "green",
    connected: "green", warning: "yellow", degraded: "yellow", idle: "gray",
    paused: "gray", disabled: "gray", breached: "red", rejected: "red", failed: "red",
    risk_rejected: "red", halted: "red", error: "red", canceled: "gray",
  })[status.toLowerCase()] ?? "blue";

/* --------------------------------------------------------- loading / states */

export function Skeleton({ className = "h-6 w-full" }: { className?: string }) {
  return <div className={`skeleton rounded ${className}`} />;
}

/** A block of skeleton rows mimicking a card body while data loads. */
export function LoadingSkeleton({ rows = 3, className = "" }: { rows?: number; className?: string }) {
  return (
    <div className={`space-y-2.5 ${className}`}>
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className={`h-5 ${i === 0 ? "w-2/3" : i % 2 ? "w-full" : "w-5/6"}`} />
      ))}
    </div>
  );
}

export function EmptyState({ text, hint, icon, action }: {
  text: string; hint?: string; icon?: ReactNode; action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-4 py-10 text-center">
      <div className="text-zinc-600">{icon ?? <Icons.layers size={28} />}</div>
      <div className="text-sm text-zinc-400">{text}</div>
      {hint && <div className="mono text-xs text-zinc-600">{hint}</div>}
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, title = "Something went wrong", onRetry }: {
  error: unknown; title?: string; onRetry?: () => void;
}) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
      <div className="flex items-center gap-2 font-medium text-red-300">
        <Icons.alert size={15} /> {title}
      </div>
      <div className="mt-1 text-red-200/80">{msg}</div>
      {onRetry && (
        <button onClick={onRetry} className="mt-2 inline-flex items-center gap-1.5 rounded border border-red-500/40 px-2 py-1 text-xs text-red-200 hover:bg-red-500/15">
          <Icons.refresh size={13} /> Retry
        </button>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------- button */

type ButtonTone =
  | "default" | "primary" | "secondary" | "ghost" | "danger" | "warning" | "success" | "demo";

const BUTTON_TONES: Record<ButtonTone, string> = {
  default: "border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-zinc-200",
  secondary: "border-zinc-700 bg-zinc-800/60 hover:bg-zinc-700/70 text-zinc-300",
  ghost: "border-transparent bg-transparent hover:bg-zinc-800/70 text-zinc-300",
  primary: "border-sky-500/40 bg-sky-500/20 hover:bg-sky-500/30 text-sky-200",
  success: "border-emerald-500/40 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-200",
  warning: "border-amber-500/40 bg-amber-500/20 hover:bg-amber-500/30 text-amber-200",
  danger: "border-red-500/40 bg-red-500/20 hover:bg-red-500/35 text-red-200",
  demo: "border-violet-500/40 bg-violet-500/20 hover:bg-violet-500/30 text-violet-200",
};

export function Button({
  children, onClick, tone = "default", disabled = false, type = "button",
  size = "md", icon, title, className = "",
}: {
  children: ReactNode; onClick?: () => void; tone?: ButtonTone;
  disabled?: boolean; type?: "button" | "submit";
  size?: "sm" | "md"; icon?: ReactNode; title?: string; className?: string;
}) {
  const sizeCls = size === "sm" ? "px-2.5 py-1 text-xs" : "px-3 py-1.5 text-sm";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-lg border font-medium transition active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40 disabled:active:scale-100 ${sizeCls} ${BUTTON_TONES[tone]} ${className}`}
    >
      {icon}
      {children}
    </button>
  );
}

/* --------------------------------------------------------------------- form */

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-zinc-400">
      {label}
      {children}
      {hint && <span className="font-normal text-zinc-600">{hint}</span>}
    </label>
  );
}

export const inputCls =
  "rounded-lg border border-zinc-700 bg-zinc-900 px-2.5 py-1.5 text-sm text-zinc-200 outline-none transition focus:border-sky-500/70 focus:ring-1 focus:ring-sky-500/30";

/* ---------------------------------------------------------------------- tabs */

/** Lightweight tab strip for progressive disclosure (summary → details → raw). */
export function Tabs({ tabs, active, onChange }: {
  tabs: { id: string; label: ReactNode }[]; active: string; onChange: (id: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1 rounded-lg border border-zinc-800 bg-zinc-900/40 p-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`rounded-md px-3 py-1 text-sm font-medium transition ${
            active === t.id ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:text-zinc-200"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
