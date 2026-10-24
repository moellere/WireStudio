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
KiCad-DRC clearance violations (freerouting#191), and with its usage
analytics off -- a server routing a user's board reports nothing upstream.

``RouteParams`` carries what the caller may tune: passes, via cost, and
keepout rectangles in the board's own coordinates (the placement is
deterministic, so a design always lands the same way). Keepouts are written
into the board as rule areas before the DSN export, next to the antenna
keepouts module footprints already carry. Every parameter is part of the
cache key.

A routed board is DRC'd (``wirestudio.kicad.drc``) when kicad-cli is
present, and the summary is stored beside it in the cache slot.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from wirestudio.kicad.fab import is_routed

_CACHE_VERSION = "3"
_TIMEOUT = int(os.environ.get("WIRESTUDIO_ROUTE_TIMEOUT", "600"))
_BRIDGE_TIMEOUT = 120  # seconds per pcbnew bridge call
_BRIDGE = Path(__file__).with_name("pcbnew_bridge.py")


@dataclass(frozen=True)
class Keepout:
    """A rectangle (board mm, top-left origin as in the emitted board) the
    router keeps tracks and/or vias out of, on both copper layers."""
    x: float
    y: float
    w: float
    h: float
    tracks: bool = True
    vias: bool = True

    def __post_init__(self) -> None:
        if self.w <= 0 or self.h <= 0:
            raise ValueError("a keepout needs a positive width and height")
        if not (self.tracks or self.vias):
            raise ValueError("a keepout must keep out tracks, vias, or both")

    @classmethod
    def parse(cls, text: str) -> "Keepout":
        """`x,y,w,h` keeps out tracks and vias; a fifth field `tracks` or
        `vias` keeps out only that."""
        fields = [f.strip() for f in text.split(",")]
        if len(fields) not in (4, 5):
            raise ValueError(f"keepout {text!r}: expected x,y,w,h[,tracks|vias]")
        try:
            x, y, w, h = (float(f) for f in fields[:4])
        except ValueError:
            raise ValueError(f"keepout {text!r}: x, y, w and h are millimetres") from None
        only = fields[4] if len(fields) == 5 else None
        if only not in (None, "tracks", "vias"):
            raise ValueError(f"keepout {text!r}: the fifth field is tracks or vias")
        return cls(x, y, w, h, tracks=only in (None, "tracks"), vias=only in (None, "vias"))

    def zone(self) -> str:
        x0, y0, x1, y1 = self.x, self.y, self.x + self.w, self.y + self.h
        tracks = "not_allowed" if self.tracks else "allowed"
        vias = "not_allowed" if self.vias else "allowed"
        return (
            "\t(zone\n\t\t(net 0)\n\t\t(net_name \"\")\n"
            '\t\t(layers "F.Cu" "B.Cu")\n'
            '\t\t(name "wirestudio keepout")\n'
            "\t\t(hatch edge 0.5)\n"
            "\t\t(connect_pads (clearance 0))\n"
            "\t\t(min_thickness 0.25)\n"
            "\t\t(filled_areas_thickness no)\n"
            f"\t\t(keepout (tracks {tracks}) (vias {vias}) "
            "(pads allowed) (copperpour not_allowed) (footprints allowed))\n"
            "\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))\n"
            f"\t\t(polygon (pts (xy {x0:g} {y0:g}) (xy {x1:g} {y0:g}) (xy {x1:g} {y1:g}) (xy {x0:g} {y1:g})))\n"
            "\t)\n"
        )


