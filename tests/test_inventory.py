"""Local component inventory: store, design cross-check, and API."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
import json

from wirestudio.inventory import check_inventory, entries_from_csv, entries_to_csv
from wirestudio.model import Design
from wirestudio.inventory.store import FileInventoryStore, InventoryEntry


def test_entry_validation():
    with pytest.raises(ValueError):
        InventoryEntry(library_id="bme280", quantity=-1)
    with pytest.raises(ValueError):
        InventoryEntry(library_id="bme280", kind="widget")
    with pytest.raises(ValueError):
        InventoryEntry(library_id="", quantity=1)


def test_file_store_roundtrip(tmp_path):
    path = tmp_path / "inventory.json"
    store = FileInventoryStore(path=path)
    assert store.list() == []
    store.set(InventoryEntry(library_id="bme280", quantity=3, location="bin 1"))
    store.set(InventoryEntry(library_id="ssd1306", quantity=1))
    assert {e.library_id for e in store.list()} == {"bme280", "ssd1306"}
    assert store.get("bme280").quantity == 3
    # Persisted to disk: a fresh store over the same file sees it.
    assert FileInventoryStore(path=path).get("bme280").location == "bin 1"
    assert store.remove("bme280") is True
    assert store.remove("bme280") is False  # idempotent
    assert store.get("bme280") is None


def test_check_inventory_statuses(garage_motion_design, library):
    # garage-motion uses bme280 + hc-sr501. Have one, lack the other.
    report = check_inventory(
        garage_motion_design, library, [InventoryEntry(library_id="bme280", quantity=5)]
    )
    by_id = {ln.library_id: ln for ln in report.lines}
    assert by_id["bme280"].status == "have" and by_id["bme280"].on_hand == 5
    assert by_id["hc-sr501"].status == "need" and by_id["hc-sr501"].on_hand == 0
    assert report.summary["have"] == 1 and report.summary["need"] == 1


def test_check_inventory_partial(garage_motion_design, library):
    # bme280 needs 1; having 0 < needed but >0 elsewhere isn't relevant -- use a
    # part present but short by setting quantity below the design's need.
    report = check_inventory(
        garage_motion_design, library, [InventoryEntry(library_id="bme280", quantity=0)]
    )
    bme = next(ln for ln in report.lines if ln.library_id == "bme280")
    assert bme.status == "need"  # quantity 0 -> need


@pytest.fixture
def client(library, tmp_path) -> TestClient:
    store = FileInventoryStore(path=tmp_path / "inventory.json")
    return TestClient(create_app(library=library, inventory=store))


def test_inventory_crud_endpoints(client):
    assert client.get("/inventory").json() == []
    r = client.put("/inventory/bme280", json={"kind": "component", "quantity": 4, "location": "A1"})
    assert r.status_code == 200 and r.json()["quantity"] == 4
    assert [e["library_id"] for e in client.get("/inventory").json()] == ["bme280"]
    assert client.delete("/inventory/bme280").json() == {"deleted": "bme280"}
    assert client.get("/inventory").json() == []


def test_inventory_endpoint_validation(client):
    # Unknown library id -> 404; negative quantity / bad kind -> 422.
    assert client.put("/inventory/does-not-exist", json={"quantity": 1}).status_code == 404
    assert client.put("/inventory/bme280", json={"quantity": -1}).status_code == 422
    assert client.put("/inventory/bme280", json={"kind": "widget", "quantity": 1}).status_code == 422
    assert client.delete("/inventory/bme280").status_code == 404  # nothing to delete


def test_recommend_inventory_boost(client):
    client.put("/inventory/bme280", json={"quantity": 2})
    matches = client.post(
        "/library/recommend", json={"query": "temperature humidity", "use_inventory": True}
    ).json()["matches"]
    bme = next(m for m in matches if m["library_id"] == "bme280")
    assert bme["on_hand"] == 2 and "have 2" in bme["rationale"]
    # With inventory off, the on-hand boost + rationale are absent.
    off = client.post(
        "/library/recommend", json={"query": "temperature humidity", "use_inventory": False}
    ).json()["matches"]
    assert next(m for m in off if m["library_id"] == "bme280")["on_hand"] == 0


def test_min_quantity_validation():
    with pytest.raises(ValueError):
        InventoryEntry(library_id="bme280", quantity=1, min_quantity=-1)


def test_low_stock_flag():
    assert InventoryEntry(library_id="x", quantity=2, min_quantity=3).low_stock is True
    assert InventoryEntry(library_id="x", quantity=5, min_quantity=3).low_stock is False
    assert InventoryEntry(library_id="x", quantity=0, min_quantity=0).low_stock is False  # no threshold


def test_csv_roundtrip():
    entries = [
        InventoryEntry(library_id="bme280", quantity=3, min_quantity=1, location="A1", note="porch"),
        InventoryEntry(library_id="oled-encoder", kind="module", quantity=1),
    ]
    back = entries_from_csv(entries_to_csv(entries)).entries
    assert [e.library_id for e in back] == ["bme280", "oled-encoder"]
    assert back[0].min_quantity == 1 and back[0].location == "A1" and back[0].note == "porch"
    assert back[1].kind == "module"


def test_csv_bad_row_is_rejected_not_raised():
    # A row that can't validate is reported with its line number and reason,
    # so a bad cell in row 40 doesn't cost the other 62 rows.
    result = entries_from_csv("library_id,quantity\nbme280,-1\nssd1306,2\n")
    assert [e.library_id for e in result.entries] == ["ssd1306"]
    assert len(result.rejected) == 1
    assert result.rejected[0].row == 2
    assert "quantity" in result.rejected[0].reason


def test_set_inventory_low_stock_in_response(client):
    body = client.put("/inventory/bme280", json={"quantity": 1, "min_quantity": 5}).json()
    assert body["min_quantity"] == 5 and body["low_stock"] is True


def test_inventory_csv_export_import(client):
    client.put("/inventory/bme280", json={"quantity": 3, "min_quantity": 1, "location": "A1"})
    csv_text = client.get("/inventory/export.csv").text
    assert csv_text.startswith("library_id,") and "bme280" in csv_text
    client.delete("/inventory/bme280")
    assert client.get("/inventory").json() == []
    assert client.post("/inventory/import", json={"csv": csv_text}).json()["imported"] == 1
    restored = client.get("/inventory").json()[0]
    assert restored["library_id"] == "bme280" and restored["min_quantity"] == 1


def test_inventory_import_reports_unknown_library_id(client):
    r = client.post("/inventory/import", json={"csv": "library_id,quantity\nnot-a-part,2\n"})
    body = r.json()
    assert body["imported"] == 0 and body["updated"] == 0
    assert len(body["rejected"]) == 1
    assert "not-a-part" in body["rejected"][0]["reason"]


# --- discrete parts -------------------------------------------------------

FIXTURE_CSV = Path(__file__).resolve().parent / "fixtures" / "transistor_inventory.csv"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"


def test_part_entry_validation():
    part = InventoryEntry(kind="part", mpn="IRF4905", quantity=5, family="mosfet")
    assert part.key == "part:IRF4905" and part.label == "IRF4905"
    with pytest.raises(ValueError):
        InventoryEntry(kind="part", quantity=1)  # no mpn
    with pytest.raises(ValueError):
        InventoryEntry(kind="part", mpn="X", library_id="bme280")  # both ids
    with pytest.raises(ValueError):
        InventoryEntry(library_id="bme280", mpn="X")  # component carrying an mpn
    with pytest.raises(ValueError):
        InventoryEntry(kind="part", mpn="X", family="sorcery")
    with pytest.raises(ValueError):
        InventoryEntry(kind="part", mpn="X", v_max=-5)


def test_part_key_cannot_shadow_a_library_id(tmp_path):
    # A drawer part happening to be named 'adc' must not overwrite the
    # 'adc' component entry.
    store = FileInventoryStore(path=tmp_path / "inventory.json")
    store.set(InventoryEntry(library_id="adc", quantity=1))
    store.set(InventoryEntry(kind="part", mpn="adc", quantity=99))
    assert store.get("adc").quantity == 1
    assert store.get("part:adc").quantity == 99
    assert len(store.list()) == 2


def test_old_inventory_json_still_loads(tmp_path):
    # Files written before parts existed carry only library_id/kind/quantity.
    path = tmp_path / "inventory.json"
    path.write_text(
        '{"schema_version": "0.1", "entries": ['
        '{"library_id": "bme280", "kind": "component", "quantity": 3, '
        '"min_quantity": 0, "location": "A1", "note": ""}]}'
    )
    entry = FileInventoryStore(path=path).get("bme280")
    assert entry.quantity == 3 and entry.location == "A1"
    assert entry.family == "" and entry.v_max is None


def test_real_drawer_csv_imports_every_row():
    """The 63-part transistor drawer: every row lands, nothing is dropped."""
    result = entries_from_csv(FIXTURE_CSV.read_text())
    # The header is on line 5 -- four rows of summary preamble precede it.
    assert result.header_row == 5
    assert len(result.entries) == 63
    assert sum(e.quantity for e in result.entries) == 720  # matches the sheet
    assert all(e.kind == "part" for e in result.entries)
    # The trailing "Total Inventory, 720" row is reported, not silently kept.
    assert len(result.rejected) == 1
    assert result.rejected[0].reason == "looks like a summary row"
    assert result.rejected[0].row == 69


def test_real_drawer_csv_maps_specs():
    by_mpn = {e.mpn: e for e in entries_from_csv(FIXTURE_CSV.read_text()).entries}
    # P-channel MOSFET: family/polarity normalised, V/A lifted from the note.
    irf = by_mpn["IRF4905"]
    assert irf.family == "mosfet" and irf.polarity == "p"
    assert irf.package == "TO-220" and irf.pinout == "G-D-S"
    assert irf.v_max == 55.0 and irf.i_max == 74.0  # magnitudes; note says -55V, -74A
    assert irf.quantity == 5 and "TO-220 24x5 kit" in irf.location
    # 'BJT Darlington' collapses to the bjt family.
    assert by_mpn["BC517"].family == "bjt" and by_mpn["BC517"].polarity == "npn"
    # A regulator's "Polarity / Type" column isn't a polarity; kept verbatim.
    assert by_mpn["L7805CV"].family == "regulator"
    assert by_mpn["L7805CV"].polarity == "+5 v linear"
    # Every part the hbridge_mosfet subcircuit needs is in this drawer.
    assert {"IRF4905", "IRFZ44N", "2N3904"} <= set(by_mpn)


def test_drawer_csv_roundtrips_through_export():
    entries = entries_from_csv(FIXTURE_CSV.read_text()).entries
    back = entries_from_csv(entries_to_csv(entries))
    assert back.rejected == []
    assert {e.key: e for e in back.entries} == {e.key: e for e in entries}


def test_import_endpoint_keeps_every_drawer_row(client):
    body = client.post(
        "/inventory/import", json={"csv": FIXTURE_CSV.read_text()}
    ).json()
    assert body["imported"] == 63 and body["updated"] == 0
    assert [r["reason"] for r in body["rejected"]] == ["looks like a summary row"]
    assert len(client.get("/inventory").json()) == 63
    # Re-importing the same sheet updates rather than duplicating.
    again = client.post(
        "/inventory/import", json={"csv": FIXTURE_CSV.read_text()}
    ).json()
    assert again["imported"] == 0 and again["updated"] == 63


def test_part_crud_endpoints(client):
    r = client.put("/inventory/parts/IRF4905", json={
        "quantity": 5, "family": "mosfet", "polarity": "p",
        "package": "TO-220", "pinout": "G-D-S", "v_max": 55, "i_max": 74,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["key"] == "part:IRF4905" and body["mpn"] == "IRF4905"
    assert body["library_id"] == "" and body["kind"] == "part"
    assert body["v_max"] == 55 and body["family"] == "mosfet"
    assert client.delete("/inventory/parts/IRF4905").json() == {"deleted": "part:IRF4905"}
    assert client.delete("/inventory/parts/IRF4905").status_code == 404


def test_part_endpoint_validation(client):
    assert client.put("/inventory/parts/X", json={"quantity": -1}).status_code == 422
    assert client.put(
        "/inventory/parts/X", json={"quantity": 1, "family": "sorcery"}
    ).status_code == 422
    # A part needs no library file -- that is the whole point.
    assert client.put(
        "/inventory/parts/NOT-IN-ANY-LIBRARY", json={"quantity": 1}
    ).status_code == 200


# --- matching discrete parts ---------------------------------------------


def _drawer():
    return entries_from_csv(FIXTURE_CSV.read_text()).entries


@pytest.mark.parametrize(
    "raw,family,expected",
    [
        ("470", "resistor", 470.0),
        ("470R", "resistor", 470.0),
        ("470 ohm", "resistor", 470.0),
        ("4R7", "resistor", 4.7),
        ("1k", "resistor", 1000.0),
        ("4k7", "resistor", 4700.0),
        ("10K", "resistor", 10000.0),
        ("1M", "resistor", 1e6),
        ("100nF", "capacitor", 1e-7),
        ("100n", "capacitor", 1e-7),
        ("0.1uF", "capacitor", 1e-7),
        ("22pF", "capacitor", 22e-12),
        ("IRF4905", "resistor", None),  # an MPN is not a value
        ("", "resistor", None),
    ],
)
def test_normalize_value(raw, family, expected):
    from wirestudio.inventory.match import normalize_value

    got = normalize_value(raw, family)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_family_comes_from_the_designator():
    from wirestudio.inventory.match import family_for_ref

    assert family_for_ref("R3") == "resistor"
    assert family_for_ref("C12") == "capacitor"
    assert family_for_ref("Q1") == "transistor"
    assert family_for_ref("U2") == "ic"
    assert family_for_ref("J1") == ""  # a connector isn't drawer stock


def test_check_parts_matches_the_hbridge_against_the_real_drawer(library):
    """The circuit #262 built from this drawer now reads back against it."""
    from wirestudio.inventory.check import check_parts

    design = Design.model_validate(
        json.loads((EXAMPLES_DIR / "motor-position.json").read_text()))
    by_value = {ln.value: ln for ln in check_parts(design, library, _drawer())}

    # Semiconductors match by MPN, with the quantity the bridge needs.
    for mpn, on_hand in (("IRF4905", 5), ("IRFZ44N", 5), ("2N3904", 35)):
        line = by_value[mpn]
        assert line.status == "have" and line.needed == 2
        assert line.on_hand == on_hand and line.matched == f"part:{mpn}"
        assert len(line.refs) == 2

    # Common passives aren't inventoried but aren't missing either.
    assert by_value["10k"].status == "assumed"
    assert by_value["10k"].refs == ["R3", "R6"]
    assert by_value["100nF"].status == "assumed"
    # A motor connector is not drawer stock; saying "need" would be noise.
    assert by_value["Motor"].status == "untracked"


