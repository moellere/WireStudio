"""The UART parts with no driver carry a frame decoder written from the
datasheet, the same text in the `circuitpython:` and `micropython:`
blocks. Each framework's generated setup runs here against stub modules
and its decoder is fed frames: valid ones decode, a bad checksum, a bad
header or a torn frame do not."""
from __future__ import annotations

import ast
import json
import sys
import types
from pathlib import Path

import pytest

from tests.test_python_blocks import StubModule
from wirestudio.generate import circuitpython_gen, micropython_gen
from wirestudio.library import default_library
from wirestudio.library.check import synthetic_design

LIB = default_library()
EXAMPLES = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"
GENERATORS = {"circuitpython": circuitpython_gen.generate_code,
              "micropython": micropython_gen.generate_code}


def generate(cid: str, framework: str, params: dict | None = None) -> str:
    design = synthetic_design(LIB.component(cid), LIB, on_buses=True)
    design.components[0].params.update(params or {})
    out = GENERATORS[framework](design, LIB)
    assert out["warnings"] == []
    return out["code"]


def decoder(cid: str, framework: str, monkeypatch):
    code = generate(cid, framework).split("\nwhile True:")[0]
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]:
                if name != "time":
                    monkeypatch.setitem(sys.modules, name, StubModule(name))
    scope: dict = {"__name__": "__main__"}
    exec(compile(code, "main.py", "exec"), scope)
    return scope["dut_decode"]



FRAMEWORKS = pytest.mark.parametrize("framework", list(GENERATORS))


@FRAMEWORKS
def test_mhz19_decodes_the_datasheet_reply(framework, monkeypatch):
    decode = decoder("mhz19", framework, monkeypatch)
    reply = bytes.fromhex("ff860260470000 00d1".replace(" ", ""))  # datasheet: 0x0260 = 608 ppm
    assert decode(reply) == 608
    assert decode(reply[:-1] + b"\xd2") is None
    assert decode(reply[:8]) is None
    assert decode(None) is None


@FRAMEWORKS
@pytest.mark.parametrize("abc, command", [(False, "ff017900000000 0086"), (True, "ff0179a0000000 00e6")])
def test_mhz19_sets_baseline_calibration_with_a_checked_command(framework, abc, command, monkeypatch):
    raw = bytes.fromhex(command.replace(" ", ""))
    assert (0x100 - sum(raw[1:8])) & 0xFF == raw[8]
    escaped = "".join("\\x%02x" % b for b in raw)
    assert f'.write(b"{escaped}")' in generate("mhz19", framework, {"automatic_baseline_calibration": abc})


def _cse_frame(header=0x55, adj=0x70, v=(190000, 800), i=(12000, 24000), p=(5000000, 50000)):
    body = bytes([0x5A]) + b"".join(x.to_bytes(3, "big") for pair in (v, i, p) for x in pair) + bytes([adj, 0, 0])
    return bytes([header]) + body + bytes([sum(body[1:]) & 0xFF])


@FRAMEWORKS
def test_cse7766_decodes_coefficient_over_cycle(framework, monkeypatch):
    decode = decoder("cse7766", framework, monkeypatch)
    assert len(_cse_frame()) == 24
    assert decode(b"\x01\x02" + _cse_frame() + _cse_frame()[:10]) == (237.5, 0.5, 100.0)
    # 0xF2: power cycle out of range, the chip's way of saying no load.
    assert decode(_cse_frame(header=0xF2)) == (237.5, 0.5, 0.0)
    assert decode(_cse_frame(adj=0x40)) == (237.5, 0.0, 0.0)
    assert decode(_cse_frame(header=0xAA)) is None  # chip not calibrated
    bad = bytearray(_cse_frame())
    bad[-1] ^= 1
    assert decode(bytes(bad)) is None


def test_cse7766_bus_keeps_its_even_parity():
    design = synthetic_design(LIB.component("cse7766"), LIB, on_buses=True)
    design.buses[0].parity = "EVEN"
    assert "parity=busio.UART.Parity.EVEN" in circuitpython_gen.generate_code(design, LIB)["code"]
    assert "parity=0" in micropython_gen.generate_code(design, LIB)["code"]


