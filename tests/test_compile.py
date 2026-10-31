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


def test_esptool_comes_from_the_lorawan_extra_when_platformio_has_none(monkeypatch, tmp_path):
    """The -full image's PlatformIO never fetched tool-esptoolpy (that happens
    on an upload, which the compile worker never does), so merge_bin found no
    esptool and every LoRaWAN build shipped without a factory image. The
    extra now installs esptool, and the module is the fallback."""
    import sys

    monkeypatch.setattr(cw, "_pio_packages_dir", lambda: tmp_path)
    monkeypatch.setattr(cw.shutil, "which", lambda name: None)
    assert cw._esptool_cmd() == [sys.executable, "-m", "esptool"]


def test_the_factory_merge_runs_on_the_module_esptool(monkeypatch, tmp_path):

    monkeypatch.setattr(cw, "_pio_packages_dir", lambda: tmp_path / "none")
    monkeypatch.setattr(cw.shutil, "which", lambda name: None)
    build = tmp_path / "build"
    build.mkdir()
    for name, size in (("bootloader.bin", 4096), ("partitions.bin", 3072), ("firmware.bin", 8192)):
        (build / name).write_bytes(b"\xe9" + b"\x00" * (size - 1))
    out = tmp_path / "factory.bin"
    assert cw._merge_factory(build, "esp32", out), "merge_bin failed"
    assert out.stat().st_size > 0x10000
