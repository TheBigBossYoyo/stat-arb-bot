import { describe, it, expect, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import Layout from "./Layout";
import { renderWithProviders, installFetch } from "../../test/renderWithProviders";

const status = {
  mode: "paper", bot_status: "idle", controls_enabled: false, live_trading_allowed: false,
  server_time: "2026-06-15T09:00:00Z", kill_switch: { active: false, reason: null },
};

beforeEach(() => {
  installFetch({
    "/api/status": status,
    "/api/risk/status": { kill_switch: { active: false } },
    "/api/dashboard/summary": {
      live_eligible: false, controls_enabled: false, kill_switch_active: false, product: "long_only_t212",
      decision: { headline: "", recommended: "", action: "", capital_stage: "paper", status: "paper_candidate" },
      health: {}, next_action: "", trading212: { enabled: true, mode: "demo", allow_demo_orders: false },
      reports: [], jobs: [],
    },
  });
});

describe("Layout shell", () => {
  it("top bar always shows NOT LIVE ELIGIBLE", async () => {
    renderWithProviders(<Layout><div>child content</div></Layout>);
    expect((await screen.findAllByText(/not live eligible/i)).length).toBeGreaterThan(0);
  });

  it("renders grouped sidebar sections and the child content", async () => {
    renderWithProviders(<Layout><div>child content</div></Layout>);
    expect(screen.getByText("Supervised Paper")).toBeInTheDocument();
    expect(screen.getByText("Risk & Safety")).toBeInTheDocument();
    expect(screen.getByText("child content")).toBeInTheDocument();
  });

  it("has no live-trading control anywhere", () => {
    renderWithProviders(<Layout><div>child content</div></Layout>);
    expect(screen.queryByRole("button", { name: /go live|enable live|run live/i })).toBeNull();
  });
});
