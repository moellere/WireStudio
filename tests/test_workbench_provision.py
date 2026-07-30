"""Headless LoRaWAN bring-up on a workbench slot.

The invariants asserted here are the ones that produced wrong results on
real hardware, not hypotheticals.
"""
import re

import pytest

from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.workbench import WorkbenchUnavailable
from wirestudio.workbench.serial import SerialUnavailable, answer_prompts
from wirestudio.targets.lorawan.workbench_provision import (
    dev_eui_from_mac,
    mac_from_flash_log,
    provision_events,
)

FLASH_LOG = [
    "esptool v5.3.1",
    "Chip type:          ESP32-D0WDQ6 (revision v1.0)",
    "MAC:                10:52:1c:66:b6:e0",
    "Wrote 552528 bytes at 0x00000000 in 5.8 seconds.",
    "Hash of data verified.",
]


def _design(board="ttgo-t-beam", **lorawan):
    kw = {}
    if lorawan:
        kw["lorawan"] = lorawan
    return Design(
        schema_version="0.1",
        id="d1",
        name="d1",
        target="lorawan",
        board={"library_id": board, "mcu": "esp32"},
        power={"supply": "usb", "rail_voltage_v": 3.3},
        **kw,
    )


# ----------------------------------------------------------------------
# DevEUI derivation
# ----------------------------------------------------------------------


def test_dev_eui_matches_the_browser_derivation():
    """The board must keep one identity whichever host provisioned it."""
    assert dev_eui_from_mac("10:52:1c:66:b6:e0") == "10521cfffe66b6e0"
    assert dev_eui_from_mac("64:b7:08:ab:89:74") == "64b708fffeab8974"


def test_dev_eui_rejects_a_non_mac():
    with pytest.raises(ValueError):
        dev_eui_from_mac("not-a-mac")


def test_mac_read_from_the_flash_log():
    """The bench exposes no chip-detect, so esptool's own output is the only
    place the eFuse MAC appears."""
    assert mac_from_flash_log(FLASH_LOG) == "10:52:1c:66:b6:e0"
    assert mac_from_flash_log(["no mac here"]) is None


# ----------------------------------------------------------------------
# Serial prompt driver
# ----------------------------------------------------------------------


