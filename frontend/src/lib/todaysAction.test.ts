import { describe, it, expect } from "vitest";
import { computeTodaysAction, type TodaysActionInput } from "./todaysAction";

const base: TodaysActionInput = {
  controlsEnabled: true,
  killSwitchActive: false,
  decisionStatus: "paper_candidate",
  health: { state: "IN PROGRESS", mode: "shadow", last_run_date: null, missing_days_gap: 0, min_days: 30, days_remaining: 27, forward_days_completed: 3 },
  trading212: { enabled: true, api_key_configured: true, allow_demo_orders: false },
  todayUtc: "2026-06-15",
};

describe("computeTodaysAction priority", () => {
  it("kill switch wins over everything", () => {
    const a = computeTodaysAction({ ...base, killSwitchActive: true });
    expect(a.key).toBe("kill-switch");
    expect(a.tone).toBe("danger");
    expect(a.ctaHref).toBe("/safety");
  });

  it("non-candidate product stops the operator", () => {
    const a = computeTodaysAction({ ...base, decisionStatus: "do_not_trade" });
    expect(a.key).toBe("product-not-candidate");
    expect(a.ctaHref).toBe("/product-decision");
  });

  it("no session → start one", () => {
    const a = computeTodaysAction({ ...base, health: { ...base.health, state: "NOT STARTED" } });
    expect(a.key).toBe("start-session");
    expect(a.ctaLabel).toMatch(/start supervised paper session/i);
  });

  it("no session + missing broker creds → setup check", () => {
    const a = computeTodaysAction({
      ...base,
      health: { ...base.health, state: "NOT STARTED" },
      trading212: { enabled: true, api_key_configured: false, allow_demo_orders: false },
    });
    expect(a.key).toBe("broker-not-configured");
    expect(a.ctaHref).toBe("/t212-setup");
  });

  it("already ran today → no action needed", () => {
    const a = computeTodaysAction({ ...base, health: { ...base.health, last_run_date: "2026-06-15" } });
    expect(a.key).toBe("done-today");
    expect(a.tone).toBe("ok");
  });

  it("active session, nothing today → run today", () => {
    const a = computeTodaysAction({ ...base, health: { ...base.health, last_run_date: "2026-06-13" } });
    expect(a.key).toBe("run-today");
  });

  it("multi-day gap → review missed days", () => {
    const a = computeTodaysAction({ ...base, health: { ...base.health, last_run_date: "2026-06-10", missing_days_gap: 5 } });
    expect(a.key).toBe("missed-day");
    expect(a.tone).toBe("warn");
  });

  it("minimum reached → generate final report", () => {
    const a = computeTodaysAction({ ...base, health: { ...base.health, state: "READY FOR FINAL REVIEW" } });
    expect(a.key).toBe("final-report");
  });

  it("failed run → review failed job", () => {
    const a = computeTodaysAction({ ...base, health: { ...base.health, state: "FAILED" } });
    expect(a.key).toBe("failed-job");
  });

  it("flags read-only when controls are disabled", () => {
    const a = computeTodaysAction({ ...base, controlsEnabled: false, health: { ...base.health, state: "NOT STARTED" } });
    expect(a.readOnlyNote).toBe(true);
  });
});
