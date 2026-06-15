"""Build-backend seam: how a design's generated firmware becomes a binary.

A *generate* step (``TargetPlugin.generate``) is pure text. A *build* step runs
a toolchain over that text to produce a flashable artifact -- slow, stateful,
with a streamed log that can fail. Today there's exactly one build path per
target (in-pod PlatformIO for lorawan; the fleet-for-esphome handoff for
esphome), but they share a shape: probe availability, enqueue a job, stream its
log, fetch the artifact.

``BuildBackend`` is that shape. The lorawan API routes through
``LorawanTarget.build_backend()`` instead of importing the compile worker
directly, so a *remote* LoRaWAN build worker (a build-agent pool, the way
fleet-for-esphome pools esphome builds) drops in later as a second backend
without touching the endpoint -- the same way a new sensor is a new library
block, not a generator edit. There's no remote LoRaWAN backend today; the seam
just keeps adding one additive.

The shape is deliberately the worker shape (``enqueue -> job_id``, then stream /
fetch by id) even though the local backend builds synchronously inside
``stream`` -- a remote worker pool needs the id-first split, and the local
backend satisfies it trivially (its id is the content-addressed cache key,
computable without building).
"""
from __future__ import annotations

from typing import Iterator, Optional, Protocol, runtime_checkable

from wirestudio.library import Library
from wirestudio.model import Design


class BuildUnavailable(RuntimeError):
    """The backend's toolchain / service isn't available (e.g. no PlatformIO on
    a cache-miss, or an unreachable build worker). Mirrors RenderUnavailable /
    CompileUnavailable: the API turns it into a 503 / SSE error frame."""


@runtime_checkable
class BuildBackend(Protocol):
    """A build path for a target's generated firmware.

    Implementations are cheap to construct and hold no per-build state between
    calls -- everything needed to resume is addressed by ``job_id``, so a build
    survives across requests (a remote worker keeps building; the local cache
    keeps the artifact).
    """

    id: str

    def status(self) -> dict:
        """Availability probe. Shape mirrors the other feature gates:
        ``{"available": bool, "reason": str | None, ...}``."""
        ...

    def enqueue(self, design: Design, library: Library) -> str:
        """Return the job id for building ``design``. Cheap and idempotent: the
        local backend returns the content-addressed cache key (no build yet); a
        remote worker submits the job and returns its handle."""
        ...

    def stream(self, job_id: str, design: Design, library: Library) -> Iterator[dict]:
        """Yield ``{"type": "log", "data": ...}`` events for the build, then a
        final ``{"type": "done", "ok": bool, "job_id": str, ...}``. The local
        backend runs the toolchain here (a warm cache replays the stored log);
        a remote worker polls and re-emits. Raises ``BuildUnavailable`` when the
        toolchain/service is missing on a cache miss."""
        ...

    def artifact(self, job_id: str, name: str = "firmware.bin") -> Optional[bytes]:
        """The built artifact bytes for ``job_id`` (``firmware.bin`` /
        ``factory.bin``), or None when absent (not built yet, or an OTA backend
        that installs rather than returns a file)."""
        ...
