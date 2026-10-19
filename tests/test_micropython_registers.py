"""The MicroPython blocks that talk to the chip directly (no driver) are
datasheet register code. Each generated main.py runs here against a fake
`machine` bus for one pass of its loop: the bytes it writes are the
datasheet's commands, and the readings it prints are the datasheet's own
worked examples decoded."""
from __future__ import annotations

import sys
import types

import pytest

from wirestudio.generate.micropython_gen import generate_code
from wirestudio.library import default_library
from wirestudio.library.check import synthetic_design


class _Stop(Exception):
    pass


class FakeI2C:
    def __init__(self, **_):
        self.writes: list[tuple[int, bytes]] = []
        self.reads: dict[int, list[bytes]] = {}

    def writeto(self, addr, data):
        self.writes.append((addr, bytes(data)))

    def readfrom(self, addr, n):
        data = self.reads[addr].pop(0)
        assert len(data) == n
        return data


class FakeSPI:
    def __init__(self, **_):
        self.written: list[bytes] = []
        self.to_read: list[bytes] = []

    def write(self, data):
        self.written.append(bytes(data))

    def read(self, n):
        data = self.to_read.pop(0)
        assert len(data) == n
        return data

    def write_readinto(self, out, buf):
        self.written.append(bytes(out))
        buf[:] = self.to_read.pop(0)


class FakePin:
    OUT = 1
    IN = 0
    PULL_UP = 2

    def __init__(self, n, *a, **k):
        self.n, self.level = n, k.get("value")

    def __call__(self, v=None):
        if v is not None:
            self.level = v
        return self.level


def run(component: str, params: dict, prepare, monkeypatch, capsys) -> tuple[dict, list[str]]:
    """Generate main.py for one component, run it for one loop pass with
    the fake bus `prepare` primes, and return the bus objects and output."""
    lib = default_library()
    design = synthetic_design(lib.component(component), lib, on_buses=True)
    design.components[0].params.update(params)
    code = generate_code(design, lib)["code"]
    buses: dict = {}

    def make(kind):
        def ctor(*a, **k):
            obj = kind(**k)
            prepare(obj)
            buses.setdefault(kind.__name__, obj)
            return obj
        return ctor

    machine = types.ModuleType("machine")
    machine.Pin = FakePin
    machine.SoftI2C = make(FakeI2C)
    machine.SoftSPI = make(FakeSPI)
    fake_time = types.ModuleType("time")
    fake_time.sleep_ms = lambda ms: None

    def sleep(_s):
        raise _Stop

    fake_time.sleep = sleep
    monkeypatch.setitem(sys.modules, "machine", machine)
    monkeypatch.setitem(sys.modules, "time", fake_time)
    with pytest.raises(_Stop):
        exec(compile(code, "main.py", "exec"), {"__name__": "__main__"})
    monkeypatch.undo()
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln]
    return buses, lines


def test_bh1750_powers_on_and_reads_continuous_high_resolution(monkeypatch, capsys):
    def prepare(i2c):
        i2c.reads[0x23] = [b"\x01\x2c"]  # 300 counts
    buses, out = run("bh1750", {}, prepare, monkeypatch, capsys)
    assert buses["FakeI2C"].writes == [(0x23, b"\x01"), (0x23, b"\x10")]
    assert out[-1].endswith(": 250 lux")


def test_htu21d_decodes_the_datasheet_examples(monkeypatch, capsys):
    # Datasheet: 0x683A is 24.7C, 0x4E85 is 32.3 %RH (status bits masked).
    def prepare(i2c):
        i2c.reads[0x40] = [b"\x68\x3a\x7c", b"\x4e\x85\x6b"]
    buses, out = run("htu21d", {}, prepare, monkeypatch, capsys)
    assert buses["FakeI2C"].writes == [(0x40, b"\xf3"), (0x40, b"\xf5")]
    assert out[-1].endswith(": 24.7C 32%")


@pytest.mark.parametrize("raw, shown", [
    (b"\x01\x90\x00\x00", "25.00C"),     # datasheet: +25.00C
    (b"\xf0\x60\x00\x00", "-250.00C"),   # datasheet: -250.00C
    (b"\x00\x01\x00\x01", "fault"),      # D16 set, open thermocouple
])
def test_max31855_decodes_the_datasheet_examples(raw, shown, monkeypatch, capsys):
    def prepare(spi):
        spi.to_read = [raw]
    _, out = run("max31855", {}, prepare, monkeypatch, capsys)
    assert out[-1].endswith(f": {shown}")


def test_mcp3008_sends_start_single_ended_channel_and_reads_ten_bits(monkeypatch, capsys):
    lib = default_library()
    design = synthetic_design(lib.component("mcp3008"), lib, on_buses=True)
    code = generate_code(design, lib)["code"]
    spi = FakeSPI()
    spi.to_read = [b"\x00\x02\x34"]
    machine = types.ModuleType("machine")
    machine.Pin = FakePin
    machine.SoftSPI = lambda **k: spi
    fake_time = types.ModuleType("time")
    monkeypatch.setitem(sys.modules, "machine", machine)
    monkeypatch.setitem(sys.modules, "time", fake_time)
    setup = code.split("\nwhile True:")[0]
    scope: dict = {"__name__": "__main__"}
    exec(compile(setup, "main.py", "exec"), scope)
    assert scope["dut_read"](3) == 0x234
    assert spi.written == [bytes([0x01, 0xB0, 0x00])]


@pytest.mark.parametrize("model, command", [
    ("sgp40", b"\x26\x0f\x80\x00\xa2\x66\x66\x93"),
    ("sgp41", b"\x26\x19\x80\x00\xa2\x66\x66\x93"),
])
def test_sgp4x_measures_raw_with_the_default_compensation(model, command, monkeypatch, capsys):
    def prepare(i2c):
        i2c.reads[0x59] = [b"\x80\x00\xa2"]
    buses, out = run("sgp4x", {"model": model}, prepare, monkeypatch, capsys)
    assert buses["FakeI2C"].writes == [(0x59, command)]
    assert out[-1].endswith(": raw VOC 32768")


@pytest.mark.parametrize("variant, released", [("pcf8574", b"\xff"), ("pcf8575", b"\xff\xff")])
def test_pcf857x_releases_every_pin(variant, released, monkeypatch, capsys):
    buses, _ = run("pcf8574", {"variant": variant, "address": "0x21"}, lambda i2c: None,
                   monkeypatch, capsys)
    assert buses["FakeI2C"].writes == [(0x21, released)]


def test_apa102_frames_the_strip_in_its_colour_order(monkeypatch, capsys):
    buses, _ = run("apa102", {"num_leds": 2, "rgb_order": "BGR"}, lambda spi: None,
                   monkeypatch, capsys)
    led = bytes([0xFF, 0, 8, 0])  # full brightness, B G R = 0, 8, 0
    assert buses["FakeSPI"].written == [bytes(4) + led * 2 + b"\xff" * 4]
    buses, _ = run("apa102", {"num_leds": 1, "rgb_order": "RGB"}, lambda spi: None,
                   monkeypatch, capsys)
    assert buses["FakeSPI"].written == [bytes(4) + bytes([0xFF, 0, 8, 0]) + b"\xff" * 4]
