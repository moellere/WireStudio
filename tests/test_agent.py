"""Tests for the agent layer.

The Anthropic API call itself is not exercised here -- it requires a live
network call and an API key. We cover:
- The pure-Python tool implementations against a real Library.
- Session JSONL round-trips with a temporary directory.
- The /agent/* API contract: status reporting, 503 when no key, 404 for
  unknown sessions.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.agent.session import FileSessionStore, new_session_id
from wirestudio.agent.tools import execute_tool
from wirestudio.api.app import create_app
from wirestudio.library import default_library

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


@pytest.fixture
def garage_motion_design() -> dict:
    return json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())


@pytest.fixture
def lib():
    return default_library()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def test_search_components_returns_matches(lib):
    out, is_error = execute_tool("search_components", {"query": "motion"}, {}, lib)
    assert is_error is False
    body = json.loads(out)
    ids = {m["library_id"] for m in body["matches"]}
    assert "hc-sr501" in ids


def test_search_components_with_no_matches(lib):
    out, is_error = execute_tool("search_components", {"query": "no-such-thing-xyz"}, {}, lib)
    body = json.loads(out)
    assert body["matches"] == []
    assert body["total"] == 0


def test_list_boards_includes_known(lib):
    out, _ = execute_tool("list_boards", {}, {}, lib)
    body = json.loads(out)
    ids = {b["library_id"] for b in body["boards"]}
    assert {"esp32-devkitc-v4", "wemos-d1-mini"} <= ids


def test_set_board_updates_design(lib, garage_motion_design):
    out, is_error = execute_tool(
        "set_board", {"library_id": "wemos-d1-mini"}, garage_motion_design, lib,
    )
    assert is_error is False
    assert garage_motion_design["board"]["library_id"] == "wemos-d1-mini"
    assert garage_motion_design["board"]["mcu"] == "esp8266"


def test_set_board_unknown_returns_error(lib, garage_motion_design):
    out, is_error = execute_tool(
        "set_board", {"library_id": "no-such-board"}, garage_motion_design, lib,
    )
    assert is_error is True
    body = json.loads(out)
    assert "no-such-board" in body["error"]


def test_add_component_auto_ids_and_records_instance(lib, garage_motion_design):
    out, is_error = execute_tool(
        "add_component", {"library_id": "ssd1306", "label": "OLED"},
        garage_motion_design, lib,
    )
    assert is_error is False
    body = json.loads(out)
    assert body["instance_id"] == "ssd1306_1"
    assert any(c["id"] == "ssd1306_1" for c in garage_motion_design["components"])


def test_add_component_id_hint_used_when_free(lib, garage_motion_design):
    out, _ = execute_tool(
        "add_component",
        {"library_id": "ssd1306", "instance_id_hint": "main_oled"},
        garage_motion_design, lib,
    )
    body = json.loads(out)
    assert body["instance_id"] == "main_oled"


def test_add_component_falls_back_when_hint_taken(lib, garage_motion_design):
    garage_motion_design.setdefault("components", []).append(
        {"id": "main_oled", "library_id": "ssd1306", "label": "x", "params": {}}
    )
    out, _ = execute_tool(
        "add_component",
        {"library_id": "ssd1306", "instance_id_hint": "main_oled"},
        garage_motion_design, lib,
    )
    body = json.loads(out)
    assert body["instance_id"] != "main_oled"
    assert body["instance_id"].startswith("ssd1306_")


def test_remove_component_drops_component_and_connections(lib, garage_motion_design):
    out, is_error = execute_tool(
        "remove_component", {"instance_id": "bme1"}, garage_motion_design, lib,
    )
    assert is_error is False
    assert all(c["id"] != "bme1" for c in garage_motion_design["components"])
    assert all(c["component_id"] != "bme1" for c in garage_motion_design["connections"])


def test_remove_component_unknown(lib, garage_motion_design):
    out, _ = execute_tool(
        "remove_component", {"instance_id": "ghost"}, garage_motion_design, lib,
    )
    body = json.loads(out)
    assert body["ok"] is False


def test_set_param_set_and_delete(lib, garage_motion_design):
    execute_tool(
        "set_param", {"instance_id": "bme1", "key": "address", "value": "0x77"},
        garage_motion_design, lib,
    )
    bme1 = next(c for c in garage_motion_design["components"] if c["id"] == "bme1")
    assert bme1["params"]["address"] == "0x77"

    execute_tool(
        "set_param", {"instance_id": "bme1", "key": "address", "value": None},
        garage_motion_design, lib,
    )
    assert "address" not in bme1["params"]


def test_set_connection_updates_existing(lib, garage_motion_design):
    out, is_error = execute_tool(
        "set_connection",
        {
            "component_id": "pir1", "pin_role": "OUT",
            "target": {"kind": "gpio", "pin": "GPIO5"},
        },
        garage_motion_design, lib,
    )
    assert is_error is False
    conn = next(
        c for c in garage_motion_design["connections"]
        if c["component_id"] == "pir1" and c["pin_role"] == "OUT"
    )
    assert conn["target"] == {"kind": "gpio", "pin": "GPIO5"}


def test_add_bus_appends_and_dedupes(lib, garage_motion_design):
    out, _ = execute_tool(
        "add_bus", {"id": "i2c1", "type": "i2c", "sda": "GPIO16", "scl": "GPIO17"},
        garage_motion_design, lib,
    )
    body = json.loads(out)
    assert body["ok"] is True
    assert any(b["id"] == "i2c1" for b in garage_motion_design["buses"])

    out2, _ = execute_tool(
        "add_bus", {"id": "i2c1", "type": "i2c", "sda": "GPIO16", "scl": "GPIO17"},
        garage_motion_design, lib,
    )
    body2 = json.loads(out2)
    assert body2["ok"] is False


def test_render_returns_yaml_and_ascii(lib, garage_motion_design):
    out, is_error = execute_tool("render", {}, garage_motion_design, lib)
    assert is_error is False
    body = json.loads(out)
    assert body["ok"] is True
    assert body["yaml"].startswith("esphome:\n  name: garage-motion")
    assert "ESP32-DevKitC-V4" in body["ascii"]


def test_validate_succeeds_on_known_example(lib, garage_motion_design):
    out, _ = execute_tool("validate", {}, garage_motion_design, lib)
    body = json.loads(out)
    assert body["ok"] is True
    assert body["design_id"] == "garage-motion-v1"


def test_validate_fails_on_missing_field(lib):
    out, _ = execute_tool("validate", {}, {"id": "x"}, lib)
    body = json.loads(out)
    assert body["ok"] is False


def test_unknown_tool_is_error(lib):
    out, is_error = execute_tool("set_anything", {}, {}, lib)
    assert is_error is True


def test_bad_argument_shape_is_error(lib):
    out, is_error = execute_tool("search_components", {"oops": "wrong"}, {}, lib)
    assert is_error is True


# ---------------------------------------------------------------------------
# Session JSONL round-trip
# ---------------------------------------------------------------------------

def test_session_round_trip(tmp_path):
    store = FileSessionStore(root=tmp_path)
    sid = new_session_id()
    assert store.exists(sid) is False
    assert store.load(sid) == []

    store.append(sid, "user", "hi")
    store.append(sid, "assistant", "hello")
    msgs = store.load(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "hi"
    assert "timestamp" in msgs[0]


def test_session_id_traversal_rejected(tmp_path):
    store = FileSessionStore(root=tmp_path)
    with pytest.raises(ValueError):
        store.path("../etc/passwd")
    with pytest.raises(ValueError):
        store.path("foo/bar")
    with pytest.raises(ValueError):
        store.path("")


# ---------------------------------------------------------------------------
# API contract
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch, tmp_path) -> TestClient:
    # Make sure the agent is reported as unavailable for the contract test
    # below, regardless of whether the dev environment has a key set.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return TestClient(create_app(sessions=FileSessionStore(root=tmp_path)))


def test_agent_status_no_key(client):
    r = client.get("/agent/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "ANTHROPIC_API_KEY" in body["reason"]


def test_agent_turn_503_without_key(client, garage_motion_design):
    r = client.post("/agent/turn", json={
        "design": garage_motion_design,
        "message": "add a BME280",
    })
    assert r.status_code == 503
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_agent_session_404_for_unknown(client):
    r = client.get("/agent/sessions/nonexistent")
    assert r.status_code == 404


def test_session_store_rejects_traversal_directly(tmp_path):
    """The defensive belt: even if a traversal got past the URL router, the
    SessionStore would reject it before touching the filesystem."""
    store = FileSessionStore(root=tmp_path)
    with pytest.raises(ValueError):
        store.path("../passwd")
