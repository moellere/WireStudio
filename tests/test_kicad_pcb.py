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
    assert {"GND", "+5V", "+3V3", "BUS_i2c0_SDA", "BUS_i2c0_SCL"} <= set(nets)
    assert "BUS_i2c0" not in nets
    sda = {(p.component_id, p.pin_role) for p in nets["BUS_i2c0_SDA"].pads}
    scl = {(p.component_id, p.pin_role) for p in nets["BUS_i2c0_SCL"].pads}
    assert sda == {("bme1", "SDA"), ("__board__", "IO21")}
    assert scl == {("bme1", "SCL"), ("__board__", "IO22")}


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
def test_pcb_pours_gnd_on_the_bottom_inside_the_outline(lib):
    pcb = generate_kicad_pcb(_design("garage-motion"), lib)
    gnd = re.search(r'\(net (\d+) "GND"\)', pcb).group(1)
    zones = re.findall(r"^\t\(zone\n(.*?)^\t\)$", pcb, re.S | re.M)
    assert len(zones) == 1
    zone = zones[0]
    assert f"(net {gnd})" in zone and '(layer "B.Cu")' in zone
    assert "(connect_pads yes" in zone
    assert "(filled_polygon" not in pcb  # the route step fills it
    ox0, oy0, ox1, oy1 = map(float, re.search(
        r"\(gr_rect\n\t\t\(start ([\d.]+) ([\d.]+)\)\n\t\t\(end ([\d.]+) ([\d.]+)\)", pcb).groups())
    pts = [tuple(map(float, p)) for p in re.findall(r"\(xy ([\d.]+) ([\d.]+)\)", zone)]
    assert all(ox0 < x < ox1 and oy0 < y < oy1 for x, y in pts)


@libs_required
def test_pcb_without_a_gnd_net_has_no_pour(lib):
    design = _design("garage-motion")
    design.connections = [c for c in design.connections
                          if not (c.target.kind == "rail" and c.target.rail.lower() == "gnd")]
    assert not re.search(r"^\t\(zone$", generate_kicad_pcb(design, lib), re.M)


@libs_required
def test_pcb_embeds_board_and_component_footprints(lib):
    pcb = generate_kicad_pcb(_design("garage-motion"), lib)
    fps = re.findall(r'\(footprint "([^"]+)"', pcb)
    assert "RF_Module:ESP32-WROOM-32" in fps  # the board, M1
    assert "Package_LGA:Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering" in fps


@libs_required
def test_pcb_binds_pin_mapped_pad_to_net(lib):
    """The BME280's VCC role -> VDD pin -> a real footprint pad, carrying the
    +3V3 net; SDA/SCL land on the I2C bus's line nets. Exercises symbol
    pin-name -> number -> pad resolution end to end."""
    pcb = generate_kicad_pcb(_design("garage-motion"), lib)
    assert re.search(r'\(net \d+ "\+3V3"\)', pcb)
    assert re.search(r'\(net \d+ "BUS_i2c0_SDA"\)', pcb)
    assert re.search(r'\(net \d+ "BUS_i2c0_SCL"\)', pcb)


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


# ---------------------------------------------------------------------------
# Subcircuits
# ---------------------------------------------------------------------------

def test_build_netlist_expands_subcircuit_nodes(lib):
    nets = {n.name: n for n in build_netlist(_design("motor-position"), lib)}
    gate = {(p.ref, p.pin_role) for p in nets["bridge_gate_a"].pads}
    assert gate == {("Q1", "G"), ("Q2", "G"), ("Q3", "C"), ("R1", "2")}
    assert {(p.ref, p.pin_role) for p in nets["GPIO_GPIO18"].pads} == {
        ("R2", "1"), ("R3", "1"), ("M1", "IO18"),
    }
    assert {p.ref for p in nets["bridge_out_a"].pads} == {"Q1", "Q2", "C2", "J1"}
    assert all(p.part_id for p in nets["bridge_gate_a"].pads)


@libs_required
def test_pcb_binds_every_subcircuit_pad(lib):
    import re
    pcb = generate_kicad_pcb(_design("motor-position"), lib)
    blocks = {
        re.search(r'"Reference" "([^"]+)"', b).group(1): b
        for b in re.split(r"\n\t\(footprint ", pcb)[1:]
    }
    assert {"Q1", "Q6", "R1", "R6", "C1", "C2", "J1"} <= set(blocks)
    for ref in ("Q1", "R1", "C2", "J1"):
        pads = len(re.findall(r'\(pad "\d+"', blocks[ref]))
        assert len(re.findall(r'\(net \d+ "', blocks[ref])) == pads
    assert '(net ' in blocks["R1"] and '"bridge_gate_a"' in blocks["R1"]


def _harness(lib):
    import json

    from wirestudio.model import Design
    path = Path(__file__).resolve().parent.parent / "wirestudio" / "examples" / "actuator-harness.json"
    return Design.model_validate(json.loads(path.read_text()))


