"""Tests for `_run_solve_pins` wrapper function."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirestudio.agent.tools import _run_solve_pins
from wirestudio.library import default_library


REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


@pytest.fixture
def library():
    return default_library()


def _load(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / f"{name}.json").read_text())


def _connection(d: dict, component_id: str, pin_role: str) -> dict:
    return next(
        c for c in d["connections"]
        if c["component_id"] == component_id and c["pin_role"] == pin_role
    )


def test_run_solve_pins_mutates_design(library):
    """Verify that _run_solve_pins mutates the input design dictionary in-place."""
    design = _load("wasserpir")
    # Unbind the PIR's OUT connection.
    _connection(design, "pir1", "OUT")["target"] = {"kind": "gpio", "pin": ""}

    # Run the wrapper
    result = _run_solve_pins(design, library)

    # Verify the output format
    assert result["ok"] is True
    assert len(result["assigned"]) == 1
    assignment = result["assigned"][0]
    assert assignment["component_id"] == "pir1"
    assert assignment["pin_role"] == "OUT"
    assert assignment["old_target"] == {"kind": "gpio", "pin": ""}
    assert "pin" in assignment["new_target"]
    assert assignment["new_target"]["pin"] != ""
    assert result["unresolved"] == []
    assert result["warnings"] == []

    # Verify the design was mutated in-place
    mutated_target = _connection(design, "pir1", "OUT")["target"]
    assert mutated_target == assignment["new_target"]

def test_run_solve_pins_already_solved(library):
    """Verify that an already solved design returns an empty assigned list and doesn't mutate."""
    design = _load("wasserpir")
    original_target = _connection(design, "pir1", "OUT")["target"]

    result = _run_solve_pins(design, library)

    assert result["ok"] is True
    assert result["assigned"] == []
    assert result["unresolved"] == []
    assert result["warnings"] == []

    # Verify the design wasn't changed
    mutated_target = _connection(design, "pir1", "OUT")["target"]
    assert mutated_target == original_target

def test_run_solve_pins_unresolved(library):
    """Verify that unresolved dependencies are correctly reported."""
    design = _load("wasserpir")

    # BME280 requires i2c but we won't supply the bus
    design["components"].append({
        "id": "bme1",
        "library_id": "bme280",
        "label": "BME",
        "params": {}
    })
    design["connections"].append({
        "component_id": "bme1",
        "pin_role": "SDA",
        "target": {"kind": "bus", "bus_id": ""}
    })

    result = _run_solve_pins(design, library)

    assert result["ok"] is True
    # The BME280 should trigger an unresolved bus warning since no i2c bus exists
    assert any(u["code"] == "no_matching_bus" and "bme1" in u["text"] for u in result["unresolved"])

def test_run_solve_pins_warnings(library):
    """Verify that warnings are correctly reported."""
    design = _load("wasserpir")
    # Change the existing board to a missing one
    design["board"]["library_id"] = "non_existent_board"

    result = _run_solve_pins(design, library)
    assert result["ok"] is True
    assert any(w["code"] == "unknown_board" for w in result["warnings"])
