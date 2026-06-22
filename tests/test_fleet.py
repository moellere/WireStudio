"""Tests for the fleet-for-esphome (fleet) handoff client + endpoints.

Uses ``httpx.MockTransport`` to stand in for the addon's /ui/api/* surface
so we exercise the real client logic without ever touching a network or
spinning up the addon.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from wirestudio.agent.session import FileSessionStore
from wirestudio.api.app import create_app
from wirestudio.designs.store import FileDesignStore
from wirestudio.fleet.client import FleetClient, FleetUnavailable, _validate_filename

pytestmark = pytest.mark.anyio

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


# ---------------------------------------------------------------------------
# Fake addon
# ---------------------------------------------------------------------------

class FakeFleetAddon:
    """Minimal in-memory imitation of the ha-addon's /ui/api/* endpoints."""

    def __init__(self, *, expected_token: str = "tok-123") -> None:
        self.expected_token = expected_token
        self.files: dict[str, str] = {}  # final_filename -> content
        self.compile_runs: list[dict] = []
        self._next_run = 1
        # run_id -> {log, finished}; tests mutate this directly to drive the
        # log-tail polling tests through compiling -> finished.
        self.job_logs: dict[str, dict] = {}
        # Job rows surfaced by GET /ui/api/queue; tests append job dicts
        # ({"id", "run_id", "state", "target", "finished_at"}) to drive the
        # run-status verdict tests.
        self.queue_jobs: list[dict] = []
        # run_id -> {"app": bytes | None, "factory": bytes | None}; tests
        # populate this to drive the firmware-artifact passthrough tests.
        # None means "not built" -> the addon 404s (matches the fleet-side
        # contract that 404 = not ready or unavailable).
        self.firmware: dict[str, dict[str, bytes | None]] = {}

    def transport(self) -> httpx.MockTransport:
        def handler(req: httpx.Request) -> httpx.Response:
            auth = req.headers.get("authorization", "")
            if auth != f"Bearer {self.expected_token}":
                return httpx.Response(401, json={"error": "unauthorized"})
            path = req.url.path
            method = req.method

            if method == "GET" and path == "/ui/api/targets":
                return httpx.Response(
                    200,
                    json={
                        "targets": [
                            {"filename": f, "name": f}
                            for f in sorted(self.files.keys())
                        ],
                    },
                )

            if method == "POST" and path == "/ui/api/targets":
                body = json.loads(req.content)
                name = body["filename"]
                final = f"{name}.yaml"
                if final in self.files:
                    return httpx.Response(400, json={"error": "exists"})
                pending = f".pending.{final}"
                self.files[pending] = ""
                return httpx.Response(200, json={"target": pending, "ok": True})

            if method == "POST" and path.startswith("/ui/api/targets/") and path.endswith("/content"):
                target = path[len("/ui/api/targets/"):-len("/content")]
                body = json.loads(req.content)
                content = body.get("content", "")
                if target.startswith(".pending."):
                    final = target[len(".pending."):]
                    if final in self.files:
                        return httpx.Response(400, json={"error": "exists"})
                    self.files.pop(target, None)
                    self.files[final] = content
                    return httpx.Response(200, json={"ok": True, "renamed_to": final})
                self.files[target] = content
                return httpx.Response(200, json={"ok": True})

            if method == "POST" and path == "/ui/api/compile":
                body = json.loads(req.content)
                run_id = f"run-{self._next_run}"
                self._next_run += 1
                self.compile_runs.append({"run_id": run_id, "targets": body.get("targets")})
                self.job_logs.setdefault(run_id, {"log": "", "finished": False})
                return httpx.Response(200, json={"run_id": run_id, "enqueued": 1})

            if method == "GET" and path == "/ui/api/queue":
                return httpx.Response(200, json=self.queue_jobs)

            if method == "GET" and path.startswith("/ui/api/jobs/") and path.endswith("/log"):
                run_id = path[len("/ui/api/jobs/"):-len("/log")]
                if run_id not in self.job_logs:
                    return httpx.Response(404, json={"error": "Job not found"})
                offset = int(req.url.params.get("offset", "0"))
                full = self.job_logs[run_id]["log"]
                return httpx.Response(200, json={
                    "log": full[offset:],
                    "offset": len(full),
                    "finished": bool(self.job_logs[run_id]["finished"]),
                })

            # GET /ui/api/jobs/{run_id}/firmware            -> app image
            # GET /ui/api/jobs/{run_id}/firmware/factory    -> factory image
            if method == "GET" and path.startswith("/ui/api/jobs/") and (
                path.endswith("/firmware") or path.endswith("/firmware/factory")
            ):
                kind = "factory" if path.endswith("/factory") else "app"
                trim = "/firmware/factory" if kind == "factory" else "/firmware"
                run_id = path[len("/ui/api/jobs/"):-len(trim)]
                slot = self.firmware.get(run_id)
                if slot is None:
                    return httpx.Response(404, json={"error": "unknown run_id"})
                data = slot.get(kind)
                if data is None:
                    return httpx.Response(404, json={"error": f"no {kind} image"})
                return httpx.Response(
                    200,
                    content=data,
                    headers={"content-type": "application/octet-stream"},
                )

            return httpx.Response(404, json={"error": "not found"})

        return httpx.MockTransport(handler)

    def make_client(self, *, token: str = "tok-123") -> FleetClient:
        return FleetClient(
            base_url="http://fake-fleet.local",
            token=token,
            transport=self.transport(),
        )


