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


def _merged(n=0x10000, bootloader_at=0x1000):
    """A classic-ESP32 merged image: padding, bootloader, partition table."""
    blob = bytearray(b"\xff" * n)
    blob[bootloader_at] = 0xE9
    blob[0x8000:0x8002] = b"\xaa\x50"
    return bytes(blob)


# What an app-only (OTA) image looks like at offset 0: the image header,
# then code -- no partition table at 0x8000. Read back from a T3 V1.6.1.
_APP_ONLY = b"\xe9\x08\x02\x20\xf0\x36\x08\x40" + b"\x00" * 0x10000


def _serve(files):
    """A _fetch_firmware that serves `files` (name -> bytes) and 404s the rest."""
    import httpx

    fetched = []

    def fetch(url):
        fetched.append(url.rsplit("/", 1)[-1])
        name = fetched[-1]
        if name not in files:
            req = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))
        return files[name]

    return fetch, fetched


def test_firmware_serves_the_factory_image(monkeypatch):
    """2.7.26: `.factory.bin` is the install image, the plain `.bin` app-only."""
    fetch, fetched = _serve({
        "firmware-tlora-v2-1-1_6-2.7.26.54e0d8d.factory.bin": _merged(),
        "firmware-tlora-v2-1-1_6-2.7.26.54e0d8d.bin": _APP_ONLY,
    })
    monkeypatch.setattr(M, "_latest_stable", lambda: "v2.7.26.54e0d8d")
    monkeypatch.setattr(M, "_fetch_firmware", fetch)
    client = TestClient(create_app())
    r = client.get("/meshtastic/firmware?board=ttgo-lora32-v2")
    assert r.status_code == 200
    assert r.content == _merged()
    assert r.headers["x-flash-offset"] == "0"
    assert "factory.bin" in r.headers["content-disposition"]
    assert fetched == ["firmware-tlora-v2-1-1_6-2.7.26.54e0d8d.factory.bin"]


def test_firmware_falls_back_to_a_merged_plain_bin(monkeypatch):
    """2.7.15 published the install image as the plain `.bin`."""
    fetch, fetched = _serve({"firmware-heltec-v3-2.7.15.567b8ea.bin": _merged(bootloader_at=0x0)})
    monkeypatch.setattr(M, "_latest_stable", lambda: "v2.7.15.567b8ea")
    monkeypatch.setattr(M, "_fetch_firmware", fetch)
    r = TestClient(create_app()).get("/meshtastic/firmware?board=heltec-wifi-lora32-v3")
    assert r.status_code == 200
    assert fetched[-1] == "firmware-heltec-v3-2.7.15.567b8ea.bin"


def test_an_app_only_image_is_refused(monkeypatch):
    """Written at 0x0 it boot-loops the board on "flash read err, 1000"."""
    fetch, _ = _serve({"firmware-tbeam-2.7.26.54e0d8d.bin": _APP_ONLY})
    monkeypatch.setattr(M, "_latest_stable", lambda: "v2.7.26.54e0d8d")
    monkeypatch.setattr(M, "_fetch_firmware", fetch)
    r = TestClient(create_app()).get("/meshtastic/firmware?board=ttgo-t-beam")
    assert r.status_code == 502
    assert "app-only" in r.json()["detail"]


def test_firmware_explicit_version_skips_release_lookup(monkeypatch):
    def boom():
        raise RuntimeError("should not be called")

    fetch, _ = _serve({"firmware-tbeam-2.5.0.abcdef.factory.bin": _merged()})
    monkeypatch.setattr(M, "_latest_stable", boom)
    monkeypatch.setattr(M, "_fetch_firmware", fetch)
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


def test_boards_meshtastic_stopped_publishing_are_not_offered():
    """Heltec V1/V2 and TTGO LoRa32 V1 have no image in the stable
    releases; offering them would end in a 404 after the user picked one."""
    client = TestClient(create_app())
    for board in ("heltec-wifi-lora32-v2", "ttgo-lora32-v1"):
        assert client.get(f"/meshtastic/firmware?board={board}").status_code == 422
