"""Every `circuitpython:` and `micropython:` block's generated file runs:
setup plus one pass of the loop, against stub modules standing in for
`board` or `machine`, the core modules and the drivers. The generators
already parse the file; this catches what parsing cannot, such as a name
a fragment uses but never imports or defines."""
from __future__ import annotations

import ast
import json
import sys
import types
from pathlib import Path

import pytest

from wirestudio.generate import circuitpython_gen, micropython_gen
from wirestudio.generate.circuitpython_gen import generate_code
from wirestudio.library import default_library
from wirestudio.library.check import synthetic_design

LIB = default_library()
EXAMPLES = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"
GENERATORS = {"circuitpython": circuitpython_gen.generate_code,
              "micropython": micropython_gen.generate_code}
CASES = [(fw, c.id) for fw in GENERATORS for c in sorted(LIB.list_components(), key=lambda c: c.id)
         if getattr(c, fw) is not None]
PARAMS = {"sx127x": {"frequency": 868000000}, ("circuitpython", "i2s_microphone"): {"pdm": True}}
# Values a stub cannot stand in for: a tuple `%` unpacks, a UART's bytes.
_NO_BYTES = {"read": lambda *a: b""}
# An I2C bus that locks and answers every read with nonzero bytes.
_I2C = {"try_lock": lambda: True,
        "writeto_then_readfrom": lambda addr, out, buf: buf.__setitem__(slice(None), bytes(range(1, len(buf) + 1)))}
ATTRS = {
    ("circuitpython", "bmp180"): _I2C,
    ("circuitpython", "mpu6886"): _I2C,
    ("circuitpython", "axp192"): _I2C,
    ("circuitpython", "lcd_pcf8574"): _I2C,
    ("circuitpython", "xpt2046"): {"try_lock": lambda: True},
    ("circuitpython", "rc522"): {"try_lock": lambda: True},
    ("circuitpython", "esp32_camera"): {"take": lambda timeout: b"\xff\xd8"},
    ("micropython", "i2s_microphone"): {"readinto": lambda buf: len(buf)},
    ("circuitpython", "sht4x"): {"measurements": (21.5, 40.0)},
    ("micropython", "sht4x"): {"measurements": (21.5, 40.0)},
    ("micropython", "sht3xd"): {"get_temp_humi": lambda: (21.5, 40.0)},
    ("micropython", "pmsx003"): _NO_BYTES,
    ("micropython", "uart_gps"): _NO_BYTES,
}


class _Stop(Exception):
    pass


