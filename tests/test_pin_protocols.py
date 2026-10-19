"""The bit-banged and sampled parts with no driver carry datasheet code,
the same text in the `circuitpython:` and `micropython:` blocks; only
the pin access differs. Each framework's generated setup runs here
against recording pins: the waveforms decode to the datasheet's command
bytes, and the decoders turn known frames and samples into values."""
from __future__ import annotations

import math
import sys
import types

import pytest

from tests.test_python_blocks import StubModule
from wirestudio.generate import circuitpython_gen, micropython_gen
from wirestudio.library import default_library
from wirestudio.library.check import synthetic_design

LIB = default_library()
GENERATORS = {"circuitpython": circuitpython_gen.generate_code,
              "micropython": micropython_gen.generate_code}
FRAMEWORKS = pytest.mark.parametrize("framework", list(GENERATORS))


class Clock:
    def __init__(self):
        self.ms = 0

    def module(self) -> types.ModuleType:
        mod = types.ModuleType("time")
        mod.ticks_ms = lambda: self.ms
        mod.ticks_add = lambda a, b: a + b
        mod.ticks_diff = lambda a, b: a - b
        mod.sleep_ms = mod.sleep_us = lambda t: None
        mod.monotonic = lambda: self.ms / 1000
        return mod


def setup_scope(cid: str, framework: str, monkeypatch, params: dict | None = None,
                clock: Clock | None = None) -> tuple[dict, list[tuple[int, int]], dict[str, int]]:
    """Run a generated file's setup; return its scope, the log of
    (gpio, level) every pin was driven to, and the wiring."""
    design = synthetic_design(LIB.component(cid), LIB, on_buses=True)
    design.components[0].params.update(params or {})
    out = GENERATORS[framework](design, LIB)
    assert out["warnings"] == []
    log: list[tuple[int, int]] = []

    class MpPin:
        OUT, IN, OPEN_DRAIN, PULL_UP, IRQ_FALLING, IRQ_RISING = 1, 0, 2, 3, 4, 5

        def __init__(self, n, *a, value=None, **k):
            self.n = n
            if value is not None:
                self(value)

        def __call__(self, v=None):
            if v is not None:
                log.append((self.n, int(v)))

        def irq(self, trigger=None, handler=None):
            self.handler = handler

    class CpPin:
        def __init__(self, name):
            self.n = int(name[2:])

        def switch_to_output(self, value=False, **k):
            log.append((self.n, int(value)))

        @property
        def value(self):
            return 0

        @value.setter
        def value(self, v):
            log.append((self.n, int(v)))

    for name in ("machine", "board", "digitalio", "analogio", "busio"):
        monkeypatch.setitem(sys.modules, name, StubModule(name))
    sys.modules["machine"].Pin = MpPin
    sys.modules["board"].__getattr__ = lambda name: name  # P(n) finds "IO<n>"
    sys.modules["digitalio"].DigitalInOut = CpPin
    monkeypatch.setitem(sys.modules, "time", (clock or Clock()).module())
    scope: dict = {"__name__": "__main__"}
    exec(compile(out["code"].split("\nwhile True:")[0], "main.py", "exec"), scope)
    wiring = {c.pin_role: int(c.target.pin[4:]) for c in design.connections if c.target.kind == "gpio"}
    return scope, log, wiring


def _frames_tm1637(log, clk, dio):
    """Bytes between start and stop conditions, LSB first, every ninth
    clock the ACK."""
    level, frames, bits = {clk: 1, dio: 1}, [], None
    for n, v in log:
        if n == dio and level[clk] and level[dio] and not v:
            bits = []
        elif n == dio and level[clk] and not level[dio] and v and bits is not None:
            # The stop condition's own CLK rise leaves one bit past the last ACK.
            frames.append([sum(b << i for i, b in enumerate(bits[k:k + 8]))
                           for k in range(0, len(bits) - len(bits) % 9, 9)])
            bits = None
        elif n == clk and v and not level[clk] and bits is not None:
            bits.append(level[dio])
        level[n] = v
    return frames