# ---------------------------------------------------------------------------
# FleetClient unit tests
# ---------------------------------------------------------------------------

async def test_filename_validation_accepts_slug():
    assert _validate_filename("garage-motion") == "garage-motion"
    assert _validate_filename("dev1") == "dev1"
    assert _validate_filename("garage-motion.yaml") == "garage-motion"


async def test_filename_validation_rejects_garbage():
    with pytest.raises(ValueError):
        _validate_filename("")
    with pytest.raises(ValueError):
        _validate_filename("Has Spaces")
    with pytest.raises(ValueError):
        _validate_filename("UPPER")
    with pytest.raises(ValueError):
        _validate_filename("-leading-hyphen")
    with pytest.raises(ValueError):
        _validate_filename("a" * 65)


async def test_is_available_unconfigured():
    fc = FleetClient(base_url="", token="")
    ok, reason = await fc.is_available()
    assert not ok and "FLEET_URL" in reason

    fc = FleetClient(base_url="http://x", token="")
    ok, reason = await fc.is_available()
    assert not ok and "FLEET_TOKEN" in reason


async def test_is_available_unauthorized():
    addon = FakeFleetAddon(expected_token="right")
    fc = addon.make_client(token="wrong")
    ok, reason = await fc.is_available()
    assert not ok
    assert "unauthorized" in reason


async def test_is_available_ok():
    addon = FakeFleetAddon()
    ok, reason = await addon.make_client().is_available()
    assert ok and reason is None


async def test_push_creates_new_device():
    addon = FakeFleetAddon()
    fc = addon.make_client()
    result = await fc.push_device("garage-motion", "esphome:\n  name: garage-motion\n")
    assert result.created is True
    assert result.filename == "garage-motion.yaml"
    assert result.run_id is None
    assert addon.files["garage-motion.yaml"].startswith("esphome:")
    # Pending should be gone after rename.
    assert ".pending.garage-motion.yaml" not in addon.files
    assert addon.compile_runs == []


async def test_push_overwrites_existing_device():
    addon = FakeFleetAddon()
    addon.files["dev1.yaml"] = "old: content\n"
    fc = addon.make_client()
    result = await fc.push_device("dev1", "new: content\n")
    assert result.created is False
    assert addon.files["dev1.yaml"] == "new: content\n"


async def test_push_with_compile_returns_run_id():
    addon = FakeFleetAddon()
    fc = addon.make_client()
    result = await fc.push_device("dev2", "yaml: text\n", compile=True)
    assert result.run_id == "run-1"
    assert result.enqueued == 1
    assert addon.compile_runs == [{"run_id": "run-1", "targets": ["dev2.yaml"]}]


async def test_push_unconfigured_raises():
    fc = FleetClient(base_url="", token="")
    with pytest.raises(FleetUnavailable):
        await fc.push_device("x", "yaml")


async def test_push_invalid_name_raises_value_error():
    addon = FakeFleetAddon()
    fc = addon.make_client()
    with pytest.raises(ValueError):
        await fc.push_device("Has Spaces", "yaml")


# ---------------------------------------------------------------------------
# /fleet/* HTTP contract
# ---------------------------------------------------------------------------

@pytest.fixture
def garage_motion_design() -> dict:
    return json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())


