"""Local component inventory: store, design cross-check, and API."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.inventory import check_inventory, entries_from_csv, entries_to_csv
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
