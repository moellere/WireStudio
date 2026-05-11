"""Tests for the MCP resources registered in `wirestudio/mcp/server.py`."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from wirestudio.designs.store import FileDesignStore
from wirestudio.library import default_library
from wirestudio.mcp.server import build_mcp_server


pytestmark = pytest.mark.anyio


EXPECTED_STATIC_URIS = {
    "library://components",
    "library://boards",
}

EXPECTED_TEMPLATE_URIS = {
    "library://components/{component_id}",
    "library://boards/{board_id}",
    "design://{design_id}/json",
    "design://{design_id}/yaml",
    "design://{design_id}/ascii",
}


def _seed_design(store: FileDesignStore, design_id: str = "res-test") -> str:
    """Save a minimal design with one component so the design resources
    have something to render against."""
    library = default_library()
    design: dict[str, Any] = {
        "schema_version": "0.1",
        "id": design_id,
        "name": "Resource Test",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [],
        "buses": [],
        "connections": [],
    }
    # Seed via the same helper the MCP add_component tool uses so the
    # design lands with real connections.
    from wirestudio.designs.seed import add_component_with_connections
    add_component_with_connections(design, library, library_id="bme280")
    store.save(design, design_id=design_id)
    return design_id


def _content_as_text(content: list[Any]) -> str:
    assert content, "expected resource content"
    return content[0].content


@pytest.fixture
def mcp_server(tmp_path: Path):
    store = FileDesignStore(root=tmp_path / "designs")
    server = build_mcp_server(default_library(), store)
    return server, store


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_static_resources_registered(mcp_server):
    server, _ = mcp_server
    resources = await server.list_resources()
    uris = {str(r.uri) for r in resources}
    assert EXPECTED_STATIC_URIS <= uris


async def test_template_resources_registered(mcp_server):
    server, _ = mcp_server
    templates = await server.list_resource_templates()
    uris = {t.uriTemplate for t in templates}
    assert EXPECTED_TEMPLATE_URIS <= uris


# ---------------------------------------------------------------------------
# Library catalog
# ---------------------------------------------------------------------------


async def test_components_index_returns_compact_entries(mcp_server):
    server, _ = mcp_server
    content = _content_as_text(await server.read_resource("library://components"))
    payload = json.loads(content)
    ids = {c["id"] for c in payload["components"]}
    assert "bme280" in ids
    # Compact shape: id/name/category/use_cases/aliases only.
    entry = next(c for c in payload["components"] if c["id"] == "bme280")
    assert set(entry.keys()) == {"id", "name", "category", "use_cases", "aliases"}


async def test_component_detail_returns_full_library_entry(mcp_server):
    server, _ = mcp_server
    content = _content_as_text(
        await server.read_resource("library://components/bme280")
    )
    payload = json.loads(content)
    # Full entry has the electrical block + esphome template.
    assert "electrical" in payload
    assert "esphome" in payload
    assert payload["id"] == "bme280"


async def test_component_detail_unknown_id_raises(mcp_server):
    server, _ = mcp_server
    with pytest.raises(Exception):
        await server.read_resource("library://components/not-a-real-part")


async def test_boards_index_returns_compact_entries(mcp_server):
    server, _ = mcp_server
    content = _content_as_text(await server.read_resource("library://boards"))
    payload = json.loads(content)
    ids = {b["id"] for b in payload["boards"]}
    assert "esp32-devkitc-v4" in ids
    entry = next(b for b in payload["boards"] if b["id"] == "esp32-devkitc-v4")
    assert "mcu" in entry and "chip_variant" in entry


async def test_board_detail_returns_full_entry(mcp_server):
    server, _ = mcp_server
    content = _content_as_text(
        await server.read_resource("library://boards/esp32-devkitc-v4")
    )
    payload = json.loads(content)
    # Full entry exposes the GPIO pinout + default buses.
    assert "gpio_capabilities" in payload
    assert "default_buses" in payload


# ---------------------------------------------------------------------------
# Design resources
# ---------------------------------------------------------------------------


async def test_design_json_returns_raw_dict(mcp_server):
    server, store = mcp_server
    design_id = _seed_design(store)
    content = _content_as_text(
        await server.read_resource(f"design://{design_id}/json")
    )
    payload = json.loads(content)
    assert payload["id"] == design_id
    assert any(c["library_id"] == "bme280" for c in payload["components"])


async def test_design_yaml_renders_esphome_yaml(mcp_server):
    server, store = mcp_server
    design_id = _seed_design(store)
    content = _content_as_text(
        await server.read_resource(f"design://{design_id}/yaml")
    )
    parsed = yaml.safe_load(content)
    assert "esphome" in parsed
    # BME280 lands as an I2C sensor under the sensor: list (it's a
    # canonical ESPHome platform).
    assert "sensor" in parsed or "i2c" in parsed


async def test_design_ascii_renders_diagram(mcp_server):
    server, store = mcp_server
    design_id = _seed_design(store)
    content = _content_as_text(
        await server.read_resource(f"design://{design_id}/ascii")
    )
    # ASCII output should include the board name and the BME280 instance.
    assert "ESP32" in content or "esp32" in content
    assert "bme280" in content.lower()


async def test_design_resource_unknown_id_raises(mcp_server):
    server, _ = mcp_server
    with pytest.raises(Exception):
        await server.read_resource("design://no-such-design/yaml")


async def test_design_yaml_reflects_latest_state(mcp_server):
    """Read-after-write: an MCP tool mutation followed by a re-read of
    the design://{id}/yaml resource must show the new component."""
    server, store = mcp_server
    design_id = _seed_design(store)

    # Add a second component via the MCP tool surface.
    result = await server.call_tool(
        "add_component",
        {"design_id": design_id, "library_id": "hc-sr501"},
    )
    assert result is not None  # tool succeeded

    content = _content_as_text(
        await server.read_resource(f"design://{design_id}/yaml")
    )
    # HC-SR501 emits a binary_sensor entry with its human label set as
    # the ESPHome `name`. The post-write YAML must surface it.
    assert "HC-SR501" in content
    assert "binary_sensor" in content
