"""Thread-safe store of dashboard jobs (Phase 2).

Keeps the live job records in memory and mirrors a compact view to disk so the
operator can still see the last actions after a server restart. Also encodes the
*conflict* policy: two jobs that mutate the same paper session must never run at
once, and the same job type is never duplicated while one is already in flight.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.dashboard.action_schemas import JobRecord, JobStatus, JobType, SafetyLevel

log = get_logger(__name__)

# Job types that mutate the supervised-paper session: only one may run at a time.
_PAPER_MUTATORS: frozenset[JobType] = frozenset({
    JobType.SUPERVISED_PAPER_START,
    JobType.SUPERVISED_PAPER_DAILY_SHADOW,
    JobType.SUPERVISED_PAPER_DAILY_DEMO_PREVIEW,
    JobType.SUPERVISED_PAPER_DAILY_DEMO_EXECUTE,
    JobType.SUPERVISED_PAPER_FINAL_REPORT,
    JobType.SUPERVISED_PAPER_STOP,
})


def _conflict_group(job_type: JobType) -> str:
    """Jobs in the same group cannot run concurrently."""
    if job_type in _PAPER_MUTATORS:
        return "paper_session"
    if job_type == JobType.KILL_SWITCH_ACTION:
        return "kill_switch"
    return f"self:{job_type.value}"   # otherwise only de-dup against the same type


class JobStore:
    def __init__(self, persist_path: Path | None = None, max_jobs: int = 200) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._lock = threading.RLock()
        self._persist_path = Path(persist_path) if persist_path else None
        self._max_jobs = max_jobs

    # -- creation / lookup -------------------------------------------------------

    def create(self, job_type: JobType, safety_level: SafetyLevel,
               params: dict[str, Any], status: JobStatus = JobStatus.QUEUED) -> JobRecord:
        job = JobRecord(id=uuid.uuid4().hex[:12], job_type=job_type,
                        safety_level=safety_level, status=status, params=dict(params))
        with self._lock:
            self._jobs[job.id] = job
            self._evict_locked()
            self._persist_locked()
        return job

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, limit: int = 100) -> list[JobRecord]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    # -- mutation (always persist after) -----------------------------------------

    def set_status(self, job_id: str, status: JobStatus, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status
            if status == JobStatus.RUNNING and job.started_at is None:
                job.started_at = datetime.now(UTC)
            if status.terminal:
                job.finished_at = datetime.now(UTC)
            for k, v in fields.items():
                setattr(job, k, v)
            self._persist_locked()

    def append_log(self, job_id: str, line: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.logs.append(f"{datetime.now(UTC).isoformat(timespec='seconds')}  {line}")
            del job.logs[:-500]   # keep the tail bounded

    def set_progress(self, job_id: str, progress: float, step: str = "") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.progress = max(0.0, min(1.0, progress))
            if step:
                job.step = step

    def request_cancel(self, job_id: str) -> JobRecord | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            job.cancel_requested = True
            if job.status == JobStatus.QUEUED:
                job.status = JobStatus.CANCELLED
                job.finished_at = datetime.now(UTC)
            self._persist_locked()
            return job

    # -- conflict / de-dup -------------------------------------------------------

    def find_conflict(self, job_type: JobType) -> JobRecord | None:
        """An *active* job (queued/running) that conflicts with `job_type`, if any."""
        group = _conflict_group(job_type)
        with self._lock:
            for job in self._jobs.values():
                if job.status in (JobStatus.QUEUED, JobStatus.RUNNING) \
                        and _conflict_group(job.job_type) == group:
                    return job
        return None

    # -- internals ---------------------------------------------------------------

    def _evict_locked(self) -> None:
        if len(self._jobs) <= self._max_jobs:
            return
        terminal = sorted(
            (j for j in self._jobs.values() if j.status.terminal),
            key=lambda j: j.created_at,
        )
        for job in terminal[: len(self._jobs) - self._max_jobs]:
            self._jobs.pop(job.id, None)

    def _persist_locked(self) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            recent = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)[:50]
            data = [j.public() for j in recent]
            self._persist_path.write_text(json.dumps(data, default=str, indent=2),
                                          encoding="utf-8")
        except Exception:  # noqa: BLE001 — persistence is best-effort, never fatal
            log.debug("job store persist failed", exc_info=True)