def _rdm_frame(tag_hex="0F00ABCDEF", check=None):
    data = bytes.fromhex(tag_hex)
    x = data[0] ^ data[1] ^ data[2] ^ data[3] ^ data[4] if check is None else check
    return b"\x02" + tag_hex.encode() + b"%02X" % x + b"\x03"


@FRAMEWORKS
def test_rdm6300_decodes_the_tag_id(framework, monkeypatch):
    decode = decoder("rdm6300", framework, monkeypatch)
    assert decode(b"\x03\x02zz" + _rdm_frame()) == 0x00ABCDEF
    assert decode(_rdm_frame(check=0x00)) is None
    assert decode(_rdm_frame()[:-1]) is None
    assert decode(b"\x02" + b"\xff" * 12 + b"\x03") is None


def _ld_frame(state=3, moving=(120, 100), still=(80, 50), detect=150):
    data = bytes([0x02, 0xAA, state]) + moving[0].to_bytes(2, "little") + bytes([moving[1]]) \
        + still[0].to_bytes(2, "little") + bytes([still[1]]) + detect.to_bytes(2, "little") + b"\x55\x00"
    return b"\xf4\xf3\xf2\xf1" + len(data).to_bytes(2, "little") + data + b"\xf8\xf7\xf6\xf5"


@FRAMEWORKS
def test_ld2410_decodes_the_latest_target_report(framework, monkeypatch):
    decode = decoder("ld2410", framework, monkeypatch)
    newest = _ld_frame(state=2, moving=(0, 0), still=(95, 40))
    assert decode(b"\x00" + _ld_frame() + newest + newest[:9]) == (2, 0, 0, 95, 40)
    assert decode(_ld_frame()) == (3, 120, 100, 80, 50)
    torn = bytearray(_ld_frame())
    torn[-1] = 0
    assert decode(bytes(torn)) is None


@FRAMEWORKS
def test_ld2420_reads_simple_text_and_energy_frames(framework, monkeypatch):
    decode = decoder("ld2420", framework, monkeypatch)
    assert decode(b"Range 0\r\nOFF\r\nON\r\nRange 152\r\n") == (True, 152)
    assert decode(b"OFF\r\n") == (False, None)
    energy = b"\xf4\xf3\xf2\xf1\x23\x00\x01\x58\x02" + bytes(32) + b"\xf8\xf7\xf6\xf5"
    assert decode(b"\x00" + energy) == (True, 0x258)  # 600 cm
    assert decode(energy[:-1]) is None
    assert decode(b"Range x\r\n") is None


def _rf_frame(action, sync, low, high, code):
    return bytes([0xAA, action]) + b"".join(v.to_bytes(2, "big") for v in (sync, low, high)) \
        + code.to_bytes(3, "big") + b"\x55"


@FRAMEWORKS
def test_rf_bridge_decodes_received_and_learned_codes(framework, monkeypatch):
    decode = decoder("rf_bridge", framework, monkeypatch)
    rx = _rf_frame(0xA4, 0x2A80, 0x0118, 0x0398, 0xA1B2C3)
    learned = _rf_frame(0xA3, 0x1F40, 0x00F0, 0x02D0, 0x00FF01)
    assert decode(b"\xaa\xa0\x55" + rx + learned) == [
        (0x2A80, 0x0118, 0x0398, 0xA1B2C3), (0x1F40, 0x00F0, 0x02D0, 0x00FF01)]
    assert decode(rx[:-1] + b"\x00") == []


@FRAMEWORKS
def test_nextion_decodes_touch_events(framework, monkeypatch):
    decode = decoder("nextion", framework, monkeypatch)
    end = b"\xff\xff\xff"
    assert decode(b"\x1a" + end + b"\x65\x00\x02\x01" + end + b"\x66\x01" + end + b"\x65\x01\x07\x00" + end) == [
        (0, 2, True), (1, 7, False)]


def _bl_packet(addr, value):
    data = value.to_bytes(3, "little")
    return data + bytes([(addr + sum(data)) & 0xFF ^ 0xFF])