def test_check_parts_reports_short_and_missing_stock(library):
    from wirestudio.inventory.check import check_parts

    design = Design.model_validate(
        json.loads((EXAMPLES_DIR / "motor-position.json").read_text()))
    thin = [
        InventoryEntry(kind="part", mpn="IRF4905", quantity=1, family="mosfet"),
        # IRFZ44N absent entirely; 2N3904 absent entirely.
    ]
    by_value = {ln.value: ln for ln in check_parts(design, library, thin)}
    assert by_value["IRF4905"].status == "partial"  # needs 2, has 1
    assert by_value["IRFZ44N"].status == "need"
    assert by_value["2N3904"].status == "need"


def test_check_parts_matches_passives_by_magnitude(library):
    """0.1uF in the drawer satisfies a 100nF on the board."""
    from wirestudio.inventory.check import check_parts

    design = Design.model_validate(
        json.loads((EXAMPLES_DIR / "motor-position.json").read_text()))
    drawer = [
        InventoryEntry(kind="part", mpn="C-0.1uF", quantity=50,
                       family="capacitor", value="0.1uF"),
    ]
    line = next(
        ln for ln in check_parts(design, library, drawer) if ln.value == "100nF")
    assert line.status == "have" and line.on_hand == 50
    assert line.matched == "part:C-0.1uF"


