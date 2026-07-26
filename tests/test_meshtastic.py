from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
import wirestudio.api.meshtastic as M


def test_status_reports_boards_and_version(monkeypatch):
    monkeypatch.setattr(M, "_latest_stable", lambda: "v2.6.11.60ec05e")
    client = TestClient(create_app())
    body = client.get("/meshtastic/firmware/status").json()
    assert body["available"] is True
    assert body["version"] == "v2.6.11.60ec05e"
    assert "heltec-wifi-lora32-v4" in body["boards"]
    assert "ttgo-t-beam" in body["boards"]


def test_status_degrades_when_release_list_unreachable(monkeypatch):
    def boom():
        raise RuntimeError("offline")

    monkeypatch.setattr(M, "_latest_stable", boom)
    client = TestClient(create_app())
    body = client.get("/meshtastic/firmware/status").json()
    assert body["available"] is False
    assert "offline" in body["reason"]


def test_firmware_resolves_variant_and_version(monkeypatch):
    fetched = {}

    def fake_fetch(url):
        fetched["url"] = url
        return b"MESH"

    monkeypatch.setattr(M, "_latest_stable", lambda: "v2.6.11.60ec05e")
    monkeypatch.setattr(M, "_fetch_firmware", fake_fetch)
    client = TestClient(create_app())
    r = client.get("/meshtastic/firmware?board=heltec-wifi-lora32-v3")
    assert r.status_code == 200
    assert r.content == b"MESH"
    assert r.headers["x-flash-offset"] == "0"
    assert fetched["url"] == (
        f"{M._FILES_BASE}/firmware-2.6.11.60ec05e/"
        "firmware-heltec-v3-2.6.11.60ec05e.factory.bin"
    )


def test_firmware_explicit_version_skips_release_lookup(monkeypatch):
    def boom():
        raise RuntimeError("should not be called")

    monkeypatch.setattr(M, "_latest_stable", boom)
    monkeypatch.setattr(M, "_fetch_firmware", lambda url: b"MESH")
    client = TestClient(create_app())
    r = client.get("/meshtastic/firmware?board=ttgo-t-beam&version=v2.5.0.abcdef")
    assert r.status_code == 200


def test_firmware_unknown_board_422():
    client = TestClient(create_app())
    assert client.get("/meshtastic/firmware?board=wemos-d1-mini").status_code == 422


def test_firmware_upstream_failure_502(monkeypatch):
    monkeypatch.setattr(M, "_latest_stable", lambda: "v2.6.11.60ec05e")

    def boom(url):
        raise RuntimeError("nope")

    monkeypatch.setattr(M, "_fetch_firmware", boom)
    client = TestClient(create_app())
    r = client.get("/meshtastic/firmware?board=ttgo-t-beam")
    assert r.status_code == 502
