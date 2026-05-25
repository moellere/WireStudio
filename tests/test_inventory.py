"""Local component inventory: store, design cross-check, and API."""
from __future__ import annotations

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
    back = entries_from_csv(entries_to_csv(entries))
    assert [e.library_id for e in back] == ["bme280", "oled-encoder"]
    assert back[0].min_quantity == 1 and back[0].location == "A1" and back[0].note == "porch"
    assert back[1].kind == "module"


def test_csv_bad_row_raises():
    with pytest.raises(ValueError):
        entries_from_csv("library_id,quantity\nbme280,-1\n")


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


def test_inventory_import_skips_unknown(client):
    r = client.post("/inventory/import", json={"csv": "library_id,quantity\nnot-a-part,2\n"})
    assert r.json() == {"imported": 0, "skipped": ["not-a-part"]}
