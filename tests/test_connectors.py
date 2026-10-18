"""The connector family beyond the three sizes that shipped with #300, the
`J` designator, and the netlist golden. Regenerate the golden with

    python -m wirestudio.kicad.netlist wirestudio/examples/actuator-harness.json \\
        > tests/golden/actuator-harness.net.txt
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from wirestudio.kicad.netlist import assign_refs, format_netlist
from wirestudio.library import component_footprint, default_library
from wirestudio.library.check import check_component_yaml
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLED = REPO_ROOT / "wirestudio" / "library" / "components"
EXAMPLE = REPO_ROOT / "wirestudio" / "examples" / "actuator-harness.json"

SIZES = {"connector_1x02": 2, "connector_1x05": 5, "connector_1x06": 6, "connector_1x07": 7,
         "connector_2x05_idc": 10}


@pytest.fixture
def lib():
    return default_library()


@pytest.fixture
def harness() -> Design:
    return Design.model_validate(json.loads(EXAMPLE.read_text()))


@pytest.mark.parametrize("lib_id,count", sorted(SIZES.items()))
def test_every_size_is_all_passthrough_and_binds_positionally(lib, lib_id, count):
    comp = lib.component(lib_id)
    assert [p.role for p in comp.electrical.pins] == [f"P{i}" for i in range(1, count + 1)]
    assert {p.kind for p in comp.electrical.pins} == {"passthrough"}
    assert comp.kicad.symbol_lib == "Connector_Generic"
    assert check_component_yaml((BUNDLED / f"{lib_id}.yaml").read_text(), lib).ok


@pytest.mark.parametrize("lib_id", [i for i in SIZES if i != "connector_2x05_idc"])
def test_single_row_sizes_name_a_footprint_per_family(lib, lib_id):
    comp = lib.component(lib_id)
    n = SIZES[lib_id]
    seen = set()
    for family in comp.params_schema["family"]["enum"]:
        fp = component_footprint(comp, {"family": family})
        assert ":" in fp and f"1x{n:02d}" in fp, (lib_id, family, fp)
        seen.add(fp)
    assert len(seen) == 4


def test_idc_header_has_one_footprint_and_no_family(lib):
    comp = lib.component("connector_2x05_idc")
    assert comp.params_schema == {}
    assert component_footprint(comp, {}) == "Connector_IDC:IDC-Header_2x05_P2.54mm_Vertical"
    assert comp.kicad.symbol == "Conn_02x05_Odd_Even"


def test_connectors_take_the_j_designator(lib, harness):
    refs = assign_refs(harness, lib)
    connectors = [c.id for c in harness.components
                  if lib.component(c.library_id).category == "connector"]
    assert len(connectors) == 2 and "harness" in connectors
    # The bridge's own motor terminal keeps J1; the connectors follow it.
    assert refs["bridge.j_motor"] == "J1"
    assert {refs[c] for c in connectors} == {"J2", "J3"}


def test_actuator_harness_netlist_matches_golden(lib, harness, golden_dir):
    assert format_netlist(harness, lib) == (golden_dir / "actuator-harness.net.txt").read_text()


def test_component_check_renders_every_family(lib, tmp_path, monkeypatch):
    """A `family` value whose footprint does not exist fails the check even
    when the default family's does."""
    fp_dir = tmp_path / "fp"
    for lib_name, name in (
        ("Connector_JST", "JST_XH_B4B-XH-A_1x04_P2.50mm_Vertical"),
        ("Connector_JST", "JST_PH_B4B-PH-K_1x04_P2.00mm_Vertical"),
        ("Connector_PinHeader_2.54mm", "PinHeader_1x04_P2.54mm_Vertical"),
    ):
        (fp_dir / f"{lib_name}.pretty").mkdir(parents=True, exist_ok=True)
        (fp_dir / f"{lib_name}.pretty" / f"{name}.kicad_mod").write_text("(footprint)")
    monkeypatch.setenv("KICAD8_FOOTPRINT_DIR", str(fp_dir))
    report = check_component_yaml((BUNDLED / "connector_1x04.yaml").read_text(), lib)
    assert any("MKDS-1,5-4_1x04" in e and "not in the KiCad footprint library" in e
               for e in report.errors), report.errors
