"""Tests for the parametric OpenSCAD enclosure generator (0.8 v1).

The generator emits text -- there's no easy way to validate the output
short of running OpenSCAD itself, so we lean on substring assertions
that pin the meaningful invariants:

  - tunables block lives at the top with the documented variable names
  - PCB length / width / thickness from the board YAML appear verbatim
  - every mount hole's [x, y] lands in the standoffs holes list
  - every port renders a `translate(...) cube(...)` pair on the right
    wall (short_a -> x=0 face, short_b -> outer_l face, etc.)
  - boards without enclosure metadata raise EnclosureUnavailable
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from studio.enclosure import EnclosureUnavailable, generate_scad
from studio.library import default_library
from studio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


@pytest.fixture
def lib():
    return default_library()


def _design(name: str) -> Design:
    return Design.model_validate(json.loads((EXAMPLES_DIR / f"{name}.json").read_text()))


def test_emits_tunables_block_at_top(lib):
    scad = generate_scad(_design("garage-motion"), lib)
    head = scad[: scad.find("// === Geometry ===")]
    for tunable in ("wall = ", "floor = ", "clearance = ", "standoff_h = ",
                    "standoff_d = ", "standoff_hole = ", "port_clearance = "):
        assert tunable in head, f"missing tunable {tunable!r} in header"


def test_pcb_dimensions_appear_verbatim(lib):
    scad = generate_scad(_design("garage-motion"), lib)  # esp32-devkitc-v4
    assert "board_l = 54.4;" in scad
    assert "board_w = 28.6;" in scad
    assert "board_t = 1.6;" in scad


def test_mount_holes_render_as_xy_pairs(lib):
    scad = generate_scad(_design("garage-motion"), lib)
    # esp32-devkitc-v4 has two holes at (3.0, 14.3) and (51.4, 14.3).
    assert "[3.0, 14.3]" in scad
    assert "[51.4, 14.3]" in scad


def test_usb_cutout_pierces_short_a_wall(lib):
    """USB micro on short_a means the cutout sits at x=0 (translate
    starts at -1) and the cube extends `wall + 2` along x."""
    scad = generate_scad(_design("garage-motion"), lib)
    section = scad[scad.find("module shell()"):]
    assert "// usb_micro on short_a" in section
    # Single line (the next translate after the comment) starts with -1.
    after = section[section.find("// usb_micro on short_a"):]
    next_translate = after.split("translate(", 1)[1]
    assert next_translate.startswith("[-1,"), next_translate[:80]


def test_short_b_port_translates_from_outer_length(lib):
    """TTGO LoRa32 V1 has an SMA jack on short_b -- the cutout's near
    face should sit at outer_l - wall - 1, not at -1."""
    scad = generate_scad(_design("ttgo-lora32"), lib)
    section = scad[scad.find("// sma on short_b"):]
    next_translate = section.split("translate(", 1)[1]
    assert next_translate.startswith("[outer_l - wall - 1,"), next_translate[:80]


def test_multi_temp_d1_mini_has_four_standoffs(lib):
    """The D1 Mini board metadata declares 4 mount holes -- each lands
    in the standoffs holes list."""
    scad = generate_scad(_design("multi-temp"), lib)
    holes_block = scad[scad.find("holes = ["):scad.find("];", scad.find("holes = ["))]
    coords = [line.strip().rstrip(",") for line in holes_block.splitlines()
              if line.strip().startswith("[")]
    assert len(coords) == 4, holes_block


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


def test_output_is_self_contained_openscad(lib):
    """Sanity: the generated text uses only OpenSCAD primitives we
    expect (cube, cylinder, translate, difference, module). No external
    use<>/include<>; no raw library lookup."""
    scad = generate_scad(_design("garage-motion"), lib)
    assert "include <" not in scad
    assert "use <" not in scad
    for prim in ("module shell()", "module standoffs()", "shell();",
                  "standoffs();", "cube(", "cylinder(", "difference()", "translate("):
        assert prim in scad


def test_d1_mini_round_trip(lib):
    """Different board family + dimensions: D1 Mini (34.2 x 25.6, 4 holes)."""
    scad = generate_scad(_design("wasserpir"), lib)
    assert "board_l = 34.2;" in scad
    assert "board_w = 25.6;" in scad
    holes_block = scad[scad.find("holes = ["):scad.find("];", scad.find("holes = ["))]
    coord_lines = [line.strip() for line in holes_block.splitlines()
                    if line.strip().startswith("[")]
    assert len(coord_lines) == 4
