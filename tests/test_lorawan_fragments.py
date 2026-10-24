"""The LoRaWAN target's UART, SPI and Modbus blocks are C++ ports of the
frame decoders tests/test_uart_frames.py checks in the Python blocks. Here
each one is rendered for a design, compiled on the host against small
fakes of the serial port, SPI and millis(), and fed the same frames:
valid ones land in the payload fields, a bad checksum, noise or a torn
frame do not."""
from __future__ import annotations

import shutil
import struct
import subprocess

import pytest

from tests import test_uart_frames as T
from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.targets.lorawan.codec import fields_for
from wirestudio.targets.lorawan.firmware_gen import component_fragments

pytestmark = pytest.mark.skipif(shutil.which("g++") is None, reason="needs a host C++ compiler")

LIB = default_library()
SPI = LIB.board("ttgo-lora32-v2").default_buses["spi"]

PRELUDE = r"""
#include <cctype>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <functional>
#include <vector>
enum { SERIAL_8N1, SERIAL_8E1, SERIAL_8O1, LOW = 0, HIGH = 1, OUTPUT = 1, MSBFIRST = 1, SPI_MODE0 = 0 };
unsigned long now_ms = 1;
unsigned long millis() { return now_ms++; }
void delay(unsigned long ms) { now_ms += ms; }
void pinMode(int, int) {}
void digitalWrite(int, int) {}
// The peer: what it sends back for each write.
std::function<std::vector<uint8_t>(const std::vector<uint8_t>&)> peer;
struct HardwareSerial {
  std::deque<uint8_t> rx;
  explicit HardwareSerial(int) {}
  void begin(unsigned long, int, int, int) {}
  int available() { return (int)rx.size(); }
  int read() { int b = rx.front(); rx.pop_front(); return b; }
  size_t write(const uint8_t* b, size_t n) {
    if (peer) for (uint8_t x : peer(std::vector<uint8_t>(b, b + n))) rx.push_back(x);
    return n;
  }
  void flush() {}
  void setTimeout(unsigned long) {}
  size_t readBytes(uint8_t* b, size_t n) {
    size_t i = 0;
    while (i < n && !rx.empty()) { b[i++] = rx.front(); rx.pop_front(); }
    return i;
  }
};
struct SPISettings { SPISettings(long, int, int) {} };
struct SPIClass {
  std::deque<uint8_t> miso;
  void begin(int, int, int) {}
  void beginTransaction(SPISettings) {}
  void endTransaction() {}
  uint8_t transfer(uint8_t) { if (miso.empty()) return 0; uint8_t r = miso.front(); miso.pop_front(); return r; }
} SPI;
"""


def _design(components, buses=(), connections=()) -> Design:
    return Design.model_validate({
        "schema_version": "1.0", "id": "dut", "name": "dut", "target": "lorawan", "lorawan": {},
        "board": {"library_id": "ttgo-lora32-v2", "mcu": "esp32"},
        "power": {"supply": "usb", "rail_voltage_v": 3.3},
        "components": [{"id": i, "library_id": c, "label": i, "params": p} for i, c, p in components],
        "buses": list(buses),
        "connections": [{"component_id": c, "pin_role": r, "target": t} for c, r, t in connections],
    })


def _on(bus_id):
    return {"kind": "bus", "bus_id": bus_id}


def _hub(component_id):
    return {"kind": "component", "component_id": component_id}


def _uart_part(inst, cid, roles=("TX", "RX"), params=None, baud=9600, parity="NONE"):
    return _design([(inst, cid, params or {})],
                   [{"id": "u", "type": "uart", "rx": "GPIO16", "tx": "GPIO17", "baud_rate": baud, "parity": parity}],
                   [(inst, r, _on("u")) for r in roles])


def _bytes(data) -> str:
    return "{" + ", ".join(str(b) for b in data) + "}"


def run(tmp_path, design: Design, main: str) -> dict[str, int]:
    """Compile the design's own fragments with `main` run between setup and
    one loop pass; return every payload field the parts report."""
    ours = {c.id for c in design.components}
    frags = [f for f in component_fragments(design, LIB) if f["id"] in ours]
    fields = [f for f in fields_for(design, LIB) if f["name"].split("_")[0] in ours]
    prints = "".join(f'  printf("{f["name"]}=%lld\\n", (long long)({f["cpp_expr"]}));\n' for f in fields)
    src = (PRELUDE + "\n".join(f.get("globals", "") for f in frags)
           + "\nvoid setup_() {\n" + "\n".join(f.get("setup", "") for f in frags) + "\n}\n"
           + "void loop_() {\n" + "\n".join(f.get("loop", "") for f in frags) + "\n}\n"
           + "int main() {\n  setup_();\n" + main + "\n  loop_();\n" + prints + "}\n")
    (tmp_path / "dut.cpp").write_text(src)
    subprocess.run(["g++", "-std=c++17", "-o", str(tmp_path / "dut"), str(tmp_path / "dut.cpp")],
                   check=True, capture_output=True, text=True)
    out = subprocess.run([str(tmp_path / "dut")], check=True, capture_output=True, text=True).stdout
    return {k: int(v) for k, v in (line.split("=") for line in out.split())}


