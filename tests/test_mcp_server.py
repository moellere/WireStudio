"""Tests for the MCP server wrapper around the agent tool surface."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from wirestudio.designs.store import FileDesignStore
from wirestudio.library import default_library
from wirestudio.mcp.server import build_mcp_server


pytestmark = pytest.mark.anyio


EXPECTED_TOOLS = {
    "search_components",
    "list_boards",
    "recommend",
    "render",
    "validate",
    "set_board",
    "add_component",
    "remove_component",
    "set_param",
    "set_connection",
    "add_bus",
    "solve_pins",
    "set_active_design",
    "get_active_design",
}


def _seed_design(store: FileDesignStore, design_id: str = "test-bench") -> str:
    design = {
        "schema_version": "0.1",
        "id": design_id,
        "name": "Test Bench",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [],
        "buses": [],
        "connections": [],
    }
    store.save(design, design_id=design_id)
    return design_id


def _content_to_dict(content: list[Any]) -> dict:
    """Decode the first TextContent payload as JSON."""
    assert content, "expected at least one content block"
    text = getattr(content[0], "text", None)
    assert isinstance(text, str)
    return json.loads(text)


@pytest.fixture
def mcp_server(tmp_path: Path):
    store = FileDesignStore(root=tmp_path / "designs")
    server = build_mcp_server(default_library(), store)
    return server, store


async def test_all_expected_tools_registered(mcp_server):
    server, _ = mcp_server
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert names == EXPECTED_TOOLS


async def test_tool_input_schemas_include_design_id_for_mutating_tools(mcp_server):
    server, _ = mcp_server
    tools = {t.name: t for t in await server.list_tools()}
    for name in {"set_board", "add_component", "remove_component", "set_param",
                 "set_connection", "add_bus", "solve_pins", "render", "validate"}:
        schema = tools[name].inputSchema
        assert "design_id" in schema.get("properties", {}), f"{name} missing design_id"


async def test_search_components_finds_bme280(mcp_server):
    server, _ = mcp_server
    out = await server.call_tool("search_components", {"query": "bme280"})
    payload = _content_to_dict(out)
    assert payload["total"] >= 1
    ids = [m["library_id"] for m in payload["matches"]]
    assert "bme280" in ids


async def test_list_boards_returns_known_board(mcp_server):
    server, _ = mcp_server
    out = await server.call_tool("list_boards", {})
    payload = _content_to_dict(out)
    ids = {b["library_id"] for b in payload["boards"]}
    assert "esp32-devkitc-v4" in ids


async def test_add_component_persists_to_store(mcp_server):
    server, store = mcp_server
    design_id = _seed_design(store)

    out = await server.call_tool(
        "add_component",
        {"design_id": design_id, "library_id": "bme280"},
    )
    payload = _content_to_dict(out)
    assert payload["ok"] is True

    # The mutation must have been written back to the store -- otherwise
    # the next tool call (or the browser) sees a stale design.
    saved = store.load(design_id)
    assert len(saved["components"]) == 1
    assert saved["components"][0]["library_id"] == "bme280"
    assert saved["components"][0]["id"] == payload["instance_id"]


async def test_validate_against_stored_design(mcp_server):
    server, store = mcp_server
    design_id = _seed_design(store)
    out = await server.call_tool("validate", {"design_id": design_id})
    payload = _content_to_dict(out)
    assert payload["ok"] is True
    assert payload["design_id"] == design_id


async def test_render_against_stored_design(mcp_server):
    server, store = mcp_server
    design_id = _seed_design(store)
    out = await server.call_tool("render", {"design_id": design_id})
    payload = _content_to_dict(out)
    assert payload["ok"] is True
    assert "yaml" in payload
    assert "ascii" in payload


async def test_remove_component_persists(mcp_server):
    server, store = mcp_server
    design_id = _seed_design(store)
    add = _content_to_dict(
        await server.call_tool(
            "add_component", {"design_id": design_id, "library_id": "bme280"}
        )
    )
    instance_id = add["instance_id"]

    out = await server.call_tool(
        "remove_component",
        {"design_id": design_id, "instance_id": instance_id},
    )
    assert _content_to_dict(out)["ok"] is True
    assert store.load(design_id)["components"] == []


async def test_unknown_design_id_surfaces_as_tool_error(mcp_server):
    server, _ = mcp_server
    # Unknown design_id triggers FileNotFoundError in the store. FastMCP's
    # contract is that tool exceptions become an isError-flagged result;
    # call_tool itself raises ToolError so the model can recover instead
    # of seeing a black-hole response.
    with pytest.raises(Exception):
        await server.call_tool(
            "validate", {"design_id": "no-such-design"}
        )


async def test_mounted_mcp_route_requires_token(monkeypatch, tmp_path: Path):
    # End-to-end: build the FastAPI app with MCP mounted, hit /mcp without
    # a token, expect 401. We also confirm the route is mounted at all
    # (a 404 would indicate the mount path was wrong).
    monkeypatch.setenv("WIRESTUDIO_MCP_TOKEN", "test-secret")
    monkeypatch.setenv("DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))

    from wirestudio.api.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    # Lifespan needs to run for the MCP session manager. httpx.ASGITransport
    # handles startup/shutdown around the request, but we use lifespan="on"
    # via the lifespan manager pattern.
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize"},
            headers={"Accept": "application/json, text/event-stream"},
        )
    assert r.status_code == 401, r.text


async def test_non_mcp_paths_unaffected_by_token(monkeypatch, tmp_path: Path):
    # Regression: with the MCP app mounted at "/", an unscoped middleware
    # would 401 every fall-through path -- including the SPA root and the
    # rest of the API. The token must only gate /mcp.
    monkeypatch.setenv("WIRESTUDIO_MCP_TOKEN", "test-secret")
    monkeypatch.setenv("DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))

    from wirestudio.api.app import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # Existing FastAPI route -- token must not interfere.
        health = await c.get("/health")
        assert health.status_code == 200
        # Library route the SPA hits unauthenticated.
        boards = await c.get("/library/boards")
        assert boards.status_code == 200
        # Unknown path: should land in the mcp_app router (not the auth
        # gate) and 404 cleanly. A 401 here would be the regression.
        unknown = await c.get("/no-such-path")
        assert unknown.status_code != 401


async def test_prod_wrapper_gates_api_mcp(monkeypatch, tmp_path: Path):
    # Regression for the nested-mount case. In wirestudio.api.serve the
    # studio app is mounted under /api, which means the inner mcp_app
    # middleware sees scope[path] as "/api/mcp" rather than "/mcp" by the
    # time it runs (Starlette's nested Mount('/') doesn't reliably strip).
    # The middleware must still 401 unauthed traffic, and /api/library/...
    # must remain open.
    monkeypatch.setenv("WIRESTUDIO_MCP_TOKEN", "test-secret")
    monkeypatch.setenv("DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<!doctype html><title>t</title>")

    from wirestudio.api.serve import create_serve_app

    app = create_serve_app(static)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        # SPA root -- unauthenticated, must serve index.html.
        root = await c.get("/")
        assert root.status_code == 200
        assert "<title>t</title>" in root.text
        # API routes the SPA hits -- still unauthenticated.
        health = await c.get("/api/health")
        assert health.status_code == 200
        # The MCP endpoint -- gated.
        mcp_unauthed = await c.post(
            "/api/mcp",
            json={},
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert mcp_unauthed.status_code == 401, mcp_unauthed.text