def _make_client(monkeypatch, tmp_path, addon: FakeFleetAddon | None) -> TestClient:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FLEET_URL", raising=False)
    monkeypatch.delenv("FLEET_TOKEN", raising=False)
    factory = (lambda: addon.make_client()) if addon else None
    return TestClient(create_app(
        sessions=FileSessionStore(root=tmp_path / "sessions"),
        designs=FileDesignStore(root=tmp_path / "designs"),
        fleet_client_factory=factory,
    ))


async def test_fleet_status_unconfigured(monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path, addon=None)
    r = client.get("/fleet/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "FLEET_URL" in body["reason"]


async def test_fleet_status_ok(monkeypatch, tmp_path):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.get("/fleet/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["url"] == "http://fake-fleet.local"


async def test_fleet_push_unconfigured_returns_503(monkeypatch, tmp_path, garage_motion_design):
    client = _make_client(monkeypatch, tmp_path, addon=None)
    r = client.post("/fleet/push", json={"design": garage_motion_design})
    assert r.status_code == 503
    assert "FLEET_URL" in r.json()["detail"]


async def test_fleet_push_invalid_design_returns_422(monkeypatch, tmp_path):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post("/fleet/push", json={"design": {"id": "x"}})
    assert r.status_code == 422


async def test_fleet_push_round_trip_no_compile(monkeypatch, tmp_path, garage_motion_design):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post("/fleet/push", json={"design": garage_motion_design})
    assert r.status_code == 200
    body = r.json()
    # garage-motion's fleet.device_name is "garage-motion"; that wins over the
    # design id "garage-motion-v1".
    assert body["filename"] == "garage-motion.yaml"
    assert body["created"] is True
    assert body["run_id"] is None
    assert "garage-motion.yaml" in addon.files
    assert "esphome:" in addon.files["garage-motion.yaml"]


async def test_fleet_push_with_compile(monkeypatch, tmp_path, garage_motion_design):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post("/fleet/push", json={"design": garage_motion_design, "compile": True})
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "run-1"
    assert body["enqueued"] == 1
    assert addon.compile_runs[0]["targets"] == ["garage-motion.yaml"]


async def test_fleet_push_uses_device_name_override(monkeypatch, tmp_path, garage_motion_design):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post(
        "/fleet/push",
        json={"design": garage_motion_design, "device_name": "kitchen-pir"},
    )
    assert r.status_code == 200
    assert r.json()["filename"] == "kitchen-pir.yaml"
    assert "kitchen-pir.yaml" in addon.files


async def test_fleet_push_invalid_device_name_returns_422(monkeypatch, tmp_path, garage_motion_design):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post(
        "/fleet/push",
        json={"design": garage_motion_design, "device_name": "Has Spaces"},
    )
    assert r.status_code == 422


async def test_fleet_push_strict_clean_design_passes(monkeypatch, tmp_path, garage_motion_design):
    """garage-motion is warning-clean; strict push goes through."""
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post(
        "/fleet/push",
        json={"design": garage_motion_design, "strict": True},
    )
    assert r.status_code == 200
    assert r.json()["created"] is True


async def test_fleet_push_strict_blocks_on_compat_warning(monkeypatch, tmp_path):
    """ttgo-lora32 has a known boot_strap_output warning; strict push 422s
    with the same envelope as /design/render?strict=true so the UI can
    surface it the same way. The non-strict path still ships the file."""
    design = json.loads((EXAMPLES_DIR / "ttgo-lora32.json").read_text())
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)

    permissive = client.post("/fleet/push", json={"design": design})
    assert permissive.status_code == 200, permissive.json()

    strict = client.post("/fleet/push", json={"design": design, "strict": True})
    assert strict.status_code == 422
    detail = strict.json()["detail"]
    assert detail["error"] == "strict_mode_blocked"
    assert "compatibility issue" in detail["message"]
    assert all(w["severity"] in ("warn", "error") for w in detail["warnings"])
    # The push must NOT have hit the addon when strict refuses.
    assert len(addon.compile_runs) == 0


# ---------------------------------------------------------------------------
# Compile-run status
# ---------------------------------------------------------------------------

async def test_get_run_status_passed():
    addon = FakeFleetAddon()
    addon.queue_jobs = [
        {"id": "j1", "run_id": "run-7", "state": "success",
         "target": "dev.yaml", "finished_at": "2026-05-17T00:00:00Z"},
        {"id": "j0", "run_id": "other", "state": "failed", "target": "x.yaml"},
    ]
    status = await addon.make_client().get_run_status("run-7")
    assert status.verdict == "passed"
    assert [j.job_id for j in status.jobs] == ["j1"]


async def test_get_run_status_failed_beats_success():
    addon = FakeFleetAddon()
    addon.queue_jobs = [
        {"id": "a", "run_id": "r", "state": "success", "target": "a.yaml"},
        {"id": "b", "run_id": "r", "state": "failed", "target": "b.yaml"},
    ]
    assert (await addon.make_client().get_run_status("r")).verdict == "failed"


async def test_get_run_status_running_while_in_flight():
    addon = FakeFleetAddon()
    addon.queue_jobs = [
        {"id": "a", "run_id": "r", "state": "success", "target": "a.yaml"},
        {"id": "b", "run_id": "r", "state": "working", "target": "b.yaml"},
    ]
    assert (await addon.make_client().get_run_status("r")).verdict == "running"


async def test_get_run_status_unknown_when_not_in_queue():
    addon = FakeFleetAddon()
    status = await addon.make_client().get_run_status("ghost")
    assert status.verdict == "unknown"
    assert status.jobs == []


async def test_get_run_status_unconfigured_raises():
    with pytest.raises(FleetUnavailable):
        await FleetClient(base_url="", token="").get_run_status("r")


async def test_fleet_job_status_unconfigured_returns_503(monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path, addon=None)
    r = client.get("/fleet/jobs/run-1")
    assert r.status_code == 503
    assert "FLEET_URL" in r.json()["detail"]


async def test_fleet_job_status_verdict(monkeypatch, tmp_path):
    addon = FakeFleetAddon()
    addon.queue_jobs = [
        {"id": "j1", "run_id": "run-1", "state": "success",
         "target": "garage-motion.yaml", "finished_at": "2026-05-17T00:00:00Z"},
    ]
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.get("/fleet/jobs/run-1")
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "passed"
    assert body["jobs"][0]["job_id"] == "j1"
    assert body["jobs"][0]["state"] == "success"


async def test_fleet_job_status_unknown_run(monkeypatch, tmp_path):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.get("/fleet/jobs/ghost")
    assert r.status_code == 200
    assert r.json()["verdict"] == "unknown"


# ---------------------------------------------------------------------------
# Build log polling
# ---------------------------------------------------------------------------

async def test_get_job_log_unconfigured_raises():
    fc = FleetClient(base_url="", token="")
    with pytest.raises(FleetUnavailable):
        await fc.get_job_log("run-1")


async def test_get_job_log_unknown_run_id_raises():
    addon = FakeFleetAddon()
    fc = addon.make_client()
    with pytest.raises(FleetUnavailable):
        await fc.get_job_log("nope")


async def test_get_job_log_returns_chunks_and_finished_flag():
    addon = FakeFleetAddon()
    addon.job_logs["run-1"] = {"log": "compiling...\n", "finished": False}
    fc = addon.make_client()
    chunk1 = await fc.get_job_log("run-1", offset=0)
    assert chunk1.log == "compiling...\n"
    assert chunk1.offset == len("compiling...\n")
    assert chunk1.finished is False
    # Append more output, poll from where we left off.
    addon.job_logs["run-1"]["log"] += "linking...\n"
    addon.job_logs["run-1"]["finished"] = True
    chunk2 = await fc.get_job_log("run-1", offset=chunk1.offset)
    assert chunk2.log == "linking...\n"
    assert chunk2.finished is True


async def test_fleet_job_log_endpoint_unconfigured_returns_503(monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path, addon=None)
    r = client.get("/fleet/jobs/run-1/log")
    assert r.status_code == 503


async def test_fleet_job_log_endpoint_round_trip(monkeypatch, tmp_path):
    addon = FakeFleetAddon()
    addon.job_logs["run-42"] = {"log": "hello world\n", "finished": False}
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.get("/fleet/jobs/run-42/log")
    assert r.status_code == 200
    body = r.json()
    assert body["log"] == "hello world\n"
    assert body["finished"] is False
    # Continue from the returned offset.
    addon.job_logs["run-42"] = {"log": "hello world\nbuild ok\n", "finished": True}
    r2 = client.get(f"/fleet/jobs/run-42/log?offset={body['offset']}")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["log"] == "build ok\n"
    assert body2["finished"] is True


async def test_fleet_job_log_unknown_run_id_returns_502(monkeypatch, tmp_path):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.get("/fleet/jobs/nope/log")
    assert r.status_code == 502


# ---------------------------------------------------------------------------
# Build-artifact passthrough (fleet -> studio -> browser WebSerial)
# ---------------------------------------------------------------------------

async def test_get_firmware_returns_app_image_bytes():
    addon = FakeFleetAddon()
    addon.firmware["run-1"] = {"app": b"FAKE-APP-IMAGE", "factory": None}
    fc = addon.make_client()
    data = await fc.get_firmware("run-1")
    assert data == b"FAKE-APP-IMAGE"


async def test_get_firmware_factory_uses_factory_subpath():
    addon = FakeFleetAddon()
    addon.firmware["run-1"] = {
        "app": b"APP",
        "factory": b"BOOT+PART+APP",
    }
    fc = addon.make_client()
    data = await fc.get_firmware("run-1", factory=True)
    assert data == b"BOOT+PART+APP"


async def test_get_firmware_unknown_run_id_raises():
    addon = FakeFleetAddon()
    fc = addon.make_client()
    with pytest.raises(FleetUnavailable, match="not available"):
        await fc.get_firmware("nope")


async def test_get_firmware_factory_missing_raises():
    # The build produced an app image but the older ESPHome on the fleet
    # didn't emit firmware-factory.bin -- the addon 404s factory while the
    # app image is fine. The dialog falls back / surfaces the message.
    addon = FakeFleetAddon()
    addon.firmware["run-1"] = {"app": b"APP", "factory": None}
    fc = addon.make_client()
    with pytest.raises(FleetUnavailable, match="not available"):
        await fc.get_firmware("run-1", factory=True)


async def test_get_firmware_unconfigured_raises():
    fc = FleetClient(base_url=None, token=None)
    with pytest.raises(FleetUnavailable, match="missing"):
        await fc.get_firmware("run-1")


async def test_fleet_firmware_endpoint_unconfigured_returns_503(monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path, addon=None)
    r = client.get("/fleet/jobs/run-1/firmware")
    assert r.status_code == 503


async def test_fleet_firmware_endpoint_round_trips_app_image(monkeypatch, tmp_path):
    addon = FakeFleetAddon()
    addon.firmware["run-7"] = {"app": b"\x01\x02APP", "factory": None}
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.get("/fleet/jobs/run-7/firmware")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"] == 'attachment; filename="run-7.bin"'
    assert r.content == b"\x01\x02APP"


async def test_fleet_firmware_endpoint_round_trips_factory_image(monkeypatch, tmp_path):
    addon = FakeFleetAddon()
    addon.firmware["run-7"] = {"app": b"app", "factory": b"\xe9\x00\x00FACTORY"}
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.get("/fleet/jobs/run-7/firmware?factory=true")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="run-7-factory.bin"'
    assert r.content == b"\xe9\x00\x00FACTORY"


async def test_fleet_firmware_endpoint_unknown_run_id_returns_404(monkeypatch, tmp_path):
    # 404 means "not ready yet / not built" -- the dialog uses this to keep
    # waiting on the compile rather than treating it as a fleet outage (which
    # would be 502).
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.get("/fleet/jobs/ghost/firmware")
    assert r.status_code == 404


async def test_fleet_firmware_endpoint_addon_unreachable_returns_502(monkeypatch, tmp_path):
    # Addon returns a 5xx (here, simulated via missing handler -> 404 then
    # mapped to "not available"). For a transport-level failure we'd return
    # 502; cover that explicitly by pointing the client at a transport that
    # always 500s.
    def boom_handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/ui/api/jobs/") and req.url.path.endswith(
            "/firmware"
        ):
            return httpx.Response(500, json={"error": "internal"})
        return httpx.Response(404)

    transport = httpx.MockTransport(boom_handler)
    fc = FleetClient(
        base_url="http://broken-fleet.local", token="tok-123", transport=transport,
    )

    class _BrokenAddon:
        def make_client(self): return fc

    client = _make_client(monkeypatch, tmp_path, addon=_BrokenAddon())
    r = client.get("/fleet/jobs/run-1/firmware")
    assert r.status_code == 502


