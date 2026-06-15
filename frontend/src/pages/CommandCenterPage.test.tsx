import { describe, it, expect, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import CommandCenterPage from "./CommandCenterPage";
import { renderWithProviders, installFetch } from "../test/renderWithProviders";

const summary = {
  live_eligible: false, controls_enabled: true, kill_switch_active: false,
  product: "long_only_t212",
  decision: { headline: "Long-only T212 is the lead product", recommended: "long_only_t212", action: "begin supervised paper", capital_stage: "paper", status: "paper_candidate" },
  health: { state: "NOT STARTED", message: "no forward session yet", min_days: 30, concentration_top_weight: 0.12 },
  next_action: "begin supervised paper",
  trading212: { enabled: true, mode: "demo", account_type: "demo", api_key_configured: true, api_secret_configured: true, allow_demo_orders: false, live_orders_supported: false, kill_switch_active: false },
  reports: [], jobs: [],
};
const decision = { headline: "h", recommended: "long_only_t212", action: "a", capital_stage: "paper", live_eligible: false,
  products: [{ product: "long_only_t212", name: "Long-only T212", venue: "trading212", asset_class: "equity", shorting: false, leverage: false, venue_wired: true, venue_kind: "demo", gates_passed: 18, gates_total: 18, status: "paper_candidate", eligible_label: "", risk: "medium", missing: [], notes: [], live_eligible: false }] };

beforeEach(() => {
  installFetch({
    "/api/dashboard/summary": summary,
    "/api/product-decision": decision,
    "/api/paper-final/": { available: false },
  });
});

describe("CommandCenterPage", () => {
  it("renders Today's required action for a not-started session", async () => {
    renderWithProviders(<CommandCenterPage />);
    expect(await screen.findByText(/start a supervised paper session/i)).toBeInTheDocument();
  });

  it("always asserts NOT LIVE ELIGIBLE and exposes no live button", async () => {
    renderWithProviders(<CommandCenterPage />);
    expect((await screen.findAllByText(/not live eligible/i)).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /go live|run live|enable live/i })).toBeNull();
  });

  it("shows the paper health score card when a session is active", async () => {
    installFetch({
      "/api/dashboard/summary": {
        ...summary,
        health: { ...summary.health, state: "IN PROGRESS", last_run_date: "2026-06-15",
          forward_days_completed: 8, days_remaining: 22 },
        monitor: {
          health_score: 88, classification: "healthy",
          alert_counts: { critical: 0, warning: 1, info: 0, active_total: 1, resolved_total: 0 },
          next_expected_run: "2026-06-16", missed_days: 0, weekly_due: false,
          final_review_ready: false, days_remaining_to_min: 22, days_remaining_to_target: 82,
          ran_today: true, suggested_next_action: "review warnings",
        },
      },
      "/api/product-decision": decision,
      "/api/paper-final/": { available: false },
    });
    renderWithProviders(<CommandCenterPage />);
    expect(await screen.findByText("Paper health score")).toBeInTheDocument();
    expect(screen.getByText("Critical alerts")).toBeInTheDocument();
    expect(screen.getByText("Warning alerts")).toBeInTheDocument();
  });
});