@FRAMEWORKS
def test_bl0906_checks_and_scales_register_reads(framework, monkeypatch):
    decode = decoder("bl0906", framework, monkeypatch)
    scope = decode.__globals__
    # ESPHome's bl0906 constants for the stock CT and divider.
    assert scope["dut_uref"] == pytest.approx(1.097 * 100000 / (13162 * 100 * 1000))
    assert scope["dut_iref"] == pytest.approx(1.097 / (12875 * 10.2 * 1000 / 2000))
    assert decode(0x16, _bl_packet(0x16, 0x2C1A80)) == 0x2C1A80
    assert decode(0x23, _bl_packet(0x23, 0xFFFF38), True) == -200  # power is signed 24-bit
    bad = bytearray(_bl_packet(0x16, 0x2C1A80))
    bad[3] ^= 1
    assert decode(0x16, bytes(bad)) is None
    assert decode(0x16, b"\x00\x00") is None


class FakeUART:
    """A UART whose peer answers each write through `answer`; both
    frameworks' read calls drain what it queued."""

    def __init__(self, answer):
        self.answer = answer
        self.sent: list[bytes] = []
        self.rx = b""

    def write(self, data):
        self.sent.append(bytes(data))
        self.rx += self.answer(bytes(data))

    def reset_input_buffer(self):
        self.rx = b""

    @property
    def in_waiting(self):
        return len(self.rx)

    def read(self, n=None):
        data, self.rx = (self.rx, b"") if n is None else (self.rx[:n], self.rx[n:])
        return data or None


def _clock() -> types.ModuleType:
    """A clock that advances 10 ms each time it is read; sleeping is free."""
    mod = types.ModuleType("time")
    now = [0.0]

    def tick():
        now[0] += 0.01
        return now[0]
    mod.monotonic = tick
    mod.ticks_ms = lambda: int(tick() * 1000)
    mod.ticks_add = lambda a, b: a + b
    mod.ticks_diff = lambda a, b: a - b
    mod.sleep = mod.sleep_ms = mod.sleep_us = lambda s: None
    return mod