def _stream(inst, data) -> str:
    return f"  for (uint8_t b : std::vector<uint8_t>{_bytes(data)}) {inst}Serial.rx.push_back(b);"


def _answer(request, reply) -> str:
    return (f"  peer = [](const std::vector<uint8_t>& q) {{ return q == std::vector<uint8_t>{_bytes(request)}"
            f" ? std::vector<uint8_t>{_bytes(reply)} : std::vector<uint8_t>{{}}; }};")


MHZ19_READ = bytes.fromhex("ff0186000000000079")


@pytest.mark.parametrize("reply, ppm", [
    (bytes.fromhex("ff86026047000000d1"), 608),  # the datasheet's example
    (bytes.fromhex("ff86026047000000d2"), 0),    # bad checksum
    (bytes.fromhex("ff86026047000000"), 0),      # short
])
def test_mhz19(tmp_path, reply, ppm):
    got = run(tmp_path, _uart_part("co2", "mhz19"), _answer(MHZ19_READ, reply))
    assert got == {"co2_co2_ppm": ppm}


@pytest.mark.parametrize("data, want", [
    (b"\x01\x02" + T._cse_frame() + T._cse_frame()[:10], (2375, 500, 1000)),
    (T._cse_frame(header=0xF2), (2375, 500, 0)),  # power cycle out of range: no load
    (T._cse_frame(adj=0x40), (2375, 0, 0)),
    (T._cse_frame(header=0xAA), (0, 0, 0)),  # chip not calibrated
    (T._cse_frame()[:-1] + bytes([T._cse_frame()[-1] ^ 1]), (0, 0, 0)),
])
def test_cse7766(tmp_path, data, want):
    got = run(tmp_path, _uart_part("plug", "cse7766", roles=("TX",), baud=4800, parity="EVEN"),
              _stream("plug", data))
    assert got == dict(zip(("plug_voltage", "plug_current", "plug_power"), want))


_NEWEST = T._ld_frame(state=2, moving=(0, 0), still=(95, 40))


@pytest.mark.parametrize("data, want", [
    (b"\x00" + T._ld_frame() + _NEWEST + _NEWEST[:9], (2, 0, 95)),
    (T._ld_frame(), (3, 120, 80)),
    (T._ld_frame()[:-1] + b"\x00", (0, 0, 0)),
])
def test_ld2410(tmp_path, data, want):
    got = run(tmp_path, _uart_part("radar", "ld2410", baud=256000), _stream("radar", data))
    assert got == dict(zip(("radar_target", "radar_moving_cm", "radar_still_cm"), want))


_ENERGY = b"\xf4\xf3\xf2\xf1\x23\x00\x01\x58\x02" + bytes(32) + b"\xf8\xf7\xf6\xf5"


@pytest.mark.parametrize("data, want", [
    (b"Range 0\r\nOFF\r\nON\r\nRange 152\r\n", (1, 152)),
    (b"OFF\r\n", (0, 0)),
    (b"\x00" + _ENERGY, (1, 600)),
    (_ENERGY[:-1], (0, 0)),
])
def test_ld2420(tmp_path, data, want):
    got = run(tmp_path, _uart_part("presence", "ld2420", baud=115200), _stream("presence", data))
    assert got == dict(zip(("presence_presence", "presence_distance_cm"), want))


def _pms(words):
    frame = b"\x42\x4d" + (2 * len(words) + 2).to_bytes(2, "big") + b"".join(w.to_bytes(2, "big") for w in words)
    return frame + (sum(frame) & 0xFFFF).to_bytes(2, "big")


_PMS = _pms([11, 22, 33, 12, 25, 40, 0, 0, 0, 0, 0, 0, 0])  # atmospheric PM in words 4-6


@pytest.mark.parametrize("data, want", [
    (b"\x42\x00\x42" + _PMS, (12, 25, 40)),
    (_PMS[:-1] + b"\x00", (0, 0, 0)),
])
def test_pmsx003(tmp_path, data, want):
    got = run(tmp_path, _uart_part("pm", "pmsx003"), _stream("pm", data))
    assert got == dict(zip(("pm_pm1_0", "pm_pm2_5", "pm_pm10"), want))


