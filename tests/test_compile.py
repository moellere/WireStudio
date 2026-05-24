from __future__ import annotations

import pytest

from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets.lorawan import compile as cw


@pytest.fixture
def lib():
    return default_library()


def _design(board_id: str, **lorawan) -> Design:
    kw = {"target": "lorawan", "lorawan": lorawan} if lorawan or True else {}
    return Design(
        schema_version="0.1",
        id="dev1",
        name="Dev 1",
        board={"library_id": board_id, "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        **kw,
    )


def test_cache_key_stable_and_board_specific(lib):
    k1 = cw.cache_key(_design("ttgo-lora32-v1"), lib)
    k2 = cw.cache_key(_design("ttgo-lora32-v1"), lib)
    k3 = cw.cache_key(_design("heltec-wifi-lora32-v3"), lib)
    assert k1 == k2
    assert k1 != k3


def test_cache_key_changes_with_subband(lib):
    a = cw.cache_key(_design("ttgo-lora32-v1", sub_band=2), lib)
    b = cw.cache_key(_design("ttgo-lora32-v1", sub_band=1), lib)
    assert a != b


def test_status_shape():
    st = cw.platformio_status()
    assert set(st) == {"available", "pio", "version", "reason"}
    assert isinstance(st["available"], bool)


def test_status_unavailable_when_pio_missing(monkeypatch):
    monkeypatch.setattr(cw, "_pio_cmd", lambda: None)
    st = cw.platformio_status()
    assert st["available"] is False
    assert "PlatformIO" in st["reason"]


def test_compile_raises_unavailable_on_miss_without_pio(monkeypatch, tmp_path, lib):
    monkeypatch.setattr(cw, "_pio_cmd", lambda: None)
    with pytest.raises(cw.CompileUnavailable):
        cw.compile_firmware(_design("ttgo-lora32-v1"), lib, cache_dir=tmp_path)


def test_cache_hit_short_circuits_without_pio(monkeypatch, tmp_path, lib):
    # A warm cache must not need the toolchain at all.
    design = _design("ttgo-lora32-v1")
    key = cw.cache_key(design, lib)
    slot = tmp_path / key
    slot.mkdir(parents=True)
    (slot / "firmware.bin").write_bytes(b"\x00fake-bin")
    (slot / "build.log").write_text("cached log")

    monkeypatch.setattr(cw, "_pio_cmd", lambda: None)  # prove no pio needed
    result = cw.compile_firmware(design, lib, cache_dir=tmp_path)
    assert result.ok and result.cache_hit
    assert result.bin_path == slot / "firmware.bin"
    assert result.log == "cached log"
    assert result.env == "ttgo-lora32-v1"
