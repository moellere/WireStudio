from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets.lorawan import chirpstack as cs
from wirestudio.targets.lorawan.compile import cache_key


class _FakeChirp:
    """Stand-in for ChirpStackClient: no grpc, records what was provisioned."""

    def __init__(self, *, configured: bool = True, activation: dict | None = None) -> None:
        self._configured = configured
        self._activation = activation
        self.provisioned: dict | None = None
        self.codec_set: str | None = None

    def is_configured(self) -> bool:
        return self._configured

    def provision_device(self, *, dev_eui, app_key, application_name, device_profile_name,
                         join_eui=None, codec=None):
        self.provisioned = {
            "dev_eui": dev_eui, "app_key": app_key, "join_eui": join_eui,
            "device_profile_name": device_profile_name, "codec": codec,
        }
        return {"application_id": "app-1", "device_profile_id": "dp-1"}

    def get_activation(self, dev_eui):
        return self._activation

    def set_device_codec(self, dev_eui, codec):
        self.codec_set = codec
        return "dp-1"

    def get_device_codec(self, dev_eui):
        return {
            "device_profile_id": "dp-1",
            "device_profile_name": "wirestudio-ttgo-t-beam-us915-sub2-gps-batt",
            "codec_runtime": "JS" if self.codec_set else "NONE",
            "has_codec": bool(self.codec_set),
            "codec_chars": len(self.codec_set or ""),
        }


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _design(board_id: str, **lorawan) -> dict:
    return Design(
        schema_version="0.1",
        id="d",
        name="D",
        target="lorawan",
        lorawan=lorawan,
        board={"library_id": board_id, "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
    ).model_dump(mode="json", exclude_none=True)


def _seed_cache(tmp_path, design: dict, *, bin_bytes=b"FAKEBIN", log="cached log") -> str:
    d = Design.model_validate(design)
    key = cache_key(d, default_library())
    slot = tmp_path / key
    slot.mkdir(parents=True)
    (slot / "firmware.bin").write_bytes(bin_bytes)
    (slot / "build.log").write_text(log)
    return key


def test_compile_status(client):
    r = client.get("/lorawan/compile/status")
    assert r.status_code == 200
    assert "available" in r.json()


def test_compile_rejects_invalid_design(client):
    assert client.post("/lorawan/compile", json={"nope": 1}).status_code == 422


def test_compile_rejects_non_radio_board(client):
    r = client.post("/lorawan/compile", json=_design("esp32-devkitc-v4"))
    assert r.status_code == 422


def test_compile_cache_hit_streams_done(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WIRESTUDIO_FW_CACHE", str(tmp_path))
    design = _design("ttgo-lora32-v1")
    key = _seed_cache(tmp_path, design)

    r = client.post("/lorawan/compile", json=design)
    assert r.status_code == 200
    events = [json.loads(line[len("data: "):])
              for line in r.text.splitlines() if line.startswith("data: ")]
    done = [e for e in events if e["type"] == "done"]
    assert done and done[0]["cache_hit"] is True
    assert done[0]["cache_key"] == key
    assert done[0]["env"] == "ttgo-lora32-v1"


def test_firmware_download_after_cache_hit(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WIRESTUDIO_FW_CACHE", str(tmp_path))
    key = _seed_cache(tmp_path, _design("ttgo-lora32-v1"), bin_bytes=b"\x00\x01BIN")

    r = client.get(f"/lorawan/firmware/{key}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.content == b"\x00\x01BIN"


def test_firmware_404_unknown_key(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WIRESTUDIO_FW_CACHE", str(tmp_path))
    assert client.get("/lorawan/firmware/deadbeef").status_code == 404


def test_firmware_404_bad_key_format(client):
    # Path-traversal / non-hex keys never reach the filesystem.
    assert client.get("/lorawan/firmware/not-hex-..").status_code == 404


def test_factory_image_download(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WIRESTUDIO_FW_CACHE", str(tmp_path))
    key = _seed_cache(tmp_path, _design("ttgo-t-beam"))
    (tmp_path / key / "factory.bin").write_bytes(b"\xe9FACTORY")  # 0xe9 = ESP image magic
    r = client.get(f"/lorawan/firmware/{key}/factory")
    assert r.status_code == 200 and r.content == b"\xe9FACTORY"


def test_factory_image_404_when_absent(client, tmp_path, monkeypatch):
    monkeypatch.setenv("WIRESTUDIO_FW_CACHE", str(tmp_path))
    key = _seed_cache(tmp_path, _design("ttgo-t-beam"))  # firmware.bin only, no factory
    assert client.get(f"/lorawan/firmware/{key}/factory").status_code == 404


def test_provision_registers_device_and_returns_appkey(client, monkeypatch):
    fake = _FakeChirp()
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: fake)
    design = _design("ttgo-t-beam")  # GPS + battery -> per-type profile + codec
    r = client.post("/lorawan/provision", json={"dev_eui": "70B3D57ED0001234", "design": design})
    assert r.status_code == 200
    body = r.json()
    assert body["dev_eui"] == "70b3d57ed0001234"  # normalized lowercase
    assert body["band"] == "US915" and body["sub_band"] == 2
    assert re.fullmatch(r"[0-9a-f]{32}", body["app_key"])  # 16-byte AppKey
    # The AppKey returned to the host is exactly the one registered in ChirpStack.
    assert fake.provisioned and fake.provisioned["app_key"] == body["app_key"]
    # Per-device-type profile + matching codec.
    assert fake.provisioned["device_profile_name"] == "wirestudio-ttgo-t-beam-us915-sub2-gps-batt"
    assert "data.lat" in fake.provisioned["codec"]


def test_provision_rejects_bad_dev_eui(client, monkeypatch):
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: _FakeChirp())
    assert client.post("/lorawan/provision", json={"dev_eui": "nothex"}).status_code == 422


def test_chirpstack_status_passthrough(client, monkeypatch):
    monkeypatch.setattr(
        cs, "chirpstack_status",
        lambda *a, **k: {"available": True, "url": "chirpstack:8080", "reason": None},
    )
    r = client.get("/lorawan/chirpstack/status")
    assert r.status_code == 200
    assert r.json() == {"available": True, "url": "chirpstack:8080", "reason": None}


def test_provision_503_when_chirpstack_unconfigured(client, monkeypatch):
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: _FakeChirp(configured=False))
    r = client.post("/lorawan/provision", json={"dev_eui": "70b3d57ed0001234"})
    assert r.status_code == 503


def test_activation_reports_joined(client, monkeypatch):
    fake = _FakeChirp(activation={"dev_addr": "01020304", "f_cnt_up": 3})
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: fake)
    r = client.get("/lorawan/activation/64b708fffeab8974")
    assert r.status_code == 200
    body = r.json()
    assert body["joined"] is True
    assert body["dev_addr"] == "01020304"


def test_activation_reports_not_joined(client, monkeypatch):
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: _FakeChirp(activation=None))
    r = client.get("/lorawan/activation/64b708fffeab8974")
    assert r.status_code == 200
    assert r.json()["joined"] is False


def test_activation_rejects_bad_dev_eui(client, monkeypatch):
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: _FakeChirp())
    assert client.get("/lorawan/activation/nothex").status_code == 422


