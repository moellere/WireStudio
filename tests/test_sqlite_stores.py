"""The SQLite design and session stores behave like the file ones."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.agent.session import FileSessionStore, SqliteSessionStore
from wirestudio.api.app import create_app
from wirestudio.designs.store import FileDesignStore, SqliteDesignStore

EXAMPLES = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"


@pytest.fixture(params=["file", "sqlite"])
def design_store(request, tmp_path):
    if request.param == "file":
        return FileDesignStore(root=tmp_path / "designs")
    return SqliteDesignStore(tmp_path / "designs.db")


@pytest.fixture(params=["file", "sqlite"])
def session_store(request, tmp_path):
    if request.param == "file":
        return FileSessionStore(root=tmp_path / "sessions")
    return SqliteSessionStore(tmp_path / "sessions.db")


def test_design_store_round_trip_list_and_delete(design_store):
    garage = json.loads((EXAMPLES / "garage-motion.json").read_text())
    motor = json.loads((EXAMPLES / "motor-position.json").read_text())
    gid_expected = garage["id"]
    assert design_store.list() == [] and not design_store.exists(gid_expected)
    gid, saved_at = design_store.save(garage)
    assert gid == gid_expected and saved_at.endswith("+00:00")
    design_store.save(motor, design_id="Motor Position!")
    assert design_store.exists(gid) and design_store.exists("motor-position")
    assert design_store.load(gid)["name"] == garage["name"]
    listed = {s.id: s for s in design_store.list()}
    assert listed[gid].component_count == len(garage["components"])
    assert listed["motor-position"].board_library_id == "esp32-devkitc-v4"
    # Overwrite keeps one row.
    garage["name"] = "renamed"
    design_store.save(garage)
    assert design_store.load(gid)["name"] == "renamed"
    assert len(design_store.list()) == 2
    assert design_store.delete(gid) is True
    assert design_store.delete(gid) is False
    with pytest.raises(FileNotFoundError):
        design_store.load(gid)
    with pytest.raises(ValueError):
        design_store.save({"name": "no id"})


def test_session_store_appends_in_order(session_store):
    assert session_store.load("abc") == [] and not session_store.exists("abc")
    first = session_store.append("abc", "user", "hello")
    session_store.append("abc", "assistant", "hi")
    session_store.append("other", "user", "elsewhere")
    assert first["role"] == "user" and first["timestamp"]
    history = session_store.load("abc")
    assert [(m["role"], m["content"]) for m in history] == [("user", "hello"), ("assistant", "hi")]
    assert all(m["timestamp"] for m in history)
    assert session_store.exists("abc") and session_store.load("other")[0]["content"] == "elsewhere"
    with pytest.raises(ValueError):
        session_store.append("", "user", "x")


def test_sqlite_stores_survive_reopen(tmp_path):
    SqliteDesignStore(tmp_path / "d.db").save({"id": "one", "name": "One", "board": {}, "components": []})
    SqliteSessionStore(tmp_path / "s.db").append("s1", "user", "kept")
    assert SqliteDesignStore(tmp_path / "d.db").load("one")["name"] == "One"
    assert SqliteSessionStore(tmp_path / "s.db").load("s1")[0]["content"] == "kept"


def test_env_selects_the_sqlite_stores(tmp_path, monkeypatch):
    monkeypatch.setenv("DESIGNS_DB", str(tmp_path / "designs.db"))
    monkeypatch.setenv("SESSIONS_DB", str(tmp_path / "sessions.db"))
    client = TestClient(create_app())
    design = json.loads((EXAMPLES / "garage-motion.json").read_text())
    assert client.post("/designs", json={"design": design}).status_code in (200, 201)
    assert (tmp_path / "designs.db").exists()
    assert [d["id"] for d in client.get("/designs").json()] == [design["id"]]
