"""Tests for the MCP long-running-job registry."""
from __future__ import annotations

import time

import pytest

from wirestudio.mcp.jobs import JobNotFound, JobRegistry


def _wait(reg: JobRegistry, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = reg.status(job_id)
        if snap["state"] != "running":
            return snap
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} still running after {timeout}s")


def test_sync_generator_events_are_collected():
    reg = JobRegistry()
    job_id = reg.start("compile", lambda: iter(
        [{"step": 1}, {"step": 2}, {"step": 3}]
    ))
    snap = _wait(reg, job_id)
    assert snap["state"] == "done"
    assert snap["event_count"] == 3
    assert snap["last_event"] == {"step": 3}
    assert reg.events(job_id)["events"] == [{"step": 1}, {"step": 2}, {"step": 3}]


def test_async_generator_is_driven_on_the_worker():
    async def produce():
        for i in range(3):
            yield {"step": i}

    reg = JobRegistry()
    job_id = reg.start("flash", produce)
    snap = _wait(reg, job_id)
    assert snap["state"] == "done"
    assert snap["event_count"] == 3


def test_producer_exception_becomes_error_state():
    def produce():
        yield {"step": 1}
        raise RuntimeError("bench went away")

    reg = JobRegistry()
    job_id = reg.start("flash", produce)
    snap = _wait(reg, job_id)
    assert snap["state"] == "error"
    assert "bench went away" in snap["error"]
    # Events emitted before the failure are still readable.
    assert reg.events(job_id)["events"] == [{"step": 1}]


def test_events_paginate_with_a_cursor():
    reg = JobRegistry()
    job_id = reg.start("compile", lambda: iter([{"n": i} for i in range(10)]))
    _wait(reg, job_id)

    first = reg.events(job_id, since=0, limit=4)
    assert first["events"] == [{"n": i} for i in range(4)]
    assert first["next_since"] == 4
    assert first["done"] is False

    rest = reg.events(job_id, since=first["next_since"], limit=100)
    assert rest["events"] == [{"n": i} for i in range(4, 10)]
    assert rest["done"] is True


def test_unknown_job_raises():
    with pytest.raises(JobNotFound):
        JobRegistry().status("nope")


def test_running_jobs_are_never_evicted():
    """A full registry must not drop work still in flight."""
    reg = JobRegistry(max_jobs=2)
    release = []

    def blocker():
        while not release:
            time.sleep(0.005)
        yield {"done": True}

    live = reg.start("flash", blocker)
    for _ in range(5):
        finished = reg.start("compile", lambda: iter([{"x": 1}]))
        _wait(reg, finished)

    # The blocked job survived five evictions of finished jobs.
    assert reg.status(live)["state"] == "running"
    release.append(True)
    assert _wait(reg, live)["state"] == "done"


def test_non_dict_events_are_wrapped_not_dropped():
    reg = JobRegistry()
    job_id = reg.start("compile", lambda: iter(["plain line"]))
    _wait(reg, job_id)
    assert reg.events(job_id)["events"] == [{"message": "plain line"}]
