"""API tests for the autoroute surfaces (/design/kicad/route*).

The toolchain is stubbed the same way test_kicad_route.py does it, so the
SSE flow, the cache-key artifact fetch, and the fab route= gating run
without KiCad or Java.
"""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = REPO_ROOT / "wirestudio" / "examples" / "garage-motion.json"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _script(path: Path, body: str) -> str:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture
def toolchain(tmp_path, monkeypatch):
    bridge = _script(
        tmp_path / "fake-python",
        'case "$2" in\n'
        "probe) echo 8.0.9 ;;\n"
        'dsn) echo dsn > "$4" ;;\n'
        'ses) printf \'(kicad_pcb (segment (net 1)))\' > "$3" ;;\n'
        "esac\n",
    )
    java = _script(tmp_path / "fake-java", 'echo "pass 1 done"\necho session > "$6"\n')
    jar = tmp_path / "freerouting.jar"
    jar.write_bytes(b"jar")
    monkeypatch.setenv("WIRESTUDIO_PCBNEW_PYTHON", bridge)
    monkeypatch.setenv("WIRESTUDIO_JAVA", java)
    monkeypatch.setenv("WIRESTUDIO_FREEROUTING_JAR", str(jar))
    monkeypatch.setenv("WIRESTUDIO_ROUTE_CACHE", str(tmp_path / "cache"))
    return tmp_path


def _design() -> dict:
    return json.loads(EXAMPLE.read_text())


def test_route_status_shape(client):
    body = client.get("/design/kicad/route/status").json()
    assert set(body) == {"available", "pcbnew", "java", "freerouting_jar", "reason"}


def test_routed_board_bad_key_and_missing(client, toolchain):
    assert client.get("/design/kicad/route/not-a-key").status_code == 422
    assert client.get("/design/kicad/route/0123456789abcdef").status_code == 404


kicad_libs = pytest.mark.skipif(
    __import__("wirestudio.kicad.pcb", fromlist=["pcb_status"]).pcb_status()["available"]
    is False,
    reason="KiCad footprint/symbol libs not configured",
)


@kicad_libs
def test_route_sse_then_artifact(client, toolchain):
    with client.stream("POST", "/design/kicad/route", json=_design()) as resp:
        assert resp.status_code == 200
        frames = [
            json.loads(line[len("data: "):])
            for line in resp.iter_lines()
            if line.startswith("data: ")
        ]
    done = frames[-1]
    assert done["type"] == "done" and done["ok"] is True
    assert "board" not in done
    routed = client.get(f"/design/kicad/route/{done['cache_key']}")
    assert routed.status_code == 200
    assert "(segment" in routed.text


@kicad_libs
def test_fab_gerbers_route_unavailable_is_503(client, monkeypatch):
    monkeypatch.setenv("WIRESTUDIO_PCBNEW_PYTHON", "/bin/false")
    monkeypatch.delenv("WIRESTUDIO_FREEROUTING_JAR", raising=False)
    resp = client.post("/design/fab/gerbers?route=true", json=_design())
    assert resp.status_code == 503


def test_fab_status_reports_route(client):
    body = client.get("/design/fab/status").json()
    assert "route" in body and "route_reason" in body
