"""The dashboard action orchestrator (Phase 2).

`ActionOrchestrator.submit(request)` is the single entry point every dashboard
POST action goes through. It:

  1. validates every safety gate server-side (role / phrase / env / kill switch /
     product decision) — a failure becomes a REFUSED job, audited, with a reason;
  2. refuses duplicate / conflicting jobs (e.g. two paper-session mutations);
  3. creates the job record, writes an audit event, and links the two;
  4. runs the handler on a worker thread, capturing logs/progress and the result;
  5. transitions the job to SUCCEEDED / FAILED / CANCELLED.

There is no path here that can place a live order — the orchestrator only knows
the read / research / paper / demo handlers in `actions.HANDLERS`.
"""

from __future__ import annotations

import threading
from pathlib import Path

from app.config.settings import Settings
from app.core.logging import get_logger
from app.dashboard.action_audit import record_action
from app.dashboard.action_permissions import ACTION_SPECS, ActionRefused, evaluate_gates
from app.dashboard.action_schemas import (
    ActionRequest,
    JobRecord,
    JobStatus,
    SafetyLevel,
)
from app.dashboard.actions import HANDLERS, ActionContext, HandlerError
from app.dashboard.job_store import JobStore
from app.data.storage import Storage

log = get_logger(__name__)


class ActionOrchestrator:
    def __init__(self, settings: Settings, storage: Storage,
                 job_store: JobStore | None = None) -> None:
        self.settings = settings
        self.storage = storage
        self.store = job_store or JobStore(
            persist_path=Path(settings.runtime_dir) / "dashboard_jobs.json")

    # -- submit ------------------------------------------------------------------

    def submit(self, request: ActionRequest) -> JobRecord:
        spec = ACTION_SPECS.get(request.job_type)
        if spec is None:
            return self._refuse(request, SafetyLevel.READ, f"unknown action {request.job_type}")

        # 1) safety gates
        try:
            gate_ctx = evaluate_gates(self.settings, self.storage, request)
        except ActionRefused as exc:
            return self._refuse(request, spec.safety_level, exc.reason)

        # 2) conflict / de-dup
        conflict = self.store.find_conflict(request.job_type)
        if conflict is not None:
            return self._refuse(
                request, spec.safety_level,
                f"a conflicting job is already {conflict.status.value} "
                f"({conflict.job_type.value}, id {conflict.id}) — wait for it to finish.")

        # 3) create + audit + run
        job = self.store.create(request.job_type, spec.safety_level, request.params,
                                status=JobStatus.QUEUED)
        audit_id = record_action(
            self.storage, self.settings, action=f"job_{request.job_type.value}",
            confirmed=request.confirm_phrase.strip() != "",
            payload={**request.params, "reason": request.reason},
            result=f"queued job {job.id}")
        self.store.set_status(job.id, JobStatus.QUEUED, audit_id=audit_id)

        confirm_demo = bool(gate_ctx.get("confirm_demo"))
        self._spawn(job, request, confirm_demo)
        return job

    def _refuse(self, request: ActionRequest, safety: SafetyLevel, reason: str) -> JobRecord:
        job = self.store.create(request.job_type, safety, request.params,
                                status=JobStatus.REFUSED)
        audit_id = record_action(
            self.storage, self.settings, action=f"job_{request.job_type.value}",
            confirmed=False, payload={**request.params, "reason": request.reason},
            result=f"refused: {reason}")
        self.store.set_status(job.id, JobStatus.REFUSED, refusal_reason=reason,
                              audit_id=audit_id)
        log.info("dashboard action refused: %s — %s", request.job_type.value, reason)
        return job

    def _spawn(self, job: JobRecord, request: ActionRequest, confirm_demo: bool) -> None:
        handler = HANDLERS.get(request.job_type)
        if handler is None:
            self.store.set_status(job.id, JobStatus.FAILED,
                                  error=f"no handler for {request.job_type.value}")
            return

        def run() -> None:
            self.store.set_status(job.id, JobStatus.RUNNING)
            ctx = ActionContext(settings=self.settings, storage=self.storage,
                                params=request.params, confirm_demo=confirm_demo,
                                job=job, store=self.store)
            try:
                if job.cancel_requested:
                    self.store.set_status(job.id, JobStatus.CANCELLED,
                                          refusal_reason="cancelled before start")
                    return
                result = handler(ctx)
                report_path = result.pop("report_path", None) if isinstance(result, dict) else None
                self.store.set_status(job.id, JobStatus.SUCCEEDED, result=result or {},
                                      report_path=report_path, progress=1.0)
                self._finalise_audit(job, "succeeded")
            except HandlerError as exc:
                self.store.set_status(job.id, JobStatus.FAILED, error=str(exc)[:500])
                self._finalise_audit(job, f"failed: {exc}")
            except Exception as exc:  # noqa: BLE001 — reported on the job record
                log.exception("dashboard job %s failed", job.id)
                self.store.set_status(job.id, JobStatus.FAILED, error=str(exc)[:500])
                self._finalise_audit(job, f"error: {exc}")

        threading.Thread(target=run, daemon=True, name=f"action-{job.id}").start()

    def _finalise_audit(self, job: JobRecord, outcome: str) -> None:
        record_action(self.storage, self.settings,
                      action=f"job_{job.job_type.value}_result", confirmed=True,
                      payload={"job_id": job.id}, result=outcome)

    # -- queries / control -------------------------------------------------------

    def list_jobs(self, limit: int = 100) -> list[dict]:
        return [j.public() for j in self.store.list(limit)]

    def get_job(self, job_id: str) -> dict | None:
        job = self.store.get(job_id)
        return job.public() if job else None

    def job_logs(self, job_id: str) -> dict | None:
        job = self.store.get(job_id)
        if job is None:
            return None
        return {"id": job.id, "status": job.status.value, "step": job.step,
                "progress": round(job.progress, 3), "logs": list(job.logs)}

    def cancel(self, job_id: str) -> dict | None:
        job = self.store.request_cancel(job_id)
        if job is None:
            return None
        record_action(self.storage, self.settings, action="job_cancel", confirmed=True,
                      payload={"job_id": job_id}, result=f"cancel requested ({job.status.value})")
        return job.public()

    def capabilities(self) -> list[dict]:
        """The action catalogue the frontend uses to render buttons + gates."""
        out = []
        for jt, spec in ACTION_SPECS.items():
            out.append({
                "job_type": jt.value, "safety_level": spec.safety_level.value,
                "min_role": spec.min_role.name.lower(),
                "confirm_level": spec.confirm_level.value, "phrase": spec.phrase,
                "needs_demo_env": spec.needs_demo_env,
                "needs_acknowledge": spec.needs_acknowledge,
                "blocks_when_killed": spec.blocks_when_killed,
                "requires_product_ok": spec.requires_product_ok,
                "live_eligible": False,
            })
        return out
