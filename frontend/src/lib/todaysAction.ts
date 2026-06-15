// Pure logic for the Command Center "Today's required action" card.
//
// Given the dashboard summary, it returns the single most important thing the
// operator should do right now, with a primary call-to-action. Kept side-effect
// free so it is unit-tested directly (see todaysAction.test.ts). The order of the
// rules below IS the priority — the first matching rule wins.

export type ActionTone = "info" | "ok" | "warn" | "danger" | "muted";

export interface TodaysActionInput {
  controlsEnabled: boolean;
  killSwitchActive: boolean;
  decisionStatus: string;
  health: {
    state: string;
    mode?: string;
    last_run_date?: string | null;
    missing_days_gap?: number;
    can_generate_final_report?: boolean;
    days_remaining?: number;
    forward_days_completed?: number;
    min_days?: number;
  };
  trading212: { enabled: boolean; api_key_configured: boolean; allow_demo_orders: boolean };
  latestJobFailed?: boolean;
  nextActionText?: string;
  /** Override "today" (UTC yyyy-mm-dd) for deterministic tests. */
  todayUtc?: string;
}

export interface TodaysAction {
  key: string;
  eyebrow: string;
  title: string;
  detail: string;
  tone: ActionTone;
  ctaLabel: string;
  ctaHref: string;
  /** When controls are read-only, the action page still opens but POSTs are disabled. */
  readOnlyNote?: boolean;
}

const todayIso = (): string => new Date().toISOString().slice(0, 10);

export function computeTodaysAction(input: TodaysActionInput): TodaysAction {
  const today = input.todayUtc ?? todayIso();
  const h = input.health;
  const state = (h.state ?? "").toUpperCase();
  const brokerDemoIntent = (h.mode ?? "").startsWith("demo");
  const brokerMissing = input.trading212.enabled && !input.trading212.api_key_configured;

  // 1) Kill switch — blocks everything until resolved.
  if (input.killSwitchActive) {
    return {
      key: "kill-switch",
      eyebrow: "Safety first",
      title: "Resolve the kill switch before continuing",
      detail: "The kill switch is engaged, so no actions can run. Review why it engaged, then disengage it from the Safety Center (stricter confirmation required).",
      tone: "danger",
      ctaLabel: "Open Safety Center",
      ctaHref: "/safety",
    };
  }

  // 2) Product is no longer a paper candidate — stop and review.
  if (input.decisionStatus && input.decisionStatus !== "paper_candidate") {
    return {
      key: "product-not-candidate",
      eyebrow: "Product decision",
      title: "Stop and review the product decision",
      detail: `The product decision is "${input.decisionStatus.replace(/_/g, " ")}", not paper_candidate. Paper/demo session actions are refused until the product is eligible again.`,
      tone: "danger",
      ctaLabel: "Review product decision",
      ctaHref: "/product-decision",
    };
  }

  // 3) A failed run / refused-or-failed job needs attention.
  if (state === "FAILED" || input.latestJobFailed) {
    return {
      key: "failed-job",
      eyebrow: "Needs attention",
      title: "Review the failed job",
      detail: "The most recent run did not complete. Open the run history to read the error or refusal reason before trying again.",
      tone: "warn",
      ctaLabel: state === "FAILED" ? "Open Supervised Paper" : "Open Safety Center",
      ctaHref: state === "FAILED" ? "/supervised-paper" : "/safety",
    };
  }

  // 4) Final review available — generate the final report.
  if (state === "READY FOR FINAL REVIEW" || h.can_generate_final_report) {
    return {
      key: "final-report",
      eyebrow: "Milestone reached",
      title: "Generate the final paper report",
      detail: `The minimum forward period is complete (${h.forward_days_completed ?? 0}/${h.min_days ?? 30} days). Generate the final supervised-paper report for review. This still does not enable anything live.`,
      tone: "ok",
      ctaLabel: "Generate final report",
      ctaHref: "/supervised-paper",
      readOnlyNote: !input.controlsEnabled,
    };
  }

  // 5) No session yet — start one (or fix the broker first if demo is intended).
  if (state === "NOT STARTED" || state === "") {
    if (brokerMissing) {
      return {
        key: "broker-not-configured",
        eyebrow: "Before you start",
        title: "Run the Trading 212 setup check",
        detail: "Trading 212 is enabled but demo credentials are not configured. Run the setup check and add demo keys to .env before starting a demo session. Shadow mode needs no broker.",
        tone: "warn",
        ctaLabel: "Open Trading 212 Setup",
        ctaHref: "/t212-setup",
      };
    }
    return {
      key: "start-session",
      eyebrow: "Get started",
      title: "Start a supervised paper session",
      detail: "Begin the forward supervised-paper period for long-only Trading 212. Start in shadow mode (no broker) — you can switch to demo preview later.",
      tone: "info",
      ctaLabel: "Start supervised paper session",
      ctaHref: "/supervised-paper",
      readOnlyNote: !input.controlsEnabled,
    };
  }

  // 6) Active session, but the broker is needed for the chosen demo mode.
  if (brokerDemoIntent && brokerMissing) {
    return {
      key: "broker-not-configured",
      eyebrow: "Needs attention",
      title: "Run the Trading 212 setup check",
      detail: "This session runs in a demo mode but Trading 212 demo credentials are missing. Configure them before the next demo day.",
      tone: "warn",
      ctaLabel: "Open Trading 212 Setup",
      ctaHref: "/t212-setup",
    };
  }

  // 7) Active session — already ran today?
  if (h.last_run_date && h.last_run_date === today) {
    return {
      key: "done-today",
      eyebrow: "All caught up",
      title: "No action needed today",
      detail: `Today's paper day has already been recorded (${h.last_run_date}). ${h.days_remaining ?? 0} forward day(s) remain until the ${h.min_days ?? 30}-day minimum.`,
      tone: "ok",
      ctaLabel: "View Supervised Paper",
      ctaHref: "/supervised-paper",
    };
  }

  // 8) Active session with a multi-day gap — review the missed day(s).
  if ((h.missing_days_gap ?? 0) >= 2) {
    return {
      key: "missed-day",
      eyebrow: "Needs attention",
      title: "Review the missed paper day(s)",
      detail: `It has been ${h.missing_days_gap} day(s) since the last recorded paper day. Review the gap, then run today's day. Replay days never count as forward days.`,
      tone: "warn",
      ctaLabel: "Open Supervised Paper",
      ctaHref: "/supervised-paper",
      readOnlyNote: !input.controlsEnabled,
    };
  }

  // 9) Active session, nothing run today — run today's day.
  return {
    key: "run-today",
    eyebrow: "Today's task",
    title: "Run today's shadow / demo-preview day",
    detail: `Record today's supervised paper day for long-only Trading 212. ${h.days_remaining ?? 0} forward day(s) remain until the ${h.min_days ?? 30}-day minimum. Demo execution stays gated.`,
    tone: "info",
    ctaLabel: "Run today's paper day",
    ctaHref: "/supervised-paper",
    readOnlyNote: !input.controlsEnabled,
  };
}
