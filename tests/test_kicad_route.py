"""Tests for the Freerouting autoroute step.

The real toolchain (pcbnew + Java + the Freerouting jar) is exercised in CI's
pcb-route workflow; here the bridge interpreter and java are stubbed with
small shell scripts so the event flow, caching, verification, and failure
paths run anywhere.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from wirestudio.kicad.route import (
    RouteError,
    RouteUnavailable,
    route_board,
    route_cache_key,
    route_events,
    route_status,
)

UNROUTED = '(kicad_pcb (version 20240108) (net 0 "") (net 1 "VCC"))\n'
ROUTED = UNROUTED.replace("))\n", ') (segment (net 1)))\n')


def _script(path: Path, body: str) -> str:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture
def toolchain(tmp_path, monkeypatch):
    """Fake bridge interpreter + java that mimic a successful roundtrip."""
    bridge = _script(
        tmp_path / "fake-python",
        'case "$2" in\n'
        "probe) echo 8.0.9 ;;\n"
        'dsn) echo dsn > "$4" ;;\n'
        'ses) printf \'%s\' \'' + ROUTED.replace("\n", "") + '\' > "$3" ;;\n'
        "esac\n",
    )
    java = _script(
        tmp_path / "fake-java",
        'echo "pass 1: 12 of 12 routed"\necho session > "$6"\n',
    )
    jar = tmp_path / "freerouting.jar"
    jar.write_bytes(b"jar")
    monkeypatch.setenv("WIRESTUDIO_PCBNEW_PYTHON", bridge)
    monkeypatch.setenv("WIRESTUDIO_JAVA", java)
    monkeypatch.setenv("WIRESTUDIO_FREEROUTING_JAR", str(jar))
    return tmp_path


def test_status_shape_and_unavailable_reasons(monkeypatch):
    monkeypatch.setenv("WIRESTUDIO_PCBNEW_PYTHON", "/bin/false")
    monkeypatch.delenv("WIRESTUDIO_FREEROUTING_JAR", raising=False)
    status = route_status()
    assert set(status) == {"available", "pcbnew", "java", "freerouting_jar", "reason"}
    assert status["available"] is False
    assert "pcbnew" in status["reason"]
    assert "Freerouting jar" in status["reason"]


def test_status_available_with_toolchain(toolchain):
    status = route_status()
    assert status["available"] is True
    assert status["pcbnew"] == "8.0.9"
    assert status["reason"] is None


def test_cache_key_folds_in_board_and_passes():
    a = route_cache_key(UNROUTED)
    assert a == route_cache_key(UNROUTED)
    assert a != route_cache_key(ROUTED)
    assert a != route_cache_key(UNROUTED, max_passes=5)


def test_route_events_roundtrip(toolchain, tmp_path):
    events = list(route_events(UNROUTED, cache_dir=tmp_path / "cache"))
    done = events[-1]
    assert done["type"] == "done"
    assert done["ok"] is True and done["routed"] is True
    assert "(segment" in done["board"]
    assert any(e["type"] == "log" and "12 of 12" in e["data"] for e in events)


def test_route_events_cache_hit_replays_log(toolchain, tmp_path):
    cache = tmp_path / "cache"
    first = list(route_events(UNROUTED, cache_dir=cache))[-1]
    # Break the toolchain: a cache hit must not touch it.
    os.environ["WIRESTUDIO_PCBNEW_PYTHON"] = "/bin/false"
    events = list(route_events(UNROUTED, cache_dir=cache))
    done = events[-1]
    assert done["cache_hit"] is True
    assert done["board"] == first["board"]
    assert any(e["type"] == "log" and "12 of 12" in e["data"] for e in events)


def test_cache_miss_without_toolchain_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("WIRESTUDIO_PCBNEW_PYTHON", "/bin/false")
    monkeypatch.delenv("WIRESTUDIO_FREEROUTING_JAR", raising=False)
    with pytest.raises(RouteUnavailable):
        list(route_events(UNROUTED, cache_dir=tmp_path / "cache"))


def test_no_session_file_is_a_failed_done(toolchain, tmp_path):
    _script(tmp_path / "fake-java", 'echo "could not route"\n')
    events = list(route_events(UNROUTED, cache_dir=tmp_path / "cache"))
    done = events[-1]
    assert done["ok"] is False and done["board"] is None
    assert any("no session file" in e["data"] for e in events if e["type"] == "log")


def test_unrouted_result_is_a_failed_done(toolchain, tmp_path):
    # Bridge whose SES import leaves the board without copper.
    _script(
        tmp_path / "fake-python",
        'case "$2" in\n'
        "probe) echo 8.0.9 ;;\n"
        'dsn) echo dsn > "$4" ;;\n'
        'ses) : ;;\n'
        "esac\n",
    )
    done = list(route_events(UNROUTED, cache_dir=tmp_path / "cache"))[-1]
    assert done["ok"] is False and done["board"] is None


def test_watchdog_kills_a_hung_router(toolchain, tmp_path):
    _script(tmp_path / "fake-java", "exec sleep 30\n")
    events = list(route_events(UNROUTED, cache_dir=tmp_path / "cache", timeout=1))
    done = events[-1]
    assert done["ok"] is False
    assert any("TIMED OUT" in e["data"] for e in events if e["type"] == "log")


def test_route_board_returns_text_or_raises(toolchain, tmp_path):
    assert "(segment" in route_board(UNROUTED, cache_dir=tmp_path / "c1")
    _script(tmp_path / "fake-java", 'echo "could not route"\n')
    with pytest.raises(RouteError, match="could not route"):
        route_board(ROUTED, cache_dir=tmp_path / "c2")