# ---------------------------------------------------------------------------
# SSE log relay
# ---------------------------------------------------------------------------

def _parse_sse(body: str) -> list[dict]:
    """Parse the studio's SSE stream into a list of {event, data} entries."""
    events: list[dict] = []
    for raw in body.split("\n\n"):
        if not raw.strip():
            continue
        ev: dict = {"event": "message"}
        for line in raw.splitlines():
            if line.startswith("event: "):
                ev["event"] = line[len("event: "):]
            elif line.startswith("data: "):
                ev["data"] = json.loads(line[len("data: "):])
        events.append(ev)
    return events


async def test_fleet_job_log_stream_emits_chunks_then_done(monkeypatch, tmp_path):
    addon = FakeFleetAddon()
    addon.job_logs["run-1"] = {"log": "compiling...\nlinking...\nbuild ok\n", "finished": True}
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    # interval_ms=0 (clamped to 100ms by the server) is fine; the loop
    # exits on the first iteration since finished=True from the start.
    r = client.get("/fleet/jobs/run-1/log/stream?interval_ms=0")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    # At least one data frame and a final done frame.
    assert events[0]["event"] == "message"
    assert events[0]["data"]["log"].startswith("compiling")
    assert events[0]["data"]["finished"] is True
    assert events[-1]["event"] == "done"


