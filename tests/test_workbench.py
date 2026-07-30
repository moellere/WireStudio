"""Workbench remote flash transport (phase 1)."""
import base64
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.workbench import Slot, WorkbenchClient, WorkbenchUnavailable

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _slot(label="SLOT1", **over):
    d = {
        "label": label,
        "state": "idle",
        "present": True,
        "detected_chip": "esp32",
        "url": f"rfc2217://bench:400{label[-1]}",
        "flapping": False,
        "last_error": None,
        "usb_devices": [{"product": "CP2104 USB to UART Bridge Controller"}],
    }
    d.update(over)
    return d


class FakeBench:
    """Stands in for the Pi's portal. Records what it was asked to flash."""

    # Verified against the reference bench: one buffered JSON answer, not
    # a line stream, and the esptool exit status is its own field.
    OK_OUTPUT = (
        "esptool v5.3.1\nConnecting......\nChip type:          ESP32-D0WDQ6\n"
        "Writing at 0x00000000 [                    ]   0.0% 0/197883 bytes...\n"
        "Wrote 365264 bytes at 0x00000000 in 4.6 seconds.\nHash of data verified.\n"
    )
    FAIL_OUTPUT = (
        "esptool v5.3.1\nConnecting......\n"
        "Writing at 0x00000000 [                    ]   0.0% 0/197883 bytes...\n"
        "A fatal error occurred: Packet content transfer stopped\n"
    )

    def __init__(self, slots=None, flash_status=200, returncode=0, require_token="s3cret"):
        self.slots = slots if slots is not None else [_slot()]
        self.flash_status = flash_status
        self.returncode = returncode
        self.require_token = require_token
        self.flashed: list[dict] = []

    def handler(self, req: httpx.Request) -> httpx.Response:
        if self.require_token and req.headers.get("authorization") != f"Bearer {self.require_token}":
            return httpx.Response(401, json={"error": "unauthorized"})
        if req.url.path == "/api/info":
            return httpx.Response(200, json={"hostname": "bench", "slots_configured": len(self.slots)})
        if req.url.path == "/api/devices":
            return httpx.Response(200, json={"slots": self.slots})
        if req.url.path == "/api/flash":
            if self.flash_status >= 400:
                return httpx.Response(
                    self.flash_status, json={"ok": False, "error": "esptool: no serial data"}
                )
            self.flashed.append({"body": req.content})
            ok = self.returncode == 0
            return httpx.Response(
                200,
                json={
                    "ok": ok,
                    "output": self.OK_OUTPUT if ok else self.FAIL_OUTPUT,
                    "returncode": self.returncode,
                },
            )
        return httpx.Response(404)

    def client(self, **kw) -> WorkbenchClient:
        kw.setdefault("base_url", "http://bench:8080")
        kw.setdefault("token", self.require_token or "t")
        return WorkbenchClient(transport=httpx.MockTransport(self.handler), **kw)


def _app(bench, monkeypatch):
    monkeypatch.delenv("WORKBENCH_URL", raising=False)
    monkeypatch.delenv("WORKBENCH_TOKEN", raising=False)
    return TestClient(create_app(workbench_client_factory=bench.client))


def _parse_sse(body: str) -> list[dict]:
    events = []
    for raw in body.split("\n\n"):
        if not raw.strip():
            continue
        ev = {"event": "message"}
        for line in raw.splitlines():
            if line.startswith("event: "):
                ev["event"] = line[len("event: "):]
            elif line.startswith("data: "):
                ev["data"] = json.loads(line[len("data: "):])
        events.append(ev)
    return events


# ----------------------------------------------------------------------
# Slot health
# ----------------------------------------------------------------------


def test_empty_slot_is_not_flashable():
    ok, reason = Slot.from_api(
        _slot(present=False, state="absent", usb_devices=[])
    ).flashable
    assert not ok
    assert "empty" in reason


def test_non_serial_peripheral_is_not_reported_as_empty():
    """SLOT4 on the reference bench holds an SDR: attached, but no devnode."""
    ok, reason = Slot.from_api(
        _slot(present=False, state="absent", usb_devices=[{"product": "RTL2832U"}])
    ).flashable
    assert not ok
    assert "no serial device" in reason and "RTL2832U" in reason


