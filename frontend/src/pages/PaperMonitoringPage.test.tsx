import { beforeEach, describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders, installFetch } from "../test/renderWithProviders";
import { THEME_STORAGE_KEY } from "../theme/theme";
import PaperMonitoringPage from "./PaperMonitoringPage";

const MONITOR = {
  product: "long_only_t212", generated_at: "2026-06-15T10:00:00", session_id: "PS-TEST",
  active: true, live_eligible: false,
  metrics: {
    session_id: "PS-TEST", mode: "shadow", started_at: "2026-06-01",
    forward_days_completed: 8, expected_trading_days: 8, missed_days: 0,
    days_remaining_to_min: 22, days_remaining_to_target: 82, min_days: 30, target_days: 90,
    last_run_date: "2026-06-15", ran_today: true, next_expected_run: "2026-06-16",
    paper_pnl_pct: 1.2, benchmark_pnl_pct: 0.8, excess_return_pct: 0.4,
    tracking_error_pct_daily: 0.3, current_drawdown_pct: -2.1, concentration_top_weight: 0.2,
    turnover_per_year: 28, cash_drag_pct: 4, n_holdings: 12, benchmark_beta: 0.9,
    avg_slippage_bps: 5, order_count: 4, rejected_orders: 0, skipped_orders: 0, reject_rate_pct: 0,
    broker_errors: 0, risk_breaches: 0, data_quality_events: 0, data_stale: false,
    can_generate_final_report: false, paper_vs_backtest_status: "invalid",
    paper_vs_backtest_verdict: "invalid / not comparable", stop_state: "OK",
    weekly_due: false, final_review_ready: false,
  },
  health: { stop_rules: { state: "OK", triggered: [] } },
  health_score: {
    score: 91, classification: "healthy", overrides: [], live_eligible: false,
    components: [
      { name: "operational_completeness", score: 100, weight: 0.2, weighted: 20, detail: "8/8 days" },
      { name: "concentration", score: 100, weight: 0.12, weighted: 12, detail: "top 20%" },
    ],
  },
  alerts: [
    { alert_id: "AL-1", timestamp: "2026-06-15T09:00:00", session_id: "PS-TEST",
      severity: "warning", category: "turnover_drift", title: "Turnover far from expectation",
      message: "turnover off", evidence: {}, suggested_action: "check schedule",
      resolved: false, resolved_at: "", resolution_note: "", dedup_key: "turnover_drift:warning" },
  ],
  alert_counts: { critical: 0, warning: 1, info: 0, active_total: 1, resolved_total: 0 },
  paper_vs_backtest: { verdict: "invalid / not comparable", forward_days: 8, rows: [], notes: [] },
  suggested_next_action: "Review 1 warning alert(s) on the Paper Monitoring page.",
  snapshots: [
    { date: "2026-06-14", score: 90, classification: "healthy", paper_pnl_pct: 1.0,
      benchmark_pnl_pct: 0.7, drawdown_pct: -1.5, concentration_top_weight: 0.2,
      turnover_per_year: 28, active_alerts: 1, critical_alerts: 0, warning_alerts: 1 },
    { date: "2026-06-15", score: 91, classification: "healthy", paper_pnl_pct: 1.2,
      benchmark_pnl_pct: 0.8, drawdown_pct: -2.1, concentration_top_weight: 0.2,
      turnover_per_year: 28, active_alerts: 1, critical_alerts: 0, warning_alerts: 1 },
  ],
};

function mockApi() {
  installFetch({
    "/api/paper/health": MONITOR,
    "/api/dashboard/capabilities": { live_eligible: false, controls_enabled: false, role: "viewer", actions: [] },
  });
}

describe("PaperMonitoringPage", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark", "light");
    mockApi();
  });

  it("renders the health score, classification and alerts", async () => {
    renderWithProviders(<PaperMonitoringPage />);
    expect(await screen.findByText("Health score components")).toBeInTheDocument();
    // the hero shows the score + a HEALTHY classification badge (uppercased)
    expect(screen.getByText("HEALTHY")).toBeInTheDocument();
    expect(screen.getByText(/Turnover far from expectation/)).toBeInTheDocument();
    expect(screen.getAllByText(/NOT LIVE ELIGIBLE/i).length).toBeGreaterThan(0);
  });

  it("exposes no live-trading control", async () => {
    renderWithProviders(<PaperMonitoringPage />);
    await screen.findByText("Health score components");
    expect(screen.queryByRole("button", { name: /live/i })).toBeNull();
  });

  it("renders in light mode", async () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    renderWithProviders(<PaperMonitoringPage />);
    expect(await screen.findByText("Health score components")).toBeInTheDocument();
    expect(screen.getByText("HEALTHY")).toBeInTheDocument();
    expect(document.documentElement.classList.contains("light")).toBe(true);
  });
});