def _frames_tm1638(log, stb, clk, dio):
    level, frames, bits = {stb: 1, clk: 1, dio: 1}, [], []
    for n, v in log:
        if n == stb and not v:
            bits = []
        elif n == stb and v and not level[stb]:
            frames.append([sum(b << i for i, b in enumerate(bits[k:k + 8])) for k in range(0, len(bits), 8)])
        elif n == clk and v and not level[clk] and not level[stb]:
            bits.append(level[dio])
        level[n] = v
    return frames


@FRAMEWORKS
def test_tm1637_sends_the_datasheet_commands(framework, monkeypatch):
    scope, log, wiring = setup_scope("tm1637", framework, monkeypatch, {"intensity": 4})
    dashes = [0x40, [0xC0, 0x40, 0x40, 0x40, 0x40], 0x8C]
    assert _frames_tm1637(log, wiring["CLK"], wiring["DIO"]) == [[dashes[0]], dashes[1], [dashes[2]]]
    log.clear()
    scope["dut_show"]("1234")
    assert _frames_tm1637(log, wiring["CLK"], wiring["DIO"])[1] == [0xC0, 0x06, 0x5B, 0x4F, 0x66]


@FRAMEWORKS
def test_tm1638_sends_the_datasheet_commands(framework, monkeypatch):
    _, log, wiring = setup_scope("tm1638", framework, monkeypatch, {"intensity": 9})
    assert _frames_tm1638(log, wiring["STB"], wiring["CLK"], wiring["DIO"]) == [
        [0x40], [0xC0] + [0x40, 0x00] * 8, [0x8F]]  # brightness capped at 7


@FRAMEWORKS
@pytest.mark.parametrize("point, duration, per_volt, window", [
    (None, None, 100.0, 0.2),
    ("0.05 -> 30", "1s", 600.0, 1.0),
])
def test_ct_clamp_takes_the_rms_about_the_bias_and_calibrates(framework, point, duration, per_volt, window,
                                                              monkeypatch):
    params = {k: v for k, v in (("calibration_point", point), ("sample_duration", duration)) if v}
    scope, _, _ = setup_scope("ct_clamp", framework, monkeypatch, params)
    assert scope["dut_amps_per_volt"] == pytest.approx(per_volt)
    assert scope["dut_window"] == pytest.approx(window)
    sine = [1.65 + 0.1 * math.sin(2 * math.pi * k / 100) for k in range(1000)]
    assert scope["dut_rms"](sine) == pytest.approx(0.1 / math.sqrt(2))
    assert scope["dut_rms"]([]) == 0.0


def _wiegand(value: int, n: int) -> list[int]:
    """Even parity over the first half of the frame, odd over the last
    (37 bits: 19 each, sharing the middle bit), as ESPHome checks them."""
    data = [value >> i & 1 for i in range(n - 3, -1, -1)]
    first, last = {26: (12, 12), 34: (16, 16), 37: (18, 17)}[n]
    return [sum(data[:first]) % 2] + data + [1 - sum(data[last:]) % 2]


def test_wiegand_frames_on_the_gap_and_decodes_tags_and_keys(monkeypatch):
    clock = Clock()
    scope, _, _ = setup_scope("wiegand", "micropython", monkeypatch, clock=clock)
    d0, d1, edge = scope["dut_d0"], scope["dut_d1"], scope["dut_edge"]
    for frame in (_wiegand(1 << 16 | 12345, 26), [1, 0, 1, 1]):
        for bit in frame:
            clock.ms += 2
            edge(d1 if bit else d0)
        clock.ms += 30
    clock.ms += 1  # the next edge closes the second frame
    edge(d0)
    decode = scope["dut_decode"]
    assert [decode(f) for f in scope["dut_frames"]] == [("tag", 1 << 16 | 12345), ("key", "#")]
    assert decode(_wiegand(0xDEADBEEF, 34)) == ("tag", 0xDEADBEEF)
    assert decode(_wiegand(0x5DEADBEEF, 37)) == ("tag", 0x5DEADBEEF)
    bad = _wiegand(42, 26)
    bad[0] ^= 1
    assert decode(bad) is None
    assert decode([1, 0, 0, 0, 0, 1, 1, 1]) == ("key", "7")  # 8-bit: inverted key, then the key
    assert decode([1, 0, 0, 0, 0, 1, 1, 0]) is None
