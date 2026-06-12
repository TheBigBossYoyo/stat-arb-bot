export interface KillSwitchState { active: boolean; reason: string }

export interface BrokerStatus {
  broker: string; display_name: string; enabled: boolean; mode: string;
  asset_class: string; key_configured: boolean; connected: boolean | null;
  latency_ms: number | null; detail: string;
  capabilities: Record<string, unknown>;
}

export interface SystemStatus {
  mode: string; bot_status: string; app_env: string;
  live_trading_env: boolean; confirm_live_env: boolean; live_trading_allowed: boolean;
  controls_enabled: boolean; kill_switch: KillSwitchState;
  brokers: BrokerStatus[]; last_equity_ts: string | null;
  last_order_ts: string | null; server_time: string;
}

export interface PortfolioSummary {
  as_of: string | null; equity: number; cash: number; daily_pnl: number;
  total_pnl: number; realized_pnl: number; fees_paid: number;
  gross_exposure: number; net_exposure: number; open_pairs: number;
  current_drawdown_pct: number; max_drawdown_pct: number; n_trades: number;
  has_data: boolean;
}

export interface EquityPoint {
  ts: string; equity: number; gross: number; net: number; open_pairs: number;
}

export interface RiskLimitStatus {
  name: string; current: number; limit: number; pct_used: number; status: string;
}

export interface RiskStatus {
  kill_switch: KillSwitchState; limits: RiskLimitStatus[]; as_of: string;
}

export interface StrategyStatus {
  name: string; version: string; kind: string; paused: boolean; health: string;
  n_trades: number; total_pnl: number; win_rate_pct: number | null;
  total_fees: number; last_signal_ts: string | null;
}

export interface PairInfo {
  id: number; universe: string; interval: string; symbol_a: string; symbol_b: string;
  beta: number; alpha: number; correlation: number; eg_pvalue: number;
  adf_pvalue: number; half_life_bars: number; spread_std: number; score: number;
  is_active: boolean; window_start: string; window_end: string;
}

export interface BacktestSummary {
  id: number; strategy: string; interval: string; start_ts: string; end_ts: string;
  created_at: string; metrics: Record<string, number | string | null>;
  report_path: string;
}

export interface BacktestDetail extends BacktestSummary {
  params: Record<string, unknown>;
  equity: [string, number][];
  trades: Record<string, unknown>[];
}

export interface OrderInfo {
  id: number; ts: string; mode: string; broker: string; strategy: string;
  pair_key: string; symbol: string; side: string; order_type: string;
  quantity: number; ref_price: number; notional: number; status: string;
  fill_price: number; fee: number; error: string;
}

export interface TradeInfo {
  id: number; mode: string; strategy: string; pair_key: string; direction: string;
  entry_ts: string; exit_ts: string; holding_bars: number; entry_z: number;
  exit_z: number; pnl: number; fees: number; exit_reason: string;
}

export interface SignalInfo {
  id: number; ts: string; mode: string; strategy: string; pair_key: string;
  action: string; z_score: number; hedge_ratio: number; accepted: boolean;
  reject_reason: string;
}

export interface AuditEvent {
  id: number; ts: string; actor: string; action: string; mode: string;
  confirmed: boolean; payload: Record<string, unknown>; result: string;
}

export interface LogEvent { ts: string; level: string; logger: string; message: string }

export interface JobInfo {
  id: string; kind: string; status: string; started_at: string;
  finished_at: string | null; error: string; result: Record<string, unknown>;
}

export interface PerformanceRow {
  strategy?: string; pair_key?: string; n_trades: number; total_pnl: number;
  avg_pnl: number; win_rate_pct: number; total_fees: number; avg_holding_bars: number;
}