async def test_fleet_job_log_stream_unconfigured_returns_503(monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path, addon=None)
    r = client.get("/fleet/jobs/run-1/log/stream")
    assert r.status_code == 503


async def test_fleet_job_log_stream_unknown_run_id_emits_error_event(monkeypatch, tmp_path):
    """The addon returns 404 for unknown run_ids; the SSE relay surfaces
    that as an `event: error` frame and exits, rather than 502'ing the
    whole stream (HTTP status is already committed by the time the
    polling loop sees the failure)."""
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.get("/fleet/jobs/nope/log/stream?interval_ms=0")
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert any(e["event"] == "error" for e in events), events
    err = next(e for e in events if e["event"] == "error")
    assert "nope" in err["data"]["message"]


# --- fleet push with lorawan_secrets (W3 follow-up) ----------------------------

import json as _json  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_LORAWAN_EXAMPLE = _Path(__file__).resolve().parent.parent / "wirestudio" / "examples" / "lorawan-battery-uplink.json"


def _lorawan_design() -> dict:
    return _json.loads(_LORAWAN_EXAMPLE.read_text())


async def test_fleet_push_lorawan_secrets_inlines_literals_in_pushed_yaml(
    monkeypatch, tmp_path,
):
    """The lorawan_secrets body field replaces !secret references with
    literal values in the YAML written to the fleet. Removes the manual
    'edit fleet's secrets.yaml after provisioning' step for the
    external-component path."""
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post("/fleet/push", json={
        "design": _lorawan_design(),
        "lorawan_secrets": {
            "dev_eui": "70b3d57ed0001234",
            "join_eui": "70b3d57ed0000000",
            "app_key": "00112233445566778899aabbccddeeff",
        },
    })
    assert r.status_code == 200, r.json()
    body = r.json()
    pushed = addon.files[body["filename"]]
    assert "dev_eui: 70b3d57ed0001234" in pushed
    assert "join_eui: 70b3d57ed0000000" in pushed
    assert "app_key: 00112233445566778899aabbccddeeff" in pushed
    # No !secret references for the three LoRaWAN keys in the pushed YAML.
    assert "!secret dev_eui" not in pushed
    assert "!secret join_eui" not in pushed
    assert "!secret app_key" not in pushed