def test_flapping_slot_is_refused_with_its_error():
    ok, reason = Slot.from_api(
        _slot(flapping=True, last_error="usb disconnect")
    ).flashable
    assert not ok
    assert "flapping" in reason and "usb disconnect" in reason


def test_busy_slot_is_refused_naming_its_state():
    ok, reason = Slot.from_api(_slot(state="monitoring")).flashable
    assert not ok
    assert "monitoring" in reason


def test_idle_present_slot_is_flashable():
    ok, reason = Slot.from_api(_slot()).flashable
    assert ok and reason is None


# ----------------------------------------------------------------------
# Config gate
# ----------------------------------------------------------------------


async def test_unconfigured_without_url(monkeypatch):
    monkeypatch.delenv("WORKBENCH_URL", raising=False)
    monkeypatch.delenv("WORKBENCH_TOKEN", raising=False)
    ok, reason = await WorkbenchClient().is_available()
    assert not ok and reason == "WORKBENCH_URL not set"


async def test_url_alone_is_not_configured():
    """A URL without a token must not be enough -- see docs/workbench.md."""
    wc = WorkbenchClient(base_url="http://bench:8080", token="")
    assert not wc.is_configured()
    ok, reason = await wc.is_available()
    assert not ok and reason == "WORKBENCH_TOKEN not set"


async def test_bad_token_reports_unauthorized():
    bench = FakeBench()
    ok, reason = await bench.client(token="wrong").is_available()
    assert not ok and "unauthorized" in reason


async def test_available_when_configured_and_reachable():
    ok, reason = await FakeBench().client().is_available()
    assert ok and reason is None


# ----------------------------------------------------------------------
# Endpoints
# ----------------------------------------------------------------------


def test_status_reports_reason_and_hint_when_unconfigured(monkeypatch):
    monkeypatch.delenv("WORKBENCH_URL", raising=False)
    monkeypatch.delenv("WORKBENCH_TOKEN", raising=False)
    body = TestClient(create_app()).get("/workbench/status").json()
    assert body["available"] is False
    assert body["reason"] == "WORKBENCH_URL not set"
    assert "WORKBENCH_URL" in body["configure_hint"]


def test_status_is_200_even_when_unavailable(monkeypatch):
    """The UI keys off `available`; a status probe must not itself fail."""
    monkeypatch.delenv("WORKBENCH_URL", raising=False)
    assert TestClient(create_app()).get("/workbench/status").status_code == 200


def test_slots_surface_flashability(monkeypatch):
    bench = FakeBench(
        slots=[_slot("SLOT1"), _slot("SLOT2", present=False, state="absent", usb_devices=[])]
    )
    r = _app(bench, monkeypatch).get("/workbench/slots")
    assert r.status_code == 200
    slots = {s["label"]: s for s in r.json()["slots"]}
    assert slots["SLOT1"]["flashable"] is True
    assert slots["SLOT2"]["flashable"] is False
    assert "empty" in slots["SLOT2"]["blocked_reason"]


def test_slots_503_when_unconfigured(monkeypatch):
    monkeypatch.delenv("WORKBENCH_URL", raising=False)
    monkeypatch.delenv("WORKBENCH_TOKEN", raising=False)
    r = TestClient(create_app()).get("/workbench/slots")
    assert r.status_code == 503
    assert "WORKBENCH_URL" in r.json()["detail"]


def test_flash_streams_bench_output_then_done(monkeypatch):
    bench = FakeBench()
    r = _app(bench, monkeypatch).post(
        "/workbench/flash",
        json={
            "slot": "SLOT1",
            "images": [{"offset": "0x10000", "data": base64.b64encode(b"firmware").decode()}],
        },
    )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert any("Hash of data verified" in e["data"].get("data", "") for e in events)
    assert events[-1]["data"] == {
        "type": "done", "ok": True, "slot": "SLOT1", "returncode": 0,
    }
    assert len(bench.flashed) == 1


def test_uploads_parts_named_bin_at_offset(monkeypatch):
    """The portal keys parts by `bin@<offset>`; any other name is ignored
    and the flash fails as "no binaries to flash"."""
    bench = FakeBench()
    _app(bench, monkeypatch).post(
        "/workbench/flash",
        json={
            "slot": "SLOT1",
            "images": [{"offset": "0x10000", "data": base64.b64encode(b"fw").decode()}],
        },
    )
    assert b'name="bin@0x10000"' in bench.flashed[0]["body"]