def test_check_inventory_carries_parts(library):
    design = Design.model_validate(
        json.loads((EXAMPLES_DIR / "motor-position.json").read_text()))
    report = check_inventory(design, library, _drawer())
    assert report.parts_summary["have"] == 3
    assert report.parts_summary["assumed"] == 5
    assert report.parts_summary["need"] == 0
    # The component-level lines are unchanged in shape.
    assert all(hasattr(ln, "library_id") for ln in report.lines)


def test_check_endpoint_reports_parts(client):
    client.post("/inventory/import", json={"csv": FIXTURE_CSV.read_text()})
    design = json.loads((EXAMPLES_DIR / "motor-position.json").read_text())
    body = client.post("/design/inventory/check", json={"design": design}).json()
    assert body["parts_summary"]["have"] == 3
    irf = next(p for p in body["parts"] if p["value"] == "IRF4905")
    assert irf["status"] == "have" and irf["refs"] == ["Q1", "Q4"]


# ---------------------------------------------------------------------------
# Substitution (proposals only)
# ---------------------------------------------------------------------------

def _fet(mpn, polarity="p", v=55, i=74, qty=5, package="TO-220", pinout="G-D-S"):
    return InventoryEntry(kind="part", mpn=mpn, family="mosfet", polarity=polarity,
                          v_max=v, i_max=i, quantity=qty, package=package, pinout=pinout)