def test_bl0906(tmp_path):
    uref = 1.097 * 100000 / (13162 * 100 * 1000)
    iref = 1.097 / (12875 * (5.1 + 5.1) * 1000 / 2000)
    pref = 1.097 * 1.097 * 100000 / (40.41259 * ((5.1 + 5.1) * 1000 / 2000) * 100 * 1000)
    regs = {0x16: 0x2C1A80, 0x4E: 200000, 0x5E: 600, 0x0D: 1500000, 0x23: 0xFFFF38}
    regs_bad = {0x0E: 1500000}  # a reply with a bad checksum is dropped
    answers = "".join(f"    if (q[1] == {a}) return std::vector<uint8_t>{_bytes(T._bl_packet(a, v))};\n"
                      for a, v in regs.items())
    for a, v in regs_bad.items():
        bad = T._bl_packet(a, v)
        answers += f"    if (q[1] == {a}) return std::vector<uint8_t>{_bytes(bad[:3] + bytes([bad[3] ^ 1]))};\n"
    got = run(tmp_path, _uart_part("em", "bl0906", baud=19200),
              "  peer = [](const std::vector<uint8_t>& q) {\n" + answers + "    return std::vector<uint8_t>{};\n  };")
    assert got["em_voltage"] == round(0x2C1A80 * uref * 10)
    assert got["em_frequency"] == 5000
    assert got["em_temp_c"] == int(((600 - 64) * 12.5 / 59 - 40) * 10)
    assert got["em_ch1_current"] == round(1500000 * iref * 1000)
    assert got["em_ch1_power"] == int(-200 * pref)  # power is signed 24-bit
    assert got["em_ch2_current"] == 0


def _spi_design(components, connections):
    return _design(components, [{"id": "s", "type": "spi", **SPI}], connections)


def _miso(data) -> str:
    return f"  for (uint8_t b : std::vector<uint8_t>{_bytes(data)}) SPI.miso.push_back(b);"


@pytest.mark.parametrize("quarters, fault, want", [(101, False, 101), (-41, False, -41), (101, True, 0)])
def test_max31855(tmp_path, quarters, fault, want):
    word = ((quarters & 0x3FFF) << 18) | (0x10000 if fault else 0)
    design = _spi_design([("tc", "max31855", {})],
                         [("tc", "CLK", _on("s")), ("tc", "MISO", _on("s")), ("tc", "CS", {"kind": "gpio", "pin": "GPIO25"})])
    assert run(tmp_path, design, _miso(word.to_bytes(4, "big"))) == {"tc_temp_c": want}  # x4: 25.25 C, -10.25 C


def test_mcp3008_channel_reads_through_its_hub(tmp_path):
    design = _spi_design(
        [("adc", "mcp3008", {}), ("ch5", "mcp3008_channel", {"number": 5, "reference_voltage": "5.0V"})],
        [("adc", r, _on("s")) for r in ("CLK", "MOSI", "MISO")]
        + [("adc", "CS", {"kind": "gpio", "pin": "GPIO2"}), ("ch5", "HUB", _hub("adc"))])
    assert run(tmp_path, design, _miso([0, 0x02, 0x00])) == {"ch5_voltage": round(512 * 5.0 * 1000 / 1023)}


def _modbus(child, cid, params=None):
    return _design([("bus", "modbus", {}), (child, cid, params or {})],
                   [{"id": "u", "type": "uart", "rx": "GPIO16", "tx": "GPIO17", "baud_rate": 9600}],
                   [("bus", "UART", _on("u")), ("bus", "FLOW", {"kind": "gpio", "pin": "GPIO4"}),
                    (child, "HUB", _hub("bus"))])


def _read(count) -> bytes:
    req = bytes([1, 0x04, 0, 0, 0, count])
    return req + T._modbus_crc(req)


def test_pzemac_reads_through_the_modbus_hub(tmp_path):
    regs = {0: 2305, 1: 0x86A0, 2: 0x0001, 3: 23050, 4: 0, 5: 0x5678, 6: 0x0012, 7: 500, 8: 98}
    # The test suite's slave sends a noise byte before its reply.
    got = run(tmp_path, _modbus("mains", "pzemac"), _answer(_read(10), T._modbus_reply(regs)(_read(10))))
    assert got == {"mains_voltage": 2305, "mains_current": 10000, "mains_power": 23050,
                   "mains_energy": 0x125678, "mains_frequency": 500, "mains_power_factor": 98}


def test_modbus_drops_a_reply_with_a_bad_crc(tmp_path):
    reply = bytearray(T._modbus_reply({0: 2305})(_read(10)))
    reply[-1] ^= 1
    got = run(tmp_path, _modbus("mains", "pzemac"), _answer(_read(10), bytes(reply)))
    assert got["mains_voltage"] == 0


@pytest.mark.parametrize("three_phase, watts", [(False, 9800), (True, 29400)])
def test_sdm_meter_reads_big_endian_floats(tmp_path, three_phase, watts):
    floats = {0x00: 231.5, 0x06: 4.25, 0x0C: 980.0, 0x34: 2940.0, 0x46: 50.02, 0x48: 1234.5, 0x4A: 6.75}
    regs = {}
    for reg, value in floats.items():
        regs[reg], regs[reg + 1] = struct.unpack(">HH", struct.pack(">f", value))
    got = run(tmp_path, _modbus("meter", "sdm_meter", {"three_phase": three_phase}),
              _answer(_read(80), T._modbus_reply(regs)(_read(80))))
    assert got == {"meter_voltage": 2315, "meter_current": 425, "meter_power": watts, "meter_frequency": 5002,
                   "meter_import_energy": 123450, "meter_export_energy": 675}