def test_nonzero_returncode_is_a_failure_not_a_success(monkeypatch):
    """esptool can exit non-zero with HTTP 200 and ok:false -- reporting
    that as a successful flash is the worst failure this endpoint has."""
    bench = FakeBench(returncode=2)
    r = _app(bench, monkeypatch).post(
        "/workbench/flash",
        json={"slot": "SLOT1", "images": [{"offset": "0x0", "data": base64.b64encode(b"x").decode()}]},
    )
    events = _parse_sse(r.text)
    assert events[-1]["event"] == "error"
    assert "fatal error" in events[-1]["data"]["message"]
    assert not any(e["data"].get("type") == "done" for e in events if e["event"] == "message")


def test_esptool_log_is_split_into_lines(monkeypatch):
    """The bench answers with one JSON blob; emitting it verbatim would
    put escaped JSON in front of the operator instead of a log."""
    bench = FakeBench()
    r = _app(bench, monkeypatch).post(
        "/workbench/flash",
        json={"slot": "SLOT1", "images": [{"offset": "0x0", "data": base64.b64encode(b"x").decode()}]},
    )
    logs = [e["data"]["data"] for e in _parse_sse(r.text) if e["data"].get("type") == "log"]
    assert "esptool v5.3.1" in logs
    assert "Hash of data verified." in logs


def test_flash_rejects_busy_slot_before_streaming(monkeypatch):
    """409 rather than an SSE error frame -- the stream must not open."""
    bench = FakeBench(slots=[_slot(state="flashing")])
    r = _app(bench, monkeypatch).post(
        "/workbench/flash",
        json={"slot": "SLOT1", "images": [{"offset": "0x0", "data": base64.b64encode(b"x").decode()}]},
    )
    assert r.status_code == 409
    assert "flashing" in r.json()["detail"]
    assert not bench.flashed


def test_flash_refuses_flapping_slot(monkeypatch):
    bench = FakeBench(slots=[_slot(flapping=True, last_error="usb disconnect")])
    r = _app(bench, monkeypatch).post(
        "/workbench/flash",
        json={"slot": "SLOT1", "images": [{"offset": "0x0", "data": base64.b64encode(b"x").decode()}]},
    )
    assert r.status_code == 409
    assert not bench.flashed


def test_flash_requires_images(monkeypatch):
    bench = FakeBench()
    r = _app(bench, monkeypatch).post("/workbench/flash", json={"slot": "SLOT1", "images": []})
    assert r.status_code == 422


def test_flash_rejects_malformed_base64(monkeypatch):
    bench = FakeBench()
    r = _app(bench, monkeypatch).post(
        "/workbench/flash",
        json={"slot": "SLOT1", "images": [{"offset": "0x0", "data": "not!base64"}]},
    )
    assert r.status_code == 422
    assert not bench.flashed


def test_flash_unknown_slot_is_502(monkeypatch):
    bench = FakeBench()
    r = _app(bench, monkeypatch).post(
        "/workbench/flash",
        json={"slot": "SLOT9", "images": [{"offset": "0x0", "data": base64.b64encode(b"x").decode()}]},
    )
    assert r.status_code == 502


def test_flash_bench_error_becomes_sse_error_frame(monkeypatch):
    """A failure after the pre-check passed can only surface mid-stream."""
    bench = FakeBench(flash_status=500)
    r = _app(bench, monkeypatch).post(
        "/workbench/flash",
        json={"slot": "SLOT1", "images": [{"offset": "0x0", "data": base64.b64encode(b"x").decode()}]},
    )
    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[-1]["event"] == "error"
    # The bench's own words, not a generic "http 500".
    assert "esptool: no serial data" in events[-1]["data"]["message"]


async def test_client_flash_refuses_empty_images():
    with pytest.raises(WorkbenchUnavailable, match="no images"):
        async for _ in FakeBench().client().flash("SLOT1", []):
            pass


async def test_offsets_parsed_as_hex():
    """Browser sends "0x10000"; decimal parsing would flash at 10000."""
    from wirestudio.api.workbench import _parse_images

    images = _parse_images([{"offset": "0x10000", "data": base64.b64encode(b"x").decode()}])
    assert images[0][0] == 0x10000