def test_find_substitutes_applies_hard_constraints():
    from wirestudio.inventory import find_substitutes
    from wirestudio.library import PartRequirements

    req = PartRequirements(family="mosfet", polarity="p", v_min=20, i_min=3)
    drawer = [
        _fet("IRF9540", v=100, i=19),
        _fet("WRONG-POL", polarity="n"),
        _fet("LOW-V", v=12),
        _fet("LOW-I", i=2),
        _fet("NO-RATING", v=None, i=None),
        _fet("SMD", package="SOT-23"),
        _fet("EMPTY", qty=0),
        InventoryEntry(kind="part", mpn="BC327", family="bjt", polarity="pnp",
                       v_max=45, i_max=0.8, quantity=10),
    ]
    subs = find_substitutes(
        "IRF4905", drawer, requires=req,
        footprint="Package_TO_SOT_THT:TO-220-3_Vertical")
    assert [s.mpn for s in subs] == ["IRF9540"]
    assert subs[0].on_hand == 5 and subs[0].key == "part:IRF9540"
    assert subs[0].caveats == ["gate threshold and Rds(on) not compared"]


def test_find_substitutes_flags_pinout_and_unknown_package():
    from wirestudio.inventory import find_substitutes
    from wirestudio.library import PartRequirements

    req = PartRequirements(family="bjt", polarity="npn", v_min=10, i_min=0.05)
    drawer = [
        InventoryEntry(kind="part", mpn="2N3904", family="bjt", polarity="npn",
                       v_max=40, i_max=0.2, quantity=1, package="TO-92", pinout="E-B-C"),
        InventoryEntry(kind="part", mpn="BC337", family="bjt", polarity="npn",
                       v_max=45, i_max=0.8, quantity=35, package="TO-92", pinout="C-B-E"),
        InventoryEntry(kind="part", mpn="MYSTERY", family="bjt", polarity="npn",
                       v_max=45, i_max=0.8, quantity=2),
    ]
    subs = {s.mpn: s for s in find_substitutes(
        "2N3904", drawer, requires=req, footprint="Package_TO_SOT_THT:TO-92_Inline")}
    assert set(subs) == {"BC337", "MYSTERY"}
    assert "pinout C-B-E differs from E-B-C" in subs["BC337"].caveats
    assert "package not recorded" in subs["MYSTERY"].caveats
    # The original never proposes itself.
    assert "2N3904" not in subs


