"""The register-level parts with no driver carry datasheet code, the same
text in the `circuitpython:` and `micropython:` blocks; only the bus
access differs. Each framework's generated setup runs here against a
fake I2C bus that serves register reads and records writes."""
from __future__ import annotations

import ast
import sys

import pytest

from tests.test_python_blocks import StubModule, _fake_time
from wirestudio.generate import circuitpython_gen, micropython_gen
from wirestudio.library import default_library
from wirestudio.library.check import synthetic_design

LIB = default_library()
GENERATORS = {"circuitpython": circuitpython_gen.generate_code,
              "micropython": micropython_gen.generate_code}
FRAMEWORKS = pytest.mark.parametrize("framework", list(GENERATORS))


class FakeI2C:
    """Registers by (address, register); reads run on from the register
    asked for, as the chips auto-increment."""

    def __init__(self, regs: dict[int, dict[int, int]]):
        self.regs = regs
        self.writes: list[tuple[int, int, int]] = []

    def _read(self, addr, reg, n):
        return bytes(self.regs.get(addr, {}).get(reg + k, 0) for k in range(n))

    def _write(self, addr, reg, value):
        self.writes.append((addr, reg, value))
        self.regs.setdefault(addr, {})[reg] = value

    # machine.SoftI2C
    def readfrom_mem(self, addr, reg, n):
        return self._read(addr, reg, n)

    def writeto_mem(self, addr, reg, data):
        self._write(addr, reg, data[0])

    # busio.I2C
    def try_lock(self):
        return True

    def unlock(self):
        pass

    def writeto_then_readfrom(self, addr, out, buf):
        buf[:] = self._read(addr, out[0], len(buf))

    def writeto(self, addr, data):
        self._write(addr, data[0], data[1])


class FakeSPI:
    """Records every transfer and answers it through `answer`."""

    def __init__(self, answer=lambda out: bytes(len(out))):
        self.answer = answer
        self.sent: list[bytes] = []

    def try_lock(self):
        return True

    def unlock(self):
        pass

    def configure(self, **k):
        pass

    def write_readinto(self, out, buf):
        self.sent.append(bytes(out))
        buf[:] = self.answer(bytes(out))


class FakePCF8574:
    """An I2C bus whose one device takes single-byte port writes."""

    def __init__(self):
        self.port: list[tuple[int, int]] = []

    def try_lock(self):
        return True

    def unlock(self):
        pass

    def writeto(self, addr, data):
        self.port.extend((addr, b) for b in data)


def setup_scope(cid: str, framework: str, bus, monkeypatch, params: dict | None = None) -> dict:
    design = synthetic_design(LIB.component(cid), LIB, on_buses=True)
    design.components[0].params.update(params or {})
    out = GENERATORS[framework](design, LIB)
    assert out["warnings"] == []
    code = out["code"].split("\nwhile True:")[0]
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]:
                if name != "time":
                    monkeypatch.setitem(sys.modules, name, StubModule(name))
    monkeypatch.setitem(sys.modules, "time", _fake_time())
    if framework == "micropython":
        sys.modules["machine"].SoftI2C = sys.modules["machine"].SoftSPI = lambda *a, **k: bus
    elif "busio" in sys.modules and isinstance(sys.modules["busio"], StubModule):
        sys.modules["busio"].I2C = sys.modules["busio"].SPI = lambda *a, **k: bus
    scope: dict = {"__name__": "__main__"}
    exec(compile(code, "main.py", "exec"), scope)
    return scope


def _words(*values: int) -> dict[int, int]:
    raw = b"".join((v & 0xFFFF).to_bytes(2, "big") for v in values)
    return dict(enumerate(raw))


# BMP180 datasheet, section 3.5: the calibration, UT and UP of the worked example.
BMP180_CAL = [408, -72, -14383, 32741, 32757, 23153, 6190, 4, -32768, -8711, 2868]


@FRAMEWORKS
def test_bmp180_reads_signed_calibration_and_compensates_the_datasheet_example(framework, monkeypatch):
    regs = {0x77: {0xAA + k: v for k, v in _words(*BMP180_CAL).items()}}
    scope = setup_scope("bmp180", framework, FakeI2C(regs), monkeypatch)
    assert scope["dut_cal"] == BMP180_CAL  # AC4-AC6 unsigned, the rest signed
    assert scope["dut_compensate"](BMP180_CAL, 27898, 23843, 0) == (15.0, 69964)


@FRAMEWORKS
def test_mpu6886_configures_the_chip_and_scales_its_readings(framework, monkeypatch):
    bus = FakeI2C({})
    scope = setup_scope("mpu6886", framework, bus, monkeypatch)
    assert bus.writes == [(0x68, 0x6B, 0x01), (0x68, 0x1B, 0x18), (0x68, 0x1C, 0x00)]
    raw = bytes(_words(16384, -8192, 0, 0, 164, -1640, 0).values())
    accel, temp, gyro = scope["dut_decode"](raw)
    assert accel == (1.0, -0.5, 0.0)
    assert temp == 25.0
    assert [round(g, 6) for g in gyro] == [10.0, -100.0, 0.0]


