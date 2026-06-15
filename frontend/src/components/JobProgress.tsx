import type { JobRecord } from "../lib/actionTypes";
import { Badge } from "./ui";

const TONE: Record<string, string> = {
  queued: "gray", running: "blue", succeeded: "green",
  failed: "red", refused: "red", cancelled: "gray",
};

/** Live status of one orchestrator job: badge, step, progress, refusal/error, report. */
export default function JobProgress({ job }: { job?: JobRecord | null }) {
  if (!job) return null;
  const pct = Math.round((job.progress || 0) * 100);
  const running = job.status === "running" || job.status === "queued";
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-sm">
      <div className="flex items-center gap-2">
        <Badge tone={TONE[job.status] ?? "gray"}>{job.status}</Badge>
        <span className="text-zinc-300">{job.step || job.job_type.replace(/_/g, " ")}</span>
        {job.audit_id != null && (
          <span className="ml-auto text-xs text-zinc-600">audit #{job.audit_id}</span>
        )}
      </div>
      {running && (
        <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-zinc-800">
          <div className="h-full bg-sky-500 transition-all" style={{ width: `${pct}%` }} />
        </div>
      )}
      {job.refusal_reason && (
        <div className="mt-2 rounded border border-red-500/30 bg-red-500/10 px-2 py-1 text-red-300">
          Refused: {job.refusal_reason}
        </div>
      )}
      {job.error && <div className="mt-2 text-red-300">Error: {job.error}</div>}
      {job.report_path && (
        <div className="mt-2 text-xs text-zinc-500">
          Report written: <span className="mono text-zinc-400">{job.report_path}</span>
        </div>
      )}
    </div>
  );
}
