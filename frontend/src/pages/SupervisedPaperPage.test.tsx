import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import SupervisedPaperPage from "./SupervisedPaperPage";

const operatorStatus = {
  product: "long_only_t212", live_eligible: false, controls_enabled: false, kill_switch_active: false,
  health: {
    state: "IN PROGRESS", mode: "shadow", forward_days_completed: 3, min_days: 30,
    days_remaining: 27, last_run_date: "2026-06-14", missing_days_gap: 0,
    stop_rules: { state: "OK", triggered: [] },
  },
  decision: { headline: "h", recommended: "r", action: "a", capital_stage: "paper", status: "paper_candidate" },
  trading212: { enabled: true, mode: "demo", api_key_configured: true, api_secret_configured: true, allow_demo_orders: false, live_orders_supported: false },
  checklist: [], next_action: "run tomorrow", latest_summary: "", confirm_phrase_demo_execute: "RUN DEMO PAPER DAY",
};

beforeEach(() => {
  global.fetch = vi.fn(async () => ({ ok: true, json: async () => operatorStatus })) as unknown as typeof fetch;
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <SupervisedPaperPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SupervisedPaperPage safety", () => {
  it("disables demo-execute by default and exposes no live button", async () => {
    renderPage();
    const demo = await screen.findByRole("button", { name: /run demo execute day/i });
    expect(demo).toBeDisabled();
    expect(screen.queryByRole("button", { name: /run live/i })).toBeNull();
    expect(screen.getByText(/No live button exists/i)).toBeInTheDocument();
  });

  it("disables the shadow run when controls are read-only", async () => {
    renderPage();
    const shadow = await screen.findByRole("button", { name: /run shadow day/i });
    expect(shadow).toBeDisabled();
  });
});