@dataclass(frozen=True)
class RouteParams:
    max_passes: int = 20
    # Freerouting's router.scoring.via_costs; higher trades vias for longer
    # tracks. None keeps Freerouting's default.
    via_costs: Optional[int] = None
    keepouts: tuple[Keepout, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not 1 <= self.max_passes <= 200:
            raise ValueError("max_passes must be 1-200")
        if self.via_costs is not None and not 0 <= self.via_costs <= 10_000:
            raise ValueError("via_costs must be 0-10000")

    def key(self) -> str:
        return repr((self.max_passes, self.via_costs, self.keepouts))

    def apply(self, board_text: str) -> str:
        """The board with the keepout rule areas added, before the DSN."""
        if not self.keepouts:
            return board_text
        head, close = board_text.rstrip().rsplit(")", 1)
        return head.rstrip() + "\n" + "".join(k.zone() for k in self.keepouts) + ")" + close + "\n"

    def freerouting_args(self) -> list[str]:
        args = ["-mp", str(self.max_passes), "-mt", "1", "--gui.enabled=false",
                "--usage_and_diagnostic_data.disable_analytics=true"]
        if self.via_costs is not None:
            args.append(f"--router.scoring.via_costs={self.via_costs}")
        return args


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


def routed_drc(key: str, *, cache_dir: Optional[Path] = None) -> Optional[dict]:
    """The DRC summary of the routed board under ``key``: the stored one,
    or computed now and stored when kicad-cli is here. None when there is
    no routed board or no kicad-cli; ``{"error": ...}`` when the check ran
    and failed."""
    from wirestudio.kicad.drc import DrcError, drc_status, run_drc

    slot = Path(cache_dir or _default_cache_dir()) / key
    stored = slot / "drc.json"
    if stored.is_file():
        return json.loads(stored.read_text())
    board = slot / "routed.kicad_pcb"
    if not board.is_file() or not drc_status()["available"]:
        return None
    try:
        summary = run_drc(board.read_text())
    except (DrcError, OSError, subprocess.SubprocessError) as exc:
        return {"error": str(exc)}
    stored.write_text(json.dumps(summary))
    return summary


def route_cache_key(board_text: str, params: RouteParams = RouteParams()) -> str:
    h = hashlib.sha256()
    h.update(_CACHE_VERSION.encode())
    h.update(params.key().encode())
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
    params: RouteParams = RouteParams(),
    *,
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
    key = route_cache_key(board_text, params)
    slot = Path(cache_dir or _default_cache_dir()) / key
    cached_board = slot / "routed.kicad_pcb"
    cached_log = slot / "route.log"

    if use_cache and cached_board.exists():
        if cached_log.exists():
            yield {"type": "log", "data": cached_log.read_text()}
        routed = cached_board.read_text()
        yield {"type": "done", "ok": True, "routed": is_routed(routed),
               "cache_key": key, "cache_hit": True, "board": routed,
               "drc": routed_drc(key, cache_dir=cache_dir)}
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
        board_path.write_text(params.apply(board_text))

        try:
            _bridge(python, "dsn", str(board_path), str(dsn_path))
        except RouteError as exc:
            yield {"type": "log", "data": f"DSN export failed: {exc}\n"}
            yield {"type": "done", "ok": False, "routed": False,
                   "cache_key": key, "cache_hit": False, "board": None}
            return

        proc = subprocess.Popen(
            [_java(), "-jar", str(_freerouting_jar()),
             "-de", str(dsn_path), "-do", str(ses_path), *params.freerouting_args()],
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
               "board": routed_text if ok else None,
               "drc": routed_drc(key, cache_dir=cache_dir) if ok else None}


def route_board(
    board_text: str,
    params: RouteParams = RouteParams(),
    *,
    timeout: int = _TIMEOUT,
    cache_dir: Optional[Path] = None,
    use_cache: bool = True,
) -> str:
    """Route and return the routed board text. Raises RouteError (with the
    Freerouting log) if routing completed without producing copper."""
    log: list[str] = []
    for event in route_events(
        board_text, params, timeout=timeout, cache_dir=cache_dir, use_cache=use_cache,
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
    parser.add_argument("--passes", type=int, default=RouteParams.max_passes)
    parser.add_argument("--via-costs", type=int, default=None)
    parser.add_argument("--out", help="write the routed board here (default: stdout)")
    args = parser.parse_args(argv)

    if args.status:
        print(json.dumps(route_status(), indent=2))
        return 0
    if not args.board:
        parser.error("board path required unless --status")
    try:
        routed = route_board(Path(args.board).read_text(),
                             RouteParams(max_passes=args.passes, via_costs=args.via_costs))
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
