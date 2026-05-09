"""Tests for the saved-design persistence layer.

Covers DesignStore round-trips with a temporary directory, id sanitization,
and the /designs/* HTTP contract (validation, 404, traversal rejection).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.agent.session import SessionStore, FileSessionStore
from wirestudio.api.app import create_app
from wirestudio.designs.store import DesignStore, FileDesignStore, sanitize_id

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


@pytest.fixture
def garage_motion_design() -> dict:
    return json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())


# ---------------------------------------------------------------------------
# DesignStore unit tests
# ---------------------------------------------------------------------------

def test_sanitize_id_lowercases_and_replaces_specials():
    assert sanitize_id("Garage Motion v1") == "garage-motion-v1"
    assert sanitize_id("---Foo___Bar  Baz---") == "foo-bar-baz"
    assert sanitize_id("HCSR501") == "hcsr501"
    assert sanitize_id("ttgo-lora32") == "ttgo-lora32"


def test_sanitize_id_rejects_empty_and_invalid():
    with pytest.raises(ValueError):
        sanitize_id("")
    with pytest.raises(ValueError):
        sanitize_id("   ")
    with pytest.raises(ValueError):
        sanitize_id("***")  # all chars sanitized away


def test_save_and_load_round_trip(tmp_path, garage_motion_design):
    store = FileDesignStore(root=tmp_path)
    sid, saved_at = store.save(garage_motion_design)
    assert sid == "garage-motion-v1"
    assert saved_at  # ISO timestamp
    assert store.exists(sid)
    loaded = store.load(sid)
    assert loaded == garage_motion_design


def test_save_overwrites(tmp_path, garage_motion_design):
    store = FileDesignStore(root=tmp_path)
    sid1, _ = store.save(garage_motion_design)
    modified = dict(garage_motion_design)
    modified["name"] = "Renamed"
    sid2, _ = store.save(modified)
    assert sid1 == sid2  # same id, different content
    loaded = store.load(sid1)
    assert loaded["name"] == "Renamed"


def test_save_with_explicit_id(tmp_path, garage_motion_design):
    store = FileDesignStore(root=tmp_path)
    sid, _ = store.save(garage_motion_design, design_id="My Custom Name")
    assert sid == "my-custom-name"
    assert store.load(sid)["id"] == "garage-motion-v1"  # internal id unchanged


def test_save_missing_id_raises(tmp_path):
    store = FileDesignStore(root=tmp_path)
    with pytest.raises(ValueError):
        store.save({"name": "no id"})


def test_list_returns_summaries_newest_first(tmp_path, garage_motion_design):
    store = FileDesignStore(root=tmp_path)
    second = dict(garage_motion_design)
    second["id"] = "second"
    second["name"] = "Second design"
    store.save(garage_motion_design)
    # Force the second to have a later mtime.
    import time
    time.sleep(0.05)
    store.save(second)
    summaries = store.list()
    assert [s.id for s in summaries] == ["second", "garage-motion-v1"]
    assert summaries[0].name == "Second design"
    assert summaries[0].component_count == len(garage_motion_design["components"])


def test_load_unknown_raises(tmp_path):
    store = FileDesignStore(root=tmp_path)
    with pytest.raises(FileNotFoundError):
        store.load("nope")


def test_delete(tmp_path, garage_motion_design):
    store = FileDesignStore(root=tmp_path)
    sid, _ = store.save(garage_motion_design)
    assert store.delete(sid) is True
    assert not store.exists(sid)
    assert store.delete(sid) is False  # idempotent on missing


def test_path_rejects_traversal(tmp_path):
    store = FileDesignStore(root=tmp_path)
    with pytest.raises(ValueError):
        store.path("../passwd")
    with pytest.raises(ValueError):
        store.path("foo/bar")
    with pytest.raises(ValueError):
        store.path("")


# ---------------------------------------------------------------------------
# /designs/* HTTP contract
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return TestClient(create_app(
        sessions=FileSessionStore(root=tmp_path / "sessions"),
        designs=FileDesignStore(root=tmp_path / "designs"),
    ))


def test_list_empty_returns_empty(client):
    r = client.get("/designs")
    assert r.status_code == 200
    assert r.json() == []


def test_save_then_list_then_load_then_delete(client, garage_motion_design):
    r = client.post("/designs", json={"design": garage_motion_design})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "garage-motion-v1"
    assert body["saved_at"]

    listed = client.get("/designs").json()
    assert len(listed) == 1
    assert listed[0]["id"] == "garage-motion-v1"
    assert listed[0]["board_library_id"] == "esp32-devkitc-v4"

    fetched = client.get("/designs/garage-motion-v1").json()
    assert fetched == garage_motion_design

    deleted = client.delete("/designs/garage-motion-v1")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True, "id": "garage-motion-v1"}
    assert client.get("/designs").json() == []


def test_save_invalid_design_returns_422(client):
    r = client.post("/designs", json={"design": {"id": "x", "name": "x"}})
    assert r.status_code == 422


def test_save_no_id_returns_422(client, garage_motion_design):
    bad = dict(garage_motion_design)
    bad.pop("id", None)
    r = client.post("/designs", json={"design": bad})
    assert r.status_code == 422


def test_load_unknown_returns_404(client):
    r = client.get("/designs/no-such-design")
    assert r.status_code == 404


def test_delete_unknown_returns_404(client):
    r = client.delete("/designs/no-such-design")
    assert r.status_code == 404
