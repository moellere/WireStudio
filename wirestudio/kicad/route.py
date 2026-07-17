"""Autoroute a generated ``.kicad_pcb`` with Freerouting.

Pipeline: board text -> Specctra DSN (pcbnew, via pcbnew_bridge.py under the
system python) -> ``java -jar freerouting.jar`` batch mode -> SES import back
into the board (bridge again). Everything is subprocess-based: pcbnew's SWIG
bindings live in KiCad's python, and Freerouting is GPL-3 Java invoked at
arm's length.

Gated like the other server-side-tool features: ``route_status()`` reports
``available`` and the POST raises ``RouteUnavailable`` -> 503. Results are
content-addressed on the unrouted board text + routing params, mirroring the
firmware cache, so re-routing an unchanged board replays the stored log and
returns instantly.

Freerouting runs with ``-mt 1``: multithreaded routing is a known source of
KiCad-DRC clearance violations (freerouting#191).
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Iterator, Optional

from wirestudio.kicad.fab import is_routed

_CACHE_VERSION = "1"
_TIMEOUT = int(os.environ.get("WIRESTUDIO_ROUTE_TIMEOUT", "600"))
_BRIDGE_TIMEOUT = 120  # seconds per pcbnew bridge call
_DEFAULT_PASSES = 20
_BRIDGE = Path(__file__).with_name("pcbnew_bridge.py")


class RouteUnavailable(RuntimeError):
    """The pcbnew bridge, Java, or the Freerouting jar isn't available."""


class RouteError(RuntimeError):
    """A routing step ran and failed; ``str()`` carries the tool output."""


def _default_cache_dir() -> Path:
    return Path(
        os.environ.get("WIRESTUDIO_ROUTE_CACHE")
        or Path(tempfile.gettempdir()) / "wirestudio-route-cache"
    )


def _pcbnew_python() -> Optional[str]:
    """Interpreter that can import pcbnew. The app's venv usually can't, so
    default to the system python3 and let WIRESTUDIO_PCBNEW_PYTHON override."""
    return (
        os.environ.get("WIRESTUDIO_PCBNEW_PYTHON")
        or shutil.which("python3")
        or shutil.which("python")
    )


def _java() -> Optional[str]:
    return os.environ.get("WIRESTUDIO_JAVA") or shutil.which("java")


def _freerouting_jar() -> Optional[Path]:
    jar = os.environ.get("WIRESTUDIO_FREEROUTING_JAR")
    if jar and Path(jar).is_file():
        return Path(jar)
    return None


