"""Tests for the MCP hardware tool surface (workbench / ChirpStack / fleet).

These drive the *real* clients against wire-level fakes -- `FakeBench`
speaks the Pi portal's HTTP shapes and the fleet handler speaks the
addon's -- rather than substituting a fake client. A fake client would
only prove the tools call the methods I think exist; three bugs this
month survived exactly that.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from wirestudio.designs.store import FileDesignStore
from wirestudio.fleet import FleetClient
from wirestudio.library import default_library
from wirestudio.mcp.server import build_mcp_server
from wirestudio.workbench import WorkbenchClient

from tests.test_workbench import FakeBench, _slot

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _seed(store: FileDesignStore, design_id: str = "bench-dut") -> str:
    store.save(
        {
            "schema_version": "0.1",
            "id": design_id,
            "name": "Bench DUT",
            "board": {
                "library_id": "esp32-devkitc-v4",
                "mcu": "esp32",
                "framework": "arduino",
            },
            "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
            "components": [],
            "buses": [],
            "connections": [],
        },
        design_id=design_id,
    )
    return design_id


def _payload(result: Any) -> dict:
    """Decode an MCPServer call_tool result into its JSON dict."""
    content = result.content
    assert content, "expected at least one content block"
    text = getattr(content[0], "text", None)
    assert isinstance(text, str), f"unexpected content: {content!r}"
    return json.loads(text)


def _server(tmp_path: Path, *, bench: FakeBench | None = None, fleet_handler=None):
    store = FileDesignStore(root=tmp_path / "designs")
    _seed(store)

    def wb_factory():
        if bench is None:
            return WorkbenchClient(base_url="", token="")
        # FakeBench requires a bearer by default, so the token path is
        # exercised too even though WORKBENCH_TOKEN is optional in prod.
        return WorkbenchClient(
            base_url="http://bench:8080", token=bench.require_token or "",
            transport=httpx.MockTransport(bench.handler),
        )

    def fleet_factory():
        if fleet_handler is None:
            return FleetClient(base_url="", token="")
        return FleetClient(
            base_url="http://fleet:8080", token="tok",
            transport=httpx.MockTransport(fleet_handler),
        )

    server = build_mcp_server(
        default_library(), store,
        workbench_factory=wb_factory, fleet_factory=fleet_factory,
    )
    return server, store


async def _wait_job(server, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = _payload(await server.call_tool("job_status", {"job_id": job_id}))
        if snap["state"] != "running":
            return snap
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished")


# ---------------------------------------------------------------------------
# Workbench
# ---------------------------------------------------------------------------

async def test_workbench_slots_reports_flashability(tmp_path):
    bench = FakeBench(slots=[_slot("SLOT1"), _slot("SLOT2", flapping=True)])
    server, _ = _server(tmp_path, bench=bench)

    out = _payload(await server.call_tool("workbench_slots", {}))
    assert out["ok"] is True
    by_label = {s["label"]: s for s in out["slots"]}
    assert by_label["SLOT1"]["flashable"] is True
    assert by_label["SLOT2"]["flashable"] is False
    assert by_label["SLOT2"]["blocked_reason"]


async def test_workbench_slots_without_config_is_an_error_not_a_crash(tmp_path):
    server, _ = _server(tmp_path)  # no bench -> unconfigured client
    out = _payload(await server.call_tool("workbench_slots", {}))
    assert out["ok"] is False
    assert "WORKBENCH_URL" in out["error"]


async def test_workbench_flash_returns_a_job_that_completes(tmp_path):
    bench = FakeBench(slots=[_slot("SLOT1")])
    server, _ = _server(tmp_path, bench=bench)

    out = _payload(await server.call_tool("workbench_flash", {
        "slot": "SLOT1",
        "images": [{"offset": "0x10000", "data": "aGVsbG8="}],
        "chip": "esp32",
    }))
    assert out["ok"] is True, out
    assert out["bytes"] == 5

    snap = await _wait_job(server, out["job_id"])
    assert snap["state"] == "done", snap
    assert snap["event_count"] > 0
    assert bench.flashed, "the bench was never asked to flash"


async def test_workbench_flash_refuses_a_flapping_slot(tmp_path):
    bench = FakeBench(slots=[_slot("SLOT1", flapping=True)])
    server, _ = _server(tmp_path, bench=bench)

    out = _payload(await server.call_tool("workbench_flash", {
        "slot": "SLOT1",
        "images": [{"offset": "0x0", "data": "aGVsbG8="}],
    }))
    assert out["ok"] is False
    assert "not flashable" in out["error"]
    assert not bench.flashed


async def test_workbench_flash_requires_exactly_one_firmware_source(tmp_path):
    bench = FakeBench(slots=[_slot("SLOT1")])
    server, _ = _server(tmp_path, bench=bench)

    neither = _payload(await server.call_tool("workbench_flash", {"slot": "SLOT1"}))
    assert neither["ok"] is False
    assert "exactly one" in neither["error"]

    both = _payload(await server.call_tool("workbench_flash", {
        "slot": "SLOT1",
        "fleet_run_id": "123",
        "images": [{"offset": "0x0", "data": "aGVsbG8="}],
    }))
    assert both["ok"] is False
    assert "exactly one" in both["error"]


async def test_workbench_flash_rejects_a_bad_image_payload(tmp_path):
    bench = FakeBench(slots=[_slot("SLOT1")])
    server, _ = _server(tmp_path, bench=bench)

    out = _payload(await server.call_tool("workbench_flash", {
        "slot": "SLOT1",
        "images": [{"offset": "0x0", "data": "not!base64!"}],
    }))
    assert out["ok"] is False
    assert "image 0" in out["error"]
    assert not bench.flashed


async def test_flash_failure_surfaces_as_job_error(tmp_path):
    """A non-zero esptool return arrives under HTTP 200 -- the job must not
    report done."""
    bench = FakeBench(slots=[_slot("SLOT1")], returncode=1)
    server, _ = _server(tmp_path, bench=bench)

    out = _payload(await server.call_tool("workbench_flash", {
        "slot": "SLOT1",
        "images": [{"offset": "0x0", "data": "aGVsbG8="}],
    }))
    assert out["ok"] is True
    snap = await _wait_job(server, out["job_id"])
    assert snap["state"] == "error", snap


# ---------------------------------------------------------------------------
# Fleet
# ---------------------------------------------------------------------------

def _fleet_handler(
    *,
    existing: list[dict] | None = None,
    firmware: bytes = b"\xe9firmware",
    factory_firmware: bytes | None = b"\xe9factory-merged",
):
    """Speaks the addon's actual shapes.

    Two field names here are the ones the client really reads, and both
    have burned us: the target list is keyed by ``target`` (not
    ``filename``), and a queue row's id is ``id`` with state in ``state``
    (not ``job_id``/``status``). Artifacts hang off the **job** id, not
    the run id -- so a fetch by run_id must 404 and fall through.
    """
    targets = existing if existing is not None else []

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/ui/api/targets":
            if req.method == "GET":
                return httpx.Response(200, json=targets)
            return httpx.Response(200, json={"ok": True, "run_id": "run-1"})
        if path.startswith("/ui/api/targets/"):
            return httpx.Response(200, json={"ok": True, "run_id": "run-1"})
        if path == "/ui/api/queue":
            return httpx.Response(200, json=[
                {"run_id": "run-1", "id": "job-9", "target": "dut.yaml",
                 "state": "success", "finished_at": "2026-08-01T00:00:00Z"},
            ])
        # Two distinct artifacts: /firmware is the bare app image,
        # /firmware/factory is the merged bootloader+table+app. A build
        # may publish the first without the second.
        if path == "/ui/api/jobs/job-9/firmware/factory":
            if factory_firmware is None:
                return httpx.Response(404, json={"error": "no factory image"})
            return httpx.Response(200, content=factory_firmware)
        if path == "/ui/api/jobs/job-9/firmware":
            return httpx.Response(200, content=firmware)
        if path.endswith("/log"):
            return httpx.Response(200, json={"log": "Linking .pio\n", "offset": 14,
                                             "finished": True})
        if path in ("/ui/api/status", "/health"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"error": f"no route {path}"})

    return handler


async def test_fleet_job_status_reports_the_real_verdict_field(tmp_path):
    """RunStatus carries `verdict` and JobStatus carries `job_id`/`state` --
    reading any other attribute yields silent Nones."""
    server, _ = _server(tmp_path, fleet_handler=_fleet_handler())
    out = _payload(await server.call_tool("fleet_job_status", {"run_id": "run-1"}))
    assert out["ok"] is True, out
    assert out["verdict"] == "passed"
    assert out["jobs"] == [{
        "job_id": "job-9", "target": "dut.yaml", "state": "success",
        "finished_at": "2026-08-01T00:00:00Z",
    }]


def _merged_image(app_len: int = 4096) -> bytes:
    """A blob shaped like esptool merge_bin output.

    0xE9 image magic at 0, an ESP-IDF partition table (0xAA50) at 0x8000,
    and another image at 0x10000 -- the layout observed in the fleet
    addon's real artifact.
    """
    blob = bytearray(b"\x00" * (0x10000 + app_len))
    blob[0] = 0xE9
    blob[0x8000:0x8002] = b"\xaa\x50"
    blob[0x10000] = 0xE9
    return bytes(blob)


def _app_image(size: int = 4096) -> bytes:
    """A bare app image: ESP magic, and nothing at the partition offset."""
    return b"\xe9" + b"\x11" * (size - 1)


def test_merged_and_app_images_are_told_apart():
    from wirestudio.mcp.hardware import is_merged_image

    assert is_merged_image(_merged_image()) is True
    assert is_merged_image(_app_image()) is False
    assert is_merged_image(b"") is False
    assert is_merged_image(b"\x00" * 0x20000) is False  # no ESP magic


async def test_merged_artifact_is_written_at_zero(tmp_path):
    """A merged image at the app offset boot-loops the board.

    The live addon serves a merged image from `/firmware` despite that
    endpoint being described as the app image, so the offset has to come
    from the bytes.
    """
    bench = FakeBench(slots=[_slot("SLOT1")])
    server, _ = _server(
        tmp_path, bench=bench,
        fleet_handler=_fleet_handler(firmware=_merged_image()),
    )

    out = _payload(await server.call_tool("workbench_flash", {
        "slot": "SLOT1", "fleet_run_id": "run-1",
    }))
    assert out["ok"] is True, out
    await _wait_job(server, out["job_id"])

    body = bench.flashed[0]["body"]
    assert b'name="bin@0x0"' in body, "merged image must be written at 0x0"
    assert b'name="bin@0x10000"' not in body


async def test_bare_app_artifact_is_written_at_the_app_offset(tmp_path):
    bench = FakeBench(slots=[_slot("SLOT1")])
    server, _ = _server(
        tmp_path, bench=bench,
        fleet_handler=_fleet_handler(firmware=_app_image()),
    )

    out = _payload(await server.call_tool("workbench_flash", {
        "slot": "SLOT1", "fleet_run_id": "run-1",
    }))
    assert out["ok"] is True, out
    await _wait_job(server, out["job_id"])

    body = bench.flashed[0]["body"]
    assert b'name="bin@0x10000"' in body
    assert b'name="bin@0x0"' not in body


async def test_explicit_offset_overrides_detection(tmp_path):
    bench = FakeBench(slots=[_slot("SLOT1")])
    server, _ = _server(
        tmp_path, bench=bench,
        fleet_handler=_fleet_handler(firmware=_merged_image()),
    )

    out = _payload(await server.call_tool("workbench_flash", {
        "slot": "SLOT1", "fleet_run_id": "run-1", "offset": "0x20000",
    }))
    assert out["ok"] is True, out
    await _wait_job(server, out["job_id"])
    assert b'name="bin@0x20000"' in bench.flashed[0]["body"]


async def test_bad_offset_is_rejected(tmp_path):
    server, _ = _server(
        tmp_path, bench=FakeBench(slots=[_slot("SLOT1")]),
        fleet_handler=_fleet_handler(),
    )
    out = _payload(await server.call_tool("workbench_flash", {
        "slot": "SLOT1", "fleet_run_id": "run-1", "offset": "banana",
    }))
    assert out["ok"] is False
    assert "not a number" in out["error"]


async def test_firmware_is_found_via_the_job_id_not_the_run_id(tmp_path):
    """The artifact is keyed by job_id; a run_id fetch must fall through."""
    server, _ = _server(tmp_path, fleet_handler=_fleet_handler(firmware=b"y" * 32))
    out = _payload(await server.call_tool("fleet_firmware_info", {"run_id": "run-1"}))
    assert out["ok"] is True, out
    assert out["bytes"] == 32


async def test_fleet_firmware_info_reports_size_not_bytes(tmp_path):
    """The image must not cross the MCP boundary."""
    server, _ = _server(tmp_path, fleet_handler=_fleet_handler(firmware=b"x" * 4096))
    out = _payload(await server.call_tool("fleet_firmware_info", {"run_id": "run-1"}))
    assert out["ok"] is True, out
    assert out["bytes"] == 4096
    assert "data" not in out and "firmware" not in out


async def test_transport_failure_names_the_error_not_a_bare_colon(tmp_path):
    """httpx raises timeouts with no message, so `f"{e}"` renders empty.

    The tool then reported `firmware not available for run <id>: ` --
    a failure with nothing after the colon, which reads as an
    intermittent bug in the tool rather than a class of error that
    carries no text.
    """
    def timing_out(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("")

    server, _ = _server(tmp_path, fleet_handler=timing_out)

    out = _payload(await server.call_tool("fleet_firmware_info", {"run_id": "run-1"}))
    assert out["ok"] is False
    assert not out["error"].rstrip().endswith(":"), out["error"]
    assert "ConnectTimeout" in out["error"], out["error"]


async def test_fleet_status_reason_is_never_blank(tmp_path):
    def timing_out(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("")

    server, _ = _server(tmp_path, fleet_handler=timing_out)

    out = _payload(await server.call_tool("fleet_status", {}))
    assert out["available"] is False
    assert out["reason"] and out["reason"].strip() != "unreachable:"
    assert "ConnectError" in out["reason"], out["reason"]


async def test_fleet_tools_without_config_are_errors(tmp_path):
    server, _ = _server(tmp_path)
    out = _payload(await server.call_tool("fleet_push", {"design_id": "bench-dut"}))
    assert out["ok"] is False
    assert "fleet not configured" in out["error"]


# ---------------------------------------------------------------------------
# Design resolution
# ---------------------------------------------------------------------------

async def test_design_bound_tool_without_a_design_says_so(tmp_path):
    store = FileDesignStore(root=tmp_path / "designs")  # empty, no active
    server = build_mcp_server(default_library(), store)
    out = _payload(await server.call_tool("lorawan_compile", {}))
    assert out["ok"] is False
    assert "design_id" in out["error"]


async def test_eui_validation_rejects_non_hex(tmp_path):
    server, _ = _server(tmp_path)
    for bad in ("zzzzzzzzzzzzzzzz", "0011223344556677889900", "short"):
        out = _payload(await server.call_tool("lorawan_activation", {"dev_eui": bad}))
        assert out["ok"] is False, bad
        assert "16 hex" in out["error"]
