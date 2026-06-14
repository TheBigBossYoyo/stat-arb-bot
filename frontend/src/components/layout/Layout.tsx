import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../../lib/api";
import type { SystemStatus } from "../../lib/types";
import { useChannel } from "../../lib/ws";
import { useUi } from "../../store/ui";
import { Badge } from "../ui";
import KillSwitchControl from "../KillSwitch";

const NAV = [
  { to: "/", label: "Dashboard", icon: "◧" },
  { to: "/portfolio", label: "Portfolio", icon: "◔" },
  { to: "/risk", label: "Risk Cockpit", icon: "⛨" },
  { to: "/execution", label: "Execution", icon: "⇄" },
  { to: "/strategies", label: "Strategies", icon: "ƒ" },
  { to: "/pairs", label: "Pair Discovery", icon: "⋈" },
  { to: "/backtests", label: "Backtesting Lab", icon: "∿" },
  { to: "/brokers", label: "Brokers", icon: "⌁" },
  { to: "/logs", label: "Logs & Audit", icon: "≡" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

const PRODUCT_NAV = [
  { to: "/product-decision", label: "Product Decision", icon: "◆" },
  { to: "/tradability", label: "Tradability", icon: "▦" },
  { to: "/blockers", label: "Blockers", icon: "⚑" },
  { to: "/live-readiness", label: "Live Readiness", icon: "⛔" },
  { to: "/concentration", label: "Concentration", icon: "▤" },
  { to: "/deflated-sharpe", label: "Deflated Sharpe", icon: "∑" },
  { to: "/crisis-lab", label: "Crisis Lab", icon: "☇" },
  { to: "/paper-setup", label: "T212 Paper Setup", icon: "▷" },
  { to: "/order-preview", label: "Order Preview", icon: "⇧" },
  { to: "/paper-monitor", label: "Paper Monitor", icon: "◷" },
];

export default function Layout({ children }: { children: ReactNode }) {
  const { data: polled } = useQuery({
    queryKey: ["status"],
    queryFn: () => apiGet<SystemStatus>("/api/status"),
    refetchInterval: 10000,
  });
  const live = useChannel<SystemStatus>("system");
  const status = live ?? polled;
  const wsStatus = useUi((s) => s.wsStatus);
  const toasts = useUi((s) => s.toasts);

  return (
    <div className="flex h-screen overflow-hidden">
      {/* sidebar */}
      <aside className="flex w-52 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950">
        <div className="border-b border-zinc-800 px-4 py-3.5">
          <div className="text-sm font-bold tracking-wide text-zinc-100">STAT-ARB</div>
          <div className="text-[10px] uppercase tracking-widest text-zinc-500">control panel</div>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition ${
                  isActive ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
                }`
              }
            >
              <span className="w-4 text-center text-zinc-500">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
          <div className="px-3 pb-1 pt-3 text-[10px] uppercase tracking-widest text-zinc-600">
            Tradable product
          </div>
          {PRODUCT_NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition ${
                  isActive ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
                }`
              }
            >
              <span className="w-4 text-center text-zinc-500">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-zinc-800 p-3">
          <KillSwitchControl compact />
        </div>
      </aside>

      {/* main */}
      <div className="flex min-w-0 flex-1 flex-col">
        <ModeBanner status={status} />
        <header className="flex items-center gap-3 border-b border-zinc-800 bg-zinc-950/80 px-4 py-2">
          <Badge tone={status?.bot_status === "running" ? "green" : status?.bot_status === "halted" ? "red" : "gray"}>
            bot: {status?.bot_status ?? "…"}
          </Badge>
          <Badge tone={status?.kill_switch.active ? "red" : "green"}>
            kill switch: {status?.kill_switch.active ? "ACTIVE" : "off"}
          </Badge>
          <Badge tone={status?.controls_enabled ? "violet" : "gray"}>
            {status?.controls_enabled ? "controls enabled" : "read-only"}
          </Badge>
          <div className="ml-auto flex items-center gap-2 text-xs text-zinc-500">
            <span className={`inline-block h-2 w-2 rounded-full ${
              wsStatus === "connected" ? "bg-emerald-500" : wsStatus === "reconnecting" ? "bg-amber-500" : "bg-zinc-600"
            }`} />
            ws: {wsStatus}
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
