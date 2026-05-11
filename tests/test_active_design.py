"""Tests for the active-design tracker, HTTP endpoints, and MCP fallback."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from wirestudio.designs.active import ActiveDesignTracker
from wirestudio.designs.store import FileDesignStore
from wirestudio.library import default_library
from wirestudio.mcp.server import build_mcp_server


pytestmark = pytest.mark.anyio


def _seed_design(store: FileDesignStore, design_id: str = "active-test") -> str:
    """Save a renderable design so the MCP tools have something to work on."""
    design: dict[str, Any] = {
        "schema_version": "0.1",
        "id": design_id,
        "name": "Active Test",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [],
        "buses": [],
        "connections": [],
    }
    store.save(design, design_id=design_id)
    return design_id


def _tool_payload(content: list[Any]) -> dict:
    """Decode the first TextContent payload as JSON."""
    assert content
    text = getattr(content[0], "text", None)
    assert isinstance(text, str)
    return json.loads(text)


# ---------------------------------------------------------------------------
# ActiveDesignTracker unit
# ---------------------------------------------------------------------------


def test_tracker_starts_unset():
    assert ActiveDesignTracker().get() is None


def test_tracker_set_and_clear():
    t = ActiveDesignTracker()
    t.set("d1")
    assert t.get() == "d1"
    t.clear()
    assert t.get() is None


def test_tracker_empty_string_normalizes_to_none():
    t = ActiveDesignTracker(initial="d1")
    t.set("")
    assert t.get() is None


def test_tracker_initial_value():
    assert ActiveDesignTracker(initial="garage").get() == "garage"


# ---------------------------------------------------------------------------
# HTTP /designs/active
# ---------------------------------------------------------------------------


async def test_http_get_active_starts_null(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WIRESTUDIO_MCP_TOKEN", "test")
    monkeypatch.setenv("DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    from wirestudio.api.app import create_app
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.get("/designs/active")
        assert r.status_code == 200
        assert r.json() == {"id": None}


async def test_http_put_then_get_active(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WIRESTUDIO_MCP_TOKEN", "test")
    monkeypatch.setenv("DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    from wirestudio.api.app import create_app
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.put("/designs/active", json={"id": "garage"})
        assert r.status_code == 200
        assert r.json() == {"id": "garage"}

        r = await c.get("/designs/active")
        assert r.json() == {"id": "garage"}


async def test_http_put_null_clears_active(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WIRESTUDIO_MCP_TOKEN", "test")
    monkeypatch.setenv("DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    from wirestudio.api.app import create_app
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        await c.put("/designs/active", json={"id": "garage"})
        r = await c.put("/designs/active", json={"id": None})
        assert r.json() == {"id": None}


async def test_http_put_rejects_non_string_id(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WIRESTUDIO_MCP_TOKEN", "test")
    monkeypatch.setenv("DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    from wirestudio.api.app import create_app
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.put("/designs/active", json={"id": 42})
        assert r.status_code == 422


async def test_delete_design_clears_active_if_matched(monkeypatch, tmp_path: Path):
    """Deleting the active design must clear the pointer; otherwise the next
    default-resolved MCP call hits an unknown id and 500s."""
    monkeypatch.setenv("WIRESTUDIO_MCP_TOKEN", "test")
    monkeypatch.setenv("DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    from wirestudio.api.app import create_app
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        # Save a design so we can delete it.
        design = {
            "schema_version": "0.1",
            "id": "doomed",
            "name": "Doomed",
            "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "arduino"},
            "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
            "components": [],
            "buses": [],
            "connections": [],
        }
        await c.post("/designs", json={"design_id": "doomed", "design": design})
        await c.put("/designs/active", json={"id": "doomed"})
        assert (await c.get("/designs/active")).json() == {"id": "doomed"}

        await c.delete("/designs/doomed")
        assert (await c.get("/designs/active")).json() == {"id": None}


async def test_delete_unrelated_design_doesnt_clear_active(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WIRESTUDIO_MCP_TOKEN", "test")
    monkeypatch.setenv("DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    from wirestudio.api.app import create_app
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        design = {
            "schema_version": "0.1",
            "id": "keep-me",
            "name": "Keep Me",
            "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "arduino"},
            "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
            "components": [], "buses": [], "connections": [],
        }
        await c.post("/designs", json={"design_id": "keep-me", "design": design})
        await c.put("/designs/active", json={"id": "keep-me"})

        other = {**design, "id": "delete-me"}
        await c.post("/designs", json={"design_id": "delete-me", "design": other})
        await c.delete("/designs/delete-me")
        # Active pointer untouched -- only keep-me was active.
        assert (await c.get("/designs/active")).json() == {"id": "keep-me"}


# ---------------------------------------------------------------------------
# MCP set_active_design + get_active_design
# ---------------------------------------------------------------------------


@pytest.fixture
def mcp_server(tmp_path: Path):
    store = FileDesignStore(root=tmp_path / "designs")
    active = ActiveDesignTracker()
    server = build_mcp_server(default_library(), store, active=active)
    return server, store, active


async def test_mcp_set_active_design_records_id(mcp_server):
    server, store, active = mcp_server
    design_id = _seed_design(store, "garage")
    out = _tool_payload(
        await server.call_tool("set_active_design", {"design_id": design_id})
    )
    assert out == {"ok": True, "active_design_id": "garage"}
    assert active.get() == "garage"


async def test_mcp_set_active_design_unknown_id_returns_error(mcp_server):
    server, _, active = mcp_server
    out = _tool_payload(
        await server.call_tool("set_active_design", {"design_id": "no-such"})
    )
    assert out["ok"] is False
    assert "no design" in out["error"]
    assert active.get() is None


async def test_mcp_set_active_design_empty_string_clears(mcp_server):
    server, store, active = mcp_server
    _seed_design(store, "garage")
    await server.call_tool("set_active_design", {"design_id": "garage"})
    out = _tool_payload(
        await server.call_tool("set_active_design", {"design_id": ""})
    )
    assert out == {"ok": True, "active_design_id": None}
    assert active.get() is None


async def test_mcp_get_active_design(mcp_server):
    server, store, _ = mcp_server
    _seed_design(store, "garage")
    out = _tool_payload(await server.call_tool("get_active_design", {}))
    assert out == {"active_design_id": None}
    await server.call_tool("set_active_design", {"design_id": "garage"})
    out = _tool_payload(await server.call_tool("get_active_design", {}))
    assert out == {"active_design_id": "garage"}


# ---------------------------------------------------------------------------
# MCP tools default to active when design_id omitted
# ---------------------------------------------------------------------------


async def test_render_uses_active_when_design_id_omitted(mcp_server):
    server, store, active = mcp_server
    _seed_design(store, "garage")
    active.set("garage")

    out = _tool_payload(await server.call_tool("render", {}))
    assert out.get("ok") is True
    assert "yaml" in out


async def test_render_explicit_design_id_overrides_active(mcp_server):
    server, store, active = mcp_server
    _seed_design(store, "garage")
    _seed_design(store, "other")
    active.set("garage")

    out = _tool_payload(
        await server.call_tool("render", {"design_id": "other"})
    )
    assert out.get("ok") is True
    # Result includes the design_id "other"; just confirm it didn't error.


async def test_render_with_no_active_or_id_returns_error(mcp_server):
    server, _, _ = mcp_server
    out = _tool_payload(await server.call_tool("render", {}))
    assert out["ok"] is False
    assert "no active design" in out["error"].lower()


async def test_add_component_uses_active_when_design_id_omitted(mcp_server):
    server, store, active = mcp_server
    _seed_design(store, "garage")
    active.set("garage")

    out = _tool_payload(
        await server.call_tool(
            "add_component", {"library_id": "bme280"}
        )
    )
    assert out["ok"] is True
    # Reload and confirm bme280 was persisted to the active design.
    saved = store.load("garage")
    assert any(c["library_id"] == "bme280" for c in saved["components"])


async def test_add_component_with_no_design_id_or_active_errors(mcp_server):
    server, _, _ = mcp_server
    out = _tool_payload(
        await server.call_tool(
            "add_component", {"library_id": "bme280"}
        )
    )
    assert out["ok"] is False
    assert "no active design" in out["error"].lower()