@FRAMEWORKS
def test_axp192_powers_the_lora_and_gps_rails_and_reads_the_battery(framework, monkeypatch):
    bus = FakeI2C({0x34: {0x12: 0x01, 0x82: 0x01}})
    scope = setup_scope("axp192", framework, bus, monkeypatch)
    assert bus.writes == [(0x34, 0x28, 0xFF), (0x34, 0x12, 0x0D), (0x34, 0x82, 0x81)]
    assert scope["dut_battery_mv"](bytes([0xE1, 0x0C])) == pytest.approx(0xE1C * 1.1)


@FRAMEWORKS
@pytest.mark.parametrize("model, inverted, kp, ki, kv", [
    # esphome/components/hlw8012/hlw8012.cpp with a 1 mOhm shunt and a 2351 divider.
    ("HLW8012", False, 2.43 ** 2 * 2351 / 0.001 * 64 / 24 / 3579000,
     2.43 / 0.001 * 512 / 24 / 3579000, 2.43 * 2351 * 256 / 3579000),
    ("BL0937", True, 1.218 ** 2 * 2351 / 0.001 / 1721506, 1.218 / 0.001 / 94638, 1.218 * 2351 / 15397),
], ids=["HLW8012", "BL0937"])
def test_hlw8012_multipliers_follow_esphome(framework, model, inverted, kp, ki, kv, monkeypatch):
    scope = setup_scope("hlw8012", framework, FakeI2C({}), monkeypatch, {"model": model})
    assert scope["dut_inverted"] is inverted
    assert (scope["dut_kp"], scope["dut_ki"], scope["dut_kv"]) == pytest.approx((kp, ki, kv))


def _xpt2046(readings: dict[int, list[int]]):
    """Answer each conversion with the next reading queued for its
    channel, 12 bits after the busy bit."""
    queues = {ch: list(v) for ch, v in readings.items()}

    def answer(out):
        q = queues.get(out[0] & 0xF0)
        return b"\x00" + ((q.pop(0) if q else 0) << 3).to_bytes(2, "big")
    return answer


@FRAMEWORKS
def test_xpt2046_gates_on_pressure_and_averages_the_closest_samples(framework, monkeypatch):
    bus = FakeSPI(_xpt2046({0xB0: [300, 100], 0xC0: [3800, 4000],
                            0xD0: [0, 999, 1000, 1100, 1004], 0x90: [2000, 2003, 2500]}))
    scope = setup_scope("xpt2046", framework, bus, monkeypatch)
    assert bus.sent == [b"\xd0\x00\x00"]  # power down, PENIRQ armed
    assert scope["dut_touch"]() == (1002, 2001, 300 + 0xFFF - 3800)
    assert [s[0] for s in bus.sent[1:]] == [0xB1, 0xC1, 0xD1, 0x91, 0xD1, 0x91, 0xD1, 0x91, 0xD0]
    del bus.sent[:]
    assert scope["dut_touch"]() is None  # 100 + 0xFFF - 4000 is under the threshold
    assert [s[0] for s in bus.sent] == [0xB1, 0xC1, 0xD0]


def test_mcp23s17_enables_hardware_addressing_then_uses_its_opcode(monkeypatch):
    bus = FakeSPI(lambda out: bytes([0, 0, 0xA5]))
    scope = setup_scope("mcp23s17", "micropython", bus, monkeypatch, {"deviceaddress": 3})
    assert bus.sent == [b"\x40\x0a\x28", b"\x48\x0a\x28"]  # IOCON = SEQOP | HAEN
    scope["dut_wr"](0x00, 0x0F)
    assert scope["dut_rd"](0x12) == 0xA5
    assert bus.sent[2:] == [b"\x46\x00\x0f", b"\x47\x12\xff"]


def _hd44780(port: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The (rs, nibble) latched on each falling edge of E (P2)."""
    assert all(b & 0x08 for _, b in port)  # backlight stays on
    return [(prev & 1, prev >> 4) for (_, prev), (_, b) in zip(port, port[1:]) if prev & 0x04 and not b & 0x04]


@FRAMEWORKS
def test_lcd_pcf8574_enters_four_bit_mode_and_addresses_each_row(framework, monkeypatch):
    bus = FakePCF8574()
    scope = setup_scope("lcd_pcf8574", framework, bus, monkeypatch, {"address": "0x3F"})
    assert {addr for addr, _ in bus.port} == {0x3F}
    nibbles = _hd44780(bus.port)
    assert nibbles[:4] == [(0, 3), (0, 3), (0, 3), (0, 2)]
    sent = [(rs, hi << 4 | lo) for (rs, hi), (_, lo) in zip(nibbles[4::2], nibbles[5::2])]
    assert sent[:6] == [(0, 0x28), (0, 0x0C), (0, 0x01), (0, 0x06), (0, 0x02), (0, 0x80)]
    assert len(sent) == 6 + 20 and {rs for rs, _ in sent[6:]} == {1}  # the label, one 20-column row
    del bus.port[:]
    scope["dut_show"]("hello", "world", "row 2", "row 3", "no row 4")
    sent = [(rs, hi << 4 | lo) for (rs, hi), (_, lo) in zip(_hd44780(bus.port)[::2], _hd44780(bus.port)[1::2])]
    rows = [sent[k * 21:(k + 1) * 21] for k in range(4)]
    assert len(sent) == 4 * 21
    assert [r[0] for r in rows] == [(0, 0x80), (0, 0xC0), (0, 0x94), (0, 0xD4)]  # 20x4: rows 2, 3 follow 0, 1
    assert bytes(b for _, b in rows[1][1:]) == b"world" + b" " * 15
