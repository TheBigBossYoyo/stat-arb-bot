import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Skeleton, ErrorState } from "./ui";

/** Persistent red banner — every product page asserts live is blocked. */
export function NotLiveBanner() {
  return (
    <div className="rounded-lg border border-red-600/50 bg-red-600/15 px-4 py-2 text-center text-sm font-bold tracking-wide text-red-300">
      ⛔ NOT LIVE ELIGIBLE — no real-money orders can be placed from this system
    </div>
  );
}

export function DemoOnlyBanner() {
  return (
    <div className="rounded-lg border border-amber-500/50 bg-amber-500/15 px-4 py-2 text-center text-sm font-semibold tracking-wide text-amber-300">
      🧪 DEMO ONLY — the Trading 212 live endpoint is hard-blocked
    </div>
  );
}

export function ShadowBanner() {
  return (
    <div className="rounded-lg border border-sky-500/50 bg-sky-500/15 px-4 py-2 text-center text-sm font-semibold tracking-wide text-sky-300">
      👁 SHADOW MODE — SENDS NO ORDERS
    </div>
  );
}

export function PageTitle({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div>
      <h1 className="text-lg font-semibold text-zinc-100">{title}</h1>
      {subtitle && <p className="text-sm text-zinc-500">{subtitle}</p>}
    </div>
  );
}

/** Render a backend markdown report verbatim in a monospace block. */
export function ReportBlock({ report }: { report: string }) {
  if (!report) return null;
  return (
    <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs text-zinc-300">
      {report}
    </pre>
  );
}

/** Standard query wrapper: shows skeleton while loading, error state on failure. */
export function Loader<T>({ data, error, isLoading, children }: {
  data: T | undefined; error: unknown; isLoading: boolean;
  children: (data: T) => ReactNode;
}) {
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (error) return <ErrorState error={error} />;
  if (data === undefined) return <ErrorState error="no data" />;
  return <>{children(data)}</>;
}

/** Helper hook factory wrapping useQuery with sensible defaults. */
export function useApiQuery<T>(key: unknown[], path: string, fetcher: (p: string) => Promise<T>) {
  return useQuery({ queryKey: key, queryFn: () => fetcher(path) });
}
