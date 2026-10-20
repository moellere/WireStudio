"""Tests for the `.kicad_sch` writer and the s-expression tooling under it.

The geometry is checked for real by `scripts/check_sch.py`, which has
kicad-cli read the netlist back from the drawn sheet; CI runs it with
the KiCad libraries. Here: the transform the drawing rests on, the
junction rule, the symbol flattening, the writer's grammar on a tiny
in-repo library (so no KiCad install is needed), and the layout model.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.kicad import schematic as S
from wirestudio.kicad.symbol_parser import (
    QStr, dump_sexpr, embed_symbol, flatten_symbol, load_symbol_trees, parse_sexpr,
    symbol_bbox, symbol_pins,
)
from wirestudio.library import SchematicLayout, Subcircuit, default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"

# Just enough of a KiCad library for the writer: a resistor, a two-pin
# header, the ground and 5 V symbols and the flag, in KiCad's own shapes.
_LIB = '''(kicad_symbol_lib (version 20231120) (generator "test")
  (symbol "R" (pin_numbers hide) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
    (property "Reference" "R" (at 2.032 0 90) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 0 90) (effects (font (size 1.27 1.27))))
    (property "Footprint" "" (at -1.778 0 90) (effects (font (size 1.27 1.27)) (hide yes)))
    (symbol "R_0_1" (rectangle (start -1.016 -2.54) (end 1.016 2.54) (stroke (width 0.254) (type default)) (fill (type none))))
    (symbol "R_1_1"
      (pin passive line (at 0 3.81 270) (length 1.27) (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 0 -3.81 90) (length 1.27) (name "~" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "R_Small" (extends "R") (property "Value" "R_Small" (at 0 0 90) (effects (font (size 1.27 1.27)))))
  (symbol "Conn_01x02" (pin_names (offset 1.016) hide) (exclude_from_sim no) (in_bom yes) (on_board yes)
    (property "Reference" "J" (at 0 2.54 0) (effects (font (size 1.27 1.27))))
    (property "Value" "Conn_01x02" (at 0 -5.08 0) (effects (font (size 1.27 1.27))))
    (symbol "Conn_01x02_1_1"
      (rectangle (start -1.27 1.27) (end 1.27 -3.81) (stroke (width 0.254) (type default)) (fill (type background)))
      (pin passive line (at -5.08 0 0) (length 3.81) (name "Pin_1" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at -5.08 -2.54 0) (length 3.81) (name "Pin_2" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))))
  (symbol "Conn_01x03" (pin_names (offset 1.016) hide) (exclude_from_sim no) (in_bom yes) (on_board yes)
    (property "Reference" "J" (at 0 5.08 0) (effects (font (size 1.27 1.27))))
    (property "Value" "Conn_01x03" (at 0 -5.08 0) (effects (font (size 1.27 1.27))))
    (symbol "Conn_01x03_1_1"
      (rectangle (start -1.27 3.81) (end 1.27 -3.81) (stroke (width 0.254) (type default)) (fill (type background)))
      (pin passive line (at -5.08 2.54 0) (length 3.81) (name "Pin_1" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at -5.08 0 0) (length 3.81) (name "Pin_2" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))
      (pin passive line (at -5.08 -2.54 0) (length 3.81) (name "Pin_3" (effects (font (size 1.27 1.27)))) (number "3" (effects (font (size 1.27 1.27)))))))
  (symbol "GND" (power) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
    (property "Reference" "#PWR" (at 0 -6.35 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Value" "GND" (at 0 -3.81 0) (effects (font (size 1.27 1.27))))
    (symbol "GND_1_1" (pin power_in line (at 0 0 270) (length 0) (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))))
  (symbol "+5V" (power) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
    (property "Reference" "#PWR" (at 0 -3.81 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Value" "+5V" (at 0 3.556 0) (effects (font (size 1.27 1.27))))
    (symbol "+5V_1_1" (pin power_in line (at 0 0 90) (length 0) (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))))
  (symbol "PWR_FLAG" (power) (pin_names (offset 0)) (exclude_from_sim no) (in_bom yes) (on_board yes)
    (property "Reference" "#FLG" (at 0 1.905 0) (effects (font (size 1.27 1.27)) (hide yes)))
    (property "Value" "PWR_FLAG" (at 0 3.81 0) (effects (font (size 1.27 1.27))))
    (symbol "PWR_FLAG_1_1" (pin power_out line (at 0 0 90) (length 0) (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27))))))))
'''


@pytest.fixture
def sym_dir(tmp_path: Path) -> Path:
    for lib in ("Device", "Connector_Generic", "power"):
        (tmp_path / f"{lib}.kicad_sym").write_text(_LIB)
    return tmp_path


# --- s-expressions ----------------------------------------------------------

def test_dump_round_trips_quoting_and_order():
    text = '(a "q" 1 (b (c "x y") hide) 2.5)'
    tree = parse_sexpr(text)
    assert isinstance(tree[1], QStr) and tree[1] == "q"
    again = parse_sexpr(dump_sexpr(tree))
    assert again == tree
    assert '"x y"' in dump_sexpr(tree) and " hide" in dump_sexpr(tree)


def test_symbol_pins_and_bbox_read_geometry():
    tree = parse_sexpr(_LIB)
    r = next(el for el in tree[1:] if isinstance(el, list) and el[1] == "R")
    pins = symbol_pins(r)
    assert [(p.number, p.x, p.y, p.angle, p.length) for p in pins] == [
        ("1", 0.0, 3.81, 270, 1.27), ("2", 0.0, -3.81, 90, 1.27),
    ]
    assert symbol_bbox(r) == (-1.016, -3.81, 1.016, 3.81)


def test_flatten_resolves_extends_and_renames_units(sym_dir):
    trees = load_symbol_trees(sym_dir / "Device.kicad_sym")
    small = flatten_symbol(trees, "R_Small")
    assert small[1] == "R_Small"
    units = [c[1] for c in small[2:] if isinstance(c, list) and c[0] == "symbol"]
    assert units == ["R_Small_0_1", "R_Small_1_1"]
    values = [c[2] for c in small[2:] if isinstance(c, list) and c[0] == "property" and c[1] == "Value"]
    assert values == ["R_Small"]
    assert not any(isinstance(c, list) and c[0] == "extends" for c in small)
    assert symbol_pins(small) == symbol_pins(trees["R"])
    assert embed_symbol(trees, "R_Small", "Device")[1] == "Device:R_Small"


# --- geometry ---------------------------------------------------------------

@pytest.mark.parametrize("rot,mirror,want", [
    (0, None, (0.0, -3.81)),       # pin 1 of a resistor sits above the anchor
    (90, None, (-3.81, 0.0)),      # turned a quarter counter-clockwise: to the left
    (180, None, (0.0, 3.81)),
    (270, None, (3.81, 0.0)),
    (0, "x", (0.0, 3.81)),         # mirrored top for bottom
])
def test_xform_turns_a_resistor_the_way_kicad_does(rot, mirror, want):
    assert S._xform(0.0, 3.81, rot, mirror) == want


def test_power_rot_points_the_body_along_the_pin():
    assert S._power_rot("GND", 0, 1) == 0      # hanging down
    assert S._power_rot("GND", 0, -1) == 180
    assert S._power_rot("+5V", 0, -1) == 0     # standing up
    assert S._power_rot("+5V", 0, 1) == 180


def test_junctions_where_three_meet_or_a_wire_ends_inside_another():
    sheet = S.Sheet(design_id="t", title="t")
    sheet.polyline([(0.0, 0.0), (10.16, 0.0)])
    sheet.wire((5.08, 0.0), (5.08, 5.08))              # T onto the middle
    sheet.wire((10.16, 0.0), (10.16, 5.08))            # a corner: two ends only
    sheet.wire((0.0, 0.0), (0.0, 5.08))
    sheet.wire((0.0, 0.0), (0.0, -5.08))               # three ends
    S._add_junctions(sheet)
    assert sheet.junctions == [(0.0, 0.0), (5.08, 0.0)]


def test_duplicate_stubs_are_drawn_once():
    sheet = S.Sheet(design_id="t", title="t")
    sheet.wire((0.0, 0.0), (0.0, 2.54))
    sheet.wire((0.0, 0.0), (0.0, 2.54))
    sheet.wire((0.0, 2.54), (0.0, 0.0))
    assert len(sheet.wires) == 1


# --- the writer on the tiny library ------------------------------------------

def _two_resistor_design() -> Design:
    """A design the tiny library can draw: a board the test library lacks
    is left out, so the sheet is peripherals only."""
    return Design.model_validate({
        "schema_version": "0.1",
        "id": "tiny",
        "name": "Tiny",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [
            {"id": "pir1", "library_id": "hc-sr501", "label": "PIR"},
        ],
        "buses": [],
        "connections": [
            {"component_id": "pir1", "pin_role": "VCC", "target": {"kind": "rail", "rail": "5V"}},
            {"component_id": "pir1", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
            {"component_id": "pir1", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "GPIO13"}},
        ],
    })


def test_sheet_without_libraries_is_unavailable(monkeypatch):
    monkeypatch.setattr(S, "default_symbol_dirs", lambda: [])
    assert S.sch_status()["available"] is False
    with pytest.raises(S.SchematicUnavailable):
        S.build_sheet(_two_resistor_design(), default_library())


def test_writer_emits_kicad_grammar_labels_flags_and_no_connects(sym_dir, monkeypatch):
    lib = default_library()
    # The RF_Module board symbol is not in the tiny library: a symbol the
    # library lacks is a clear error, not a silent omission.
    with pytest.raises(FileNotFoundError, match="RF_Module"):
        S.build_sheet(_two_resistor_design(), lib, symbol_dir=sym_dir)

    # A board file the tiny library can draw.
    boards = {b.id: b for b in lib.list_boards()}
    monkeypatch.setattr(lib, "board", lambda bid: boards[bid].model_copy(update={"kicad": None}))
    sheet = S.build_sheet(_two_resistor_design(), lib, symbol_dir=sym_dir)
    text = S.render_sheet(sheet)
    tree = parse_sexpr(text)
    assert tree[0] == "kicad_sch"
    heads = [c[0] for c in tree[1:] if isinstance(c, list)]
    # A sideways header: the rails are labels too, not power symbols.
    labels = {c[1] for c in tree[1:] if isinstance(c, list) and c[0] == "global_label"}
    assert labels == {"GPIO_GPIO13", "+5V", "GND"}
    assert heads.count("wire") == 3 + 2            # three stubs, two flag ties
    assert heads.count("no_connect") == 0
    embedded = {c[1] for c in next(c for c in tree[1:] if c[0] == "lib_symbols")[1:]}
    assert embedded == {"Connector_Generic:Conn_01x03", "power:GND", "power:+5V", "power:PWR_FLAG"}
    refs = [c for c in tree[1:] if isinstance(c, list) and c[0] == "symbol"]
    assert len(refs) == 1 + 2 + 2                   # U1, two rail symbols, two flags
    assert text == S.render_sheet(S.build_sheet(_two_resistor_design(), lib, symbol_dir=sym_dir))  # deterministic


def test_expected_connectivity_groups_the_netlist(sym_dir, monkeypatch):
    lib = default_library()
    boards = {b.id: b for b in lib.list_boards()}
    monkeypatch.setattr(lib, "board", lambda bid: boards[bid].model_copy(update={"kicad": None}))
    sheet = S.build_sheet(_two_resistor_design(), lib, symbol_dir=sym_dir)
    assert sheet.pin_nets  # every connected pin resolved
    assert all(isinstance(g, frozenset) for g in S.expected_connectivity(sheet))


# --- layout model ------------------------------------------------------------

def test_layout_must_name_real_parts():
    with pytest.raises(ValueError, match="unknown parts"):
        Subcircuit.model_validate({
            "parts": [{"id": "r1", "ref_prefix": "R",
                       "kicad": {"symbol_lib": "Device", "symbol": "R"}, "pins": {"1": "a", "2": "b"}}],
            "schematic": {"parts": {"r2": {"at": [0, 0]}}},
        })
    layout = SchematicLayout.model_validate({"parts": {"r1": {"at": [2, 3], "rot": 90, "mirror": "x"}},
                                             "wires": [[[0, 0], [2, 0]]], "nodes": {"a": [{"at": [0, 0]}]}})
    assert layout.parts["r1"].at == (2.0, 3.0)


def test_every_subcircuit_layout_covers_every_part():
    subs = {c.id: c.subcircuit for c in default_library().list_components() if c.subcircuit is not None}
    assert len(subs) == 7
    for cid, sub in subs.items():
        assert sub.schematic is not None, cid
        assert set(sub.schematic.parts) == {p.id for p in sub.parts}, cid


# --- API ----------------------------------------------------------------------

def test_sch_routes(monkeypatch):
    import wirestudio.api.app as A

    client = TestClient(create_app())
    assert set(client.get("/design/kicad/sch/status").json()) == {"available", "symbol_dir", "reason"}
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    monkeypatch.setattr(A, "generate_kicad_sch", lambda d, lib: "(kicad_sch (version 20231120))\n")
    r = client.post("/design/kicad/sch", json=design)
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="garage-motion-v1.kicad_sch"'
    assert r.text.startswith("(kicad_sch")

    def unavailable(d, lib):
        raise S.SchematicUnavailable("symbol libraries not found (set KICAD8_SYMBOL_DIR)")
    monkeypatch.setattr(A, "generate_kicad_sch", unavailable)
    assert client.post("/design/kicad/sch", json=design).status_code == 503
    assert client.post("/design/kicad/sch", json={"id": "broken"}).status_code == 422


# --- shared internal nodes ----------------------------------------------------

_DIVIDER = {
    "parts": [
        {"id": "r_top", "ref_prefix": "R", "kicad": {"symbol_lib": "Device", "symbol": "R", "value": "10k"},
         "pins": {"1": "vsense", "2": "IN"}},
        {"id": "r_bottom", "ref_prefix": "R", "kicad": {"symbol_lib": "Device", "symbol": "R", "value": "10k"},
         "pins": {"1": "IN", "2": "GND"}},
    ],
    "schematic": {
        "parts": {"r_top": {"at": [0, 0]}, "r_bottom": {"at": [0, 10]}},
        "wires": [[[0, -5], [0, -3]], [[0, 3], [0, 7]], [[0, 13], [0, 15]]],
        "nodes": {"IN": [{"at": [0, 5]}], "GND": [{"at": [0, 15], "kind": "power"}],
                  "vsense": [{"at": [0, -5], "rot": 90}]},
    },
}


def _divider_design(tap: bool) -> Design:
    comps = [{"id": "div", "library_id": "voltage_divider", "label": "Divider"}]
    conns = [
        {"component_id": "div", "pin_role": "IN", "target": {"kind": "rail", "rail": "5V"}},
        {"component_id": "div", "pin_role": "GND", "target": {"kind": "rail", "rail": "GND"}},
    ]
    if tap:
        comps.append({"id": "tap", "library_id": "connector_1x03", "label": "Tap", "params": {"family": "pin_header"}})
        conns.append({"component_id": "tap", "pin_role": "P1",
                      "target": {"kind": "net", "component_id": "div", "net": "vsense"}})
    return Design.model_validate({
        "schema_version": "0.1", "id": "div", "name": "Divider",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": comps, "buses": [], "connections": conns,
    })


def _divider_library(monkeypatch, sub: dict):
    lib = default_library()
    boards = {b.id: b for b in lib.list_boards()}
    monkeypatch.setattr(lib, "board", lambda bid: boards[bid].model_copy(update={"kicad": None}))
    real = lib.component
    divider = real("voltage_divider").model_copy(update={"subcircuit": Subcircuit.model_validate(sub)})
    monkeypatch.setattr(lib, "component", lambda cid: divider if cid == "voltage_divider" else real(cid))
    return lib


def _labels(sheet: S.Sheet) -> list[str]:
    return [name for name, *_ in sheet.labels]


def test_internal_node_port_is_drawn_only_when_shared(sym_dir, monkeypatch):
    lib = _divider_library(monkeypatch, _DIVIDER)
    alone = S.build_sheet(_divider_design(tap=False), lib, symbol_dir=sym_dir)
    assert "div_vsense" not in _labels(alone)
    assert not alone.notes

    tapped = S.build_sheet(_divider_design(tap=True), lib, symbol_dir=sym_dir)
    assert _labels(tapped).count("div_vsense") == 2      # the layout's port and the tap's pin
    assert not tapped.notes
    group = next(g for g in S.expected_connectivity(tapped) if ("R1", "1") in g)
    assert len(group) == 2                               # the divider's top pin and the tap's


def test_shared_node_without_a_port_is_labelled_at_a_pin(sym_dir, monkeypatch):
    sub = {**_DIVIDER, "schematic": {**_DIVIDER["schematic"], "nodes": {
        k: v for k, v in _DIVIDER["schematic"]["nodes"].items() if k != "vsense"}}}
    lib = _divider_library(monkeypatch, sub)
    sheet = S.build_sheet(_divider_design(tap=True), lib, symbol_dir=sym_dir)
    assert _labels(sheet).count("div_vsense") == 2
    r1 = next(s for s in sheet.symbols if s.ref == "R1")
    pin1 = next(p for p in r1.pins if p.number == "1")
    assert (("div_vsense",) + r1.pin_at(pin1)) in {lab[:3] for lab in sheet.labels}
    assert any("no port" in n and "R1.1" in n for n in sheet.notes)
