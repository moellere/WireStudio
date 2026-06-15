from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets import get_target
from wirestudio.targets.build_backend import BuildBackend, BuildUnavailable
from wirestudio.targets.lorawan import compile as compile_mod
from wirestudio.targets.lorawan.api import build_router
from wirestudio.targets.lorawan.build_local import LocalCompileBackend


def _design(board_id: str = "ttgo-t-beam") -> Design:
    return Design(
        schema_version="0.1", id="d", name="D", target="lorawan",
        board={"library_id": board_id, "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
    )


# --- the local backend satisfies the Protocol + delegates correctly ----------

def test_local_backend_is_a_build_backend():
    # runtime_checkable Protocol: the local impl structurally conforms.
    assert isinstance(LocalCompileBackend(), BuildBackend)


def test_lorawan_target_exposes_the_local_backend():
    b = get_target("lorawan").build_backend()
    assert isinstance(b, LocalCompileBackend)
    assert get_target("esphome").build_backend() is None  # esphome hands off to fleet


def test_local_enqueue_is_the_cache_key():
    lib = default_library()
    d = _design()
    assert LocalCompileBackend().enqueue(d, lib) == compile_mod.cache_key(d, lib)


def test_local_artifact_reads_the_cache_by_id(tmp_path, monkeypatch):
    monkeypatch.setenv("WIRESTUDIO_FW_CACHE", str(tmp_path))
    key = "abc123"
    (tmp_path / key).mkdir()
    (tmp_path / key / "firmware.bin").write_bytes(b"\x00\x01BIN")
    b = LocalCompileBackend()
    assert b.artifact(key) == b"\x00\x01BIN"
    assert b.artifact(key, "factory.bin") is None       # absent -> None
    assert b.artifact("nope") is None                   # unknown id -> None


def test_local_stream_cache_hit_replays_without_a_toolchain(tmp_path, monkeypatch):
    monkeypatch.setenv("WIRESTUDIO_FW_CACHE", str(tmp_path))
    lib = default_library()
    d = _design()
    b = LocalCompileBackend()
    key = b.enqueue(d, lib)
    (tmp_path / key).mkdir()
    (tmp_path / key / "firmware.bin").write_bytes(b"BIN")
    (tmp_path / key / "build.log").write_text("cached build output")
    # No PlatformIO available, but a warm cache must not need it.
    monkeypatch.setattr(compile_mod, "_pio_cmd", lambda: None)

    events = list(b.stream(key, d, lib))
    done = [e for e in events if e["type"] == "done"]
    assert done and done[0]["ok"] is True and done[0]["cache_hit"] is True
    assert any(e["type"] == "log" and "cached build output" in e["data"] for e in events)


def test_local_stream_raises_build_unavailable_on_cache_miss_without_pio(tmp_path, monkeypatch):
    monkeypatch.setenv("WIRESTUDIO_FW_CACHE", str(tmp_path))
    monkeypatch.setattr(compile_mod, "_pio_cmd", lambda: None)
    lib = default_library()
    d = _design()
    b = LocalCompileBackend()
    with pytest.raises(BuildUnavailable):
        list(b.stream(b.enqueue(d, lib), d, lib))


# --- the endpoints are backend-agnostic: a remote worker drops in ------------

class _FakeRemoteBackend:
    """A poll-style build worker (the shape a remote LoRaWAN agent would take):
    its job id is a worker handle, not a content hash, and the artifact lives on
    the worker, not the local cache. Used to prove the lorawan endpoints don't
    care which backend they drive."""

    id = "fake-remote"

    def __init__(self, *, available: bool = True) -> None:
        self._available = available
        self._store: dict[str, dict[str, bytes]] = {}

    def status(self) -> dict:
        return {"available": self._available,
                "reason": None if self._available else "build worker unreachable"}

    def enqueue(self, design, library) -> str:
        return "remote-job-7f3a"

    def stream(self, job_id, design, library):
        if not self._available:
            raise BuildUnavailable("build worker unreachable")
        yield {"type": "log", "data": "remote worker: compiling...\n"}
        self._store.setdefault(job_id, {})["firmware.bin"] = b"REMOTE_BIN"
        yield {"type": "done", "ok": True, "cache_key": job_id, "cache_hit": False,
               "env": "ttgo-t-beam", "bin": "remote", "factory": None}

    def artifact(self, job_id, name="firmware.bin"):
        return self._store.get(job_id, {}).get(name)


def _client_for(backend) -> TestClient:
    app = FastAPI()
    app.include_router(build_router(default_library(), backend), prefix="/lorawan")
    return TestClient(app)


def test_fake_remote_backend_conforms():
    assert isinstance(_FakeRemoteBackend(), BuildBackend)


def test_endpoints_drive_a_remote_backend_unchanged():
    backend = _FakeRemoteBackend()
    client = _client_for(backend)

    assert client.get("/lorawan/compile/status").json() == {
        "available": True, "reason": None,
    }

    r = client.post("/lorawan/compile", json=json.loads(_design().model_dump_json()))
    assert r.status_code == 200
    events = [json.loads(line[len("data: "):])
              for line in r.text.splitlines() if line.startswith("data: ")]
    done = [e for e in events if e["type"] == "done"]
    assert done and done[0]["cache_key"] == "remote-job-7f3a"

    # The done event's id addresses the artifact through the same /firmware route.
    fw = client.get("/lorawan/firmware/remote-job-7f3a")
    assert fw.status_code == 200 and fw.content == b"REMOTE_BIN"


def test_endpoint_surfaces_backend_unavailable_as_sse_error():
    client = _client_for(_FakeRemoteBackend(available=False))
    r = client.post("/lorawan/compile", json=json.loads(_design().model_dump_json()))
    assert r.status_code == 200  # the stream opens, then carries the error frame
    assert "event: error" in r.text
    assert "build worker unreachable" in r.text
