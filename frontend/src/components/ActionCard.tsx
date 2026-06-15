import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { Icons } from "./icons";

export type ActionTone = "info" | "ok" | "warn" | "danger" | "muted";

const TONE: Record<ActionTone, { ring: string; chip: string; glow: string; icon: ReactNode }> = {
  info: { ring: "border-sky-500/40", chip: "bg-sky-500/15 text-sky-300", glow: "from-sky-500/10", icon: <Icons.arrowRight size={18} /> },
  ok: { ring: "border-emerald-500/40", chip: "bg-emerald-500/15 text-emerald-300", glow: "from-emerald-500/10", icon: <Icons.check size={18} /> },
  warn: { ring: "border-amber-500/40", chip: "bg-amber-500/15 text-amber-300", glow: "from-amber-500/10", icon: <Icons.alert size={18} /> },
  danger: { ring: "border-red-500/50", chip: "bg-red-500/15 text-red-300", glow: "from-red-500/10", icon: <Icons.alert size={18} /> },
  muted: { ring: "border-zinc-700", chip: "bg-zinc-500/15 text-zinc-300", glow: "from-zinc-500/5", icon: <Icons.dot size={18} /> },
};

/**
 * The big "what should I do right now" card. One title, a plain-English
 * explanation, and a single primary call-to-action (rendered as a link, a
 * button, or disabled with a reason). Used as the Command Center centrepiece.
 */
export default function ActionCard({
  eyebrow, title, detail, tone = "info", ctaLabel, ctaHref, onCta, disabled, disabledReason, right,
}: {
  eyebrow?: string; title: string; detail?: string; tone?: ActionTone;
  ctaLabel?: string; ctaHref?: string; onCta?: () => void;
  disabled?: boolean; disabledReason?: string; right?: ReactNode;
}) {
  const t = TONE[tone];
  const cta = ctaLabel ? (
    disabled ? (
      <span
        title={disabledReason}
        className="inline-flex cursor-not-allowed items-center gap-2 rounded-lg border border-zinc-700 bg-zinc-800/60 px-4 py-2 text-sm font-semibold text-zinc-500"
      >
        <Icons.lock size={15} /> {ctaLabel}
      </span>
    ) : ctaHref ? (
      <Link
        to={ctaHref}
        onClick={onCta}
        className="inline-flex items-center gap-2 rounded-lg border border-sky-500/40 bg-sky-500/20 px-4 py-2 text-sm font-semibold text-sky-100 transition hover:bg-sky-500/30 active:scale-[0.98]"
      >
        {ctaLabel} <Icons.arrowRight size={16} />
      </Link>
    ) : (
      <button
        onClick={onCta}
        className="inline-flex items-center gap-2 rounded-lg border border-sky-500/40 bg-sky-500/20 px-4 py-2 text-sm font-semibold text-sky-100 transition hover:bg-sky-500/30 active:scale-[0.98]"
      >
        {ctaLabel} <Icons.arrowRight size={16} />
      </button>
    )
  ) : null;

  return (
    <div className={`fade-in pop-elevated relative overflow-hidden rounded-2xl border ${t.ring} bg-zinc-900/70`}>
      <div className={`pointer-events-none absolute inset-0 bg-gradient-to-br ${t.glow} to-transparent`} />
      <div className="relative flex flex-col gap-4 p-5 md:flex-row md:items-center md:justify-between">
        <div className="flex items-start gap-3">
          <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${t.chip}`}>{t.icon}</span>
          <div className="min-w-0">
            {eyebrow && <div className="text-[11px] font-semibold uppercase tracking-widest text-zinc-500">{eyebrow}</div>}
            <div className="text-lg font-semibold text-zinc-50">{title}</div>
            {detail && <div className="mt-1 max-w-2xl text-sm text-zinc-400">{detail}</div>}
            {disabled && disabledReason && (
              <div className="mt-1.5 text-xs text-amber-300/90">{disabledReason}</div>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {right}
          {cta}
        </div>
      </div>
    </div>
  );
}
