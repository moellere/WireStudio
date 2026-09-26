"""Slot serial and boot verification over the REST surface, the client
half of workbench phase 2: the flash dialog reads a slot's recorder
after a flash and asks whether the firmware booted."""
from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.workbench import WorkbenchClient
from wirestudio.workbench.boot import BOOT_CHECKS


def _bench(buffer, monitor_script=None):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, str(req.url.path), dict(req.url.params)))
        if req.url.path == "/api/serial/output":
            since = float(req.url.params.get("since", "0"))
            return httpx.Response(200, json={"lines": [e for e in buffer if e["ts"] > since]})
        if req.url.path == "/api/serial/monitor":
            body = json.loads(req.content)
            matched, line = (monitor_script or {}).get(body.get("pattern"), (False, None))
            return httpx.Response(200, json={"ok": True, "matched": matched, "line": line, "output": []})
        return httpx.Response(404, json={"error": "unexpected path"})

    client = WorkbenchClient(base_url="http://bench:8080", token="", transport=httpx.MockTransport(handler))
    return client, seen


BUFFER = [
    {"ts": 10.0, "text": "old boot line"},
    {"ts": 20.5, "text": "ets Jul 29 2019 12:21:46"},
    {"ts": 21.0, "text": "[I][app:117]: " + BOOT_CHECKS["esphome"].pattern},
]


def test_slot_output_returns_lines_after_since():
    client, seen = _bench(BUFFER)
    app = TestClient(create_app(workbench_client_factory=lambda: client))
    body = app.get("/workbench/slots/SLOT1/output?since=15").json()
    assert body["slot"] == "SLOT1"
    assert [ln["text"] for ln in body["lines"]] == ["ets Jul 29 2019 12:21:46", "[I][app:117]: setup() finished successfully!"]
    assert seen[0][2]["slot"] == "SLOT1" and seen[0][2]["since"] == "15.0"


def test_verify_boot_finds_the_marker_in_the_buffer_first():
    client, seen = _bench(BUFFER)
    app = TestClient(create_app(workbench_client_factory=lambda: client))
    out = app.post("/workbench/verify-boot", json={"slot": "SLOT1", "framework": "esphome", "since": 15}).json()
    assert out["ok"] is True and out["booted"] is True
    assert out["checks"][0]["via"] == "buffer"
    assert all(path != "/api/serial/monitor" for _, path, _ in seen)


def test_verify_boot_reports_unsupported_and_missing_input():
    client, _ = _bench([])
    app = TestClient(create_app(workbench_client_factory=lambda: client))
    out = app.post("/workbench/verify-boot", json={"slot": "SLOT1", "framework": "circuitpython"}).json()
    assert out["ok"] is False and "USB mass storage" in out["error"]
    assert app.post("/workbench/verify-boot", json={"slot": "SLOT1"}).status_code == 422


def test_routes_503_when_unconfigured(monkeypatch):
    monkeypatch.delenv("WORKBENCH_URL", raising=False)
    monkeypatch.delenv("WORKBENCH_TOKEN", raising=False)
    app = TestClient(create_app(workbench_client_factory=lambda: WorkbenchClient(base_url="", token="")))
    assert app.get("/workbench/slots/SLOT1/output").status_code == 503
    assert app.post("/workbench/verify-boot", json={"slot": "SLOT1", "framework": "esphome"}).status_code == 503