class FakeSerial:
    """One prompt at a time, like the real firmware.

    An empty line re-prints the current prompt rather than advancing -- that
    is what the device does ("Error: '' is not a supported band"), and it is
    what lets the driver attach after the first prompt has already scrolled
    past.
    """

    def __init__(self, prompts, join="JOINED"):
        self.prompts = list(prompts)
        self.join = join
        self.written = []
        self.current = self.prompts.pop(0) if self.prompts else ""
        self._out = self.current.encode()
        self.closed = False

    def read(self, _n):
        out, self._out = self._out, b""
        return out

    def write(self, data):
        text = data.decode().strip()
        self.written.append(text)
        echo = data  # devices echo what they were sent
        if not text:
            self._out = echo + self.current.encode()  # re-print, do not advance
        elif self.prompts:
            self.current = self.prompts.pop(0)
            self._out = echo + self.current.encode()
        else:
            self._out = echo + f"\n{self.join}\n".encode()
        return len(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True


@pytest.fixture
def fake_serial(monkeypatch):
    import serial as pyserial

    holder = {}

    def make(script, join="JOINED"):
        dev = FakeSerial(script, join)
        holder["dev"] = dev
        monkeypatch.setattr(pyserial, "serial_for_url", lambda *a, **k: dev)
        return dev

    holder["make"] = make
    return holder


def _rules(key="ab" * 16):
    return [
        (re.compile(r"sub-?band", re.I), "2"),
        (re.compile(r"\bband\b", re.I), "US915"),
        (re.compile(r"dev\s?eui", re.I), "10521cfffe66b6e0"),
        (re.compile(r"join\s?eui", re.I), "0" * 16),
        (re.compile(r"app\s?key", re.I), key),
        (re.compile(r"nwk\s?key", re.I), key),
    ]


def test_prompts_answered_in_order(fake_serial):
    dev = fake_serial["make"]([
        "Enter LoRaWAN band (e.g. EU868 or US915)\n",
        "Enter subband for your frequency plan\n",
        "Enter joinEUI (64 bits)\n",
        "Enter devEUI (64 bits)\n",
        "Enter appKey (128 bits)\n",
        "Enter nwkKey (128 bits)\n",
    ])
    events = list(answer_prompts("loop://", _rules(), done=re.compile(r"JOINED"), timeout=10, min_interval=0.0))
    assert events[-1] == {"type": "result", "matched": "JOINED"}
    # written[0] is the empty nudge that provokes the re-print.
    assert [w for w in dev.written if w][:2] == ["US915", "2"]
    assert dev.closed


def test_key_is_redacted_from_the_log(fake_serial):
    """Devices echo what they were sent, so the key comes back on the wire."""
    key = "cd" * 16
    fake_serial["make"](["Enter appKey (128 bits)\n"])
    logs = "".join(
        e["data"]
        for e in answer_prompts(
            "loop://", _rules(key), done=re.compile(r"JOINED"), secrets=[key], timeout=10, min_interval=0.0
        )
        if e["type"] == "log"
    )
    assert key not in logs
    assert "<redacted>" in logs


def test_uppercase_echo_is_still_redacted():
    """Firmware echoes hex uppercase even when the key was sent lowercase --
    a case-sensitive redaction would leak it straight into the SSE log."""
    from wirestudio.workbench.serial import _redact

    key = "ef" * 16
    assert key not in _redact(f"[{key.upper()}]", [key])
    assert key.upper() not in _redact(f"[{key.upper()}]", [key])


def test_stalled_dialogue_raises_rather_than_hanging(fake_serial):
    fake_serial["make"](["nothing to match here\n"])
    with pytest.raises(SerialUnavailable, match="did not reach"):
        list(answer_prompts("loop://", _rules(), done=re.compile(r"JOINED"), timeout=1.5, min_interval=0.0))


# ----------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------


class FakeWorkbench:
    def __init__(self, log=None, serial_url="rfc2217://bench:4001"):
        self.log = log if log is not None else FLASH_LOG
        self.serial_url = serial_url
        self.flashed = []

    def flash_sync(self, *, slot, images, erase, **kw):
        self.flashed.append({"slot": slot, "images": images, "erase": erase})
        for line in self.log:
            yield {"type": "log", "data": line}
        yield {"type": "done", "ok": True, "slot": slot, "returncode": 0}

    def slot_sync(self, label):
        from wirestudio.workbench import Slot

        return Slot(label, "idle", True, None, None, self.serial_url, False, None)


class FakeChirp:
    def __init__(self, activation=True):
        self.calls = []
        self._activation = activation

    def provision_device(self, **kw):
        self.calls.append(kw)
        return {"application_id": "app-1", "device_profile_id": "dp-1"}

    def get_activation(self, dev_eui):
        return {"dev_addr": "0136e110"} if self._activation else None


_PROMPTS = [
    "Enter LoRaWAN band\n", "Enter subband\n", "Enter joinEUI\n",
    "Enter devEUI\n", "Enter appKey\n", "Enter nwkKey\n",
]


def _run(fake_serial, wb=None, chirp=None, design=None, join="JOINED"):
    fake_serial["make"](_PROMPTS, join=join)
    return list(
        provision_events(
            design or _design(),
            default_library(),
            slot="SLOT1",
            workbench=wb or FakeWorkbench(),
            chirpstack=chirp or FakeChirp(),
            images=[(0x0, b"fw")],
            serial_timeout=10, serial_min_interval=0.0,
        )
    )


def test_full_flow_reaches_done(fake_serial):
    chirp = FakeChirp()
    events = _run(fake_serial, chirp=chirp)
    phases = [e["phase"] for e in events if e["type"] == "phase"]
    assert phases == ["flash", "detect", "register", "registered", "provision", "verify"]
    assert events[-1]["type"] == "done"
    assert events[-1]["dev_eui"] == "10521cfffe66b6e0"
    assert events[-1]["dev_addr"] == "0136e110"


def test_registration_follows_the_flash(fake_serial):
    """The DevEUI comes out of esptool's log, so registration cannot precede
    the flash -- and provision_device's DevNonce flush has to land after the
    erase restarted the device's counter, not before."""
    events = _run(fake_serial)
    order = [e.get("phase") for e in events if e["type"] == "phase"]
    assert order.index("flash") < order.index("detect") < order.index("register")


def test_erase_is_on_by_default(fake_serial):
    """An erase empties NVS so the device re-prompts; pairing it with the
    flush in provision_device is what keeps the join from being rejected as
    a DevNonce replay."""
    wb = FakeWorkbench()
    _run(fake_serial, wb=wb)
    assert wb.flashed[0]["erase"] is True


def test_registered_key_is_the_one_pushed_to_the_device(fake_serial):
    """A mismatch here joins nothing and reports nothing useful."""
    chirp = FakeChirp()
    fake_serial["make"]([
        "Enter LoRaWAN band\n", "Enter subband\n", "Enter joinEUI\n",
        "Enter devEUI\n", "Enter appKey\n", "Enter nwkKey\n",
    ])
    list(provision_events(
        _design(), default_library(), slot="SLOT1",
        workbench=FakeWorkbench(), chirpstack=chirp,
        images=[(0x0, b"fw")], serial_timeout=10, serial_min_interval=0.0,
    ))
    sent = fake_serial["dev"].written
    assert chirp.calls[0]["app_key"] in sent


def test_missing_mac_is_a_clear_failure(fake_serial):
    wb = FakeWorkbench(log=["esptool v5.3.1", "Hash of data verified."])
    with pytest.raises(WorkbenchUnavailable, match="did not report a MAC"):
        _run(fake_serial, wb=wb)


def test_join_failure_is_not_reported_as_success(fake_serial):
    """The device answers every prompt and still fails to join -- provisioning
    that reported success here would be worse than useless."""
    with pytest.raises(SerialUnavailable, match="JOIN FAILED"):
        _run(fake_serial, join="JOIN FAILED")


def test_device_claim_is_checked_against_chirpstack(fake_serial):
    """JOINED is the device's own word for it; the activation is independent
    and is what an uplink actually gets decoded against."""
    with pytest.raises(Exception, match="no activation"):
        _run(fake_serial, chirp=FakeChirp(activation=False))
