// Types for the dashboard action/job orchestrator (backend app/dashboard/jobs.py).
import type { PaperHealth, Trading212Config } from "./productTypes";

export type JobStatus =
  | "queued" | "running" | "succeeded" | "failed" | "refused" | "cancelled";

export interface JobRecord {
  id: string;
  job_type: string;
  safety_level: string;
  status: JobStatus;
  params: Record<string, unknown>;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  progress: number;
  step: string;
  result: Record<string, unknown>;
  error: string;
  refusal_reason: string;
  audit_id: number | null;
  report_path: string | null;
  cancel_requested: boolean;
  live_eligible: boolean;
}

export interface ActionCapability {
  job_type: string;
  safety_level: string;
  min_role: string;
  confirm_level: string;
  phrase: string;
  needs_demo_env: boolean;
  needs_acknowledge: boolean;
  blocks_when_killed: boolean;
  requires_product_ok: boolean;
  live_eligible: boolean;
}

export interface CapabilitiesResp {
  live_eligible: boolean;
  controls_enabled: boolean;
  role: string;
  actions: ActionCapability[];
}

export interface ReportMeta {
  id: string;
  name: string;
  category: string;
  size: number;
  modified: number;
  stale: boolean;
  path: string;
}

export interface DashboardSummary {
  live_eligible: boolean;
  controls_enabled: boolean;
  kill_switch_active: boolean;
  product: string;
  decision: {
    headline: string; recommended: string; action: string;
    capital_stage: string; status: string;
  };
  health: PaperHealth;
  next_action: string;
  trading212: Trading212Config;
  reports: ReportMeta[];
  jobs: JobRecord[];
}

/** Body accepted by every named action endpoint. */
export interface ActionBody {
  params?: Record<string, unknown>;
  confirm_phrase?: string;
  acknowledge?: boolean;
  reason?: string;
}

export const TERMINAL_STATUSES: JobStatus[] =
  ["succeeded", "failed", "refused", "cancelled"];

export const isTerminal = (s: JobStatus | undefined): boolean =>
  !!s && TERMINAL_STATUSES.includes(s);
