import { describe, it, expect, beforeEach } from "vitest";
import { screen } from "@testing-library/react";
import Trading212OrderPreviewPage from "./Trading212OrderPreviewPage";
import { renderWithProviders, installFetch } from "../test/renderWithProviders";

beforeEach(() => {
  installFetch({
    "/api/trading212-config": {
      enabled: true, mode: "demo", account_type: "demo", api_key_configured: true,
      api_secret_configured: true, allow_demo_orders: false, live_orders_supported: false, kill_switch_active: false,
    },
  });
});

describe("Order Preview page (no standalone order button)", () => {
  it("states demo execution only happens inside the gated supervised paper run", async () => {
    renderWithProviders(<Trading212OrderPreviewPage />);
    expect(await screen.findByText(/only available inside the gated supervised paper daily run/i)).toBeInTheDocument();
  });

  it("offers preview generation but no live / execute-order button", async () => {
    renderWithProviders(<Trading212OrderPreviewPage />);
    expect((await screen.findAllByRole("button", { name: /generate shadow preview/i })).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: /go live|execute on demo|send demo|execute demo/i })).toBeNull();
  });
});
