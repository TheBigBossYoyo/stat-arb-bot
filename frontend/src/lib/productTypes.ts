// Types for the tradable-product / paper-readiness dashboard endpoints.

export interface ProductRow {
  product: string;
  name: string;
  venue: string;
  asset_class: string;
  shorting: boolean;
  leverage: boolean;
  venue_wired: boolean;
  venue_kind: string;
  gates_passed: number;
  gates_total: number;
  status: string;
  eligible_label: string;
  risk: string;
  missing: string[];
  notes: string[];
  live_eligible: boolean;
}

export interface ProductDecision {
  headline: string;
  recommended: string;
  action: string;
  capital_stage: string;
  live_eligible: boolean;
  products: ProductRow[];
}

export interface TradabilityMatrix {
  rows: ProductRow[];
  live_eligible_any: boolean;
}

export interface Blockers {
  per_product: { product: string; blocker: string }[];
  global: string[];
}

export interface LiveReadiness {
  live_eligible: boolean;
  headline: string;
  products: { product: string; status: string; eligible_label: string; gates: string }[];
}

export interface DeflatedSharpe {
  group: string;
  n_trials: number;
  with_sharpe: number;
  best_sharpe: number | null;
  mean_sharpe: number | null;
  std_sharpe: number | null;
  report: string;
}

export interface MarkdownReport {
  available: boolean;
  file?: string;
  report: string;
}

export interface Trading212Config {
  enabled: boolean;
  mode: string;
  account_type: string;
  api_key_configured: boolean;
  api_secret_configured: boolean;
  allow_demo_orders: boolean;
  live_orders_supported: boolean;
  kill_switch_active: boolean;
}

export interface OrderPreviewRow extends Record<string, unknown> {
  symbol: string;
  side: string;
  type: string;
  quantity: number;
  limit_price: number | null;
  ref_price: number;
  notional: number;
  target_weight: number;
  queued_for_open: boolean;
}

export interface OrderPreview {
  available: boolean;
  banner: string;
  live_eligible?: boolean;
  orders: OrderPreviewRow[];
  validation?: { ok: boolean; checks: Record<string, boolean>; issues: [string, string][] };
  summary?: Record<string, unknown>;
  error?: string;
}

export interface PaperStatus {
  active: boolean;
  message?: string;
  session_id?: string;
  product?: string;
  mode?: string;
  status?: string;
  started_at?: string;
  min_days?: number;
  forward_days_completed?: number;
  replay_days_recorded?: number;
  cycles?: number;
  last_date?: string;
  last_equity?: number;
}

export interface PaperFinal {
  available: boolean;
  message?: string;
  recommendation?: string;
  verdict?: string;
  live_eligible?: boolean;
  days_completed_forward?: number;
  replay_only_not_forward?: boolean;
  paper_pnl_pct?: number;
  benchmark_pnl_pct?: number | null;
  max_drawdown_pct?: number;
  checks?: Record<string, boolean>;
  equity_curve?: { date: string; equity: number }[];
}

export interface StopRule {
  rule: string;
  severity: string;
  detail: string;
  remediation: string;
}

export interface PaperHealth {
  state: string;
  product?: string;
  message?: string;
  session_id?: string;
  session_status?: string;
  stop_reason?: string;
  mode?: string;
  started_at?: string;
  min_days?: number;
  forward_days_completed?: number;
  days_remaining?: number;
  replay_days_recorded?: number;
  last_run_date?: string | null;
  missing_days_gap?: number;
  rejected_orders?: number;
  broker_errors?: number;
  paper_pnl_pct?: number;
  benchmark_pnl_pct?: number | null;
  tracking_error_pct_daily?: number | null;
  current_drawdown_pct?: number;
  concentration_top_weight?: number;
  turnover_per_year?: number;
  avg_slippage_bps?: number;
  max_reconciliation_drift?: number;
  risk_breaches?: number;
  data_quality_events?: number;
  can_generate_final_report?: boolean;
  stop_rules?: { state: string; triggered: StopRule[] };
  live_eligible?: boolean;
}

export interface OperatorStatus {
  product: string;
  live_eligible: boolean;
  controls_enabled: boolean;
  kill_switch_active: boolean;
  health: PaperHealth;
  decision: {
    headline: string; recommended: string; action: string;
    capital_stage: string; status: string;
  };
  trading212: {
    enabled: boolean; mode: string; api_key_configured: boolean;
    api_secret_configured: boolean; allow_demo_orders: boolean; live_orders_supported: boolean;
  };
  checklist: { item: string; done: boolean; note: string }[];
  next_action: string;
  latest_summary: string;
  confirm_phrase_demo_execute: string;
}

export interface OperatorRunResult {
  ok: boolean;
  refused?: boolean;
  terminal?: boolean;
  status_line?: string;
  next_action?: string;
  state?: string | null;
  live_eligible?: boolean;
}