def _probe_bridge(python: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [python, str(_BRIDGE), "probe"],
            capture_output=True, text=True, timeout=_BRIDGE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    out = (proc.stdout or proc.stderr).strip()
    return proc.returncode == 0, out


def route_status() -> dict:
    """What the autoroute step needs and whether it's all here. `available`
    is the headline the UI keys off."""
    python = _pcbnew_python()
    java = _java()
    jar = _freerouting_jar()
    missing = []
    pcbnew_version = None
    if python is None:
        missing.append("no python interpreter found for the pcbnew bridge")
    else:
        ok, out = _probe_bridge(python)
        if ok:
            pcbnew_version = out
        else:
            missing.append(
                f"pcbnew not importable by {python} (install KiCad >= 8 or set "
                f"WIRESTUDIO_PCBNEW_PYTHON): {out.splitlines()[-1] if out else 'no output'}"
            )
    if java is None:
        missing.append("java not on PATH (Freerouting needs a JRE; set WIRESTUDIO_JAVA)")
    if jar is None:
        missing.append("Freerouting jar not found (set WIRESTUDIO_FREEROUTING_JAR)")
    return {
        "available": not missing,
        "pcbnew": pcbnew_version,
        "java": java,
        "freerouting_jar": str(jar) if jar else None,
        "reason": "; ".join(missing) or None,
    }


def cached_routed_board(key: str, *, cache_dir: Optional[Path] = None) -> Optional[str]:
    """The routed board a prior run stored under ``key``, or None."""
    path = Path(cache_dir or _default_cache_dir()) / key / "routed.kicad_pcb"
    return path.read_text() if path.is_file() else None


def route_cache_key(board_text: str, *, max_passes: int = _DEFAULT_PASSES) -> str:
    h = hashlib.sha256()
    h.update(_CACHE_VERSION.encode())
    h.update(str(max_passes).encode())
    h.update(b"\0")
    h.update(board_text.encode())
    return h.hexdigest()[:16]


def _bridge(python: str, *args: str) -> None:
    proc = subprocess.run(
        [python, str(_BRIDGE), *args],
        capture_output=True, text=True, timeout=_BRIDGE_TIMEOUT,
    )
    if proc.returncode != 0:
        raise RouteError((proc.stderr or proc.stdout).strip() or f"bridge {args[0]} failed")


def route_events(
    board_text: str,
    *,
    max_passes: int = _DEFAULT_PASSES,
    timeout: int = _TIMEOUT,
    cache_dir: Optional[Path] = None,
    use_cache: bool = True,
) -> Iterator[dict]:
    """Route the board, yielding events as Freerouting works.

    Yields ``{"type": "log", "data": <line>}`` per output line and a final
    ``{"type": "done", "ok", "routed", "cache_key", "cache_hit", "board"}``
    where ``board`` is the routed board text (None on failure). A warm cache
    replays the stored log, touching no toolchain. Raises RouteUnavailable on
    a cache miss with the toolchain missing; a routing run that completes
    without producing copper is a normal ``done`` event (ok=False).
    """
    key = route_cache_key(board_text, max_passes=max_passes)
    slot = Path(cache_dir or _default_cache_dir()) / key
    cached_board = slot / "routed.kicad_pcb"
    cached_log = slot / "route.log"

    if use_cache and cached_board.exists():
        if cached_log.exists():
            yield {"type": "log", "data": cached_log.read_text()}
        routed = cached_board.read_text()
        yield {"type": "done", "ok": True, "routed": is_routed(routed),
               "cache_key": key, "cache_hit": True, "board": routed}
        return

    status = route_status()
    if not status["available"]:
        raise RouteUnavailable(status["reason"])
    python = _pcbnew_python()
    parts: list[str] = []

    with tempfile.TemporaryDirectory(prefix="wirestudio-route-") as tmp:
        work = Path(tmp)
        board_path = work / "board.kicad_pcb"
        dsn_path = work / "board.dsn"
        ses_path = work / "board.ses"
        board_path.write_text(board_text)

        try:
            _bridge(python, "dsn", str(board_path), str(dsn_path))
        except RouteError as exc:
            yield {"type": "log", "data": f"DSN export failed: {exc}\n"}
            yield {"type": "done", "ok": False, "routed": False,
                   "cache_key": key, "cache_hit": False, "board": None}
            return

        proc = subprocess.Popen(
            [_java(), "-jar", str(_freerouting_jar()),
             "-de", str(dsn_path), "-do", str(ses_path),
             "-mp", str(max_passes), "-mt", "1", "--gui.enabled=false"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, cwd=tmp,
        )
        # Watchdog: a stagnated router (no output, never exits) still gets killed.
        killed = threading.Event()

        def _kill_on_timeout() -> None:
            killed.set()
            proc.kill()

        timer = threading.Timer(timeout, _kill_on_timeout)
        timer.start()
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

        routed_text = None
        if ses_path.exists():
            try:
                _bridge(python, "ses", str(board_path), str(ses_path))
                routed_text = board_path.read_text()
            except RouteError as exc:
                parts.append(f"SES import failed: {exc}\n")
                yield {"type": "log", "data": parts[-1]}
        elif not killed.is_set():
            parts.append("Freerouting produced no session file\n")
            yield {"type": "log", "data": parts[-1]}

        ok = routed_text is not None and is_routed(routed_text)
        slot.mkdir(parents=True, exist_ok=True)
        cached_log.write_text("".join(parts))
        if ok:
            cached_board.write_text(routed_text)
        yield {"type": "done", "ok": ok, "routed": ok,
               "cache_key": key, "cache_hit": False,
               "board": routed_text if ok else None}


def route_board(
    board_text: str,
    *,
    max_passes: int = _DEFAULT_PASSES,
    timeout: int = _TIMEOUT,
    cache_dir: Optional[Path] = None,
    use_cache: bool = True,
) -> str:
    """Route and return the routed board text. Raises RouteError (with the
    Freerouting log) if routing completed without producing copper."""
    log: list[str] = []
    for event in route_events(
        board_text, max_passes=max_passes, timeout=timeout,
        cache_dir=cache_dir, use_cache=use_cache,
    ):
        if event["type"] == "log":
            log.append(event["data"])
        elif event["type"] == "done":
            if event["ok"]:
                return event["board"]
            raise RouteError("routing failed:\n" + "".join(log))
    raise RouteError("routing produced no result")


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(description="Autoroute a .kicad_pcb with Freerouting")
    parser.add_argument("board", nargs="?", help="path to a .kicad_pcb")
    parser.add_argument("--status", action="store_true", help="print availability and exit")
    parser.add_argument("--passes", type=int, default=_DEFAULT_PASSES)
    parser.add_argument("--out", help="write the routed board here (default: stdout)")
    args = parser.parse_args(argv)

    if args.status:
        print(json.dumps(route_status(), indent=2))
        return 0
    if not args.board:
        parser.error("board path required unless --status")
    try:
        routed = route_board(Path(args.board).read_text(), max_passes=args.passes)
    except (RouteUnavailable, RouteError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.out:
        Path(args.out).write_text(routed)
    else:
        print(routed)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
