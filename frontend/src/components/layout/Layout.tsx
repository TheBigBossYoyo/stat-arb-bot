import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../lib/api";
import type { SystemStatus } from "../../lib/types";
import type { DashboardSummary } from "../../lib/actionTypes";
import { useChannel } from "../../lib/ws";
import { useUi } from "../../store/ui";
import { Badge } from "../ui";
import KillSwitchControl from "../KillSwitch";

interface NavItem { to: string; label: string }
interface NavSection { title: string; items: NavItem[] }

const SECTIONS: NavSection[] = [
  { title: "Command Center", items: [
    { to: "/", label: "Overview" },
    { to: "/product-decision", label: "Product Decision" },
    { to: "/tradability", label: "Tradability" },
  ] },
  { title: "Long-only T212", items: [
    { to: "/readiness", label: "Readiness" },
    { to: "/concentration", label: "Concentration" },
    { to: "/survivorship", label: "Survivorship" },
    { to: "/crisis-lab", label: "Crisis Lab" },
    { to: "/order-preview", label: "Order Preview" },
  ] },
  { title: "Supervised Paper", items: [
    { to: "/supervised-paper", label: "Control Center" },
    { to: "/operator", label: "Daily Run" },
    { to: "/paper-monitor", label: "Monitor" },
  ] },
  { title: "Broker", items: [
    { to: "/t212-setup", label: "Trading 212 Setup" },
    { to: "/brokers", label: "Account / Status" },
  ] },
  { title: "Risk & Safety", items: [
    { to: "/live-readiness", label: "Live Readiness" },
    { to: "/safety", label: "Safety Center" },
    { to: "/blockers", label: "Blockers" },
  ] },
  { title: "Research", items: [
    { to: "/reports", label: "Reports Library" },
    { to: "/backtests", label: "Backtests" },
    { to: "/deflated-sharpe", label: "Deflated Sharpe" },
  ] },
  { title: "System", items: [
    { to: "/settings", label: "Settings" },
    { to: "/logs", label: "Logs & Audit" },
    { to: "/strategies", label: "Strategies" },
    { to: "/portfolio", label: "Portfolio" },
    { to: "/risk", label: "Risk Cockpit" },
    { to: "/execution", label: "Execution" },
    { to: "/pairs", label: "Pairs" },
  ] },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { data: polled } = useQuery({
    queryKey: ["status"],
    queryFn: () => apiGet<SystemStatus>("/api/status"),
    refetchInterval: 10000,
  });
  const { data: summary } = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => apiGet<DashboardSummary>("/api/dashboard/summary"),
    refetchInterval: 20000,
  });
  const live = useChannel<SystemStatus>("system");
  const status = live ?? polled;
  const wsStatus = useUi((s) => s.wsStatus);
  const toasts = useUi((s) => s.toasts);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* sidebar */}
      <aside className="flex w-56 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950">
        <div className="border-b border-zinc-800 px-4 py-3.5">
          <div className="text-sm font-bold tracking-wide text-zinc-100">STAT-ARB</div>
          <div className="text-[10px] uppercase tracking-widest text-zinc-500">control panel</div>
        </div>
        <nav className="flex-1 space-y-2 overflow-y-auto p-2">
          {SECTIONS.map((section) => (
            <div key={section.title}>
              <div className="px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
                {section.title}
              </div>
              {section.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm transition ${
                      isActive ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
                    }`
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <div className="border-t border-zinc-800 p-3">
          <KillSwitchControl compact />
        </div>
      </aside>

      {/* main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <ModeBanner status={status} />
        <header className="flex flex-wrap items-center gap-2 border-b border-zinc-800 bg-zinc-950/80 px-4 py-2">
          <Badge tone="red">⛔ NOT LIVE ELIGIBLE</Badge>
          <Badge tone={status?.mode === "live" ? "red" : "blue"}>mode: {status?.mode ?? "…"}</Badge>
          <Badge tone={status?.kill_switch.active ? "red" : "green"}>
            kill: {status?.kill_switch.active ? "ON" : "off"}
          </Badge>
          {summary && (
            <Badge tone={summary.decision.status === "paper_candidate" ? "green" : "yellow"}>
              {summary.decision.status}
            </Badge>
          )}
          {summary && (
            <Badge tone={summary.trading212.allow_demo_orders ? "violet" : "gray"}>
              T212 demo: {summary.trading212.enabled ? (summary.trading212.allow_demo_orders ? "orders on" : "preview") : "off"}
            </Badge>
          )}
          {summary?.health?.last_run_date && (
            <Badge tone="gray">last paper day: {summary.health.last_run_date}</Badge>
          )}
          <Badge tone={status?.controls_enabled ? "violet" : "gray"}>
            {status?.controls_enabled ? "controls" : "read-only"}
          </Badge>
          <div className="ml-auto flex items-center gap-2 text-xs text-zinc-500">
            <span className={`inline-block h-2 w-2 rounded-full ${
              wsStatus === "connected" ? "bg-emerald-500" : wsStatus === "reconnecting" ? "bg-amber-500" : "bg-zinc-600"
            }`} />
            {wsStatus}
            <span className="mono">{status ? new Date(status.server_time).toISOString().slice(11, 19) : ""} UTC</span>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto p-4">{children}</main>
      </div>

      {/* toasts */}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className={`pointer-events-auto rounded-lg border px-3 py-2 text-sm shadow-xl ${
            t.kind === "error" ? "border-red-500/40 bg-red-950 text-red-200"
            : t.kind === "success" ? "border-emerald-500/40 bg-emerald-950 text-emerald-200"
            : "border-zinc-700 bg-zinc-900 text-zinc-200"
          }`}>
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}

function ModeBanner({ status }: { status: SystemStatus | undefined | null }) {
  if (!status) return null;
  if (status.live_trading_allowed) {
    return (
      <div className="bg-red-600 px-4 py-2 text-center text-sm font-bold tracking-wide text-white">
        ⚠ LIVE TRADING ACTIVE — REAL MONEY AT RISK
      </div>
    );
  }
  return (
    <div className="border-b border-emerald-900/50 bg-emerald-950/40 px-4 py-1.5 text-center text-xs font-medium text-emerald-400">
      {status.mode.toUpperCase()} MODE — no real orders can be placed
    </div>
  );
}