def test_set_codec_applies_design_codec(client, monkeypatch):
    fake = _FakeChirp()
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: fake)
    design = _design("ttgo-t-beam")  # onboard GPS + battery
    r = client.post("/lorawan/codec", json={"dev_eui": "64b708fffeab8974", "design": design})
    assert r.status_code == 200
    assert r.json()["codec_set"] is True
    assert fake.codec_set and "data.lat" in fake.codec_set and "data.batt_mv" in fake.codec_set


def test_set_codec_reflects_external_gps(client, monkeypatch):
    fake = _FakeChirp()
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: fake)
    # Heltec has no onboard GPS; the external GPS config must still add GPS fields.
    design = _design("heltec-wifi-lora32-v3", gps={"rx_pin": "GPIO3", "tx_pin": "GPIO1"})
    r = client.post("/lorawan/codec", json={"dev_eui": "64b708fffeab8974", "design": design})
    assert r.status_code == 200
    assert "data.lat" in fake.codec_set and "data.batt_mv" not in fake.codec_set


def test_set_codec_rejects_bad_dev_eui(client, monkeypatch):
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: _FakeChirp())
    assert client.post("/lorawan/codec", json={"dev_eui": "x"}).status_code == 422


def test_get_codec_reports_runtime(client, monkeypatch):
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: _FakeChirp())  # codec_set is None -> NONE
    r = client.get("/lorawan/codec/64b708fffeab8974")
    assert r.status_code == 200
    assert r.json()["codec_runtime"] == "NONE" and r.json()["has_codec"] is False


def test_esphome_target_mounts_no_router(client):
    # The seam mounts only lorawan; esphome's endpoints stay at the top level.
    assert client.get("/lorawan/compile/status").status_code == 200
    # A bogus target prefix is not mounted.
    assert client.get("/esphome/compile/status").status_code == 404


# --- W3: provision-esphome (companion of /provision for the new path) -------
#
# The new endpoint is the orchestrator side of the external-component flow:
# it provisions a device in ChirpStack and returns the keys formatted for a
# secrets.yaml that lives next to the rendered ESPHome config. The
# AppKey is ephemeral and only travels through this response -- never
# persisted to design.json (CLAUDE.md rule).

