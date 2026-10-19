"""Every `circuitpython:` block's generated code.py runs: setup plus one
pass of the loop, against stub modules standing in for `board`, the core
modules and the bundle drivers. The generator already parses the file;
this catches what parsing cannot, such as a name a fragment uses but
never imports or defines."""
from __future__ import annotations

import ast
import sys
import types

import pytest

from wirestudio.generate.circuitpython_gen import generate_code
from wirestudio.library import default_library
from wirestudio.library.check import synthetic_design

LIB = default_library()
CP_IDS = sorted(c.id for c in LIB.list_components() if c.circuitpython is not None)
PARAMS = {"sx127x": {"frequency": 868000000}}
# Attributes a real driver returns as a tuple, which `%` unpacks.
ATTRS = {"sht4x": {"measurements": (21.5, 40.0)}}


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
    clock = iter(range(10**6))
    mod.monotonic = lambda: float(next(clock))

    def sleep(seconds):
        raise _Stop

    mod.sleep = sleep
    return mod


@pytest.mark.parametrize("cid", CP_IDS)
def test_block_runs_one_loop_pass(cid, monkeypatch):
    design = synthetic_design(LIB.component(cid), LIB, on_buses=True)
    design.components[0].params.update(PARAMS.get(cid, {}))
    out = generate_code(design, LIB)
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
    monkeypatch.setattr(Stub, "attrs", ATTRS.get(cid, {}))
    with pytest.raises(_Stop):
        exec(compile(code, "code.py", "exec"), {"__name__": "__main__"})


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