def test_find_substitutes_falls_back_to_the_original_parts_ratings():
    """No `requires:` declared: compare against the fitted part's own
    rating, and say so. IRF9540's 19 A is below IRF4905's 74 A, so under
    that conservative basis it is no longer proposed."""
    from wirestudio.inventory import find_substitutes

    drawer = [_fet("IRF4905", qty=0), _fet("IRF9540", v=100, i=19), _fet("BIG", v=60, i=80)]
    subs = find_substitutes("IRF4905", drawer)
    assert [s.mpn for s in subs] == ["BIG"]
    assert subs[0].caveats[0] == "ratings compared against IRF4905's own, not the circuit's need"
    # Nothing to compare against at all: no proposals rather than guesses.
    assert find_substitutes("IRF4905", [_fet("IRF9540")]) == []


def test_check_parts_proposes_substitutes_for_short_semiconductors(library):
    from wirestudio.inventory.check import check_parts

    design = Design.model_validate(
        json.loads((EXAMPLES_DIR / "motor-position.json").read_text()))
    drawer = [e for e in _drawer() if e.mpn != "IRF4905"]
    drawer.append(InventoryEntry(kind="part", mpn="2N3904", family="bjt", polarity="npn",
                                 v_max=40, i_max=0.2, quantity=1, package="TO-92",
                                 pinout="E-B-C"))
    drawer = [e for e in drawer if not (e.mpn == "2N3904" and e.quantity == 35)]
    by_value = {ln.value: ln for ln in check_parts(design, library, drawer)}

    irf = by_value["IRF4905"]
    assert irf.status == "need"
    assert [s.mpn for s in irf.substitutes] == ["IRF9540"]

    drv = by_value["2N3904"]
    assert drv.status == "partial"
    bc337 = next(s for s in drv.substitutes if s.mpn == "BC337")
    assert "pinout C-B-E differs from E-B-C" in bc337.caveats

    # Satisfied lines and passives carry no proposals.
    assert by_value["IRFZ44N"].status == "have" and by_value["IRFZ44N"].substitutes == []
    assert by_value["10k"].substitutes == []


def test_subcircuit_coverage(library):
    from wirestudio.inventory import subcircuit_coverage

    bridge = library.component("hbridge_mosfet")
    assert subcircuit_coverage(bridge, _drawer()) == (14, 14)
    # Passives are assumed; the six transistors are missing.
    assert subcircuit_coverage(bridge, []) == (8, 14)
    thin = [InventoryEntry(kind="part", mpn="IRF4905", quantity=1, family="mosfet")]
    assert subcircuit_coverage(bridge, thin) == (9, 14)
    assert subcircuit_coverage(library.component("bme280"), _drawer()) == (0, 0)


