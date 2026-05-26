"""Tests for the shared netlist primitives and the .kicad_pcb emitter.

`build_netlist` is pure, so its tests always run. The `generate_kicad_pcb`
tests embed real footprint geometry, so they need the pinned KiCad libraries
and skip when `KICAD8_FOOTPRINT_DIR` / `KICAD8_SYMBOL_DIR` aren't set. CI sets
them (clones kicad-footprints@8.0.0 + kicad-symbols@8.0.0); locally, clone the
two repos and point the env vars at them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from wirestudio.kicad.netlist import assign_refs, build_netlist
from wirestudio.kicad.pcb import generate_kicad_pcb, pcb_status
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"

libs_required = pytest.mark.skipif(
    not pcb_status()["available"],
    reason="KiCad footprint/symbol libs not configured (KICAD8_FOOTPRINT_DIR / KICAD8_SYMBOL_DIR)",
)


@pytest.fixture
def lib():
    return default_library()


def _design(name: str) -> Design:
    return Design.model_validate(json.loads((EXAMPLES_DIR / f"{name}.json").read_text()))


# ---------------------------------------------------------------------------
# build_netlist -- pure, always runs
# ---------------------------------------------------------------------------

def test_build_netlist_groups_rails_and_buses(lib):
    nets = {n.name: n for n in build_netlist(_design("garage-motion"), lib)}
    assert {"GND", "+5V", "+3V3", "BUS_i2c0"} <= set(nets)
    # The BME280's SDA + SCL both land on the single I2C bus net.
    roles = {(p.component_id, p.pin_role) for p in nets["BUS_i2c0"].pads}
    assert ("bme1", "SDA") in roles and ("bme1", "SCL") in roles


def test_build_netlist_refs_agree_with_assign_refs(lib):
    """Every pad's ref is exactly what assign_refs hands out -- the property
    that keeps the schematic and PCB ref designators in lockstep."""
    d = _design("garage-motion")
    refs = assign_refs(d, lib)
    for net in build_netlist(d, lib):
        for pad in net.pads:
            assert pad.ref == refs[pad.component_id]


def test_build_netlist_is_sorted_and_stable(lib):
    nets = build_netlist(_design("garage-motion"), lib)
    names = [n.name for n in nets]
    assert names == sorted(names)


def test_build_netlist_skips_connection_to_absent_component(lib):
    d = _design("garage-motion")
    # Point a connection at a component id that isn't in the design.
    d.connections[0].component_id = "ghost"
    names = {(p.component_id) for net in build_netlist(d, lib) for p in net.pads}
    assert "ghost" not in names


# ---------------------------------------------------------------------------
# generate_kicad_pcb -- needs the pinned KiCad libraries
# ---------------------------------------------------------------------------

@libs_required
def test_pcb_starts_correctly_and_is_paren_balanced(lib):
    pcb = generate_kicad_pcb(_design("garage-motion"), lib)
    assert pcb.startswith("(kicad_pcb")
    assert pcb.count("(") == pcb.count(")")
    assert '(layer "Edge.Cuts")' in pcb and "gr_rect" in pcb


@libs_required
def test_pcb_embeds_board_and_component_footprints(lib):
    pcb = generate_kicad_pcb(_design("garage-motion"), lib)
    fps = re.findall(r'\(footprint "([^"]+)"', pcb)
    assert "RF_Module:ESP32-WROOM-32" in fps  # the board, M1
    assert "Package_LGA:Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering" in fps


@libs_required
def test_pcb_binds_pin_mapped_pad_to_net(lib):
    """The BME280's VCC role -> VDD pin -> a real footprint pad, carrying the
    +3V3 net; SDA/SCL land on the I2C bus net. Exercises symbol pin-name ->
    number -> pad resolution end to end."""
    pcb = generate_kicad_pcb(_design("garage-motion"), lib)
    assert re.search(r'\(net \d+ "\+3V3"\)', pcb)
    assert re.search(r'\(net \d+ "BUS_i2c0"\)', pcb)


@libs_required
def test_pcb_pad_net_indices_are_all_declared(lib):
    """Every net index a pad references must be declared at board level, or
    KiCad rejects the file."""
    pcb = generate_kicad_pcb(_design("garage-motion"), lib)
    declared = {int(i) for i, _ in re.findall(r'^\t\(net (\d+) "([^"]*)"\)', pcb, re.M)}
    referenced = {int(i) for i in re.findall(r'^\t\t\t?\(net (\d+) "', pcb, re.M)}
    assert referenced <= declared


@libs_required
def test_pcb_generic_connector_binds_positionally(lib):
    """The HC-SR501 PIR maps to a generic header; its OUT role (3rd pin) must
    bind to pad "3" carrying the GPIO net."""
    pcb = generate_kicad_pcb(_design("garage-motion"), lib)
    assert re.search(r'\(net \d+ "GPIO_GPIO13"\)', pcb)


@libs_required
def test_pcb_every_radio_and_sensor_example_emits(lib):
    for name in ("garage-motion", "oled", "distance-sensor", "ttgo-lora32", "bluemotion"):
        pcb = generate_kicad_pcb(_design(name), lib)
        assert pcb.count("(") == pcb.count(")"), name
        assert pcb.startswith("(kicad_pcb"), name
