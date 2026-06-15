import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { NotLiveBanner, DemoOnlyBanner, ShadowBanner } from "./Banners";

describe("safety banners", () => {
  it("NotLiveBanner always states the system is not live eligible", () => {
    render(<NotLiveBanner />);
    expect(screen.getByText(/NOT LIVE ELIGIBLE/i)).toBeInTheDocument();
  });

  it("DemoOnlyBanner states demo only and that live is hard-blocked", () => {
    render(<DemoOnlyBanner />);
    expect(screen.getByText(/DEMO ONLY/i)).toBeInTheDocument();
    expect(screen.getByText(/hard-blocked/i)).toBeInTheDocument();
  });

  it("ShadowBanner states no orders are sent", () => {
    render(<ShadowBanner />);
    expect(screen.getByText(/SENDS NO ORDERS/i)).toBeInTheDocument();
  });
});
