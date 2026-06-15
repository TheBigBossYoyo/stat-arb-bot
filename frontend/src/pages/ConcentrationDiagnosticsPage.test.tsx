import { describe, it, expect, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import ConcentrationDiagnosticsPage from "./ConcentrationDiagnosticsPage";
import { renderWithProviders, installFetch, succeededJob } from "../test/renderWithProviders";

const report = { available: false, report: "not generated" };

function routes(controls: boolean) {
  return {
    "/api/concentration/": report,
    "/api/dashboard/capabilities": { live_eligible: false, controls_enabled: controls, role: controls ? "admin" : "viewer", actions: [] },
    "/api/long-only/concentration/run": succeededJob({ job_type: "concentration_analysis", result: { rows: [], gate_pass: true, baseline_oos_sharpe: 1.0 } }),
    "/api/dashboard/jobs/": succeededJob({ job_type: "concentration_analysis", result: { rows: [], gate_pass: true, baseline_oos_sharpe: 1.0 } }),
  };
}

describe("ConcentrationDiagnosticsPage rerun", () => {
  it("creates a job when controls are enabled", async () => {
    const fetchMock = installFetch(routes(true));
    renderWithProviders(<ConcentrationDiagnosticsPage />);
    const btn = await screen.findByRole("button", { name: /rerun concentration/i });
    await waitFor(() => expect(btn).not.toBeDisabled());
    fireEvent.click(btn);
    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/api/long-only/concentration/run"))).toBe(true),
    );
  });

  it("disables the rerun button in read-only mode", async () => {
    installFetch(routes(false));
    renderWithProviders(<ConcentrationDiagnosticsPage />);
    const btn = await screen.findByRole("button", { name: /rerun concentration/i });
    await waitFor(() => expect(btn).toBeDisabled());
  });
});
