"""`add_component` (agent and MCP) leaves the new part wired, or says why not."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirestudio.agent.tools import _run_add_component
from wirestudio.library import default_library

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"


@pytest.fixture
def library():
    return default_library()


def _load(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / f"{name}.json").read_text())


def _targets(d: dict, component_id: str) -> dict:
    return {c["pin_role"]: c["target"] for c in d["connections"] if c["component_id"] == component_id}


def test_gpio_pins_get_a_free_board_pin(library):
    """The eval's add-oled failure: RESET left empty because the model
    never followed up with solve_pins."""
    d = _load("garage-motion")
    used = {c["target"].get("pin") for c in d["connections"] if c["target"].get("kind") == "gpio"}
    out = _run_add_component(d, library, library_id="ssd1306")

    reset = _targets(d, out["instance_id"])["RESET"]
    assert reset["kind"] == "gpio" and reset["pin"] and reset["pin"] not in used
    assert out["assigned"]["RESET"] == reset
    assert "unbound" not in out


def test_existing_unbound_pins_are_left_alone(library):
    """Binding is scoped to the new part; another part's empty pin may be
    empty on purpose."""
    d = _load("garage-motion")
    next(c for c in d["connections"]
         if c["component_id"] == "pir1" and c["pin_role"] == "OUT")["target"] = {"kind": "gpio", "pin": ""}
    _run_add_component(d, library, library_id="ssd1306")
    assert _targets(d, "pir1")["OUT"] == {"kind": "gpio", "pin": ""}


def test_a_bus_the_board_cannot_pin_is_not_left_behind(library):
    """The 1-Wire bus has no board default, so seeding one would leave a
    pinless bus the agent has no tool to fill in."""
    d = _load("garage-motion")
    out = _run_add_component(d, library, library_id="ds18b20")

    assert not [b for b in d["buses"] if b["type"] == "1wire"]
    assert _targets(d, out["instance_id"])["DATA"] == {"kind": "bus", "bus_id": ""}
    assert any(u.startswith(f"{out['instance_id']}.DATA") and "add_bus" in u for u in out["unbound"])


def test_add_bus_then_solve_finishes_the_part(library):
    from wirestudio.agent.tools import _run_add_bus, _run_solve_pins

    d = _load("garage-motion")
    out = _run_add_component(d, library, library_id="ds18b20")
    _run_add_bus(d, library, id="wire0", type="1wire", pin="GPIO4")
    _run_solve_pins(d, library)
    assert _targets(d, out["instance_id"])["DATA"] == {"kind": "bus", "bus_id": "wire0"}


def test_a_bus_the_board_pins_is_kept(library):
    """I2C gets the board's default SDA/SCL, so the seeded bus is usable."""
    d = _load("garage-motion")
    d["buses"] = []
    d["connections"] = [c for c in d["connections"] if c["target"].get("kind") != "bus"]
    out = _run_add_component(d, library, library_id="ssd1306")

    [bus] = d["buses"]
    assert bus["type"] == "i2c" and bus["sda"] and bus["scl"]
    assert _targets(d, out["instance_id"])["SDA"] == {"kind": "bus", "bus_id": bus["id"]}
