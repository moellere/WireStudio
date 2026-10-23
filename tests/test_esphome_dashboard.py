"""Compile through an ESPHome Device Builder: client, in-process jobs, routes, MCP."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from wirestudio.esphome_dashboard import (
    DashboardClient, DashboardJobs, DashboardUnavailable, PushResult,
)

pytestmark = pytest.mark.anyio

EXAMPLES = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"


class FakeDashboard:
    """The Device Builder's WebSocket command API plus its token download,
    as a websocket connector and an httpx transport, with the commands it
    saw. Mirrors ESPHome 2026.10.0: the server-info frame on connect,
    `auth/login` in band when `requires_auth`, replies matched by
    message_id, `devices/create` answering the config filename,
    `firmware/follow_job` streaming `output` events and one `result` (`status`, `exit_code`), and a
    single-use token for the HTTP download."""

    def __init__(self, *, devices=("existing.yaml",), success=True, code=None,
                 lines=("Compiling…", "Linking", "[SUCCESS]"), password=None, hang_up=False):
        self.devices = list(devices)
        self.success = success
        self.code = (0 if success else 1) if code is None else code
        self.lines = list(lines)
        self.password = password
        self.hang_up = hang_up
        self.written: dict[str, str] = {}
        self.created_args: list[dict] = []
        self.commands: list[str] = []
        self.firmware: dict[str, dict[str, bytes]] = {}
        self.types: dict[str, str] = {}
        self.tokens: dict[str, tuple[str, str]] = {}
        self.logins = 0

    def _handle(self, authed: list, command: str, args: dict):
        """(result | error) for one request; streaming handled by the socket."""
        if self.password is not None and not authed[0] and command != "auth/login":
            return {"error_code": "not_authenticated", "details": "Authentication required"}
        if command == "auth/login":
            self.logins += 1
            if args.get("password") != self.password:
                return {"error_code": "not_authenticated", "details": "Invalid credentials"}
            authed[0] = True
            return {"result": {"token": "t", "expires_at": 1.0}}
        if command == "devices/list":
            return {"result": {"configured": [{"name": d[:-5], "configuration": d} for d in self.devices], "importable": []}}
        if command == "devices/create":
            self.created_args.append(args)
            if len(args["name"]) > 31:
                return {"error_code": "invalid_args", "details": "hostname too long"}
            fn = f"{args['name']}.yaml"
            self.written[fn] = args["file_content"]
            if fn not in self.devices:
                self.devices.append(fn)
            return {"result": {"configuration": fn, "warning": None}}
        if command == "firmware/compile":
            return {"result": {"job_id": "job1", "configuration": args["configuration"], "status": "running"}}
        if command == "firmware/get_binaries":
            built = self.firmware.get(args["configuration"], {})
            return {"result": [
                {"title": n, "file": n, **({"type": self.types[n]} if n in self.types else {})} for n in built
            ]}
        if command == "firmware/download_token":
            token = f"tok{len(self.tokens)}"
            self.tokens[token] = (args["configuration"], args["file"])
            return {"result": {"token": token}}
        return {"error_code": "unknown_command", "details": command}

    async def ws_connect(self, url: str, headers: dict):
        assert url.endswith("/ws") and url.startswith("ws://")
        dash = self

        class Socket:
            def __init__(self):
                self.out: asyncio.Queue = asyncio.Queue()
                self.authed = [False]
                self.closed = False
                self.out.put_nowait(json.dumps({
                    "server_version": "1.25.0", "esphome_version": "2026.10.0",
                    "requires_auth": dash.password is not None,
                }))

            async def recv(self):
                return await self.out.get()

            def __aiter__(self):
                return self

            async def __anext__(self):
                raw = await self.out.get()
                if raw is None:
                    raise StopAsyncIteration
                return raw

            async def send(self, raw):
                req = json.loads(raw)
                dash.commands.append(req["command"])
                mid, command, args = req["message_id"], req["command"], req["args"]
                if command == "firmware/follow_job":
                    assert args == {"job_id": "job1"}
                    for line in dash.lines:
                        self.out.put_nowait(json.dumps({"message_id": mid, "event": "output", "data": line + "\n"}))
                    if dash.hang_up:
                        self.out.put_nowait(None)
                    else:
                        self.out.put_nowait(json.dumps({
                            "message_id": mid, "event": "result",
                            "data": {"status": "completed" if dash.success else "failed", "exit_code": dash.code,
                                     "error": None, "queued_update_armed": False},
                        }))
                    return
                self.out.put_nowait(json.dumps({"message_id": "stray", "event": "output", "data": "x"}))
                self.out.put_nowait(json.dumps({"message_id": mid, **dash._handle(self.authed, command, args)}))

            async def close(self):
                self.closed = True
        return Socket()

    def transport(self) -> httpx.MockTransport:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.method == "GET" and req.url.path == "/api/firmware/download":
                found = self.tokens.pop(req.url.params.get("token", ""), None)
                if found is None:
                    return httpx.Response(401)
                blob = self.firmware.get(found[0], {}).get(found[1])
                return httpx.Response(404) if blob is None else httpx.Response(200, content=blob)
            return httpx.Response(404)
        return httpx.MockTransport(handler)

    def client(self, **kw) -> DashboardClient:
        return DashboardClient("http://dash.test:6052", transport=self.transport(), ws_connect=self.ws_connect, **kw)


async def test_client_probes_pushes_and_reports_created():
    dash = FakeDashboard()
    client = dash.client()
    assert client.is_configured()
    assert await client.is_available() == (True, None)
    assert await client.push_device("Garage-Motion", "esphome:\n  name: garage-motion\n") == PushResult("garage-motion.yaml", True)
    assert dash.written["garage-motion.yaml"].startswith("esphome:")
    assert dash.created_args[0] == {
        "name": "garage-motion", "friendly_name": "garage-motion",
        "file_content": "esphome:\n  name: garage-motion\n", "overwrite": True,
    }
    assert await client.push_device("garage-motion", "x: 1\n") == PushResult("garage-motion.yaml", False)
    with pytest.raises(ValueError):
        await client.push_device("bad name!", "x: 1\n")


async def test_client_passes_a_server_side_name_rejection_as_value_error():
    with pytest.raises(ValueError, match="invalid_args"):
        await FakeDashboard().client().push_device("x" * 40, "x: 1\n")


async def test_client_compile_relays_lines_and_result():
    dash = FakeDashboard()
    events = [e async for e in dash.client().compile("garage-motion.yaml")]
    assert dash.commands == ["firmware/compile", "firmware/follow_job"]
    assert [e["data"] for e in events[:-1]] == ["Compiling…\n", "Linking\n", "[SUCCESS]\n"]
    assert events[-1] == {"type": "done", "ok": True, "code": 0}
    dash.success, dash.code = False, 1
    assert [e async for e in dash.client().compile("x.yaml")][-1] == {"type": "done", "ok": False, "code": 1}
    dash.hang_up = True
    last = [e async for e in dash.client().compile("x.yaml")][-1]
    assert last["ok"] is False and "before the job finished" in last["reason"]


async def test_client_firmware_picks_ota_or_factory_and_unavailable_states():
    dash = FakeDashboard()
    dash.firmware["garage-motion.yaml"] = {
        "firmware.factory.bin": b"\xe9merged", "firmware.ota.bin": b"\xe9ota", "firmware.elf": b"ELF",
    }
    dash.types.update({"firmware.factory.bin": "factory", "firmware.ota.bin": "ota", "firmware.elf": "elf"})
    dash.firmware["d1.yaml"] = {"firmware.bin": b"\xe9only"}
    client = dash.client()
    assert await client.firmware("garage-motion.yaml") == b"\xe9ota"
    assert await client.firmware("garage-motion.yaml", factory=True) == b"\xe9merged"
    assert await client.firmware("d1.yaml", factory=True) == b"\xe9only"
    assert await client.firmware("nope.yaml") is None
    assert [d["file"] for d in await client.downloads("d1.yaml")] == ["firmware.bin"]
    assert not DashboardClient("").is_configured()

    async def refuse(url, headers):
        raise ConnectionRefusedError("refused")
    down = DashboardClient("http://dash.test", ws_connect=refuse)
    ok, reason = await down.is_available()
    assert ok is False and "websocket failed" in reason

    async def html(url, headers):
        class Socket:
            async def recv(self):
                return "<html>"

            async def close(self):
                pass
        return Socket()
    ok, reason = await DashboardClient("http://dash.test", ws_connect=html).is_available()
    assert ok is False and "Device Builder" in reason


async def test_client_download_token_failures_are_unavailable():
    dash = FakeDashboard()
    dash.firmware["a.yaml"] = {"firmware.bin": b"x"}
    gone = DashboardClient("http://dash.test", ws_connect=dash.ws_connect,
                           transport=httpx.MockTransport(lambda r: httpx.Response(502)))
    with pytest.raises(DashboardUnavailable, match="HTTP 502"):
        await gone.firmware("a.yaml")


async def test_client_logs_in_in_band_when_the_server_asks():
    dash = FakeDashboard(password="p")
    client = dash.client(username="u", password="p")
    assert await client.list_devices() == ["existing.yaml"]
    assert await client.push_device("new-node", "esphome:\n") == PushResult("new-node.yaml", True)
    events = [e async for e in client.compile("new-node.yaml")]
    assert events[-1]["ok"] is True
    assert dash.logins == 3


async def test_client_reports_missing_or_wrong_credentials():
    dash = FakeDashboard(password="p")
    ok, reason = await dash.client().is_available()
    assert ok is False and "ESPHOME_DASHBOARD_USERNAME" in reason and dash.logins == 0
    ok, reason = await dash.client(username="u", password="nope").is_available()
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

    dash.success, dash.code = False, 2
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


async def test_push_inlines_lorawan_secrets(monkeypatch, tmp_path):
    dash = FakeDashboard()
    client = _app(monkeypatch, tmp_path, dash)
    design = json.loads((EXAMPLES / "lorawan-battery-uplink.json").read_text())
    r = client.post("/esphome/push", json={"design": design, "compile": False, "lorawan_secrets": {
        "dev_eui": "70b3d57ed0001234", "join_eui": "70b3d57ed0000000",
        "app_key": "00112233445566778899aabbccddeeff",
    }})
    assert r.status_code == 200, r.text
    pushed = dash.written[r.json()["filename"]]
    assert "dev_eui: 70b3d57ed0001234" in pushed and "!secret app_key" not in pushed
    kept = client.post("/esphome/push", json={"design": design, "compile": False, "device_name": "plain"})
    assert "app_key: !secret app_key" in dash.written[kept.json()["filename"]]


async def test_failed_compile_and_strict_gate(monkeypatch, tmp_path):
    dash = FakeDashboard(success=False, lines=("error: boom",))
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
    assert dash.commands.count("firmware/compile") == 1


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