def _esphome_lorawan_design() -> dict:
    """Smallest external-component-path design: TTGO LoRa32 v1 + ADC battery,
    with a single payload field. Matches the W2 worked example shape."""
    return Design(
        schema_version="0.1", id="d", name="D",
        target="esphome",
        lorawan={
            "region": "US915", "sub_band": 2,
            "payload": [{"sensor": "battery"}],
        },
        board={"library_id": "ttgo-lora32-v1", "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        components=[{"id": "battery", "library_id": "adc", "label": "Battery"}],
        connections=[{
            "component_id": "battery", "pin_role": "IN",
            "target": {"kind": "gpio", "pin": "GPIO36"},
        }],
    ).model_dump(mode="json", exclude_none=True)


def test_provision_esphome_returns_secrets_block(client, monkeypatch):
    """The endpoint returns the three lorawan-for-esphome secrets in the shape
    a `secrets.yaml` consumer expects, plus the ChirpStack identifiers."""
    fake = _FakeChirp()
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: fake)
    r = client.post(
        "/lorawan/provision-esphome",
        json={"dev_eui": "70B3D57ED0001234", "design": _esphome_lorawan_design()},
    )
    assert r.status_code == 200
    body = r.json()
    secrets_block = body["secrets"]
    assert set(secrets_block) == {"dev_eui", "join_eui", "app_key"}
    assert secrets_block["dev_eui"] == "70b3d57ed0001234"   # normalised lowercase
    assert re.fullmatch(r"[0-9a-f]{32}", secrets_block["app_key"])
    assert secrets_block["join_eui"] == "0000000000000000"   # default when unset
    assert body["chirpstack"] == {"application_id": "app-1", "device_profile_id": "dp-1"}
    assert body["band"] == "US915" and body["sub_band"] == 2
    # The key registered in ChirpStack is the same one returned to the caller.
    assert fake.provisioned["app_key"] == secrets_block["app_key"]


def test_provision_esphome_uses_esphome_profile_naming(client, monkeypatch):
    """The new path uses a distinct device-profile naming scheme so it
    doesn't collide with the standalone path's per-component-set profiles."""
    fake = _FakeChirp()
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: fake)
    r = client.post(
        "/lorawan/provision-esphome",
        json={"dev_eui": "70b3d57ed0001234", "design": _esphome_lorawan_design()},
    )
    assert r.status_code == 200
    assert fake.provisioned["device_profile_name"] == "wirestudio-esphome-us915-sub2"
    # Codec is None on the new path -- the decoder is generated from
    # design.lorawan.payload by a follow-up endpoint, not by the standalone
    # codec.py (which knows only gps/dht22/oled).
    assert fake.provisioned["codec"] is None


def test_provision_esphome_passes_join_eui_when_set(client, monkeypatch):
    fake = _FakeChirp()
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: fake)
    design = _esphome_lorawan_design()
    design["lorawan"]["join_eui"] = "70b3d57ed0000000"
    r = client.post(
        "/lorawan/provision-esphome",
        json={"dev_eui": "70b3d57ed0001234", "design": design},
    )
    assert r.status_code == 200
    assert fake.provisioned["join_eui"] == "70b3d57ed0000000"
    assert r.json()["secrets"]["join_eui"] == "70b3d57ed0000000"


def test_provision_esphome_rejects_bad_dev_eui(client, monkeypatch):
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: _FakeChirp())
    r = client.post(
        "/lorawan/provision-esphome",
        json={"dev_eui": "nothex", "design": _esphome_lorawan_design()},
    )
    assert r.status_code == 422


def test_provision_esphome_rejects_empty_payload(client, monkeypatch):
    """The new path is gated on payload being non-empty -- a provision call
    against a design with no payload is a user error worth surfacing
    explicitly, not a silent provision with no-op uplinks."""
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: _FakeChirp())
    design = _esphome_lorawan_design()
    design["lorawan"]["payload"] = []
    r = client.post(
        "/lorawan/provision-esphome",
        json={"dev_eui": "70b3d57ed0001234", "design": design},
    )
    assert r.status_code == 422
    assert "payload" in r.json()["detail"]


def test_provision_esphome_rejects_design_without_lorawan_block(client, monkeypatch):
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: _FakeChirp())
    design = _esphome_lorawan_design()
    design.pop("lorawan")
    r = client.post(
        "/lorawan/provision-esphome",
        json={"dev_eui": "70b3d57ed0001234", "design": design},
    )
    assert r.status_code == 422


def test_provision_esphome_503_when_chirpstack_unconfigured(client, monkeypatch):
    monkeypatch.setattr(cs, "ChirpStackClient", lambda: _FakeChirp(configured=False))
    r = client.post(
        "/lorawan/provision-esphome",
        json={"dev_eui": "70b3d57ed0001234", "design": _esphome_lorawan_design()},
    )
    assert r.status_code == 503
