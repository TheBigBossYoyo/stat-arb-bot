import { useState, type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../lib/api";
import type { SystemStatus } from "../../lib/types";
import type { DashboardSummary } from "../../lib/actionTypes";
import { useChannel } from "../../lib/ws";
import { useUi } from "../../store/ui";
import { Badge } from "../ui";
import { Icons, type IconKey } from "../icons";
import KillSwitchControl from "../KillSwitch";
import ThemeToggle from "../ui/ThemeToggle";

interface NavItem { to: string; label: string; icon: IconKey }
interface NavSection { title: string; icon: IconKey; items: NavItem[] }

const SECTIONS: NavSection[] = [
  { title: "Command Center", icon: "command", items: [
    { to: "/", label: "Overview", icon: "gauge" },
    { to: "/product-decision", label: "Product Decision", icon: "target" },
    { to: "/tradability", label: "Tradability", icon: "layers" },
  ] },
  { title: "Long-only T212", icon: "target", items: [
    { to: "/readiness", label: "Readiness", icon: "check" },
    { to: "/concentration", label: "Concentration", icon: "chart" },
    { to: "/survivorship", label: "Survivorship", icon: "layers" },
    { to: "/crisis-lab", label: "Crisis Lab", icon: "flask" },
    { to: "/order-preview", label: "Order Preview", icon: "list" },
  ] },
  { title: "Supervised Paper", icon: "clipboard", items: [
    { to: "/supervised-paper", label: "Control Center", icon: "clipboard" },
    { to: "/operator", label: "Daily Run", icon: "refresh" },
    { to: "/paper-monitor", label: "Health Monitor", icon: "pulse" },
  ] },
  { title: "Broker", icon: "broker", items: [
    { to: "/t212-setup", label: "Trading 212 Setup", icon: "broker" },
    { to: "/brokers", label: "Account / Status", icon: "dot" },
  ] },
  { title: "Risk & Safety", icon: "shield", items: [
    { to: "/live-readiness", label: "Live Readiness", icon: "lock" },
    { to: "/safety", label: "Safety Center", icon: "shield" },
    { to: "/blockers", label: "Blockers", icon: "alert" },
  ] },
  { title: "Research", icon: "book", items: [
    { to: "/reports", label: "Reports Library", icon: "book" },
    { to: "/backtests", label: "Backtests", icon: "chart" },
    { to: "/deflated-sharpe", label: "Deflated Sharpe", icon: "pulse" },
  ] },
  { title: "System", icon: "cog", items: [
    { to: "/settings", label: "Settings", icon: "cog" },
    { to: "/logs", label: "Logs & Audit", icon: "list" },
    { to: "/strategies", label: "Strategies", icon: "layers" },
    { to: "/portfolio", label: "Portfolio", icon: "chart" },
    { to: "/risk", label: "Risk Cockpit", icon: "gauge" },
    { to: "/execution", label: "Execution", icon: "refresh" },
    { to: "/pairs", label: "Pairs", icon: "dot" },
  ] },
];

const COLLAPSE_KEY = "statarb.sidebar.collapsed";

export default function Layout({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState<boolean>(
    () => localStorage.getItem(COLLAPSE_KEY) === "1",
  );
  const toggleCollapsed = () => {
    setCollapsed((c) => {
      localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1");
      return !c;
    });
  };

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
      <aside className={`flex shrink-0 flex-col border-r border-zinc-800 bg-zinc-950/95 transition-all duration-200 ${collapsed ? "w-16" : "w-60"}`}>
        <div className="flex items-center gap-2.5 border-b border-zinc-800 px-3 py-3.5">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-sky-500/30 to-violet-500/30 text-sky-300">
            <Icons.pulse size={18} />
          </span>
          {!collapsed && (
            <div className="min-w-0">
              <div className="truncate text-sm font-bold tracking-wide text-zinc-100">STAT-ARB</div>
              <div className="text-[10px] uppercase tracking-widest text-zinc-500">control panel</div>
            </div>
          )}
          <button
            onClick={toggleCollapsed}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className={`ml-auto rounded-md p-1 text-zinc-500 transition hover:bg-zinc-800 hover:text-zinc-300 ${collapsed ? "rotate-0" : "rotate-180"}`}
          >
            <Icons.chevron size={15} />
          </button>
        </div>

        <nav className="flex-1 space-y-1.5 overflow-y-auto p-2">
          {SECTIONS.map((section) => {
            const GroupIcon = Icons[section.icon];
            return (
              <div key={section.title}>
                {collapsed ? (
                  <div className="flex justify-center py-1 text-zinc-700"><GroupIcon size={14} /></div>
                ) : (
                  <div className="flex items-center gap-1.5 px-3 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
                    {section.title}
                  </div>
                )}
                {section.items.map((item) => {
                  const ItemIcon = Icons[item.icon];
                  return (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      end={item.to === "/"}
                      title={collapsed ? item.label : undefined}
                      className={({ isActive }) =>
                        `group relative flex items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm transition ${
                          collapsed ? "justify-center" : ""
                        } ${
                          isActive
                            ? "bg-sky-500/10 text-sky-200"
                            : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
                        }`
                      }
                    >
                      {({ isActive }) => (
                        <>
                          {isActive && !collapsed && (
                            <span className="absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-sky-400" />
                          )}
                          <ItemIcon size={16} className={isActive ? "text-sky-300" : "text-zinc-500 group-hover:text-zinc-300"} />
                          {!collapsed && <span className="truncate">{item.label}</span>}
                        </>
                      )}
                    </NavLink>
                  );
                })}
              </div>
            );
          })}
        </nav>

        <div className="border-t border-zinc-800 p-3">
          {collapsed ? (
            <NavLink to="/safety" title="Kill switch — Safety Center"
                     className="flex justify-center text-zinc-400 hover:text-red-300">
              <Icons.power size={18} />
            </NavLink>
          ) : (
            <KillSwitchControl />
          )}
        </div>
      </aside>

      {/* main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <ModeBanner status={status} />
        <TopBar status={status} summary={summary} wsStatus={wsStatus} />
        <main className="flex-1 overflow-y-auto p-4 lg:p-6">{children}</main>
      </div>

      {/* toasts */}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className={`fade-in pointer-events-auto rounded-lg border px-3 py-2 text-sm pop-elevated ${
            t.kind === "error" ? "border-red-500/40 bg-red-500/10 text-red-700 dark:bg-red-950 dark:text-red-200"
            : t.kind === "success" ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-200"
            : "border-zinc-700 bg-zinc-900 text-zinc-200"
          }`}>
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}

function TopBar({ status, summary, wsStatus }: {
  status: SystemStatus | undefined | null;
  summary: DashboardSummary | undefined;
  wsStatus: string;
}) {
  return (
    <header className="flex flex-wrap items-center gap-2 border-b border-zinc-800 bg-zinc-950/80 px-4 py-2 backdrop-blur">
      <Badge tone="red" dot>NOT LIVE ELIGIBLE</Badge>
      <span className="hidden text-zinc-700 sm:inline">|</span>
      <Badge tone={status?.mode === "live" ? "red" : "blue"}>mode: {status?.mode ?? "…"}</Badge>
      {summary && (
        <Badge tone={summary.decision.status === "paper_candidate" ? "green" : "yellow"} dot>
          {summary.decision.status.replace(/_/g, " ")}
        </Badge>
      )}
      <Badge tone={status?.kill_switch.active ? "red" : "green"} dot={status?.kill_switch.active}>
        kill: {status?.kill_switch.active ? "ON" : "off"}
      </Badge>
      {summary && (
        <Badge tone={summary.trading212.allow_demo_orders ? "violet" : "gray"}>
          T212 demo: {summary.trading212.enabled ? (summary.trading212.allow_demo_orders ? "orders on" : "preview") : "off"}
        </Badge>
      )}
      <Badge tone={status?.controls_enabled ? "violet" : "gray"}>
        {status?.controls_enabled ? "controls" : "read-only"}
      </Badge>
      {summary?.health?.last_run_date && (
        <Badge tone="gray">last paper day: {summary.health.last_run_date}</Badge>
      )}
      <div className="ml-auto flex items-center gap-2 text-xs text-zinc-500">
        <span className={`inline-block h-2 w-2 rounded-full ${
          wsStatus === "connected" ? "bg-emerald-500" : wsStatus === "reconnecting" ? "bg-amber-500" : "bg-zinc-600"
        }`} />
        <span className="hidden sm:inline">{wsStatus}</span>
        <span className="mono">{status ? new Date(status.server_time).toISOString().slice(11, 19) : "--:--:--"} UTC</span>
        <ThemeToggle />
      </div>
    </header>
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
    <div className="border-b border-emerald-500/30 bg-emerald-500/10 px-4 py-1.5 text-center text-xs font-medium text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/40 dark:text-emerald-400">
      {status.mode.toUpperCase()} MODE — no real orders can be placed
    </div>
  );
}