class _StubType(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return Stub()


class Stub(metaclass=_StubType):
    """Any attribute, call, item or number a driver object might yield."""

    attrs: dict = {}

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self.attrs.get(name, Stub())

    def __call__(self, *a, **k):
        return Stub()

    def __getitem__(self, key):
        return Stub()

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False

    def __float__(self):
        return 1.0

    def __int__(self):
        return 1

    __index__ = __int__

    def _num(self, *a):
        return 1

    __add__ = __radd__ = __sub__ = __rsub__ = __mul__ = __rmul__ = _num
    __truediv__ = __rtruediv__ = __floordiv__ = __rfloordiv__ = _num
    __lshift__ = __rshift__ = __and__ = __or__ = __xor__ = _num
    __rlshift__ = __rrshift__ = __rand__ = __ror__ = __rxor__ = _num
    __lt__ = __le__ = __gt__ = __ge__ = _num


class StubModule(types.ModuleType):
    """A capitalised name is a class (so `isinstance` and class constants
    work); anything else an object."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return type(name, (Stub,), {}) if name[:1].isupper() else Stub()


def _fake_time() -> types.ModuleType:
    mod = types.ModuleType("time")
    clock = iter(range(0, 10**9, 100))
    mod.monotonic = lambda: float(next(clock))
    mod.ticks_ms = lambda: next(clock)
    mod.ticks_diff = lambda a, b: a - b
    mod.ticks_add = lambda a, b: a + b
    mod.sleep_ms = mod.sleep_us = lambda t: None

    def sleep(seconds):
        if seconds == 5:  # the main loop's pause: one pass is done
            raise _Stop

    mod.sleep = sleep
    return mod


def _design_for(cid: str):
    """The check design for `cid`; a part that hangs off a hub gets the
    hub's check design with the part added and connected to it."""
    comp = LIB.component(cid)
    hub = next((p.parent_library_id for p in comp.electrical.pins if p.kind == "hub_ref"), None)
    if hub is None:
        return synthetic_design(comp, LIB, on_buses=True)
    design = synthetic_design(LIB.component(hub), LIB, on_buses=True)
    data = design.model_dump()
    params = {k: s["default"] for k, s in comp.params_schema.items() if isinstance(s, dict) and "default" in s}
    data["components"].append({"id": "child", "library_id": cid, "label": comp.name, "params": params})
    data["connections"].append({"component_id": "child", "pin_role": "HUB",
                                "target": {"kind": "component", "component_id": "dut"}})
    return type(design).model_validate(data)


@pytest.mark.parametrize("framework, cid", CASES)
def test_block_runs_one_loop_pass(framework, cid, monkeypatch):
    design = _design_for(cid)
    design.components[0].params.update(PARAMS.get((framework, cid), PARAMS.get(cid, {})))
    out = GENERATORS[framework](design, LIB)
    assert out["warnings"] == [], out["warnings"]
    code = out["code"]
    for node in ast.walk(ast.parse(code)):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
            [node.module] if isinstance(node, ast.ImportFrom) else []
        for name in names:
            parts = name.split(".")
            for i in range(1, len(parts) + 1):
                if parts[0] != "time":
                    monkeypatch.setitem(sys.modules, ".".join(parts[:i]), StubModule(".".join(parts[:i])))
    monkeypatch.setitem(sys.modules, "time", _fake_time())
    monkeypatch.setattr(Stub, "attrs", ATTRS.get((framework, cid), {}))
    with pytest.raises(_Stop):
        exec(compile(code, "main.py", "exec"), {"__name__": "__main__"})


def test_unsupported_variant_is_skipped_with_its_reason():
    design = synthetic_design(LIB.component("ili9xxx"), LIB, on_buses=True)
    design.components[0].params["model"] = "ILI9488"
    out = generate_code(design, LIB)
    assert out["warnings"] == ["dut (ili9xxx): adafruit_ili9341 drives the ILI9341 only, not the ILI9488; skipped"]
    assert "busio.SPI" not in out["code"]  # the skipped part's bus is not emitted


def test_displays_release_the_builtin_display_once():
    design = synthetic_design(LIB.component("st7789"), LIB, on_buses=True)
    code = generate_code(design, LIB)["code"]
    assert code.count("displayio.release_displays()") == 1
    assert code.index("release_displays") < code.index("fourwire.FourWire(")


def test_ds18b20_shares_its_bus_and_picks_its_rom_by_address():
    design = synthetic_design(LIB.component("ds18b20"), LIB, on_buses=True)
    design.components[0].params["address"] = "0x1c0000031edd2a28"
    out = generate_code(design, LIB)
    assert out["warnings"] == []
    assert "ow_1wire0 = OneWireBus(P(" in out["code"]
    assert 'd.rom == (0x1c0000031edd2a28).to_bytes(8, "little")' in out["code"]
    assert (0x1c0000031edd2a28).to_bytes(8, "little")[0] == 0x28  # DS18B20 family code first


def test_micropython_ds18b20_shares_its_bus_and_reads_its_rom():
    design = synthetic_design(LIB.component("ds18b20"), LIB, on_buses=True)
    design.components[0].params["address"] = "0x1c0000031edd2a28"
    out = micropython_gen.generate_code(design, LIB)
    assert out["warnings"] == []
    assert "ow_1wire0 = onewire.OneWire(Pin(" in out["code"]
    assert "ds18x20.DS18X20(ow_1wire0)" in out["code"]
    assert 'dut_roms = [(0x1c0000031edd2a28).to_bytes(8, "little")]' in out["code"]
    assert "from machine import Pin\n" in out["code"]  # OneWire is not a machine name


def test_micropython_unsupported_variant_is_skipped_without_its_bus():
    design = synthetic_design(LIB.component("st7789"), LIB, on_buses=True)
    design.components[0].params.update({"model": "ADAFRUIT_RR_280X240"})
    out = micropython_gen.generate_code(design, LIB)
    assert out["warnings"] == ["dut (st7789): st7789py has no 240x280 panel; skipped"]
    assert "SoftSPI(" not in out["code"]


def test_micropython_ir_follows_the_board():
    rx = synthetic_design(LIB.component("remote_receiver"), LIB, on_buses=True)
    tx = synthetic_design(LIB.component("remote_transmitter"), LIB, on_buses=True)
    assert "NEC_8.Timer_id = 0" in micropython_gen.generate_code(rx, LIB)["code"]
    rx.board.library_id = tx.board.library_id = "wemos-d1-mini"
    assert "Timer_id" not in micropython_gen.generate_code(rx, LIB)["code"]  # ESP8266 keeps its soft timer
    assert micropython_gen.generate_code(tx, LIB)["warnings"] == [
        "dut (remote_transmitter): ir_tx needs the ESP32 RMT peripheral, which the ESP8266 lacks; skipped"]


@pytest.mark.parametrize("framework", list(GENERATORS))
def test_adc_applies_the_multiply_filters(framework):
    design = synthetic_design(LIB.component("adc"), LIB, on_buses=True)
    plain = GENERATORS[framework](design, LIB)["code"]
    design.components[0].params["filters"] = [{"multiply": 2.0}, {"offset": 0.1}, {"multiply": 1.5}]
    scaled = GENERATORS[framework](design, LIB)["code"]
    assert " * 3.0))" in scaled and " * 3.0))" not in plain


def _example(name: str):
    from wirestudio.model import Design
    return Design.model_validate(json.loads((EXAMPLES / f"{name}.json").read_text()))


def test_i2s_parts_take_their_clocks_from_the_bus():
    design = _example("esp32-audio")  # i2s0: LRCLK GPIO33, BCLK GPIO25; the amp's DIN on GPIO32
    cp = circuitpython_gen.generate_code(design, LIB)
    mp = micropython_gen.generate_code(design, LIB)
    assert cp["warnings"] == [] and mp["warnings"] == []
    assert "amp = audiobusio.I2SOut(P(25), P(33), P(32))" in cp["code"]
    assert "amp = I2S(0, sck=Pin(25), ws=Pin(33), sd=Pin(32), mode=I2S.TX," in mp["code"]
    design.buses[[b.type for b in design.buses].index("i2s")].lrclk = None
    assert "amp.LRCLK: i2s bus i2s0 has no lrclk pin; run Solve Pins; skipped" in \
        micropython_gen.generate_code(design, LIB)["warnings"]


@pytest.mark.parametrize("framework", list(GENERATORS))
def test_microphone_variant_each_framework_cannot_read_is_refused(framework):
    design = synthetic_design(LIB.component("i2s_microphone"), LIB, on_buses=True)
    readable = {"circuitpython": True, "micropython": False}[framework]  # PDM on one, I2S on the other
    for pdm in (True, False):
        design.components[0].params["pdm"] = pdm
        warnings = GENERATORS[framework](design, LIB)["warnings"]
        assert (warnings == []) is (pdm is readable), warnings


def test_micropython_microphone_reads_24_bit_samples_from_32_bit_slots(monkeypatch):
    design = synthetic_design(LIB.component("i2s_microphone"), LIB, on_buses=True)
    code = micropython_gen.generate_code(design, LIB)["code"].split("\nwhile True:")[0]
    monkeypatch.setitem(sys.modules, "machine", StubModule("machine"))
    scope: dict = {"__name__": "__main__"}
    exec(compile(code, "main.py", "exec"), scope)
    raw = bytes([0x00, 0x10, 0x00, 0x00, 0x00, 0xF0, 0xFF, 0xFF, 0xAA])  # +16, -16, a torn slot
    assert scope["dut_samples"](raw, len(raw)) == [16, -16]
    assert scope["dut_level"]([16, -16]) == 16.0


@pytest.mark.parametrize("framework", list(GENERATORS))
def test_amplifier_plays_a_444_hz_tone(framework, monkeypatch):
    design = synthetic_design(LIB.component("max98357a"), LIB, on_buses=True)
    code = GENERATORS[framework](design, LIB)["code"].split("\nwhile True:")[0]
    for name in ("board", "digitalio", "audiobusio", "audiocore", "machine", "array"):
        monkeypatch.setitem(sys.modules, name, StubModule(name))
    monkeypatch.setitem(sys.modules, "time", _fake_time())
    scope: dict = {"__name__": "__main__"}
    exec(compile(code, "main.py", "exec"), scope)
    tone = scope["dut_tone"]
    assert len(tone) == 36 and 16000 / len(tone) == pytest.approx(444.4, abs=0.1)
    assert max(tone) == 8000 and tone[0] == 0
    if framework == "micropython":
        assert scope["dut_wave"][2:4] == (tone[1] & 0xFFFF).to_bytes(2, "little")


def test_camera_maps_resolution_and_clock():
    design = _example("esp32cam")
    design.components[0].params.update({"resolution": "1600x1200", "xclk_frequency": "10MHz", "vertical_flip": True})
    code = circuitpython_gen.generate_code(design, LIB)["code"]
    assert "frame_size=espcamera.FrameSize.UXGA," in code
    assert "external_clock_frequency=10000000," in code
    assert "cam.vflip = True" in code


def test_hub_children_render_after_their_hub_and_need_one():
    design = _design_for("tuya_sensor")
    data = design.model_dump()
    data["components"].reverse()  # child listed first
    reordered = type(design).model_validate(data)
    for generate in GENERATORS.values():
        out = generate(reordered, LIB)
        assert out["warnings"] == []
        assert out["code"].index("def dut_poll") < out["code"].index("child_dp =")
        assert '"%g" % (child_value' not in out["code"]  # no multiply filter, no scaling
    data["connections"] = [c for c in data["connections"] if c["component_id"] != "child"]
    orphan = type(design).model_validate(data)
    for generate in GENERATORS.values():
        assert generate(orphan, LIB)["warnings"] == ["child: not connected to its hub; skipped"]


def test_tuya_sensor_scales_by_its_multiply_filters():
    code = micropython_gen.generate_code(_example("tuya-smart-plug"), LIB)["code"]
    assert '"%g" % (watts_value * 0.1)' in code


@pytest.mark.parametrize("framework, gain", [("circuitpython", "16"), ("micropython", "5")])
def test_ads1115_channels_set_their_own_gain_and_mux(framework, gain):
    code = GENERATORS[framework](_example("analog-node"), LIB)["code"]  # shunt_i: A2_A3 at 0.256 V
    assert f"shunt_i_gain = {gain}\n" in code
    assert "    ext_adc.gain = shunt_i_gain\n    return ext_adc_read(2, 3)" in code
    assert "return ext_adc_read(0, None)" in code  # panel_v: A0_GND


@pytest.mark.parametrize("framework", list(GENERATORS))
def test_mcp3008_channel_scales_to_its_reference(framework):
    design = _design_for("mcp3008_channel")
    design.components[1].params.update({"number": 5, "reference_voltage": "5.0V"})
    out = GENERATORS[framework](design, LIB)
    assert out["warnings"] == []
    if framework == "micropython":
        assert "(dut_read(5) / 1023 * child_vref)" in out["code"]
    else:
        assert "child = AnalogIn(dut, 5)" in out["code"]
    assert "child_vref = 5.0\n" in out["code"]
