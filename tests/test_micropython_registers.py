"""The MicroPython blocks that talk to the chip or the wire directly (no
driver) are datasheet code. Each generated main.py runs here against a
fake `machine`: the bytes and pin levels it writes are the datasheet's,
and the readings it decodes are the datasheet's own worked examples, a
PMS frame and the NMEA reference sentence among them."""
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


class RecordingPin:
    """A Pin that logs every level it is driven to, shared per GPIO."""

    log: list[tuple[int, int]] = []
    OUT, IN, PULL_UP, PULL_DOWN = 1, 0, 2, 3

    def __init__(self, n, *a, value=None, **k):
        self.n = n
        if value is not None:
            self(value)

    def __call__(self, v=None):
        if v is not None:
            RecordingPin.log.append((self.n, int(v)))


class FakePWM:
    def __init__(self, pin, freq=None):
        self.pin, self.duty = pin, None

    def duty_u16(self, v):
        self.duty = v


def setup_scope(component: str, params: dict, monkeypatch, **machine_attrs) -> tuple[dict, dict]:
    """Run only the setup part of a generated main.py, against a fake
    `machine`; return the module scope and the wiring (role -> GPIO)."""
    lib = default_library()
    design = synthetic_design(lib.component(component), lib, on_buses=True)
    design.components[0].params.update(params)
    code = generate_code(design, lib)["code"]
    machine = types.ModuleType("machine")
    machine.Pin = RecordingPin
    for name, value in machine_attrs.items():
        setattr(machine, name, value)
    fake_time = types.ModuleType("time")
    clock = iter(range(0, 10**9, 100))
    fake_time.ticks_ms = lambda: next(clock)
    fake_time.ticks_add = lambda a, b: a + b
    fake_time.ticks_diff = lambda a, b: a - b
    fake_time.sleep_ms = lambda ms: None
    monkeypatch.setitem(sys.modules, "machine", machine)
    monkeypatch.setitem(sys.modules, "time", fake_time)
    RecordingPin.log = []
    scope: dict = {"__name__": "__main__"}
    exec(compile(code.split("\nwhile True:")[0], "main.py", "exec"), scope)
    wiring = {c.pin_role: int(c.target.pin[4:]) for c in design.connections if c.target.kind == "gpio"}
    return scope, wiring


@pytest.mark.parametrize("decay, forward, reverse", [
    # DRV8833 truth table at half throttle: (IN1, IN2) duty.
    ("fast", (32767, 0), (0, 32767)),
    ("slow", (65535, 32768), (32768, 65535)),
])
def test_hbridge_follows_the_drv8833_truth_table(decay, forward, reverse, monkeypatch):
    scope, _ = setup_scope("hbridge", {"decay_mode": decay}, monkeypatch, PWM=FakePWM)
    in1, in2, throttle = scope["dut_in1"], scope["dut_in2"], scope["dut_throttle"]
    assert (in1.duty, in2.duty) == ((0, 0) if decay == "fast" else (65535, 65535))  # coast / brake
    throttle(0.5)
    assert (in1.duty, in2.duty) == forward
    throttle(-0.5)
    assert (in1.duty, in2.duty) == reverse


@pytest.mark.parametrize("mode, energised", [
    ("WAVE_DRIVE", ["B", "C", "D", "A"]),
    ("FULL_STEP", ["BC", "CD", "AD", "AB"]),
    ("HALF_STEP", ["AB", "B", "BC", "C", "CD", "D", "AD", "A"]),
])
def test_uln2003_steps_the_coils_in_order(mode, energised, monkeypatch):
    scope, wiring = setup_scope("uln2003", {"step_mode": mode}, monkeypatch)
    coil = {wiring[r]: r for r in "ABCD"}
    seen = []
    for _ in energised:
        RecordingPin.log = []
        scope["dut_step"]()
        seen.append("".join(sorted(coil[n] for n, v in RecordingPin.log if v)))
    assert seen == energised
    RecordingPin.log = []
    scope["dut_step"](-1)
    assert "".join(sorted(coil[n] for n, v in RecordingPin.log if v)) == energised[-2]


@pytest.mark.parametrize("count", [1, 2])
def test_sn74hc595_shifts_msb_first_then_latches(count, monkeypatch):
    scope, wiring = setup_scope("sn74hc595", {"sr_count": count}, monkeypatch)
    RecordingPin.log = []
    value = 0xA1C3 if count == 2 else 0xA1
    scope["dut_write"](value)
    data, clock, latch = wiring["DATA"], wiring["CLOCK"], wiring["LATCH"]
    level, shifted = {}, []
    for n, v in RecordingPin.log:
        if n == clock and v and not level.get(clock):
            shifted.append(level[data])
        if n == latch and v:
            assert len(shifted) == 8 * count
        level[n] = v
    assert shifted == [(value >> b) & 1 for b in range(8 * count - 1, -1, -1)]
    assert [v for n, v in RecordingPin.log if n == latch] == [1, 0]


def _pms_frame(pm1, pm25, pm10):
    body = bytes([0x42, 0x4D, 0x00, 0x1C]) + bytes(6) + b"".join(
        v.to_bytes(2, "big") for v in (pm1, pm25, pm10)) + bytes(14)
    return body + sum(body).to_bytes(2, "big")


class FakeUART:
    def __init__(self, *chunks):
        self.chunks = list(chunks)

    def read(self):
        return self.chunks.pop(0) if self.chunks else None


def test_pmsx003_reads_the_last_valid_frame(monkeypatch):
    scope, _ = setup_scope("pmsx003", {}, monkeypatch, UART=lambda *a, **k: FakeUART())
    good, newer = _pms_frame(5, 12, 20), _pms_frame(6, 13, 21)
    bad = bytearray(_pms_frame(9, 9, 9))
    bad[-1] ^= 1
    scope["uart_uart_bus0"].chunks = [b"\x00\x42" + good[:7] + good + newer + bytes(bad) + newer[:10]]
    assert scope["dut_read"]() == [6, 13, 21]
    scope["uart_uart_bus0"].chunks = [bytes(bad)]
    assert scope["dut_read"]() is None
    assert scope["dut_read"]() is None  # nothing pending


def test_uart_gps_reads_a_checked_rmc_fix(monkeypatch):
    # The NMEA reference RMC sentence, 48 07.038' N 11 31.000' E.
    rmc = b"$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A\r\n"
    scope, _ = setup_scope("uart_gps", {}, monkeypatch, UART=lambda *a, **k: FakeUART())
    uart = scope["uart_uart_bus0"]
    uart.chunks = [b"stale", b"$GPGGA,1*00\r\n" + rmc[:30], rmc[30:]]
    lat, lon = scope["dut_fix"]()
    assert (round(lat, 4), round(lon, 4)) == (48.1173, 11.5167)
    uart.chunks = [b"", rmc.replace(b"*6A", b"*6B")]
    assert scope["dut_fix"]() is None
    uart.chunks = [b"", rmc.replace(b",A,", b",V,").replace(b"*6A", b"*7D")]
    assert scope["dut_fix"]() is None
