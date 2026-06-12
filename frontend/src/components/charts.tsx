import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

const AXIS = { stroke: "#52525b", fontSize: 11 } as const;
const GRID = { stroke: "#27272a", strokeDasharray: "3 3" } as const;
const TOOLTIP = {
  contentStyle: { background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 },
  labelStyle: { color: "#a1a1aa" },
} as const;

const shortTs = (ts: string) => String(ts).slice(5, 16);

export function EquityChart({ data, height = 240 }: {
  data: { ts: string; equity: number }[]; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data}>
        <defs>
          <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#10b981" stopOpacity={0.35} />
            <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="ts" tickFormatter={shortTs} {...AXIS} minTickGap={60} />
        <YAxis domain={["auto", "auto"]} {...AXIS} width={70} />
        <Tooltip {...TOOLTIP} />
        <Area type="monotone" dataKey="equity" stroke="#10b981" fill="url(#eqFill)" strokeWidth={1.5} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function DrawdownChart({ data, height = 180 }: {
  data: { ts: string; equity: number }[]; height?: number;
}) {
  let peak = -Infinity;
  const dd = data.map((p) => {
    peak = Math.max(peak, p.equity);
    return { ts: p.ts, dd: peak > 0 ? ((p.equity - peak) / peak) * 100 : 0 };
  });
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={dd}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="ts" tickFormatter={shortTs} {...AXIS} minTickGap={60} />
        <YAxis {...AXIS} width={50} tickFormatter={(v: number) => `${v.toFixed(1)}%`} />
        <Tooltip {...TOOLTIP} formatter={(value: unknown) => [`${Number(value).toFixed(3)}%`, "drawdown"]} />
        <Area type="monotone" dataKey="dd" stroke="#ef4444" fill="#ef444433" strokeWidth={1.5} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function ExposureChart({ data, height = 180 }: {
  data: { ts: string; gross: number; net: number }[]; height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="ts" tickFormatter={shortTs} {...AXIS} minTickGap={60} />
        <YAxis {...AXIS} width={60} />
        <Tooltip {...TOOLTIP} />
        <Line type="monotone" dataKey="gross" stroke="#38bdf8" strokeWidth={1.5} dot={false} />
        <Line type="monotone" dataKey="net" stroke="#a78bfa" strokeWidth={1.5} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function PnlBars({ values, height = 180 }: { values: number[]; height?: number }) {
  const data = values.map((v, i) => ({ i: i + 1, pnl: v }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="i" {...AXIS} />
        <YAxis {...AXIS} width={50} />
        <Tooltip {...TOOLTIP} />
        <Bar dataKey="pnl">
          {data.map((d, i) => (
            <Cell key={i} fill={d.pnl >= 0 ? "#10b981" : "#ef4444"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
