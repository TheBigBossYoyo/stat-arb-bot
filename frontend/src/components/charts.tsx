import { useMemo, type ReactNode } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { EmptyState } from "./ui";
import { useTheme } from "../theme/useTheme";

/** Read a CSS custom property off <html>, with a fallback for SSR/jsdom. */
function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined" || typeof getComputedStyle !== "function") return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

/** Theme-aware chart chrome (axis/grid/tooltip). Re-reads when the theme flips. */
export function useChartTheme() {
  const { resolvedTheme } = useTheme();
  return useMemo(() => {
    const axisStroke = cssVar("--chart-axis", "#52525b");
    const gridStroke = cssVar("--chart-grid", "#27272a");
    const tipBg = cssVar("--chart-tooltip-bg", "#18181b");
    const tipBorder = cssVar("--chart-tooltip-border", "#3f3f46");
    const tipLabel = cssVar("--chart-tooltip-label", "#a1a1aa");
    return {
      axis: { stroke: axisStroke, fontSize: 11 },
      grid: { stroke: gridStroke, strokeDasharray: "3 3" },
      tooltip: {
        contentStyle: {
          background: tipBg, border: `1px solid ${tipBorder}`,
          borderRadius: 8, fontSize: 12, color: cssVar("--card-foreground", "#f4f4f5"),
        },
        labelStyle: { color: tipLabel },
        cursor: { stroke: tipBorder },
      },
    };
    // resolvedTheme is the dependency that triggers a re-read on theme change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resolvedTheme]);
}

/** Shared palette so every chart pulls from the same set of accent colours.
 *  These accent hues read well on both light and dark backgrounds. */
export const CHART_COLORS = ["#38bdf8", "#a78bfa", "#10b981", "#f59e0b", "#f472b6", "#34d399"];

const shortTs = (ts: string) => String(ts).slice(5, 16);

/** Consistent titled container for any chart, with an empty fallback. */
export function ChartCard({ title, right, height = 240, empty, children }: {
  title: string; right?: ReactNode; height?: number; empty?: boolean; children: ReactNode;
}) {
  return (
    <div className="card-elevated rounded-xl border border-zinc-800 bg-zinc-900/60">
      <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-2.5">
        <div className="text-sm font-semibold text-zinc-200">{title}</div>
        {right}
      </div>
      <div className="p-3">
        {empty ? <EmptyState text="No data to chart yet" /> : <div style={{ height }}>{children}</div>}
      </div>
    </div>
  );
}

export function EquityChart({ data, height = 240 }: {
  data: { ts: string; equity: number }[]; height?: number;
}) {
  const { axis, grid, tooltip } = useChartTheme();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data}>
        <defs>
          <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid {...grid} />
        <XAxis dataKey="ts" tickFormatter={shortTs} {...axis} minTickGap={60} />
        <YAxis domain={["auto", "auto"]} {...axis} width={70} />
        <Tooltip {...tooltip} />
        <Area type="monotone" dataKey="equity" stroke="#10b981" fill="url(#eqFill)" strokeWidth={1.5} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function DrawdownChart({ data, height = 180 }: {
  data: { ts: string; equity: number }[]; height?: number;
}) {
  const { axis, grid, tooltip } = useChartTheme();
  let peak = -Infinity;
  const dd = data.map((p) => {
    peak = Math.max(peak, p.equity);
    return { ts: p.ts, dd: peak > 0 ? ((p.equity - peak) / peak) * 100 : 0 };
  });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={dd}>
        <CartesianGrid {...grid} />
        <XAxis dataKey="ts" tickFormatter={shortTs} {...axis} minTickGap={60} />
        <YAxis {...axis} width={50} tickFormatter={(v: number) => `${v.toFixed(1)}%`} />
        <Tooltip {...tooltip} formatter={(value: unknown) => [`${Number(value).toFixed(3)}%`, "drawdown"]} />
        <Area type="monotone" dataKey="dd" stroke="#ef4444" fill="#ef444433" strokeWidth={1.5} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function ExposureChart({ data, height = 180 }: {
  data: { ts: string; gross: number; net: number }[]; height?: number;
}) {
  const { axis, grid, tooltip } = useChartTheme();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data}>
        <CartesianGrid {...grid} />
        <XAxis dataKey="ts" tickFormatter={shortTs} {...axis} minTickGap={60} />
        <YAxis {...axis} width={60} />
        <Tooltip {...tooltip} />
        <Line type="monotone" dataKey="gross" stroke="#38bdf8" strokeWidth={1.5} dot={false} />
        <Line type="monotone" dataKey="net" stroke="#a78bfa" strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function PnlBars({ values, height = 180 }: { values: number[]; height?: number }) {
  const { axis, grid, tooltip } = useChartTheme();
  const data = values.map((v, i) => ({ i: i + 1, pnl: v }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid {...grid} />
        <XAxis dataKey="i" {...axis} />
        <YAxis {...axis} width={50} />
        <Tooltip {...tooltip} />
        <Bar dataKey="pnl">
          {data.map((d, i) => (
            <Cell key={i} fill={d.pnl >= 0 ? "#10b981" : "#ef4444"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Small filled area for hero/mini contexts — minimal chrome, fills its parent. */
export function MiniArea({ data, color = "#38bdf8", height = 64 }: {
  data: { x: string | number; y: number }[]; color?: string; height?: number;
}) {
  const { tooltip } = useChartTheme();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
        <defs>
          <linearGradient id={`mini-${color}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.4} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Tooltip {...tooltip} />
        <Area type="monotone" dataKey="y" stroke={color} fill={`url(#mini-${color})`} strokeWidth={1.5} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/** Horizontal labelled bars for per-bucket contribution (monthly / sector / day). */
export function ContributionChart({ data, height = 220, unit = "%" }: {
  data: { label: string; value: number }[]; height?: number; unit?: string;
}) {
  const { axis, grid, tooltip } = useChartTheme();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ left: 12, right: 16 }}>
        <CartesianGrid {...grid} horizontal={false} />
        <XAxis type="number" {...axis} tickFormatter={(v: number) => `${v}${unit}`} />
        <YAxis type="category" dataKey="label" {...axis} width={110} />
        <Tooltip {...tooltip} formatter={(v: unknown) => [`${Number(v).toFixed(2)}${unit}`, "contribution"]} />
        <Bar dataKey="value" radius={[0, 3, 3, 0]}>
          {data.map((d, i) => <Cell key={i} fill={d.value >= 0 ? "#10b981" : "#ef4444"} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Per-scenario drawdown bars (crisis / survivorship). More negative = worse. */
export function ScenarioDrawdownChart({ data, height = 260, threshold = -45 }: {
  data: { scenario: string; dd: number }[]; height?: number; threshold?: number;
}) {
  const { axis, grid, tooltip } = useChartTheme();
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ left: 4, right: 8, bottom: 24 }}>
        <CartesianGrid {...grid} />
        <XAxis dataKey="scenario" {...axis} angle={-25} textAnchor="end" interval={0} height={60} />
        <YAxis {...axis} width={50} tickFormatter={(v: number) => `${v}%`} />
        <Tooltip {...tooltip} formatter={(v: unknown) => [`${Number(v).toFixed(1)}%`, "max DD"]} />
        <Bar dataKey="dd" radius={[3, 3, 0, 0]}>
          {data.map((d, i) => (
            <Cell key={i} fill={d.dd <= threshold ? "#ef4444" : d.dd <= threshold / 1.5 ? "#f59e0b" : "#10b981"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
