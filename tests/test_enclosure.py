"""Tests for the YAPP_Box enclosure generator.

The generator emits text; `scripts/check_enclosures.py` renders it
through OpenSCAD. These pin the invariants in the text:

  - the tunables block lives at the top with the documented names
  - PCB length / width / thickness from the board YAML appear verbatim
  - every mount hole lands in `pcbStands`
  - every port lands in the YAPP cutout list for its wall (short_a ->
    back, short_b -> front, long_a -> left, long_b -> right)
  - the pinned generator is inlined, so the file needs no library
  - boards without enclosure metadata raise EnclosureUnavailable
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirestudio.enclosure import EnclosureUnavailable, generate_scad
from wirestudio.enclosure.openscad import YAPP_REF, yapp_generator
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


@pytest.fixture
def lib():
    return default_library()


def _design(name: str) -> Design:
    return Design.model_validate(json.loads((EXAMPLES_DIR / f"{name}.json").read_text()))


def _block(scad: str, name: str) -> str:
    start = scad.index(f"\n{name} = [")
    return scad[start:scad.index("\n];", start)]


def test_emits_tunables_block_at_top(lib):
    scad = generate_scad(_design("garage-motion"), lib)
    head = scad[: scad.find("// === YAPP_Box generator ===")]
    for tunable in ("wall = ", "floor = ", "lid_t = ", "clearance = ", "standoff_h = ",
                    "standoff_d = ", "standoff_hole = ", "port_clearance = ",
                    "component_h = ", "ridge_h = "):
        assert tunable in head, f"missing tunable {tunable!r} in header"


def test_pcb_dimensions_appear_verbatim(lib):
    scad = generate_scad(_design("garage-motion"), lib)  # esp32-devkitc-v4
    assert "board_l = 54.4;" in scad
    assert "board_w = 28.6;" in scad
    assert "board_t = 1.6;" in scad
    assert "pcbLength = board_l;" in scad


def test_mount_holes_become_base_standoffs(lib):
    stands = _block(generate_scad(_design("garage-motion"), lib), "pcbStands")
    # esp32-devkitc-v4 has two holes at (3.0, 14.3) and (51.4, 14.3).
    assert "[3.0, 14.3, yappBaseOnly, yappHole, yappNoFillet]" in stands
    assert "[51.4, 14.3, yappBaseOnly, yappHole, yappNoFillet]" in stands


def test_ports_land_on_their_walls_centred_in_pcb_coordinates(lib):
    scad = generate_scad(_design("ttgo-lora32"), lib)
    back = _block(scad, "cutoutsBack")
    front = _block(scad, "cutoutsFront")
    assert "// usb_micro" in back and "// sma" in front
    assert ("[12.75 + 7.0/2, 0.0, 7.0 + 2*port_clearance, 7.0 + 2*port_clearance, 0, "
            "yappRectangle, yappCenter, yappCoordPCB]") in front
    assert "// none" in _block(scad, "cutoutsLeft")


def test_d1_mini_has_four_standoffs(lib):
    stands = _block(generate_scad(_design("multi-temp"), lib), "pcbStands")
    assert stands.count("yappBaseOnly") == 4


def test_unknown_board_raises_enclosure_unavailable(lib):
    """ESP-01S doesn't carry enclosure metadata (it plugs into a host
    PCB) -- the generator should raise cleanly, not crash."""
    design = Design.model_validate(json.loads((EXAMPLES_DIR / "bluesonoff.json").read_text()))
    with pytest.raises(EnclosureUnavailable) as exc:
        generate_scad(design, lib)
    assert "esp01_1m" in str(exc.value)


def test_design_id_and_board_name_appear_in_header(lib):
    scad = generate_scad(_design("garage-motion"), lib)
    assert "design: garage-motion-v1" in scad
    assert "Board: ESP32-DevKitC-V4" in scad


def test_output_inlines_the_pinned_generator(lib):
    """No include<>/use<>: the file renders on a machine without YAPP,
    which is what print-warden and a plain download need. The YAPP
    parameters follow the generator so their assignments win."""
    scad = generate_scad(_design("garage-motion"), lib)
    assert "include <" not in scad
    assert "use <" not in scad
    assert yapp_generator() in scad
    assert YAPP_REF[:12] in scad
    assert scad.index("module YAPPgenerate()") < scad.index("wallThickness = wall;")
    assert scad.rstrip().endswith("YAPPgenerate();")


def test_base_and_lid_heights_clear_the_tallest_part(lib):
    scad = generate_scad(_design("garage-motion"), lib)
    assert "base_wall_h = standoff_h + board_t + component_h + 1 - lid_wall_h;" in scad
    assert "ridge = max(ridge_h, 1.8 * wall);" in scad
    assert "printLidShell = true;" in scad
    assert "[shell_l/2, 5, yappLeft, yappRight, yappCenter]" in _block(scad, "snapJoins")
