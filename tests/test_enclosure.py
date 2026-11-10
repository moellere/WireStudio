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
    scad = generate_scad(_design("access-panel"), lib)
    head = scad[: scad.find("// === YAPP_Box generator ===")]
    for tunable in ("wall = ", "floor = ", "lid_t = ", "clearance = ", "standoff_h = ",
                    "standoff_d = ", "standoff_hole = ", "port_clearance = ",
                    "component_h = ", "ridge_h = "):
        assert tunable in head, f"missing tunable {tunable!r} in header"


def test_pcb_dimensions_appear_verbatim(lib):
    scad = generate_scad(_design("access-panel"), lib)  # esp32-devkitc-v4
    assert "board_l = 54.4;" in scad
    assert "board_w = 28.6;" in scad
    assert "board_t = 1.6;" in scad
    assert "pcbLength = board_l;" in scad


def test_mount_holes_become_base_standoffs(lib):
    stands = _block(generate_scad(_design("access-panel"), lib), "pcbStands")
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
    scad = generate_scad(_design("access-panel"), lib)
    assert "design: access-panel\n" in scad
    assert "Board: ESP32-DevKitC-V4" in scad


def test_output_inlines_the_pinned_generator(lib):
    """No include<>/use<>: the file renders on a machine without YAPP,
    which is what print-warden and a plain download need. The YAPP
    parameters follow the generator so their assignments win."""
    scad = generate_scad(_design("access-panel"), lib)
    assert "include <" not in scad
    assert "use <" not in scad
    assert yapp_generator() in scad
    assert YAPP_REF[:12] in scad
    assert scad.index("module YAPPgenerate()") < scad.index("wallThickness = wall;")
    assert scad.rstrip().endswith("YAPPgenerate();")


def test_base_and_lid_heights_clear_the_tallest_part(lib):
    scad = generate_scad(_design("access-panel"), lib)
    assert "base_wall_h = max(ridge, standoff_h + board_t + component_h + 1 - lid_wall_h);" in scad
    assert "ridge = max(ridge_h, 1.8 * wall);" in scad
    assert "printLidShell = true;" in scad
    assert "[shell_l/2, 5, yappLeft, yappRight, yappCenter]" in _block(scad, "snapJoins")


# --- Panel layout: parts with `enclosure:` metadata --------------------

def test_designs_without_panel_parts_keep_the_board_only_shell(lib):
    scad = generate_scad(_design("access-panel"), lib)
    assert '"Main", board_l, board_w' in scad
    assert "cavity_l" not in scad


def test_wall_panel_places_every_part(lib):
    scad = generate_scad(_design("wall-panel"), lib)
    pcbs = _block(scad, "pcb")
    assert '["Main", cavity_l, cavity_w' in pcbs
    for name in ('"board"', '"pir"', '"climate"', '"oled-knob-13-1"'):
        assert name in pcbs
    # Lid parts hang from the lid: negative standoff.
    assert '"pir", 24.3, 32.3' in pcbs and ", -3.5, " in pcbs
    assert "(face down), wall mount" in scad


def test_lid_features_cut_the_lid(lib):
    lid = _block(generate_scad(_design("wall-panel"), lib), "cutoutsLid")
    # PIR dome, encoder shaft, and the OLED bezel's taper: four steps
    # from the 17.6 x 32.6 window (turned: its width runs along Y) out to
    # 2.0 more each side at the face, shallowest widest.
    assert "11.8, yappCircle" in lid and '"pir"' in lid
    assert "4.5, yappCircle" in lid
    assert "18.6, 33.6, 0, yappRectangle, lid_t*0.8," in lid
    assert "21.6, 36.6, 0, yappRectangle, lid_t*0.2," in lid
    # Two flexure keys: three slots and a thinned hinge each.
    assert lid.count("lid_t/2") == 2


def test_lid_posts_hang_from_the_lid(lib):
    stands = _block(generate_scad(_design("wall-panel"), lib), "pcbStands")
    # Module posts, PIR posts, and a 0.6 nub under each key.
    assert stands.count("yappLidOnly") == 4 + 2 + 2
    assert stands.count("yappBaseOnly") == 1          # the DHT post
    assert "base_wall_h + lid_wall_h - 4.7 - 1.5" in stands
    nubs = [ln for ln in stands.splitlines() if ", -1, 3, 0.1, " in ln]
    assert len(nubs) == 2 and all("- 0.6 - 1.5" in ln for ln in nubs)


def test_a_key_too_close_to_its_switch_gets_no_nub(lib):
    data = json.loads((EXAMPLES_DIR / "wall-panel.json").read_text())
    design = Design.model_validate(data)
    module = lib.module("oled-knob-13")
    shallow = module.enclosure.model_copy(update={"lid_gap_mm": 4.2})
    lib._modules["oled-knob-13"] = module.model_copy(update={"enclosure": shallow})
    try:
        stands = _block(generate_scad(design, lib), "pcbStands")
    finally:
        lib._modules["oled-knob-13"] = module
    assert ", -1, 3, 0.1, " not in stands


def test_face_down_board_turns_its_ports_and_gets_a_cradle(lib):
    scad = generate_scad(_design("wall-panel"), lib)
    back = _block(scad, "cutoutsBack")
    assert back.count("// usb_c") == 2
    assert "-(board_t + 1.65)" in back
    assert "module hookBaseInside()" in scad
    assert "standoffHeight = 0;" in scad


def test_wall_mount_adds_keyholes_and_vents_the_dht(lib):
    scad = generate_scad(_design("wall-panel"), lib)
    base = _block(scad, "cutoutsBase")
    assert base.count("4.25, yappCircle") == 2
    assert base.count("10, 4.2, 0, yappRectangle") == 2
    # DHT against the bottom (port) wall and the right wall: slots in both.
    assert "yappCoordBoxInside" in _block(scad, "cutoutsBack")
    assert _block(scad, "cutoutsRight").count("yappCoordBoxInside") > 3


def test_cavity_height_stacks_what_overlaps(lib):
    scad = generate_scad(_design("wall-panel"), lib)
    line = next(ln for ln in scad.splitlines() if ln.startswith("cavity_h = "))
    # The face-down board as wired under the PIR's body; the PIR's and
    # the module's headers hang where the board is not.
    assert "component_h + board_t + underside_h + 3.5 + 1.6 + 6" in line
    assert "component_h + board_t + underside_h + 3.5 + 1.6 + 17" not in line
    assert "component_h + board_t + underside_h + 4.7 + 1.5 + 12" not in line


def test_lid_walls_hold_only_the_lid_parts(lib):
    scad = generate_scad(_design("wall-panel"), lib)
    assert "lid_wall_h = min(max([ridge + 2, 3.5 + 1.6 + 6, 4.7 + 1.5 + 2]), cavity_h - ridge);" in scad


def test_enclosure_options_alone_switch_to_the_panel_layout(lib):
    data = json.loads((EXAMPLES_DIR / "access-panel.json").read_text())
    design = Design.model_validate({**data, "enclosure": {"mount": "wall"}})
    scad = generate_scad(design, lib)
    assert "(face up), wall mount" in scad
    assert _block(scad, "cutoutsBase").count("yappCircle") == 2


def test_oled_bezel_frame_drops_to_the_glass(lib):
    tubes = _block(generate_scad(_design("wall-panel"), lib), "lightTubes")
    # 32.6 along Y (a light tube's length), 1.2 wall, bottom 0.1 over the
    # 3.6 glass, measured from the module PCB 4.7 under the lid.
    assert "32.6, 17.6, 1.2, 3.7, yappRectangle, 0, base_wall_h + lid_wall_h - 4.7" in tubes