def test_build_netlist_lands_passthrough_pins_on_resolved_nets(lib):
    """A connector position with a `net` target joins the net it names: a
    subcircuit's internal node, a role's GPIO net, or a rail."""
    from wirestudio.kicad.netlist import build_netlist
    nets = {n.name: {f"{p.ref}.{p.pin_role}" for p in n.pads} for n in build_netlist(_harness(lib), lib)}
    out_a = nets["bridge_out_a"]
    assert any(p.endswith(".P1") for p in out_a) and "Q1.D" in out_a and "J1.1" in out_a
    assert any(p.endswith(".P4") for p in nets["GPIO_GPIO34"]) and any(p.endswith(".IN") for p in nets["GPIO_GPIO34"])
    assert any(p.endswith(".P7") for p in nets["GPIO_GPIO27"])
    assert any(p.endswith(".P3") for p in nets["+3V3"])
    assert sum(1 for p in nets["GND"] if p.endswith((".P5", ".P6", ".P8", ".P4"))) == 4
    assert "UNCONNECTED" not in nets


def test_build_netlist_drops_unresolved_net_targets(lib):
    import json

    from wirestudio.kicad.netlist import assign_refs, build_netlist
    from wirestudio.model import Design
    raw = json.loads((Path(__file__).resolve().parent.parent / "wirestudio" / "examples" / "actuator-harness.json").read_text())
    for c in raw["connections"]:
        if c["component_id"] == "harness" and c["pin_role"] == "P1":
            c["target"] = {"kind": "net", "component_id": "bridge", "net": "nope"}
        if c["component_id"] == "harness" and c["pin_role"] == "P2":
            c["target"] = {"kind": "net", "component_id": "", "net": ""}
    design = Design.model_validate(raw)
    harness = assign_refs(design, lib)["harness"]
    nets = {n.name: {f"{p.ref}.{p.pin_role}" for p in n.pads} for n in build_netlist(design, lib)}
    assert not any(p in (f"{harness}.P1", f"{harness}.P2") for pads in nets.values() for p in pads)
    assert any(p == f"{harness}.P3" for pads in nets.values() for p in pads)
    assert "UNCONNECTED" not in nets


def test_skidl_script_fetches_nets_for_passthrough_pins(lib):
    from wirestudio.kicad.generator import generate_skidl
    script = generate_skidl(_harness(lib), lib)
    lines = script.splitlines()
    fetch = next(i for i, l in enumerate(lines) if 'Net.fetch("bridge_out_a")' in l)
    declared = next(i for i, l in enumerate(lines) if 'Net("bridge_out_a")' in l)
    assert declared < fetch
    assert any('c_harness["3"] += NET_PLUS__3V3' in l for l in lines)
    assert any('c_harness["5"] += GND' in l for l in lines)


def test_pcb_binds_connector_pads_and_templated_footprint(lib):
    import pytest

    from wirestudio.kicad.pcb import generate_kicad_pcb, pcb_status
    if not pcb_status()["available"]:
        pytest.skip("KiCad footprint libraries not installed")
    text = generate_kicad_pcb(_harness(lib), lib)
    assert "PinHeader_1x08_P2.54mm_Vertical" in text
    assert "JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical" in text

def test_build_netlist_binds_board_pins(lib):
    """Board pins join the nets their roles name, under the board's ref, so
    the PCB can bind the module's pads: GPIO13 -> IO13 on GPIO_GPIO13, the
    i2c0 bus on IO21/IO22, 3V3 on VDD, GND on GND."""
    nets = {n.name: n for n in build_netlist(_design("garage-motion"), lib)}
    board = {(p.pin_role, name) for name, n in nets.items() for p in n.pads if p.ref == "M1"}
    assert ("IO13", "GPIO_GPIO13") in board
    assert ("IO21", "BUS_i2c0_SDA") in board and ("IO22", "BUS_i2c0_SCL") in board
    assert ("VDD", "+3V3") in board
    assert ("GND", "GND") in board
    assert all(p.component_id == "__board__" for n in nets.values() for p in n.pads if p.ref == "M1")
    assert not any(p.ref == "M1" for p in nets["+5V"].pads)  # the module has no 5V pin


def test_build_netlist_lands_expander_pins_on_the_expanders_pads(lib):
    """An expander_pin target joins the expander's own GPIO: MCP23017 pin
    4 is GPA4 and pin 8 is GPB0, from the card's kicad.expander_pins."""
    nets = {n.name: {(p.component_id, p.pin_role) for p in n.pads}
            for n in build_netlist(_design("securitypanel"), lib)}
    assert ("mcp_hub", "GPA4") in nets["mcp_hub_GP4"]
    assert ("mcp_hub", "GPB0") in nets["mcp_hub_GP8"]
    assert all(len(pads) == 2 for name, pads in nets.items() if name.startswith("mcp_hub_GP"))


def test_build_netlist_lands_a_74hc595_output_on_its_q_pin(lib):
    nets = {n.name: {(p.component_id, p.pin_role) for p in n.pads}
            for n in build_netlist(_design("output-hub"), lib)}
    assert ("shift1", "QA") in nets["shift1_GP0"]
