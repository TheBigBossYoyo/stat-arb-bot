import { describe, it, expect, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import SafetyCenterPage from "./SafetyCenterPage";
import { renderWithProviders, installFetch } from "../test/renderWithProviders";

beforeEach(() => {
  installFetch({
    "/api/status": {
      mode: "paper", bot_status: "idle", controls_enabled: true, live_trading_allowed: false,
      server_time: "2026-06-15T09:00:00Z", kill_switch: { active: false, reason: null },
    },
    "/api/audit": [],
    "/api/dashboard/jobs": [],
    "/api/dashboard/capabilities": { live_eligible: false, controls_enabled: true, role: "admin", actions: [] },
  });
});

describe("SafetyCenterPage", () => {
  it("renders the kill switch control and the structural blocks", async () => {
    renderWithProviders(<SafetyCenterPage />);
    expect(await screen.findByText("Kill switch")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^engage/i })).toBeInTheDocument();
    expect(screen.getByText(/structurally unsupported/i)).toBeInTheDocument();
  });

  it("exposes no live-trading control", async () => {
    renderWithProviders(<SafetyCenterPage />);
    await screen.findByText("Kill switch");
    expect(screen.queryByRole("button", { name: /go live|enable live|run live/i })).toBeNull();
  });
});
