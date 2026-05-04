"""Tests for the distributed-esphome (fleet) handoff client + endpoints.

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

from studio.agent.session import SessionStore
from studio.api.app import create_app
from studio.designs.store import DesignStore
from studio.fleet.client import FleetClient, FleetUnavailable, _validate_filename

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


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
                return httpx.Response(200, json={"run_id": run_id, "enqueued": 1})

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

def test_filename_validation_accepts_slug():
    assert _validate_filename("garage-motion") == "garage-motion"
    assert _validate_filename("dev1") == "dev1"
    assert _validate_filename("garage-motion.yaml") == "garage-motion"


def test_filename_validation_rejects_garbage():
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


def test_is_available_unconfigured():
    fc = FleetClient(base_url="", token="")
    ok, reason = fc.is_available()
    assert not ok and "FLEET_URL" in reason

    fc = FleetClient(base_url="http://x", token="")
    ok, reason = fc.is_available()
    assert not ok and "FLEET_TOKEN" in reason


def test_is_available_unauthorized():
    addon = FakeFleetAddon(expected_token="right")
    fc = addon.make_client(token="wrong")
    ok, reason = fc.is_available()
    assert not ok
    assert "unauthorized" in reason


def test_is_available_ok():
    addon = FakeFleetAddon()
    ok, reason = addon.make_client().is_available()
    assert ok and reason is None


def test_push_creates_new_device():
    addon = FakeFleetAddon()
    fc = addon.make_client()
    result = fc.push_device("garage-motion", "esphome:\n  name: garage-motion\n")
    assert result.created is True
    assert result.filename == "garage-motion.yaml"
    assert result.run_id is None
    assert addon.files["garage-motion.yaml"].startswith("esphome:")
    # Pending should be gone after rename.
    assert ".pending.garage-motion.yaml" not in addon.files
    assert addon.compile_runs == []


def test_push_overwrites_existing_device():
    addon = FakeFleetAddon()
    addon.files["dev1.yaml"] = "old: content\n"
    fc = addon.make_client()
    result = fc.push_device("dev1", "new: content\n")
    assert result.created is False
    assert addon.files["dev1.yaml"] == "new: content\n"


def test_push_with_compile_returns_run_id():
    addon = FakeFleetAddon()
    fc = addon.make_client()
    result = fc.push_device("dev2", "yaml: text\n", compile=True)
    assert result.run_id == "run-1"
    assert result.enqueued == 1
    assert addon.compile_runs == [{"run_id": "run-1", "targets": ["dev2.yaml"]}]


def test_push_unconfigured_raises():
    fc = FleetClient(base_url="", token="")
    with pytest.raises(FleetUnavailable):
        fc.push_device("x", "yaml")


def test_push_invalid_name_raises_value_error():
    addon = FakeFleetAddon()
    fc = addon.make_client()
    with pytest.raises(ValueError):
        fc.push_device("Has Spaces", "yaml")


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
        sessions=SessionStore(root=tmp_path / "sessions"),
        designs=DesignStore(root=tmp_path / "designs"),
        fleet_client_factory=factory,
    ))


def test_fleet_status_unconfigured(monkeypatch, tmp_path):
    client = _make_client(monkeypatch, tmp_path, addon=None)
    r = client.get("/fleet/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "FLEET_URL" in body["reason"]


def test_fleet_status_ok(monkeypatch, tmp_path):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.get("/fleet/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["url"] == "http://fake-fleet.local"


def test_fleet_push_unconfigured_returns_503(monkeypatch, tmp_path, garage_motion_design):
    client = _make_client(monkeypatch, tmp_path, addon=None)
    r = client.post("/fleet/push", json={"design": garage_motion_design})
    assert r.status_code == 503
    assert "FLEET_URL" in r.json()["detail"]


def test_fleet_push_invalid_design_returns_422(monkeypatch, tmp_path):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post("/fleet/push", json={"design": {"id": "x"}})
    assert r.status_code == 422


def test_fleet_push_round_trip_no_compile(monkeypatch, tmp_path, garage_motion_design):
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


def test_fleet_push_with_compile(monkeypatch, tmp_path, garage_motion_design):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post("/fleet/push", json={"design": garage_motion_design, "compile": True})
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"] == "run-1"
    assert body["enqueued"] == 1
    assert addon.compile_runs[0]["targets"] == ["garage-motion.yaml"]


def test_fleet_push_uses_device_name_override(monkeypatch, tmp_path, garage_motion_design):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post(
        "/fleet/push",
        json={"design": garage_motion_design, "device_name": "kitchen-pir"},
    )
    assert r.status_code == 200
    assert r.json()["filename"] == "kitchen-pir.yaml"
    assert "kitchen-pir.yaml" in addon.files


def test_fleet_push_invalid_device_name_returns_422(monkeypatch, tmp_path, garage_motion_design):
    addon = FakeFleetAddon()
    client = _make_client(monkeypatch, tmp_path, addon=addon)
    r = client.post(
        "/fleet/push",
        json={"design": garage_motion_design, "device_name": "Has Spaces"},
    )
    assert r.status_code == 422
