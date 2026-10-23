"""A live MCP client against the mounted server: the studio app under
uvicorn on a local port, the `mcp` package's own Streamable HTTP client
with the bearer token, one design driven from `create_design` to
`render`, a resource read. The other MCP tests call the tool functions;
this one goes through the wire."""
from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path

import httpx
import pytest
import uvicorn
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

pytestmark = pytest.mark.anyio

TOKEN = "ci-token"
DESIGN = {
    "schema_version": "1.0",
    "id": "ci-bench",
    "name": "CI bench",
    "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "arduino"},
    "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
    "components": [],
    "buses": [],
    "connections": [],
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def mcp_url(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WIRESTUDIO_MCP_TOKEN", TOKEN)
    monkeypatch.setenv("DESIGNS_DIR", str(tmp_path / "designs"))
    monkeypatch.setenv("SESSIONS_DIR", str(tmp_path / "sessions"))
    from wirestudio.api.app import create_app

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            task.result()
        await asyncio.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    await task


def _body(result) -> dict:
    return json.loads(result.content[0].text)


async def test_a_client_lists_tools_drives_a_design_and_reads_resources(mcp_url):
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}) as http:
        async with streamable_http_client(mcp_url, http_client=http) as (read, write, *_):
            async with ClientSession(read, write) as session:
                await session.initialize()

                tools = {t.name for t in (await session.list_tools()).tools}
                assert {"create_design", "add_component", "solve_pins", "validate", "render",
                        "workbench_flash", "lorawan_provision"} <= tools

                assert _body(await session.call_tool("create_design", {"design": DESIGN}))["ok"]
                added = _body(await session.call_tool(
                    "add_component", {"library_id": "bme280", "design_id": "ci-bench"}))
                assert "error" not in added, added
                solved = _body(await session.call_tool("solve_pins", {"design_id": "ci-bench"}))
                assert "error" not in solved, solved
                assert _body(await session.call_tool("validate", {"design_id": "ci-bench"}))["ok"]
                rendered = _body(await session.call_tool("render", {"design_id": "ci-bench"}))
                assert "bme280" in rendered["yaml"]

                resources = {r.uri_template for r in (await session.list_resource_templates()).resource_templates}
                assert "design://{design_id}/yaml" in resources
                yaml_text = (await session.read_resource("design://ci-bench/yaml")).contents[0].text
                assert yaml_text == rendered["yaml"]
                detail = json.loads((await session.read_resource("library://components/bme280")).contents[0].text)
                assert detail["id"] == "bme280"


async def test_a_client_without_the_token_is_refused(mcp_url):
    async with httpx.AsyncClient() as http:
        with pytest.raises(Exception) as info:
            async with streamable_http_client(mcp_url, http_client=http) as (read, write, *_):
                async with ClientSession(read, write) as session:
                    await session.initialize()
        # The transport surfaces the 401 as the session's error, inside the
        # task groups the client runs under.
        leaves = [info.value]
        while any(isinstance(e, BaseExceptionGroup) for e in leaves):
            leaves = [sub for e in leaves for sub in (e.exceptions if isinstance(e, BaseExceptionGroup) else [e])]
        assert any(type(e).__name__ == "MCPError" for e in leaves), leaves
        assert (await http.post(mcp_url, json={}, headers={"Accept": "application/json, text/event-stream"})).status_code == 401
