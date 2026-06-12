import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../lib/api";
import type { AuditEvent, LogEvent } from "../lib/types";
import { fmtTs } from "../lib/formatters";
import DataTable from "../components/DataTable";
import { Badge, Card, statusTone } from "../components/ui";

const LEVELS = ["", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

export default function Logs() {
  const [level, setLevel] = useState("");
  const { data: logs } = useQuery({
    queryKey: ["logs", level],
    queryFn: () => apiGet<LogEvent[]>(`/api/logs?limit=300${level ? `&level=${level}` : ""}`),
    refetchInterval: 10000,
  });
  const { data: audit } = useQuery({
    queryKey: ["audit"], queryFn: () => apiGet<AuditEvent[]>("/api/audit?limit=100"),
  });

  return (
    <div className="space-y-4">
      <Card
        title="Application logs"
        right={
          <select value={level} onChange={(e) => setLevel(e.target.value)}
                  className="rounded-lg border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs">
            {LEVELS.map((l) => <option key={l} value={l}>{l || "all levels"}</option>)}
          </select>
        }
      >
        <DataTable
          rows={(logs ?? []) as unknown as Record<string, unknown>[]}
          searchKeys={["message", "logger", "level"]}
          csvName="logs.csv"
          pageSize={25}
          emptyText="No log records (start the paper trader or run a backtest)"
          columns={[
            { key: "ts", label: "time", render: (r) => <span className="mono text-xs">{String(r.ts).slice(0, 19)}</span> },
            {
              key: "level", label: "level",
              render: (r) => <Badge tone={
                { DEBUG: "gray", INFO: "blue", WARNING: "yellow", ERROR: "red", CRITICAL: "red" }[String(r.level)] ?? "gray"
              }>{String(r.level)}</Badge>,
            },
            { key: "logger", label: "logger", render: (r) => <span className="mono text-xs text-zinc-500">{String(r.logger)}</span> },
            { key: "message", label: "message", render: (r) => <span className="text-xs">{String(r.message).slice(0, 140)}</span> },
          ]}
        />
      </Card>

      <Card title="Dashboard audit trail">
        <DataTable
          rows={(audit ?? []) as unknown as Record<string, unknown>[]}
          searchKeys={["action", "result"]}
          csvName="audit.csv"
          emptyText="No dashboard actions yet"
          columns={[
            { key: "ts", label: "time", render: (r) => <span className="mono text-xs">{fmtTs(String(r.ts))}</span> },
            { key: "actor", label: "actor" },
            { key: "action", label: "action", render: (r) => <Badge tone="blue">{String(r.action)}</Badge> },
            { key: "mode", label: "mode" },
            { key: "confirmed", label: "confirmed", render: (r) => <Badge tone={statusTone(r.confirmed ? "filled" : "rejected")}>{String(r.confirmed)}</Badge> },
            { key: "result", label: "result", render: (r) => <span className="text-xs text-zinc-400">{String(r.result).slice(0, 100)}</span> },
          ]}
        />
      </Card>
    </div>
  );
}
