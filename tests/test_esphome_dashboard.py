"""Compile through an ESPHome dashboard: client, in-process jobs, routes, MCP."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from wirestudio.esphome_dashboard import (
    DashboardClient, DashboardJobs, PushResult,
)

pytestmark = pytest.mark.anyio

EXAMPLES = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"


class FakeDashboard:
    """The dashboard endpoints the studio uses, as an httpx transport plus
    a websocket connector, with the requests it saw. Mirrors esphome
    2026.6.5: `/devices` names configs by `configuration`; with a
    password every POST is xsrf-checked and the websocket wants the
    auth cookie; `/downloads` lists the built artifacts."""

    def __init__(self, *, devices=("existing.yaml",), exit_code=0,
                 lines=("Compiling…", "Linking", "[SUCCESS]"), password=None):
        self.devices = list(devices)
        self.exit_code = exit_code
        self.lines = list(lines)
        self.password = password
        self.written: dict[str, str] = {}
        self.spawned: list[dict] = []
        self.firmware: dict[str, dict[str, bytes]] = {}
        self.logins = 0
        self.ws_headers: list[dict] = []

    def _authed(self, req: httpx.Request) -> bool:
        return self.password is None or "authenticated=yes" in req.headers.get("cookie", "")

    def transport(self) -> httpx.MockTransport:
        def handler(req: httpx.Request) -> httpx.Response:
            path, q = req.url.path, dict(req.url.params)
            if path == "/login":
                if req.method == "GET":
                    return httpx.Response(200, text="<form>", headers={"set-cookie": "_xsrf=tok; Path=/"})
                form = dict(httpx.QueryParams(req.content.decode()))
                self.logins += 1
                if form.get("_xsrf") != "tok":
                    return httpx.Response(403)
                if form.get("password") != self.password:
                    return httpx.Response(401)
                return httpx.Response(302, headers={"location": "./", "set-cookie": "authenticated=yes; Path=/"})
            if not self._authed(req):
                return httpx.Response(302, headers={"location": "./login"})
            if self.password and req.method == "POST" and req.headers.get("x-xsrftoken") != "tok":
                return httpx.Response(403)
            if req.method == "GET" and path == "/devices":
                return httpx.Response(200, json={
                    "configured": [{"name": d[:-5], "configuration": d, "target_platform": None} for d in self.devices],
                    "importable": [],
                })
            if req.method == "POST" and path == "/edit":
                self.written[q["configuration"]] = req.content.decode()
                if q["configuration"] not in self.devices:
                    self.devices.append(q["configuration"])
                return httpx.Response(200)
            if req.method == "GET" and path == "/downloads":
                built = self.firmware.get(q["configuration"])
                if built is None:
                    return httpx.Response(404)
                return httpx.Response(200, json=[
                    {"title": name, "description": "", "file": name, "download": f"x-{name}"} for name in built
                ])
            if req.method == "GET" and path == "/download.bin":
                blob = (self.firmware.get(q["configuration"]) or {}).get(q.get("file", ""))
                return httpx.Response(404) if blob is None else httpx.Response(200, content=blob)
            return httpx.Response(404)
        return httpx.MockTransport(handler)

    async def ws_connect(self, url: str, headers: dict):
        assert url.endswith("/compile") and url.startswith("ws://")
        self.ws_headers.append(headers)
        if self.password and "authenticated=yes" not in headers.get("Cookie", ""):
            raise ConnectionError("no close frame received or sent")
        dash = self

        class Socket:
            def __init__(self):
                self.closed = False

            async def send(self, raw):
                dash.spawned.append(json.loads(raw))

            def __aiter__(self):
                async def frames():
                    for line in dash.lines:
                        yield json.dumps({"event": "line", "data": line + "\r\n"})
                    if dash.exit_code is not None:
                        yield json.dumps({"event": "exit", "code": dash.exit_code})
                return frames()

            async def close(self):
                self.closed = True
        return Socket()

    def client(self) -> DashboardClient:
        return DashboardClient("http://dash.test:6052", transport=self.transport(), ws_connect=self.ws_connect)


async def test_client_probes_pushes_and_reports_created():
    dash = FakeDashboard()
    client = dash.client()
    assert client.is_configured()
    assert await client.is_available() == (True, None)
    assert await client.push_device("Garage-Motion", "esphome:\n  name: garage-motion\n") == PushResult("garage-motion.yaml", True)
    assert dash.written["garage-motion.yaml"].startswith("esphome:")
    assert await client.push_device("garage-motion", "x: 1\n") == PushResult("garage-motion.yaml", False)
    with pytest.raises(ValueError):
        await client.push_device("bad name!", "x: 1\n")


async def test_client_compile_relays_lines_and_exit():
    dash = FakeDashboard()
    events = [e async for e in dash.client().compile("garage-motion.yaml")]
    assert dash.spawned == [{"type": "spawn", "configuration": "garage-motion.yaml"}]
    assert [e["data"] for e in events[:-1]] == ["Compiling…\r\n", "Linking\r\n", "[SUCCESS]\r\n"]
    assert events[-1] == {"type": "done", "ok": True, "code": 0}
    dash.exit_code = 1
    assert [e async for e in dash.client().compile("x.yaml")][-1]["ok"] is False
    dash.exit_code = None  # the dashboard hung up
    last = [e async for e in dash.client().compile("x.yaml")][-1]
    assert last["ok"] is False and "before exit" in last["reason"]


async def test_client_firmware_picks_ota_or_factory_and_unavailable_states():
    dash = FakeDashboard()
    dash.firmware["garage-motion.yaml"] = {"firmware.factory.bin": b"\xe9merged", "firmware.ota.bin": b"\xe9ota"}
    dash.firmware["d1.yaml"] = {"firmware.bin": b"\xe9only"}
    client = dash.client()
    assert await client.firmware("garage-motion.yaml") == b"\xe9ota"
    assert await client.firmware("garage-motion.yaml", factory=True) == b"\xe9merged"
    assert await client.firmware("d1.yaml", factory=True) == b"\xe9only"
    assert await client.firmware("nope.yaml") is None
    assert not DashboardClient("").is_configured()
    down = DashboardClient("http://dash.test", transport=httpx.MockTransport(lambda r: httpx.Response(502)))
    ok, reason = await down.is_available()
    assert ok is False and "HTTP 502" in reason
    html = DashboardClient("http://dash.test", transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    ok, reason = await html.is_available()
    assert ok is False and "not answer JSON" in reason


async def test_client_logs_in_once_with_xsrf_and_carries_the_cookie_everywhere():
    dash = FakeDashboard(password="p")
    client = DashboardClient("http://dash.test", username="u", password="p",
                             transport=dash.transport(), ws_connect=dash.ws_connect)
    assert await client.list_devices() == ["existing.yaml"]
    assert await client.push_device("new-node", "esphome:\n") == PushResult("new-node.yaml", True)
    events = [e async for e in client.compile("new-node.yaml")]
    assert events[-1]["ok"] is True
    assert dash.logins == 1
    assert "authenticated=yes" in dash.ws_headers[-1]["Cookie"]


async def test_client_reports_missing_or_wrong_credentials():
    dash = FakeDashboard(password="p")
    anon = DashboardClient("http://dash.test", transport=dash.transport(), ws_connect=dash.ws_connect)
    ok, reason = await anon.is_available()
    assert ok is False and "ESPHOME_DASHBOARD_USERNAME" in reason
    wrong = DashboardClient("http://dash.test", username="u", password="nope",
                            transport=dash.transport(), ws_connect=dash.ws_connect)
    ok, reason = await wrong.is_available()
    assert ok is False and "rejected" in reason


async def test_jobs_buffer_the_log_and_settle_a_verdict():
    dash = FakeDashboard()
    jobs = DashboardJobs()
    job = jobs.start(dash.client(), "garage-motion.yaml")
    assert job.verdict == "running" and jobs.get(job.run_id) is job
    await job.task
    chunk = jobs.log(job.run_id)
    assert chunk.finished and "Linking" in chunk.log and chunk.offset == len(job.log)
    assert jobs.log(job.run_id, offset=chunk.offset).log == ""
    assert job.verdict == "passed" and jobs.log("nope") is None

    dash.exit_code = 2
    failed = jobs.start(dash.client(), "x.yaml")
    await failed.task
    assert failed.verdict == "failed"

    async def boom(url, headers):
        raise OSError("refused")
    broken = jobs.start(DashboardClient("http://dash.test", ws_connect=boom), "x.yaml")
    await broken.task
    assert broken.verdict == "failed" and "websocket failed" in broken.error


# ---------------------------------------------------------------------------
# Routes and MCP
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from wirestudio.agent.session import FileSessionStore  # noqa: E402
from wirestudio.api.app import create_app  # noqa: E402
from wirestudio.designs.store import FileDesignStore  # noqa: E402


def _app(monkeypatch, tmp_path, dash: FakeDashboard | None):
    monkeypatch.delenv("ESPHOME_DASHBOARD_URL", raising=False)
    factory = (lambda: dash.client()) if dash else None
    return TestClient(create_app(
        sessions=FileSessionStore(root=tmp_path / "sessions"),
        designs=FileDesignStore(root=tmp_path / "designs"),
        dashboard_client_factory=factory,
        dashboard_jobs=DashboardJobs(),
    ))


def _wait_finished(client: TestClient, run_id: str) -> dict:
    for _ in range(50):
        body = client.get(f"/esphome/jobs/{run_id}/log").json()
        if body["finished"]:
            return body
        import time
        time.sleep(0.02)
    raise AssertionError("compile never finished")


async def test_routes_unconfigured(monkeypatch, tmp_path):
    client = _app(monkeypatch, tmp_path, None)
    body = client.get("/esphome/status").json()
    assert body["available"] is False and "ESPHOME_DASHBOARD_URL" in body["reason"]
    design = json.loads((EXAMPLES / "garage-motion.json").read_text())
    assert client.post("/esphome/push", json={"design": design}).status_code == 503
    assert client.get("/esphome/jobs/nope").status_code == 404


async def test_push_compile_poll_and_firmware(monkeypatch, tmp_path):
    dash = FakeDashboard()
    client = _app(monkeypatch, tmp_path, dash)
    assert client.get("/esphome/status").json() == {"available": True, "reason": None, "url": "http://dash.test:6052"}
    design = json.loads((EXAMPLES / "garage-motion.json").read_text())
    r = client.post("/esphome/push", json={"design": design, "device_name": "garage-motion"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == "garage-motion.yaml" and body["created"] and body["run_id"]
    assert dash.written["garage-motion.yaml"].startswith("esphome:")
    run_id = body["run_id"]

    log = _wait_finished(client, run_id)
    assert "[SUCCESS]" in log["log"] and log["finished"]
    status = client.get(f"/esphome/jobs/{run_id}").json()
    assert status["verdict"] == "passed" and status["filename"] == "garage-motion.yaml"

    assert client.get(f"/esphome/jobs/{run_id}/firmware").status_code == 404  # dashboard has no image
    dash.firmware["garage-motion.yaml"] = {"firmware.factory.bin": b"\xe9merged", "firmware.ota.bin": b"\xe9img"}
    assert client.get(f"/esphome/jobs/{run_id}/firmware").content == b"\xe9img"
    assert client.get(f"/esphome/jobs/{run_id}/firmware?factory=true").content == b"\xe9merged"

    # The SSE stream replays the buffered log and closes with done.
    text = client.get(f"/esphome/jobs/{run_id}/log/stream").text
    assert '"finished": true' in text and "event: done" in text

    # Without compile there is no run.
    r = client.post("/esphome/push", json={"design": design, "compile": False})
    assert r.json()["run_id"] is None and r.json()["created"] is False


async def test_failed_compile_and_strict_gate(monkeypatch, tmp_path):
    dash = FakeDashboard(exit_code=1, lines=("error: boom",))
    client = _app(monkeypatch, tmp_path, dash)
    design = json.loads((EXAMPLES / "garage-motion.json").read_text())
    run_id = client.post("/esphome/push", json={"design": design}).json()["run_id"]
    _wait_finished(client, run_id)
    assert client.get(f"/esphome/jobs/{run_id}").json()["verdict"] == "failed"
    assert client.get(f"/esphome/jobs/{run_id}/firmware").status_code == 404

    # A design that cannot render is refused before anything reaches the dashboard.
    broken = dict(design)
    broken["connections"] = [c for c in design["connections"] if c["pin_role"] != "OUT"]
    r = client.post("/esphome/push", json={"design": broken})
    assert r.status_code == 422 and "garage-motion.yaml" in dash.written  # only the earlier push landed
    assert len(dash.spawned) == 1


async def test_mcp_dashboard_tools(tmp_path):
    from wirestudio.designs.store import FileDesignStore
    from wirestudio.inventory.store import FileInventoryStore
    from wirestudio.library import default_library
    from wirestudio.mcp.server import build_mcp_server

    dash = FakeDashboard()
    store = FileDesignStore(root=tmp_path / "designs")
    design = json.loads((EXAMPLES / "garage-motion.json").read_text())
    store.save(design, design_id="garage-motion")
    server = build_mcp_server(
        default_library(), store,
        inventory=FileInventoryStore(path=tmp_path / "inventory.json"),
        dashboard_factory=lambda: dash.client(),
    )

    def payload(result):
        return json.loads(result.content[0].text)

    assert payload(await server.call_tool("esphome_dashboard_status", {}))["available"] is True
    pushed = payload(await server.call_tool("esphome_dashboard_push", {"design_id": "garage-motion"}))
    assert pushed["ok"] and pushed["filename"] == "garage-motion.yaml" and pushed["run_id"]
    run_id = pushed["run_id"]
    for _ in range(50):
        log = payload(await server.call_tool("esphome_dashboard_job_log", {"run_id": run_id}))
        if log["finished"]:
            break
        await asyncio.sleep(0.02)
    assert "[SUCCESS]" in log["log"]
    status = payload(await server.call_tool("esphome_dashboard_job_status", {"run_id": run_id}))
    assert status["verdict"] == "passed"
    assert payload(await server.call_tool("esphome_dashboard_job_status", {"run_id": "nope"}))["ok"] is False
