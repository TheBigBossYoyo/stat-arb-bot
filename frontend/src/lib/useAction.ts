import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { apiGet, apiPost } from "./api";
import type { ActionBody, JobRecord } from "./actionTypes";
import { isTerminal } from "./actionTypes";
import { useUi } from "../store/ui";

const prettify = (jobType: string): string => jobType.replace(/_/g, " ");

/**
 * Submit one dashboard action to the orchestrator and poll its job until it
 * reaches a terminal state. A refusal is a normal (HTTP 200) outcome — the
 * backend re-validates every gate, so the UI just surfaces `refusal_reason`.
 */
export function useAction(endpoint: string, opts?: { onDone?: (job: JobRecord) => void }) {
  const toast = useUi((s) => s.toast);
  const [jobId, setJobId] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: (body: ActionBody) => apiPost<JobRecord>(endpoint, body ?? {}),
    onSuccess: (job) => setJobId(job.id),
    onError: (e) => toast("error", e instanceof Error ? e.message : String(e)),
  });

  const jobQuery = useQuery({
    queryKey: ["dash-job", jobId],
    queryFn: () => apiGet<JobRecord>(`/api/dashboard/jobs/${jobId}`),
    enabled: !!jobId,
    refetchInterval: (q) =>
      isTerminal((q.state.data as JobRecord | undefined)?.status) ? false : 700,
  });

  const job: JobRecord | null = jobQuery.data ?? submit.data ?? null;
  const notified = useRef<string | null>(null);

  useEffect(() => {
    if (!job || !isTerminal(job.status)) return;
    if (notified.current === job.id) return;
    notified.current = job.id;
    if (job.status === "succeeded") toast("success", `${prettify(job.job_type)} complete.`);
    else if (job.status === "refused") toast("error", job.refusal_reason || "action refused");
    else if (job.status === "failed") toast("error", job.error || "action failed");
    opts?.onDone?.(job);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.status]);

  return {
    run: (body?: ActionBody) => submit.mutate(body ?? {}),
    job,
    busy: submit.isPending || (!!job && !isTerminal(job.status)),
    reset: () => { setJobId(null); submit.reset(); notified.current = null; },
  };
}
