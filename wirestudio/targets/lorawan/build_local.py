"""Local in-pod PlatformIO build backend for the LoRaWAN target.

Wraps ``compile.py`` (the content-addressed PlatformIO worker) in the
``BuildBackend`` shape so the lorawan API routes through the seam rather than
the worker directly. The job id is the cache key, so ``enqueue`` is a pure hash
(no build) and ``artifact`` reads the cached bin by id without needing the
design back.
"""
from __future__ import annotations

from typing import Iterator, Optional

from wirestudio.library import Library
from wirestudio.model import Design
from wirestudio.targets.build_backend import BuildUnavailable
from wirestudio.targets.lorawan.compile import (
    CompileUnavailable,
    _default_cache_dir,
    cache_key,
    compile_firmware_events,
    platformio_status,
)


class LocalCompileBackend:
    """In-pod PlatformIO build. One build at a time, content-addressed cache."""

    id = "local-platformio"

    def status(self) -> dict:
        return platformio_status()

    def enqueue(self, design: Design, library: Library) -> str:
        # The cache key folds in board + region + sub-band + template version,
        # so it both identifies the job and addresses the cached artifact.
        return cache_key(design, library)

    def stream(self, job_id: str, design: Design, library: Library) -> Iterator[dict]:
        # job_id is recomputed from the design by the worker; it's threaded
        # through so the signature matches a remote backend that polls by id.
        try:
            yield from compile_firmware_events(design, library)
        except CompileUnavailable as exc:
            raise BuildUnavailable(str(exc)) from exc

    def artifact(self, job_id: str, name: str = "firmware.bin") -> Optional[bytes]:
        path = _default_cache_dir() / job_id / name
        return path.read_bytes() if path.exists() else None
