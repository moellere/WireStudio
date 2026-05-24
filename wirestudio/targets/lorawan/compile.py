"""In-pod PlatformIO compile worker for the LoRaWAN target.

    design -> firmware project (firmware_gen) -> `pio run` -> firmware.bin

Content-addressed cache: an identical project (same board, region, sub-band,
template version) is a cache hit and needs no toolchain, so warm requests are
instant and a cache hit works even where `pio` isn't installed. `pio` is a
system/image dependency invoked as a subprocess (never imported), so a miss
without PlatformIO degrades to ``CompileUnavailable`` -- the same gating shape
as kicad-render.

CLI: ``python -m wirestudio.targets.lorawan.compile <design.json> [--status]``.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from wirestudio.library import Library, default_library
from wirestudio.model import Design
from wirestudio.targets.lorawan.firmware_gen import generate_firmware

# Bump to invalidate every cached build when the worker's build logic (not just
# the templates, which are already hashed) changes.
_CACHE_VERSION = "1"
_TIMEOUT = int(os.environ.get("WIRESTUDIO_PIO_TIMEOUT", "1800"))


class CompileUnavailable(RuntimeError):
    """PlatformIO is not installed / not on PATH."""


@dataclass
class CompileResult:
    ok: bool
    cache_key: str
    cache_hit: bool
    env: str
    log: str
    bin_path: Optional[Path] = None


def _pio_cmd() -> Optional[list[str]]:
    exe = shutil.which("pio") or shutil.which("platformio")
    if exe:
        return [exe]
    if importlib.util.find_spec("platformio") is not None:
        return [sys.executable, "-m", "platformio"]
    return None


def _default_cache_dir() -> Path:
    return Path(
        os.environ.get("WIRESTUDIO_FW_CACHE")
        or Path(tempfile.gettempdir()) / "wirestudio-fw-cache"
    )


def cache_key(design: Design, library: Library) -> str:
    """Stable key for the generated project. Hashing the rendered files folds in
    board, region, sub-band, and template version automatically."""
    files = generate_firmware(design, library)
    h = hashlib.sha256()
    h.update(_CACHE_VERSION.encode())
    for rel in sorted(files):
        h.update(rel.encode())
        h.update(b"\0")
        h.update(files[rel].encode())
        h.update(b"\0")
    return h.hexdigest()[:16]


def platformio_status() -> dict:
    """Probe for the PlatformIO CLI. `available` is the headline the UI keys off."""
    pio = _pio_cmd()
    if pio is None:
        return {
            "available": False,
            "pio": None,
            "version": None,
            "reason": "PlatformIO not found (pip install platformio, or use the worker image)",
        }
    try:
        proc = subprocess.run([*pio, "--version"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "pio": " ".join(pio), "version": None, "reason": str(exc)}
    version = (proc.stdout or proc.stderr).strip()
    ok = proc.returncode == 0
    return {
        "available": ok,
        "pio": " ".join(pio),
        "version": version if ok else None,
        "reason": None if ok else version,
    }


def compile_firmware_events(
    design: Design,
    library: Library,
    *,
    cache_dir: Optional[Path] = None,
    timeout: int = _TIMEOUT,
    use_cache: bool = True,
) -> Iterator[dict]:
    """Build the firmware, yielding events as it goes.

    Yields ``{"type": "log", "data": <chunk>}`` for each build-output line and a
    final ``{"type": "done", "ok", "cache_key", "cache_hit", "env", "bin"}``. A
    warm cache yields the stored log then done, touching no toolchain. Raises
    CompileUnavailable only on a cache miss with no PlatformIO; a failed build is
    a normal ``done`` event (ok=False), so the API can stream it like fleet does.
    """
    files = generate_firmware(design, library)
    key = cache_key(design, library)
    env = library.board(design.board.library_id).platformio_board
    slot = Path(cache_dir or _default_cache_dir()) / key
    cached_bin = slot / "firmware.bin"
    cached_log = slot / "build.log"

    if use_cache and cached_bin.exists():
        if cached_log.exists():
            yield {"type": "log", "data": cached_log.read_text()}
        yield {"type": "done", "ok": True, "cache_key": key,
               "cache_hit": True, "env": env, "bin": str(cached_bin)}
        return

    pio = _pio_cmd()
    if pio is None:
        raise CompileUnavailable(
            "PlatformIO not found; install it (pip install platformio) or run in "
            "the lorawan worker image"
        )

    project = slot / "project"
    for rel, content in files.items():
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    proc = subprocess.Popen(
        [*pio, "run", "-d", str(project)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    # Watchdog: a hung build (no output, never exits) still gets killed.
    killed = threading.Event()

    def _kill_on_timeout() -> None:
        killed.set()
        proc.kill()

    timer = threading.Timer(timeout, _kill_on_timeout)
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

    log = "".join(parts)
    slot.mkdir(parents=True, exist_ok=True)
    cached_log.write_text(log)

    built = project / ".pio" / "build" / env / "firmware.bin"
    ok = proc.returncode == 0 and built.exists()
    if ok:
        shutil.copy2(built, cached_bin)
    yield {"type": "done", "ok": ok, "cache_key": key, "cache_hit": False,
           "env": env, "bin": str(cached_bin) if ok else None}


def compile_firmware(
    design: Design,
    library: Library,
    *,
    cache_dir: Optional[Path] = None,
    timeout: int = _TIMEOUT,
    use_cache: bool = True,
) -> CompileResult:
    """Blocking build. Drains compile_firmware_events into a CompileResult.

    Raises CompileUnavailable on a cache miss with no PlatformIO.
    """
    log_parts: list[str] = []
    done: dict = {}
    for event in compile_firmware_events(
        design, library, cache_dir=cache_dir, timeout=timeout, use_cache=use_cache
    ):
        if event["type"] == "log":
            log_parts.append(event["data"])
        elif event["type"] == "done":
            done = event
    return CompileResult(
        ok=done["ok"],
        cache_key=done["cache_key"],
        cache_hit=done["cache_hit"],
        env=done["env"],
        log="".join(log_parts),
        bin_path=Path(done["bin"]) if done.get("bin") else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wirestudio.targets.lorawan.compile")
    parser.add_argument("design", nargs="?", help="path to a design.json")
    parser.add_argument("-o", "--out", help="copy the built firmware.bin here")
    parser.add_argument("--no-cache", action="store_true", help="force a rebuild")
    parser.add_argument("--status", action="store_true", help="print PlatformIO availability and exit")
    args = parser.parse_args(argv)

    if args.status:
        print(json.dumps(platformio_status(), indent=2))
        return 0
    if not args.design:
        parser.error("a design.json path is required (or pass --status)")

    design = Design.model_validate(json.loads(Path(args.design).read_text()))
    try:
        result = compile_firmware(design, default_library(), use_cache=not args.no_cache)
    except CompileUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(result.log)
    if not result.ok:
        print(f"BUILD FAILED (env={result.env}, key={result.cache_key})", file=sys.stderr)
        return 1
    print(f"OK env={result.env} key={result.cache_key} "
          f"{'(cache hit)' if result.cache_hit else ''} bin={result.bin_path}")
    if args.out and result.bin_path:
        shutil.copy2(result.bin_path, args.out)
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
