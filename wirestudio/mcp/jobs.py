"""In-process job registry for long-running MCP operations.

An MCP tool call returns once. Compile, flash and provision stream events
for minutes, so those tools start the work, hand back a `job_id`, and let
the client poll `job_status` / `job_events` until the state leaves
"running".

Jobs live in this process and die with it -- a restart loses them. Fleet
builds are the exception and deliberately stay outside this registry:
their `run_id` belongs to the fleet addon's GitHub run, survives a
wirestudio restart, and is polled through `fleet_job_status` instead.

Producers come in both flavours -- `backend.stream()` and
`provision_events()` are sync generators, `WorkbenchClient.flash()` is an
async one -- so `start()` accepts a zero-arg factory returning either and
drives it on a worker thread.
"""
from __future__ import annotations

import inspect
import itertools
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable, Optional

# Events are held per job so a client that polls slowly still sees the whole
# log. A compile emits a line per PlatformIO step; this bounds a runaway
# producer without truncating any build we have actually seen.
MAX_EVENTS_PER_JOB = 5000

# Completed jobs are evicted oldest-first once this many accumulate, so a
# long-lived server doesn't retain every build log it ever ran.
MAX_JOBS = 64


class JobNotFound(KeyError):
    """Raised when a job_id is unknown -- expired, or never existed."""


class _Job:
    __slots__ = ("id", "kind", "state", "events", "error", "started_at",
                 "finished_at", "label", "_lock")

    def __init__(self, job_id: str, kind: str, label: Optional[str]) -> None:
        self.id = job_id
        self.kind = kind
        self.label = label
        self.state = "running"
        self.events: list[dict] = []
        self.error: Optional[str] = None
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self._lock = threading.Lock()

    def append(self, event: dict) -> None:
        with self._lock:
            if len(self.events) < MAX_EVENTS_PER_JOB:
                self.events.append(event)

    def finish(self, state: str, error: Optional[str] = None) -> None:
        with self._lock:
            self.state = state
            self.error = error
            self.finished_at = time.time()

    def snapshot(self) -> dict:
        with self._lock:
            last = self.events[-1] if self.events else None
            return {
                "job_id": self.id,
                "kind": self.kind,
                "label": self.label,
                "state": self.state,
                "event_count": len(self.events),
                "last_event": last,
                "error": self.error,
                "started_at": self.started_at,
                "finished_at": self.finished_at,
                "elapsed_s": round(
                    (self.finished_at or time.time()) - self.started_at, 1
                ),
            }

    def slice(self, since: int, limit: int) -> dict:
        with self._lock:
            total = len(self.events)
            start = max(0, since)
            chunk = self.events[start:start + limit]
            return {
                "job_id": self.id,
                "state": self.state,
                "events": chunk,
                "since": start,
                "next_since": start + len(chunk),
                "event_count": total,
                "done": self.state != "running" and start + len(chunk) >= total,
                "error": self.error,
            }


class JobRegistry:
    """Thread-safe registry of running and recently-finished jobs."""

    def __init__(self, max_jobs: int = MAX_JOBS) -> None:
        self._jobs: OrderedDict[str, _Job] = OrderedDict()
        self._lock = threading.Lock()
        self._max_jobs = max_jobs
        self._counter = itertools.count(1)

    def start(
        self,
        kind: str,
        produce: Callable[[], Any],
        *,
        label: Optional[str] = None,
    ) -> str:
        """Run `produce()` on a worker thread, collecting its events.

        `produce` is a zero-arg callable returning a sync iterator or an
        async iterator of event dicts. It is called on the worker, not
        here, so a producer that blocks while starting doesn't stall the
        tool call that created the job.
        """
        job_id = f"{kind}-{next(self._counter)}-{uuid.uuid4().hex[:8]}"
        job = _Job(job_id, kind, label)
        with self._lock:
            self._jobs[job_id] = job
            self._evict_locked()

        threading.Thread(
            target=self._run, args=(job, produce), daemon=True,
            name=f"mcp-job-{job_id}",
        ).start()
        return job_id

    def _run(self, job: _Job, produce: Callable[[], Any]) -> None:
        try:
            source = produce()
            if inspect.isasyncgen(source) or inspect.isawaitable(source):
                self._drain_async(job, source)
            else:
                for event in source:
                    job.append(_as_event(event))
        except Exception as exc:  # producer failures become job state
            job.finish("error", f"{type(exc).__name__}: {exc}")
            return
        job.finish("done")

    def _drain_async(self, job: _Job, source: Any) -> None:
        import asyncio

        async def pump() -> None:
            agen = await source if inspect.isawaitable(source) else source
            async for event in agen:
                job.append(_as_event(event))

        asyncio.run(pump())

    def status(self, job_id: str) -> dict:
        return self._get(job_id).snapshot()

    def events(self, job_id: str, since: int = 0, limit: int = 200) -> dict:
        return self._get(job_id).slice(since, max(1, limit))

    def list(self) -> list[dict]:
        with self._lock:
            return [j.snapshot() for j in self._jobs.values()]

    def _get(self, job_id: str) -> _Job:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return job

    def _evict_locked(self) -> None:
        """Drop the oldest *finished* jobs past the cap.

        Running jobs are never evicted -- losing the handle to work still
        in flight would strand a client polling for it.
        """
        while len(self._jobs) > self._max_jobs:
            for jid, job in self._jobs.items():
                if job.state != "running":
                    del self._jobs[jid]
                    break
            else:
                return


def _as_event(event: Any) -> dict:
    """Producers yield dicts; anything else is wrapped rather than dropped."""
    if isinstance(event, dict):
        return event
    return {"message": str(event)}