async def test_fleet_push_without_lorawan_secrets_keeps_secret_refs(
    monkeypatch, tmp_path,
):
    """The default push (no lorawan_secrets) still emits !secret references --
    backward-compatible with the current operator flow that edits fleet's
    secrets.yaml separately."""
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post("/fleet/push", json={"design": _lorawan_design()})
    assert r.status_code == 200, r.json()
    pushed = addon.files[r.json()["filename"]]
    assert "dev_eui: !secret dev_eui" in pushed
    assert "join_eui: !secret join_eui" in pushed
    assert "app_key: !secret app_key" in pushed


async def test_fleet_push_lorawan_secrets_no_op_for_non_lorawan_designs(
    monkeypatch, tmp_path, garage_motion_design,
):
    """A garage-motion design has no lorawan: block, so a stray
    lorawan_secrets in the request is harmless -- no error, no churn."""
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post("/fleet/push", json={
        "design": garage_motion_design,
        "lorawan_secrets": {"dev_eui": "f" * 16, "join_eui": "0" * 16, "app_key": "0" * 32},
    })
    assert r.status_code == 200, r.json()
    pushed = addon.files[r.json()["filename"]]
    # The pushed YAML has no lorawan block at all; the secrets are ignored.
    assert "lorawan:" not in pushed
    assert "dev_eui" not in pushed
