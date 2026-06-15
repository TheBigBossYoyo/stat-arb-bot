import type { ReactNode } from "react";
import { vi } from "vitest";
import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

/** Render a component tree with router + react-query, retries disabled. */
export function renderWithProviders(ui: ReactNode, { route = "/" }: { route?: string } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

type RouteValue = unknown | ((url: string, init?: RequestInit) => unknown);

/**
 * Install a fetch mock that routes by URL substring. The longest matching key
 * wins, so specific paths (e.g. "/api/dashboard/jobs/") beat generic ones. POST
 * bodies are ignored — return the same payload regardless of method.
 */
export function installFetch(routes: Record<string, RouteValue>, fallback: unknown = {}) {
  const keys = Object.keys(routes).sort((a, b) => b.length - a.length);
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : String(input);
    const key = keys.find((k) => url.includes(k));
    const route = key ? routes[key] : fallback;
    const body = typeof route === "function"
      ? (route as (u: string, i?: RequestInit) => unknown)(url, init)
      : route;
    return { ok: true, status: 200, json: async () => body } as Response;
  });
  global.fetch = fetchMock as unknown as typeof fetch;
  return fetchMock;
}

/** A terminal (succeeded) job record so useAction settles immediately. */
export function succeededJob(extra: Record<string, unknown> = {}) {
  return {
    id: "job-test-1", job_type: "test", safety_level: "research", status: "succeeded",
    params: {}, created_at: "", started_at: "", finished_at: "", progress: 1, step: "done",
    result: {}, error: "", refusal_reason: "", audit_id: 1, report_path: null,
    cancel_requested: false, live_eligible: false, ...extra,
  };
}
