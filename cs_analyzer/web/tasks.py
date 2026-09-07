"""Background task manager for slow renders (parse / replay / radar).

A simple thread-pool job registry: submit(fn, **kw) returns a job id; the job
runs in a worker thread and its status/progress/result/error are polled via
get_status(). No external queue — fine for a local single-user tool.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    status: str = "pending"  # pending | running | done | error
    progress: float = 0.0
    result: str | None = None
    error: str | None = None
    started: float = 0.0
    finished: float = 0.0
    label: str = ""  # human-readable name (e.g. original demo filename)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "label": self.label,
        }


class TaskManager:
    #: Registry cap (F11): finished jobs are evicted oldest-first so a
    #  long-running server can't grow _jobs unbounded. Pending/running jobs
    #  are never evicted (they must stay pollable); if the queue itself is
    #  larger than the cap, eviction simply finds nothing to drop this round.
    _MAX_JOBS = 200

    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="csa-task")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, fn, *, label: str = "", **kwargs) -> str:
        job_id = uuid.uuid4().hex[:12]
        job = Job(id=job_id, label=label)
        with self._lock:
            self._jobs[job_id] = job
            if len(self._jobs) > self._MAX_JOBS:
                finished = sorted(
                    (j for j in self._jobs.values() if j.status in ("done", "error")),
                    key=lambda j: j.finished,
                )
                for old in finished[: len(self._jobs) - self._MAX_JOBS]:
                    self._jobs.pop(old.id, None)

        def _run() -> None:
            job.status = "running"
            job.started = time.time()
            try:
                result = fn(**kwargs)
                job.status = "done"
                job.result = str(result)
            except Exception as exc:  # noqa: BLE001
                logger.exception("task %s failed", job_id)
                job.status = "error"
                job.error = str(exc)
            finally:
                job.finished = time.time()
                job.progress = 1.0

        self._pool.submit(_run)
        return job_id

    def get_status(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.started, reverse=True)

    def recent(self, limit: int = 20) -> list[Job]:
        return self.list_jobs()[:limit]


tasks = TaskManager()
