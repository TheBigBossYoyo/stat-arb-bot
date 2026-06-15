// Types for the paper monitoring + alerting layer (app/research/paper_monitor.py).

export type HealthClassification = "healthy" | "watch" | "degraded" | "failed" | "paused";
export type AlertSeverity = "info" | "warning" | "critical";

export interface HealthScoreComponent {
  name: string;
  score: number;
  weight: number;
  weighted: number;
  detail: string;
}

export interface HealthScore {
  score: number;
  classification: HealthClassification;
  components: HealthScoreComponent[];
  overrides: string[];
  live_eligible: boolean;
}

export interface PaperAlert {
  alert_id: string;
  timestamp: string;
  session_id: string;
  severity: AlertSeverity;
  category: string;
  title: string;
  message: string;
  evidence: Record<string, unknown>;
  suggested_action: string;
  resolved: boolean;
  resolved_at: string;
  resolution_note: string;
  dedup_key: string;
}

export interface AlertCounts {
  critical: number;
  warning: number;
  info: number;
  active_total: number;
  resolved_total: number;
}

export interface HealthSnapshot {
  // index signature so snapshots can feed the generic MultiLineChart
  [key: string]: unknown;
  date: string;
  timestamp?: string;
  score: number;
  classification: HealthClassification;
  paper_pnl_pct?: number | null;
  benchmark_pnl_pct?: number | null;
  drawdown_pct?: number | null;
  concentration_top_weight?: number | null;
  turnover_per_year?: number | null;
  active_alerts: number;
  critical_alerts: number;
  warning_alerts: number;
}

export interface MonitorMetrics {
  session_id: string;
  mode: string;
  started_at: string;
  forward_days_completed: number;
  expected_trading_days: number;
  missed_days: number;
  days_remaining_to_min: number;
  days_remaining_to_target: number;
  min_days: number;
  target_days: number;
  last_run_date: string | null;
  ran_today: boolean;
  next_expected_run: string;
  paper_pnl_pct: number | null;
  benchmark_pnl_pct: number | null;
  excess_return_pct: number | null;
  tracking_error_pct_daily: number | null;
  current_drawdown_pct: number | null;
  concentration_top_weight: number | null;
  turnover_per_year: number | null;
  cash_drag_pct: number | null;
  n_holdings: number | null;
  benchmark_beta: number | null;
  avg_slippage_bps: number | null;
  order_count: number;
  rejected_orders: number;
  skipped_orders: number;
  reject_rate_pct: number;
  broker_errors: number;
  risk_breaches: number;
  data_quality_events: number;
  data_stale: boolean;
  can_generate_final_report: boolean;
  paper_vs_backtest_status: string;
  paper_vs_backtest_verdict: string;
  stop_state: string;
  weekly_due: boolean;
  final_review_ready: boolean;
}

export interface PaperMonitor {
  product: string;
  generated_at: string;
  session_id: string | null;
  active: boolean;
  metrics: MonitorMetrics & { message?: string };
  health: Record<string, unknown>;
  health_score: HealthScore;
  alerts: PaperAlert[];
  alert_counts: AlertCounts;
  paper_vs_backtest: { verdict: string; forward_days: number; rows: unknown[]; notes: string[] };
  suggested_next_action: string;
  snapshots?: HealthSnapshot[];
  live_eligible: boolean;
}

export interface AlertsResponse {
  live_eligible: boolean;
  alerts: PaperAlert[];
  counts: AlertCounts;
}

/** Compact monitoring summary embedded in /api/dashboard/summary for the cockpit. */
export interface MonitorCard {
  health_score: number;
  classification: HealthClassification;
  alert_counts: AlertCounts;
  next_expected_run: string | null;
  missed_days: number;
  weekly_due: boolean;
  final_review_ready: boolean;
  days_remaining_to_min: number;
  days_remaining_to_target: number;
  ran_today: boolean;
  suggested_next_action: string;
}

export const CLASS_TONE: Record<HealthClassification, string> = {
  healthy: "green", watch: "blue", degraded: "yellow", failed: "red", paused: "yellow",
};

export const SEVERITY_TONE: Record<AlertSeverity, string> = {
  info: "blue", warning: "yellow", critical: "red",
};