def test_recommender_scores_subcircuit_coverage(library):
    from wirestudio.recommend.recommender import recommend_components

    bare = next(r for r in recommend_components(library, "dc motor")
                if r.library_id == "hbridge_mosfet")
    stocked = next(r for r in recommend_components(library, "dc motor", inventory=_drawer())
                   if r.library_id == "hbridge_mosfet")
    assert stocked.score == bare.score + 5
    assert stocked.parts_on_hand == 14 and stocked.parts_total == 14
    assert "all 14 parts on hand" in stocked.rationale
    assert bare.parts_total == 0 and "parts on hand" not in bare.rationale

    half = next(r for r in recommend_components(library, "dc motor", inventory=[])
                if r.library_id == "hbridge_mosfet")
    assert half.parts_total == 0  # an empty drawer is no drawer


def test_check_endpoint_reports_substitutes(client):
    client.post("/inventory/import", json={"csv": FIXTURE_CSV.read_text()})
    client.delete("/inventory/parts/IRF4905")
    design = json.loads((EXAMPLES_DIR / "motor-position.json").read_text())
    body = client.post("/design/inventory/check", json={"design": design}).json()
    irf = next(p for p in body["parts"] if p["value"] == "IRF4905")
    assert irf["status"] == "need"
    assert [s["mpn"] for s in irf["substitutes"]] == ["IRF9540"]
    assert irf["substitutes"][0]["caveats"] == ["gate threshold and Rds(on) not compared"]
    have = next(p for p in body["parts"] if p["value"] == "IRFZ44N")
    assert have["substitutes"] == []


def test_recommend_endpoint_reports_part_coverage(client):
    client.post("/inventory/import", json={"csv": FIXTURE_CSV.read_text()})
    matches = client.post(
        "/library/recommend", json={"query": "dc motor", "use_inventory": True}
    ).json()["matches"]
    bridge = next(m for m in matches if m["library_id"] == "hbridge_mosfet")
    assert bridge["parts_on_hand"] == 14 and bridge["parts_total"] == 14


def test_part_requirements_validate_family():
    from pydantic import ValidationError

    from wirestudio.library import PartRequirements
    with pytest.raises(ValidationError):
        PartRequirements(family="transistor")


# ---------------------------------------------------------------------------
# Applied substitutions (part_overrides)
# ---------------------------------------------------------------------------

def _bridge_design(**overrides):
    raw = json.loads((EXAMPLES_DIR / "motor-position.json").read_text())
    raw["part_overrides"] = overrides
    return Design.model_validate(raw)


def test_part_override_changes_the_printed_value_only(library):
    from wirestudio.kicad.netlist import placed_parts

    design = _bridge_design(**{"bridge.q_hi_a": "IRF9540"})
    by_key = {p.key: p for p in placed_parts(design, library)}
    q1, q4 = by_key["bridge.q_hi_a"], by_key["bridge.q_hi_b"]
    assert q1.kicad.value == "IRF9540" and q1.substituted_for == "IRF4905"
    assert q1.kicad.symbol == "IRF4905" and q1.kicad.footprint == q4.kicad.footprint
    assert q4.kicad.value == "IRF4905" and q4.substituted_for == ""
    # The library object itself is untouched.
    assert library.component("hbridge_mosfet").subcircuit.parts[0].kicad.value == "IRF4905"


def test_check_parts_follows_overrides_and_offers_keys(library):
    from wirestudio.inventory.check import check_parts

    design = _bridge_design(**{"bridge.q_hi_a": "IRF9540", "bridge.q_hi_b": "IRF9540"})
    drawer = [e for e in _drawer() if e.mpn != "IRF4905"]
    by_value = {ln.value: ln for ln in check_parts(design, library, drawer)}
    assert "IRF4905" not in by_value
    line = by_value["IRF9540"]
    assert line.status == "have" and line.refs == ["Q1", "Q4"]
    assert line.keys == ["bridge.q_hi_a", "bridge.q_hi_b"]
    assert line.substituted_for == ["IRF4905"]
    # Unmodified lines still carry their keys, so a proposal can be applied.
    assert by_value["2N3904"].keys == ["bridge.q_drv_a", "bridge.q_drv_b"]
    assert by_value["10k"].keys == ["bridge.r_pd_a", "bridge.r_pd_b"]


