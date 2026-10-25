"""Build WLED with a design's usermods compiled in.

The release image serves a design made of runtime-tier parts; a usermod
makes it a custom build. This runs that build the way the lorawan
target's worker does: a shallow checkout of WLED at `WLED_RELEASE` in the
firmware cache, the design's `platformio_override.ini` dropped in, and
`pio run -e wirestudio` streamed, with the artifact kept under a key
that hashes the override and the release. WLED's pre-build step bundles
its web UI with npm, so Node is as much a requirement as PlatformIO.
"""
from __future__ import annotations

import fcntl
import hashlib
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Iterator, Optional

from wirestudio.library import Library
from wirestudio.model import Design
from wirestudio.targets.build_backend import BuildUnavailable
from wirestudio.targets.lorawan.compile import (
    _default_cache_dir,
    _merge_factory,
    _pio_cmd,
    platformio_status,
)
from wirestudio.targets.wled import WLED_RELEASE, build_platformio_override

WLED_REPO = "https://github.com/wled/WLED"
_ENV = "wirestudio"
_TIMEOUT = 1800
_CACHE_VERSION = "1"


def cache_dir() -> Path:
    return _default_cache_dir() / "wled"


def cache_key(override: str) -> str:
    h = hashlib.sha256()
    h.update(f"{_CACHE_VERSION}\0{WLED_RELEASE}\0".encode())
    h.update(override.encode())
    return h.hexdigest()[:16]


def status() -> dict:
    """PlatformIO, git and node together; the headline is `available`."""
    base = platformio_status()
    missing = [tool for tool in ("git", "node", "npm") if shutil.which(tool) is None]
    reasons = [r for r in (base.get("reason"),) if r]
    if missing:
        reasons.append(f"{', '.join(missing)} not found; WLED's build clones the release and bundles its web UI")
    return {**base, "available": base["available"] and not missing,
            "release": WLED_RELEASE, "reason": "; ".join(reasons) or None}


def checkout(root: Path) -> Path:
    """The release's source tree under `root`, cloned on first use."""
    src = root / f"wled-{WLED_RELEASE}"
    if (src / "platformio.ini").exists():
        return _fix_include_case(src)
    root.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", WLED_RELEASE, WLED_REPO, str(src)],
            check=True, capture_output=True, text=True, timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise BuildUnavailable(f"could not clone WLED {WLED_RELEASE}: {detail.strip()}") from exc
    return _fix_include_case(src)


# v0.15.2's usermods_list.cpp includes these headers under names that only
# resolve on a case-insensitive filesystem.
_INCLUDE_CASE = {
    ("BH1750_v2", "usermod_BH1750.h"): "usermod_bh1750.h",
    ("ST7789_display", "ST7789_Display.h"): "ST7789_display.h",
}


def _fix_include_case(src: Path) -> Path:
    for (usermod, included), actual in _INCLUDE_CASE.items():
        link = src / "usermods" / usermod / included
        if not link.exists() and link.with_name(actual).exists():
            link.symlink_to(actual)
    return src


def compile_firmware_events(
    design: Design, library: Library, *, root: Optional[Path] = None,
    timeout: int = _TIMEOUT, use_cache: bool = True,
) -> Iterator[dict]:
    """Yield `{"type": "log", "data": ...}` per build line, then a final
    `{"type": "done", "ok", "cache_key", "cache_hit", "env", "bin",
    "factory"}`. Raises `BuildUnavailable` on a cache miss without the
    toolchain, and `ValueError` for a design with no usermods."""
    override, _ = build_platformio_override(design, library)
    if override is None:
        raise ValueError("design has no usermods; the WLED release image needs no build")
    root = root or cache_dir()
    key = cache_key(override)
    slot = root / key
    cached_bin, cached_factory, cached_log = slot / "firmware.bin", slot / "factory.bin", slot / "build.log"
    if use_cache and cached_bin.exists():
        if cached_log.exists():
            yield {"type": "log", "data": cached_log.read_text()}
        yield {"type": "done", "ok": True, "cache_key": key, "cache_hit": True, "env": _ENV,
               "bin": str(cached_bin), "factory": str(cached_factory) if cached_factory.exists() else None}
        return

    pio = _pio_cmd()
    if pio is None:
        raise BuildUnavailable("PlatformIO not found; install it (pip install platformio)")
    src = checkout(root)
    chip = library.board(design.board.library_id).chip_variant or "esp32"

    # One build per checkout at a time: the override file and .pio/ are
    # shared, so a second design waits for the first.
    with (src / ".wirestudio.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        (src / "platformio_override.ini").write_text(override)
        proc = subprocess.Popen(
            [*pio, "run", "-d", str(src), "-e", _ENV],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        killed = threading.Event()

        def _kill() -> None:
            killed.set()
            proc.kill()

        timer = threading.Timer(timeout, _kill)
        timer.start()
        parts: list[str] = []
        try:
            for line in proc.stdout:  # type: ignore[union-attr]
                parts.append(line)
                yield {"type": "log", "data": line}
        finally:
            timer.cancel()
            proc.wait()
        if killed.is_set():
            parts.append(f"\nTIMED OUT after {timeout}s\n")
            yield {"type": "log", "data": parts[-1]}

        slot.mkdir(parents=True, exist_ok=True)
        cached_log.write_text("".join(parts))
        built = src / ".pio" / "build" / _ENV / "firmware.bin"
        ok = proc.returncode == 0 and built.exists()
        factory = None
        if ok:
            shutil.copy2(built, cached_bin)
            if _merge_factory(built.parent, chip, cached_factory):
                factory = str(cached_factory)
    yield {"type": "done", "ok": ok, "cache_key": key, "cache_hit": False, "env": _ENV,
           "bin": str(cached_bin) if ok else None, "factory": factory}


class LocalWledBackend:
    """In-pod PlatformIO build of the pinned release plus the design's usermods."""

    id = "local-platformio-wled"

    def status(self) -> dict:
        return status()

    def enqueue(self, design: Design, library: Library) -> str:
        override, _ = build_platformio_override(design, library)
        return cache_key(override or "")

    def stream(self, job_id: str, design: Design, library: Library) -> Iterator[dict]:
        yield from compile_firmware_events(design, library)

    def artifact(self, job_id: str, name: str = "firmware.bin") -> Optional[bytes]:
        path = cache_dir() / job_id / name
        return path.read_bytes() if path.exists() else None
