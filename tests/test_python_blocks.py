"""Every `circuitpython:` and `micropython:` block's generated file runs:
setup plus one pass of the loop, against stub modules standing in for
`board` or `machine`, the core modules and the drivers. The generators
already parse the file; this catches what parsing cannot, such as a name
a fragment uses but never imports or defines."""
from __future__ import annotations

import ast
import sys
import types

import pytest

from wirestudio.generate import circuitpython_gen, micropython_gen
from wirestudio.generate.circuitpython_gen import generate_code
from wirestudio.library import default_library
from wirestudio.library.check import synthetic_design

LIB = default_library()
GENERATORS = {"circuitpython": circuitpython_gen.generate_code,
              "micropython": micropython_gen.generate_code}
CASES = [(fw, c.id) for fw in GENERATORS for c in sorted(LIB.list_components(), key=lambda c: c.id)
         if getattr(c, fw) is not None]
PARAMS = {"sx127x": {"frequency": 868000000}}
# Values a stub cannot stand in for: a tuple `%` unpacks, a UART's bytes.
_NO_BYTES = {"read": lambda *a: b""}
# An I2C bus that locks and answers every read with nonzero bytes.
_I2C = {"try_lock": lambda: True,
        "writeto_then_readfrom": lambda addr, out, buf: buf.__setitem__(slice(None), bytes(range(1, len(buf) + 1)))}
ATTRS = {
    ("circuitpython", "bmp180"): _I2C,
    ("circuitpython", "mpu6886"): _I2C,
    ("circuitpython", "axp192"): _I2C,
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


@pytest.mark.parametrize("framework, cid", CASES)
def test_block_runs_one_loop_pass(framework, cid, monkeypatch):
    design = synthetic_design(LIB.component(cid), LIB, on_buses=True)
    design.components[0].params.update(PARAMS.get(cid, {}))
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