def test_check_part_overrides_records_each_substitution(library):
    from wirestudio.validate import check_part_overrides

    design = _bridge_design(**{"bridge.q_hi_a": "IRF9540", "bridge.nope": "X", "bridge.q_lo_a": "IRFZ44N"})
    warnings = {w.code: w for w in check_part_overrides(design, library)}
    sub = warnings["part_substituted"]
    assert sub.level == "info"
    assert sub.text.startswith("Q1 (bridge.q_hi_a): IRF9540 substituted for IRF4905; ")
    assert "gate threshold" in sub.text
    unknown = warnings["part_override_unknown"]
    assert unknown.level == "warn" and "bridge.nope" in unknown.text
    # Overriding a part with its own value is a no-op, not a substitution.
    assert len(check_part_overrides(design, library)) == 2
    assert check_part_overrides(_bridge_design(), library) == []


def test_set_part_override_tool(library):
    from wirestudio.agent.tools import execute_tool

    raw = json.loads((EXAMPLES_DIR / "motor-position.json").read_text())
    out, err = execute_tool("set_part_override", {"key": "bridge.q_hi_a", "mpn": "IRF9540"}, raw, library)
    assert not err and json.loads(out) == {
        "ok": True, "set": {"bridge.q_hi_a": "IRF9540"}, "substituted_for": "IRF4905"}
    assert raw["part_overrides"] == {"bridge.q_hi_a": "IRF9540"}
    out, _ = execute_tool("set_part_override", {"key": "bridge.q_hi_a"}, raw, library)
    assert json.loads(out)["removed"] == "bridge.q_hi_a" and raw["part_overrides"] == {}
    out, _ = execute_tool("set_part_override", {"key": "bridge.q_hi_z", "mpn": "X"}, raw, library)
    assert json.loads(out)["ok"] is False
    out, _ = execute_tool("set_part_override", {"key": "zz.q", "mpn": "X"}, raw, library)
    assert json.loads(out)["ok"] is False


def test_override_reaches_the_parts_endpoint_and_validate(client):
    design = json.loads((EXAMPLES_DIR / "motor-position.json").read_text())
    design["part_overrides"] = {"bridge.q_hi_a": "IRF9540"}
    parts = client.post("/design/parts", json=design).json()["parts"]
    q1 = next(p for p in parts if p["ref"] == "Q1")
    assert q1["value"] == "IRF9540" and q1["symbol"] == "Transistor_FET:IRF4905"
    body = client.post("/design/validate", json=design).json()
    assert any(w["code"] == "part_substituted" for w in body["warnings"])
    check = client.post("/design/inventory/check", json={"design": design}).json()
    line = next(p for p in check["parts"] if p["value"] == "IRF9540")
    assert line["keys"] == ["bridge.q_hi_a"] and line["substituted_for"] == ["IRF4905"]


# ---------------------------------------------------------------------------
# Pick list
# ---------------------------------------------------------------------------

def test_pick_list_groups_by_drawer_location(library):
    design = Design.model_validate(
        json.loads((EXAMPLES_DIR / "motor-position.json").read_text()))
    groups = check_inventory(design, library, _drawer()).pick_list
    by_kind = {}
    for g in groups:
        by_kind.setdefault(g.kind, []).append(g)

    locations = {g.location: {i.label: i for i in g.items} for g in by_kind["location"]}
    assert locations["TO-220 24x5 kit"]["IRF4905"].refs == ["Q1", "Q4"]
    assert locations["TO-220 24x5 kit"]["IRFZ44N"].needed == 2
    assert locations["2N series box (10-15 ea)"]["2N3904"].inventory_key == "part:2N3904"
    # Locations sort by name; special groups follow in a fixed order.
    assert [g.kind for g in groups] == ["location", "location", "assumed", "missing"]
    assert [g.location for g in groups[:2]] == ["2N series box (10-15 ea)", "TO-220 24x5 kit"]

    assumed = {i.label for i in by_kind["assumed"][0].items}
    assert assumed == {"470", "1k", "10k", "100nF", "470uF"}
    # The bridge itself is built from the parts above, so it is not
    # listed as a missing component; the ADC input is.
    missing = {i.label: i for i in by_kind["missing"][0].items}
    assert "Discrete MOSFET H-bridge (IRF4905 / IRFZ44N, 5 V)" not in missing
    assert next(iter(missing.values())).refs == ["feedback"]
    # Connectors are not stock and never appear.
    assert not any(i.label == "Motor" for g in groups for i in g.items)


def test_pick_list_carries_unlocated_stock_and_component_instances(garage_motion_design, library):
    stock = [
        InventoryEntry(library_id="bme280", kind="component", quantity=5, location="bin A"),
        InventoryEntry(library_id="hc-sr501", kind="component", quantity=1),
    ]
    groups = {g.kind: g for g in check_inventory(garage_motion_design, library, stock).pick_list}
    assert groups["location"].location == "bin A"
    assert groups["location"].items[0].refs  # the component instance id(s)
    assert groups["unlocated"].items[0].inventory_key == "hc-sr501"