def run_example(name: str, framework: str, uart: FakeUART, monkeypatch) -> dict:
    """Run an example's generated setup with `uart` as its UART bus."""
    from wirestudio.model import Design
    design = Design.model_validate(json.loads((EXAMPLES / f"{name}.json").read_text()))
    code = GENERATORS[framework](design, LIB)["code"].split("\nwhile True:")[0]
    for node in ast.walk(ast.parse(code)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for mod in [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]:
                if mod not in ("time", "struct"):
                    monkeypatch.setitem(sys.modules, mod, StubModule(mod))
    monkeypatch.setitem(sys.modules, "time", _clock())
    if framework == "micropython":
        sys.modules["machine"].UART = lambda *a, **k: uart
    else:
        sys.modules["busio"].UART = lambda *a, **k: uart
    scope: dict = {"__name__": "__main__"}
    exec(compile(code, "main.py", "exec"), scope)
    return scope


def _modbus_crc(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = crc >> 1 ^ 0xA001 if crc & 1 else crc >> 1
    return crc.to_bytes(2, "little")


def _modbus_reply(registers: dict[int, int]):
    """A slave answering function 0x04 from `registers`, with an echo of
    noise before the frame."""
    def answer(req):
        if req[1] != 0x04 or _modbus_crc(req[:6]) != req[6:]:
            return b""
        start, count = req[2] << 8 | req[3], req[4] << 8 | req[5]
        data = b"".join(registers.get(start + k, 0).to_bytes(2, "big") for k in range(count))
        frame = bytes([req[0], 0x04, len(data)]) + data
        return b"\x00" + frame + _modbus_crc(frame)
    return answer


@FRAMEWORKS
def test_modbus_frames_requests_and_checks_replies(framework, monkeypatch):
    scope = run_example("energy-monitor", framework, FakeUART(lambda req: b""), monkeypatch)
    crc = scope["pzem_bus_crc"]
    # Modbus over serial line, the classic example: 01 03 00 00 00 0A, CRC C5 CD.
    assert crc(bytes.fromhex("01030000000a")) == b"\xc5\xcd"
    frame = bytes.fromhex("010402abcd")
    good = frame + crc(frame)
    assert scope["pzem_bus_parse"](1, 4, b"\xff" + good) == b"\xab\xcd"
    assert scope["pzem_bus_parse"](1, 4, good[:-1] + bytes([good[-1] ^ 1])) is None
    assert scope["pzem_bus_parse"](2, 4, good) is None  # another slave's reply
    assert scope["pzem_bus_parse"](1, 4, bytes.fromhex("018402") + _modbus_crc(bytes.fromhex("018402"))) is None


@FRAMEWORKS
def test_pzemac_reads_ten_input_registers_low_word_first(framework, monkeypatch):
    regs = {0: 2305, 1: 0x86A0, 2: 0x0001, 3: 23050, 4: 0, 5: 0x5678, 6: 0x0012, 7: 500, 8: 98}
    uart = FakeUART(_modbus_reply(regs))
    scope = run_example("energy-monitor", framework, uart, monkeypatch)
    data = scope["pzem_bus_read"](1, 0x04, 0, 10)
    assert uart.sent[-1] == bytes.fromhex("01040000000a") + _modbus_crc(bytes.fromhex("01040000000a"))
    assert scope["mains_decode"](data) == (230.5, 100.0, 2305.0, 0x125678, 50.0, 0.98)
    assert scope["mains_decode"](None) is None


@FRAMEWORKS
def test_sdm_meter_reads_big_endian_floats(framework, monkeypatch):
    import struct
    floats = {0x00: 231.5, 0x06: 4.25, 0x0C: 980.0, 0x46: 50.02, 0x48: 1234.5, 0x4A: 6.75}
    regs = {}
    for reg, value in floats.items():
        hi, lo = struct.unpack(">HH", struct.pack(">f", value))
        regs[reg], regs[reg + 1] = hi, lo
    scope = run_example("rs485-energy", framework, FakeUART(_modbus_reply(regs)), monkeypatch)
    data = scope["rs485_bus_read"](1, 0x04, 0, 80)
    assert len(data) == 160
    for reg, value in floats.items():
        assert scope["meter_value"](data, reg) == pytest.approx(value)


def _tuya(cmd: int, data: bytes = b"", version: int = 0x03) -> bytes:
    frame = bytes([0x55, 0xAA, version, cmd, len(data) >> 8, len(data) & 0xFF]) + data
    return frame + bytes([sum(frame) & 0xFF])


def _tuya_mcu(req: bytes) -> bytes:
    """An MCU with a relay on DP 1, power on DP 17 and energy on DP 18."""
    if req[3] == 0x08:
        dps = bytes([1, 1, 0, 1, 1]) + bytes([17, 2, 0, 4]) + (1234).to_bytes(4, "big") \
            + bytes([18, 2, 0, 4]) + (-5).to_bytes(4, "big", signed=True)
        return _tuya(0x07, dps)
    return _tuya(req[3], b"\x00" if req[3] == 0x00 else b"")


@FRAMEWORKS
def test_tuya_initializes_the_mcu_and_collects_datapoints(framework, monkeypatch):
    uart = FakeUART(_tuya_mcu)
    scope = run_example("tuya-smart-plug", framework, uart, monkeypatch)
    assert [f[3] for f in uart.sent] == [0x00, 0x01, 0x02, 0x03, 0x08]
    assert uart.sent[0] == bytes.fromhex("55aa00000000ff")  # heartbeat, checksum included
    assert uart.sent[3] == _tuya(0x03, b"\x03", version=0)  # Wi-Fi: connected to the router
    assert scope["tuya_mcu_dps"] == {1: True, 17: 1234, 18: -5}
    scope["relay_turn"](False)
    assert uart.sent[-1] == _tuya(0x06, bytes([1, 1, 0, 1, 0]), version=0)


@FRAMEWORKS
def test_tuya_frames_survive_noise_splits_and_bad_checksums(framework, monkeypatch):
    scope = run_example("tuya-smart-plug", framework, FakeUART(lambda req: b""), monkeypatch)
    frames = scope["tuya_mcu_frames"]
    a, b = _tuya(0x07, bytes([1, 1, 0, 1, 1])), _tuya(0x22, bytes([2, 4, 0, 1, 3]))
    bad = bytearray(_tuya(0x07, bytes([3, 1, 0, 1, 1])))
    bad[-1] ^= 1
    found, rest = frames(b"\x00\x55" + a + bytes(bad) + b + b[:5])
    assert found == [(0x07, bytes([1, 1, 0, 1, 1])), (0x22, bytes([2, 4, 0, 1, 3]))]
    assert rest == b[:5]  # a torn frame waits for the rest
    assert scope["tuya_mcu_datapoints"](bytes([5, 3, 0, 2]) + b"hi" + bytes([6, 0, 0, 2, 0xAB, 0xCD])) == {
        5: "hi", 6: b"\xab\xcd"}
