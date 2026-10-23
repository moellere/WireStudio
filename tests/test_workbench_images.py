"""Images the hardware gate's flash stage writes."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from wirestudio.library import default_library
from wirestudio.workbench import images

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def lib():
    return default_library()


def _merged(n=0x10000):
    blob = bytearray(b"\xff" * n)
    blob[0] = 0xE9
    blob[0x8000:0x8002] = b"\xaa\x50"
    return bytes(blob)


@pytest.fixture
def no_network(monkeypatch):
    from wirestudio.api import circuitpython, meshtastic, micropython

    monkeypatch.setattr(circuitpython, "_latest_stable", lambda: "10.0.3")
    monkeypatch.setattr(meshtastic, "_latest_stable", lambda: "v2.7.11.ee68575")
    monkeypatch.setattr(micropython, "latest_stable",
                        lambda port, variant: (f"https://micropython.org/{port}-v1.26.1.bin", "1.26.1"))
    fetched: list[str] = []

    def fetch(url):
        fetched.append(url)
        return b"image:" + url.encode()

    monkeypatch.setattr(images, "_fetch", fetch)
    return fetched


@pytest.mark.parametrize("framework, board, offset, url_part", [
    ("circuitpython", "esp32-s3-devkitc-1", 0x0,
     "espressif_esp32s3_devkitc_1_n8/en_US/adafruit-circuitpython-espressif_esp32s3_devkitc_1_n8-en_US-10.0.3.bin"),
    ("micropython", "esp32-s3-devkitc-1", 0x0, "ESP32_GENERIC_S3-v1.26.1.bin"),
    ("micropython", "esp32-devkitc-v4", 0x1000, "ESP32_GENERIC-v1.26.1.bin"),
])
async def test_release_images(lib, no_network, framework, board, offset, url_part):
    image = await images.image_for(framework, lib.board(board), lib)
    assert image.offset == offset
    assert no_network[-1].endswith(url_part)
    assert image.data == b"image:" + no_network[-1].encode()


async def test_meshtastic_writes_only_a_merged_image(lib, monkeypatch, no_network):
    from wirestudio.api import meshtastic

    merged = _merged()
    monkeypatch.setattr(meshtastic, "_fetch_firmware", lambda url: merged)
    image = await images.image_for("meshtastic", lib.board("heltec-wifi-lora32-v3"), lib)
    assert (image.offset, image.data, image.version) == (0x0, merged, "2.7.11.ee68575")

    monkeypatch.setattr(meshtastic, "_fetch_firmware", lambda url: b"\xe9" + b"\x00" * 0x10000)
    with pytest.raises(images.ImageUnavailable, match="app-only"):
        await images.image_for("meshtastic", lib.board("heltec-wifi-lora32-v3"), lib)


async def test_a_board_with_no_build_is_unavailable_not_raised(lib, no_network):
    with pytest.raises(images.ImageUnavailable, match="no Meshtastic firmware mapping"):
        await images.image_for("meshtastic", lib.board("esp32-s3-devkitc-1"), lib)


async def test_a_failed_download_is_unavailable(lib, monkeypatch, no_network):
    def boom(url):
        raise OSError("connection reset")

    monkeypatch.setattr(images, "_fetch", boom)
    with pytest.raises(images.ImageUnavailable, match="circuitpython release download failed"):
        await images.image_for("circuitpython", lib.board("esp32-s3-devkitc-1"), lib)


class FakeDashboard:
    def __init__(self, ok=True, blob=None, configured=True):
        self.ok, self.blob, self.configured = ok, _merged() if blob is None else blob, configured
        self.pushed: dict[str, str] = {}

    def is_configured(self):
        return self.configured

    async def push_device(self, name, yaml_text):
        self.pushed[name] = yaml_text
        return SimpleNamespace(filename=f"{name}.yaml", created=True)

    async def compile(self, filename):
        yield {"type": "log", "data": "Compiling .pioenvs/x/src/main.cpp.o"}
        if not self.ok:
            yield {"type": "log", "data": "Error: ld returned 1 exit status"}
        yield {"type": "done", "ok": self.ok, "code": 0 if self.ok else 1}

    async def firmware(self, filename, factory=False):
        assert factory
        return self.blob


async def test_esphome_builds_a_board_only_design(lib):
    dash = FakeDashboard()
    image = await images.image_for("esphome", lib.board("esp32-s3-devkitc-1"), lib, dashboard=dash)

    assert (image.offset, image.data) == (0x0, dash.blob)
    yaml_text = dash.pushed["hw-gate-esp32-s3-devkitc-1"]
    assert "esp32-s3-devkitc-1" in yaml_text and "logger" in yaml_text
    assert "wifi" not in yaml_text, "the gate design carries no secrets"


@pytest.mark.parametrize("dash, match", [
    (None, "ESPHOME_DASHBOARD_URL"),
    (FakeDashboard(configured=False), "ESPHOME_DASHBOARD_URL"),
    (FakeDashboard(ok=False), "ld returned 1"),
    (FakeDashboard(blob=b"\xe9" + b"\x00" * 100), "no merged factory image"),
])
async def test_esphome_build_failures_are_unavailable(lib, dash, match):
    with pytest.raises(images.ImageUnavailable, match=match):
        await images.image_for("esphome", lib.board("esp32-s3-devkitc-1"), lib, dashboard=dash)