def test_check_endpoint_returns_pick_list(client):
    client.post("/inventory/import", json={"csv": FIXTURE_CSV.read_text()})
    design = json.loads((EXAMPLES_DIR / "motor-position.json").read_text())
    body = client.post("/design/inventory/check", json={"design": design}).json()
    kit = next(g for g in body["pick_list"] if g["location"] == "TO-220 24x5 kit")
    assert kit["kind"] == "location"
    assert {i["label"] for i in kit["items"]} == {"IRF4905", "IRFZ44N"}


# ---------------------------------------------------------------------------
# Buy list
# ---------------------------------------------------------------------------

def _jlc(catalog):
    import httpx
    from wirestudio.jlcpcb.client import JlcpcbClient

    def handler(request):
        q = request.url.params["q"]
        return httpx.Response(200, json={"components": catalog.get(q, [])})
    return JlcpcbClient(base_url="http://jlc.test", transport=httpx.MockTransport(handler))


def test_buy_list_prices_the_shortfalls(library):
    from wirestudio.inventory.buy import buy_list

    design = Design.model_validate(
        json.loads((EXAMPLES_DIR / "motor-position.json").read_text()))
    thin = [InventoryEntry(kind="part", mpn="IRF4905", quantity=1, family="mosfet"),
            InventoryEntry(kind="part", mpn="2N3904", quantity=9, family="bjt")]
    client = _jlc({
        "IRF4905": [{"lcsc": 1, "mfr": "IRF4905PBF", "package": "TO-220", "stock": 120, "price": 1.1}],
        "IRFZ44N": [{"lcsc": 2, "mfr": "IRFZ44NPBF", "package": "TO-220", "stock": 0, "price": 0.9}],
    })
    result = buy_list(design, library, thin, client)
    assert result.available and result.api_url == "http://jlc.test"
    by_label = {ln.label: ln for ln in result.lines}
    # Shortfall, not need: one IRF4905 is on hand.
    assert by_label["IRF4905"].shortfall == 1 and by_label["IRF4905"].refs == ["Q1", "Q4"]
    assert by_label["IRF4905"].status == "ok" and by_label["IRF4905"].lcsc == "C1"
    assert by_label["IRF4905"].price == 1.1 and by_label["IRF4905"].package == "TO-220"
    assert by_label["IRFZ44N"].status == "out_of_stock" and by_label["IRFZ44N"].shortfall == 2
    # A library component the drawer lacks is searched by id.
    adc = by_label["Generic analog input"]
    assert adc.kind == "component" and adc.query == "adc" and adc.status == "not_found"
    # Enough 2N3904s; common passives are assumed; neither is bought.
    assert "2N3904" not in by_label and "10k" not in by_label
    assert result.summary == {"ok": 1, "out_of_stock": 1, "not_found": 1}


def test_buy_list_survives_a_down_api(library):
    import httpx
    from wirestudio.inventory.buy import buy_list
    from wirestudio.jlcpcb.client import JlcpcbClient

    design = Design.model_validate(
        json.loads((EXAMPLES_DIR / "motor-position.json").read_text()))
    down = JlcpcbClient(base_url="http://jlc.test",
                        transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    result = buy_list(design, library, [], down)
    assert result.available is False and "503" in (result.reason or "")
    # The shortfalls are still listed, just unpriced.
    assert {ln.label for ln in result.lines} >= {"IRF4905", "IRFZ44N", "2N3904"}
    assert all(ln.status == "not_found" and "unavailable" in ln.note for ln in result.lines)


def test_buy_list_endpoint_and_tool(client, monkeypatch):
    import wirestudio.api.app as appmod
    from wirestudio.inventory.buy import BuyList, BuyLine

    fake = BuyList(design_id="x", available=True, api_url="u", lines=[
        BuyLine(label="IRF4905", kind="part", family="mosfet", shortfall=2,
                refs=["Q1", "Q4"], query="IRF4905", status="ok", note="C1 — 9 in stock",
                lcsc="C1", stock=9, price=1.0),
    ])
    monkeypatch.setattr(appmod, "buy_list", lambda d, lib, inv: fake)
    design = json.loads((EXAMPLES_DIR / "motor-position.json").read_text())
    body = client.post("/design/buy-list", json={"design": design}).json()
    assert body["summary"] == {"ok": 1, "out_of_stock": 0, "not_found": 0}
    assert body["lines"][0]["lcsc"] == "C1" and body["lines"][0]["refs"] == ["Q1", "Q4"]
