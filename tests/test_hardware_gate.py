"""The nightly hardware gate reports the failures it is there to catch."""
from __future__ import annotations

import time

import pytest

from wirestudio.workbench import gate

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeSlot:
    def __init__(self, label, present=True, flapping=False, state="idle", chip="esp32"):
        self.label, self.present, self.flapping = label, present, flapping
        self.state, self.chip, self.product, self.last_error = state, chip, None, None

    @property
    def busy(self):
        return self.state not in ("idle", "absent")

    @property
    def flashable(self):
        if not self.present:
            return False, f"{self.label} is empty"
        if self.flapping:
            return False, f"{self.label} USB link is flapping"
        if self.busy:
            return False, f"{self.label} is {self.state}"
        return True, None


class FakeBench:
    def __init__(self, slots, lines_by_slot=None):
        self._slots = slots
        self._lines = lines_by_slot or {}

    async def info(self):
        return {"hostname": "fake-bench"}

    async def slots(self):
        return self._slots

    async def output(self, slot, lines=500, since=0):
        return self._lines.get(slot, [])


class FakeChirp:
    def __init__(self, activations, last_seen):
        self._act, self._seen = activations, last_seen

    def is_configured(self):
        return True

    def get_activation(self, eui):
        return self._act.get(eui)


def _fresh(n=3):
    now = time.time()
    return [{"ts": now - 5, "text": f"line {i}"} for i in range(n)]


CONFIG = {
    "max_serial_silence_s": 1800,
    "max_uplink_silence_s": 3600,
    "devices": [{"slot": "SLOT1", "framework": "lorawan"}],
}


async def test_all_green(monkeypatch):
    report = gate.Report()
    bench = FakeBench([FakeSlot("SLOT1")], {"SLOT1": _fresh()})
    await gate.run(CONFIG, report, client=bench)
    assert not report.failed, report.rows


async def test_absent_slot_fails():
    """The failure that hid for days: a board off the USB bus."""
    report = gate.Report()
    bench = FakeBench([FakeSlot("SLOT1", present=False)])
    await gate.run(CONFIG, report, client=bench)

    assert report.failed
    stage, subject, _, detail = report.failed[0]
    assert (stage, subject) == ("slots", "SLOT1")
    assert "absent" in detail


async def test_flapping_slot_fails():
    report = gate.Report()
    bench = FakeBench([FakeSlot("SLOT1", flapping=True)])
    await gate.run(CONFIG, report, client=bench)
    assert any(s == "slots" and "flapping" in d for s, _, ok, d in report.rows if not ok)


async def test_silent_serial_fails():
    """Present and healthy, but printing nothing -- a hung board."""
    report = gate.Report()
    bench = FakeBench([FakeSlot("SLOT1")], {"SLOT1": []})
    await gate.run(CONFIG, report, client=bench)
    assert any(s == "serial" for s, _, ok, _ in report.rows if not ok)


async def test_slot_missing_from_bench_fails():
    report = gate.Report()
    bench = FakeBench([FakeSlot("SLOT9")])
    await gate.run(CONFIG, report, client=bench)
    assert any("not configured on the bench" in d for _, _, ok, d in report.rows if not ok)


async def test_unreachable_bench_stops_early():
    class Dead(FakeBench):
        async def info(self):
            raise RuntimeError("connection refused")

    report = gate.Report()
    await gate.run(CONFIG, report, client=Dead([]))

    assert len(report.rows) == 1, "downstream checks cannot mean anything"
    assert report.rows[0][0] == "bench"


async def test_a_device_silent_for_months_fails():
    """An activation only proves it joined once. This is the check that
    would have caught a board off the air since June."""
    cfg = dict(CONFIG)
    cfg["devices"] = [{"slot": "SLOT1", "framework": "lorawan", "dev_eui": "aa"}]
    report = gate.Report()
    bench = FakeBench([FakeSlot("SLOT1")], {"SLOT1": _fresh()})
    chirp = FakeChirp({"aa": {"dev_addr": "01", "f_cnt_up": 5}}, {})

    class Stubs:
        class device:
            @staticmethod
            def Get(req, metadata=None):
                class R:
                    class last_seen_at:
                        seconds = int(time.time()) - 5_000_000
                return R()

    chirp._get_stubs = lambda: Stubs
    chirp._auth = []
    await gate.run(cfg, report, client=bench, chirp=chirp)

    assert any(s == "uplinks" and "silent for over" in d
               for s, _, ok, d in report.rows if not ok), report.rows


def test_a_missing_roster_is_reported_not_raised(tmp_path):
    """The gate runs unattended; a config typo should read as one line,
    not a traceback."""
    with pytest.raises(gate.ConfigError, match="no such roster"):
        gate._load_config(tmp_path / "nope.yaml")


@pytest.mark.parametrize("body", ["", "max_serial_silence_s: 60\n"])
def test_a_roster_with_no_devices_is_rejected(tmp_path, body):
    """Silently checking nothing and exiting 0 is the worst outcome for a
    gate -- it reads as 'all clear'."""
    p = tmp_path / "roster.yaml"
    p.write_text(body)
    with pytest.raises(gate.ConfigError):
        gate._load_config(p)


OFF_BENCH = {
    "max_serial_silence_s": 1800,
    "max_uplink_silence_s": 3600,
    "devices": [
        {"slot": "SLOT1", "framework": "lorawan"},
        {"name": "TTGO LoRa32 v2", "on_bench": False, "dev_eui": "bb"},
    ],
}


def _chirp_seen(seconds_ago):
    chirp = FakeChirp({"bb": {"dev_addr": "02", "f_cnt_up": 9}}, {})

    class Stubs:
        class device:
            @staticmethod
            def Get(req, metadata=None):
                class R:
                    class last_seen_at:
                        seconds = int(time.time()) - seconds_ago
                return R()

    chirp._get_stubs = lambda: Stubs
    chirp._auth = []
    return chirp


async def test_off_bench_device_does_not_fail_the_slots_stage():
    """Its cable is out and everyone knows. Failing nightly on a known
    condition is how a gate gets muted."""
    report = gate.Report()
    bench = FakeBench([FakeSlot("SLOT1")], {"SLOT1": _fresh()})
    await gate.run(OFF_BENCH, report, client=bench, chirp=_chirp_seen(30))

    assert not report.failed, report.rows
    assert not any(s in ("slots", "serial") and "LoRa32" in subj
                   for s, subj, _, _ in report.rows)


async def test_off_bench_device_is_still_asserted_over_the_air():
    """The radio is the only assertion it gets, so it has to be a real one."""
    report = gate.Report()
    bench = FakeBench([FakeSlot("SLOT1")], {"SLOT1": _fresh()})
    await gate.run(OFF_BENCH, report, client=bench, chirp=_chirp_seen(99_999))

    assert any(s == "uplinks" and "LoRa32" in subj and "silent for over" in d
               for s, subj, ok, d in report.rows if not ok), report.rows


async def test_a_reconnected_board_is_reported():
    """Slot labels are positional, so a returning board cannot be predicted
    onto a label -- it has to be caught as 'something is here that should
    not be'. This is the whole point of listing an off-bench device."""
    report = gate.Report()
    bench = FakeBench([FakeSlot("SLOT1"), FakeSlot("SLOT7")],
                      {"SLOT1": _fresh(), "SLOT7": _fresh()})
    await gate.run(OFF_BENCH, report, client=bench, chirp=_chirp_seen(30))

    hits = [r for r in report.failed if r[1] == "SLOT7"]
    assert hits, report.rows
    assert "unexpected board present" in hits[0][3]


async def test_an_absent_unclaimed_slot_is_not_reported():
    """The bench has 31 slots and most are always empty."""
    report = gate.Report()
    bench = FakeBench([FakeSlot("SLOT1"), FakeSlot("SLOT7", present=False)],
                      {"SLOT1": _fresh()})
    await gate.run(OFF_BENCH, report, client=bench, chirp=_chirp_seen(30))
    assert not report.failed, report.rows


def test_an_on_bench_device_without_a_slot_is_rejected(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("devices:\n  - name: nameless\n    dev_eui: aa\n")
    with pytest.raises(gate.ConfigError, match="has no slot"):
        gate._load_config(p)


def test_an_off_bench_device_without_a_dev_eui_is_rejected(tmp_path):
    """Off the bench and no radio identity means nothing can be checked --
    it would sit in the roster looking monitored."""
    p = tmp_path / "r.yaml"
    p.write_text("devices:\n  - name: ghost\n    on_bench: false\n")
    with pytest.raises(gate.ConfigError, match="nothing about it can be checked"):
        gate._load_config(p)


class FlashBench(FakeBench):
    """Records writes. Like the real bench, the boot that follows a write
    goes unrecorded; a reset afterwards prints what `boot_lines` scripts
    for the framework written last."""

    def __init__(self, slots, boot_lines, fail_write=False):
        super().__init__(slots)
        self.boot_lines, self.fail_write = boot_lines, fail_write
        self.writes: list[dict] = []
        self.resets: list[str] = []
        self._written: dict[str, str] = {}

    async def slot(self, label):
        return next(s for s in self._slots if s.label == label)

    async def reset(self, slot):
        self.resets.append(slot)
        self._lines[slot] = [{"ts": time.time(), "text": t}
                             for t in self.boot_lines.get(self._written.get(slot, ""), [])]
        return {"ok": True}

    async def flash(self, slot, images, chip="esp32", erase=False, baud=921600):
        from wirestudio.workbench import WorkbenchUnavailable

        if self.fail_write:
            raise WorkbenchUnavailable("flash failed: A fatal error occurred: No serial data received.")
        self.writes.append({"slot": slot, "images": images, "chip": chip, "erase": erase})
        self._written[slot] = images[0][1].decode()
        self._lines[slot] = []
        yield {"type": "log", "data": "Hash of data verified."}
        yield {"type": "done", "ok": True, "slot": slot, "returncode": 0}

    async def monitor(self, slot, pattern=None, timeout=10.0):
        return {"matched": False, "line": None, "output": [e["text"] for e in self._lines.get(slot, [])]}


@pytest.fixture
def fake_images(monkeypatch):
    from wirestudio.workbench import images

    unavailable: dict[str, str] = {}

    async def image_for(framework, board, library, *, dashboard=None, functional_pin=None):
        unavailable.setdefault("_pins", []).append(functional_pin)
        if framework in unavailable:
            raise images.ImageUnavailable(unavailable[framework])
        offset = 0x1000 if framework == "micropython" and board.chip_variant == "esp32" else 0x0
        return images.Image(framework, offset, framework.encode(), "test")

    monkeypatch.setattr(images, "image_for", image_for)
    return unavailable


FLASH_CONFIG = {
    "devices": [{"slot": "SLOT2", "name": "spare S3", "board": "esp32-s3-devkitc-1",
                 "flash": ["esphome", "micropython", "circuitpython"]}],
}

BOOTS = {
    "esphome": ["[I][app:117]: setup() finished successfully!"],
    "micropython": ["MicroPython v1.26.1 on 2025-09-11; Generic ESP32S3 module with ESP32S3"],
    "circuitpython": ["Adafruit CircuitPython 10.3.1 on 2026-09-14; Espressif ESP32 DevKitc V4 WROOM-32E with ESP32"],
    "meshtastic": ["INFO  | ??:??:?? 0 Booted, wake cause 0 (boot count 1), reset_reason=reset"],
}


async def test_flash_writes_every_listed_framework_with_an_erase(fake_images):
    report = gate.Report()
    bench = FlashBench([FakeSlot("SLOT2", chip="esp32s3")], BOOTS)
    await gate.run(FLASH_CONFIG, report, client=bench)

    assert [w["images"][0][1] for w in bench.writes] == [b"esphome", b"micropython", b"circuitpython"]
    assert all(w["erase"] and w["chip"] == "esp32s3" for w in bench.writes)
    assert ("boot", "SLOT2/esphome", True) in [r[:3] for r in report.rows]
    assert ("boot", "SLOT2/micropython", True) in [r[:3] for r in report.rows]


async def test_a_flash_device_skips_the_serial_stage(fake_images):
    """At rest it runs whatever the last framework left, which may print
    nothing; boot is its liveness assertion."""
    report = gate.Report()
    bench = FlashBench([FakeSlot("SLOT2", chip="esp32s3")], BOOTS)
    await gate.run(FLASH_CONFIG, report, client=bench)
    assert not [r for r in report.rows if r[0] == "serial"]


async def test_boot_is_read_from_a_reset_after_each_write(fake_images):
    """covbench, 2026-10-23: the boot esptool triggers is never recorded,
    so without a reset ESPHome failed on a healthy board."""
    report = gate.Report()
    bench = FlashBench([FakeSlot("SLOT2", chip="esp32s3")], BOOTS)
    await gate.run(FLASH_CONFIG, report, client=bench)
    assert bench.resets == ["SLOT2"] * 3


async def test_meshtastic_boots_on_its_marker(fake_images):
    report = gate.Report()
    bench = FlashBench([FakeSlot("SLOT3", chip="esp32")], BOOTS)
    cfg = {"devices": [
        {"slot": "SLOT3", "board": "ttgo-lora32-v2", "flash": ["meshtastic"]}]}
    await gate.run(cfg, report, client=bench)
    assert ("boot", "SLOT3/meshtastic", True) in [r[:3] for r in report.rows]


async def test_circuitpython_boots_on_its_banner(fake_images):
    report = gate.Report()
    bench = FlashBench([FakeSlot("SLOT2", chip="esp32s3")], BOOTS)
    await gate.run(FLASH_CONFIG, report, client=bench)
    assert ("boot", "SLOT2/circuitpython", True) in [r[:3] for r in report.rows]


async def test_firmware_that_does_not_boot_fails(fake_images):
    report = gate.Report()
    bench = FlashBench([FakeSlot("SLOT2", chip="esp32s3")],
                       {"esphome": ["rst:0x10 (RTCWDT_RTC_RESET),boot:0x8"]})
    cfg = {**FLASH_CONFIG, "devices": [{**FLASH_CONFIG["devices"][0], "flash": ["esphome"]}]}
    await gate.run(cfg, report, client=bench)

    row = next(r for r in report.rows if r[:2] == ("boot", "SLOT2/esphome"))
    assert row[2] is False
    assert "RTCWDT_RTC_RESET" in row[3]


async def test_a_failed_write_is_reported_and_boot_not_asserted(fake_images):
    report = gate.Report()
    bench = FlashBench([FakeSlot("SLOT2", chip="esp32s3")], BOOTS, fail_write=True)
    await gate.run(FLASH_CONFIG, report, client=bench)

    flash_rows = [r for r in report.rows if r[0] == "flash"]
    assert len(flash_rows) == 3 and not any(r[2] for r in flash_rows)
    assert "No serial data received" in flash_rows[0][3]
    assert not [r for r in report.rows if r[0] == "boot"]


async def test_an_unavailable_image_fails_only_its_framework(fake_images):
    fake_images["esphome"] = "ESPHome needs ESPHOME_DASHBOARD_URL to compile"
    report = gate.Report()
    bench = FlashBench([FakeSlot("SLOT2", chip="esp32s3")], BOOTS)
    await gate.run(FLASH_CONFIG, report, client=bench)

    assert ("flash", "SLOT2/esphome", False) in [r[:3] for r in report.rows]
    assert ("boot", "SLOT2/micropython", True) in [r[:3] for r in report.rows]


async def test_an_unflashable_slot_is_not_written(fake_images):
    report = gate.Report()
    bench = FlashBench([FakeSlot("SLOT2", chip="esp32s3", flapping=True)], BOOTS)
    await gate.run(FLASH_CONFIG, report, client=bench)

    assert not bench.writes
    assert any(r[:2] == ("slots", "SLOT2") and not r[2] for r in report.rows)


@pytest.mark.parametrize("entry, match", [
    ("flash: [esphome]", "needs `board`"),
    ("flash: esphome\n    board: esp32-s3-devkitc-1", "must list frameworks"),
    ("flash: [tasmota]\n    board: esp32-s3-devkitc-1", "cannot flash tasmota"),
    ("flash: [esphome]\n    board: no-such-board", "unknown board"),
])
def test_a_bad_flash_entry_is_rejected(tmp_path, entry, match):
    p = tmp_path / "r.yaml"
    p.write_text(f"devices:\n  - slot: SLOT2\n    {entry}\n")
    with pytest.raises(gate.ConfigError, match=match):
        gate._load_config(p)


def test_a_valid_flash_entry_loads(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("devices:\n  - slot: SLOT2\n    board: heltec-wifi-lora32-v3\n"
                 "    flash: [esphome, meshtastic]\n")
    assert gate._load_config(p)["devices"][0]["flash"] == ["esphome", "meshtastic"]


# --- functional (phase 4) ------------------------------------------------

class FakeAPI:
    """Stands in for aioesphomeapi.APIClient. `follows` is whether the switch
    state tracks the command, as working firmware's does."""

    def __init__(self, name="hw-fn-esp32-devkitc-v4", entities=None, follows=True, refuse=False):
        self.name, self.follows, self.refuse = name, follows, refuse
        self.entities = entities if entities is not None else [
            type("SwitchInfo", (), {"key": 7, "object_id": "gate_switch", "name": "Gate switch"})()]
        self.commands: list[bool] = []
        self.hosts: list[str] = []
        self._cb = None

    def __call__(self, host, port, password):
        self.hosts.append(host)
        return self

    async def connect(self, login=False):
        if self.refuse:
            raise ConnectionRefusedError("[Errno 111] Connection refused")

    async def device_info(self):
        return type("DeviceInfo", (), {"name": self.name, "esphome_version": "2026.8.1"})()

    async def list_entities_services(self):
        return self.entities, []

    def subscribe_states(self, cb):
        self._cb = cb

    def switch_command(self, key, state):
        self.commands.append(state)
        if self.follows:
            self._cb(type("SwitchState", (), {"key": key, "state": state})())

    async def disconnect(self, force=False):
        pass


FUNCTIONAL_CONFIG = {
    "devices": [{"slot": "AUTO-1", "board": "esp32-devkitc-v4", "flash": ["esphome"], "functional": True}],
}

FUNCTIONAL_BOOTS = {"esphome": [
    "[I][app:117]: setup() finished successfully!",
    "[C][wifi:630]:   IP Address: 192.0.2.77",
]}


@pytest.fixture
def quick_ip(monkeypatch):
    from wirestudio.workbench import functional

    real = functional.wait_for_ip

    async def wait_for_ip(client, slot, since, timeout_s=60.0):
        return await real(client, slot, since, timeout_s=0)

    monkeypatch.setattr(functional, "wait_for_ip", wait_for_ip)


def _rows(report, stage):
    return [r for r in report.rows if r[0] == stage]


async def test_functional_round_trips_the_gate_switch(fake_images, quick_ip):
    report, api = gate.Report(), FakeAPI()
    bench = FlashBench([FakeSlot("AUTO-1")], FUNCTIONAL_BOOTS)
    await gate.run(FUNCTIONAL_CONFIG, report, client=bench, api_factory=api)

    assert fake_images["_pins"] == ["GPIO4"]
    assert api.hosts == ["192.0.2.77"] and api.commands == [True, False]
    [row] = _rows(report, "functional")
    assert row[:3] == ("functional", "AUTO-1/esphome", True), row
    assert "Gate switch on -> off" in row[3]


async def test_functional_is_off_unless_the_roster_asks(fake_images):
    report, api = gate.Report(), FakeAPI()
    cfg = {"devices": [{"slot": "AUTO-1", "board": "esp32-devkitc-v4", "flash": ["esphome"]}]}
    await gate.run(cfg, report, client=FlashBench([FakeSlot("AUTO-1")], FUNCTIONAL_BOOTS), api_factory=api)
    assert fake_images["_pins"] == [None] and not _rows(report, "functional") and not api.hosts


async def test_firmware_that_never_joins_wifi_fails(fake_images, quick_ip):
    report = gate.Report()
    bench = FlashBench([FakeSlot("AUTO-1")], {"esphome": FUNCTIONAL_BOOTS["esphome"][:1]})
    await gate.run(FUNCTIONAL_CONFIG, report, client=bench, api_factory=FakeAPI())
    [row] = _rows(report, "functional")
    assert not row[2] and "did not join WiFi" in row[3]


@pytest.mark.parametrize("api, says", [
    (FakeAPI(refuse=True), "did not answer"),
    (FakeAPI(name="something-else"), "answers as 'something-else'"),
    (FakeAPI(entities=[]), "no 'Gate switch' entity"),
    (FakeAPI(follows=False), "state stayed unreported"),
])
async def test_an_api_that_misbehaves_fails(fake_images, quick_ip, api, says):
    report = gate.Report()
    bench = FlashBench([FakeSlot("AUTO-1")], FUNCTIONAL_BOOTS)
    await gate.run(FUNCTIONAL_CONFIG, report, client=bench, api_factory=api)
    [row] = _rows(report, "functional")
    assert not row[2] and says in row[3], row


async def test_functional_host_skips_the_log(fake_images):
    report, api = gate.Report(), FakeAPI()
    cfg = {"devices": [dict(FUNCTIONAL_CONFIG["devices"][0], functional_host="hw-gate.local",
                            functional_pin="GPIO27")]}
    bench = FlashBench([FakeSlot("AUTO-1")], {"esphome": FUNCTIONAL_BOOTS["esphome"][:1]})
    await gate.run(cfg, report, client=bench, api_factory=api)
    assert api.hosts == ["hw-gate.local"] and fake_images["_pins"] == ["GPIO27"]
    assert _rows(report, "functional")[0][2]


@pytest.mark.parametrize("entry, match", [
    ("flash: [micropython]\n    board: esp32-devkitc-v4\n    functional: true", "add esphome"),
    ("flash: [esphome]\n    board: esp32-devkitc-v4\n    functional: true\n    functional_pin: GPIO99",
     "not a GPIO"),
])
def test_a_bad_functional_entry_is_rejected(tmp_path, entry, match):
    p = tmp_path / "r.yaml"
    p.write_text(f"devices:\n  - slot: SLOT2\n    {entry}\n")
    with pytest.raises(gate.ConfigError, match=match):
        gate._load_config(p)


def test_the_free_pin_avoids_straps_buses_and_the_console():
    from wirestudio.workbench.functional import FunctionalError, free_pin

    assert free_pin({"GPIO0": ["gpio", "strap"], "GPIO1": ["gpio", "serial_tx"],
                     "GPIO21": ["gpio", "i2c_sda"], "GPIO34": ["gpio", "input_only"],
                     "GPIO4": ["gpio", "adc", "pwm"]}) == "GPIO4"
    with pytest.raises(FunctionalError):
        free_pin({"GPIO0": ["gpio", "boot_high"]})


def test_the_functional_image_carries_wifi_the_api_and_the_switch():
    import yaml

    from wirestudio.generate.yaml_gen import render_yaml
    from wirestudio.library import default_library
    from wirestudio.model import Design
    from wirestudio.workbench.functional import design_fields

    lib = default_library()
    board = lib.board("esp32-devkitc-v4")
    design = Design.model_validate({
        "schema_version": "1.0", "id": "hw-fn-esp32-devkitc-v4", "name": "gate",
        "board": {"library_id": board.id, "mcu": board.mcu, "framework": board.framework},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0}, "buses": [],
        **design_fields("GPIO4"),
    })
    text = render_yaml(design, lib)
    assert "ssid: !secret wifi_ssid" in text and "password: !secret wifi_password" in text
    doc = yaml.safe_load(text.replace("!secret ", ""))
    assert doc["api"] == {} and doc["esphome"]["name"] == "hw-fn-esp32-devkitc-v4"
    assert doc["switch"] == [{"platform": "gpio", "pin": "GPIO4", "name": "Gate switch", "id": "gate_switch"}]


async def test_an_unreachable_dashboard_fails_the_flash_not_the_gate():
    """covbench one-off, 2026-10-26: a dashboard the gate cannot resolve
    raised out of the ESPHome image build and ended the run with a
    traceback instead of a report."""
    from wirestudio.esphome_dashboard import DashboardUnavailable

    class DeadDashboard:
        def is_configured(self):
            return True

        async def push_device(self, name, yaml_text):
            raise DashboardUnavailable("dashboard websocket failed: [Errno -3] Temporary failure in name resolution")

    report = gate.Report()
    bench = FlashBench([FakeSlot("AUTO-1")], BOOTS)
    cfg = {"devices": [{"slot": "AUTO-1", "board": "esp32-devkitc-v4", "flash": ["esphome"]}]}
    await gate.run(cfg, report, client=bench, dashboard=DeadDashboard())

    [row] = [r for r in report.rows if r[0] == "flash"]
    assert row[:3] == ("flash", "AUTO-1/esphome", False)
    assert "name resolution" in row[3]
    assert not bench.writes


async def test_a_weak_link_is_named_in_the_failure(fake_images, quick_ip, monkeypatch):
    """covbench one-off, 2026-10-26: the board joined its access point at -97 dBm,
    dropped and rejoined, and its API timed out with an empty message."""
    report = gate.Report()
    boots = {"esphome": FUNCTIONAL_BOOTS["esphome"] + [
        "[I][wifi:1588]: - 'bench-ap' (02:00:00:00:00:01) ▂▄▆█ Ch:11 -97dB P:0"]}

    class Hangs(FakeAPI):
        async def connect(self, login=False):
            import asyncio
            await asyncio.sleep(3600)

    from wirestudio.workbench import functional

    real_verify = functional.verify

    async def quick_verify(host, name, *, api_factory=None, timeout_s=30.0):
        return await real_verify(host, name, api_factory=api_factory, timeout_s=0.05)

    monkeypatch.setattr(functional, "verify", quick_verify)
    await gate.run(FUNCTIONAL_CONFIG, report, client=FlashBench([FakeSlot("AUTO-1")], boots),
                   api_factory=Hangs())
    [row] = _rows(report, "functional")
    assert not row[2]
    assert "did not answer within 0s" in row[3]
    assert "-97 dBm; too weak to hold a link" in row[3]


def test_the_functional_build_has_its_own_device_name():
    """covbench, 2026-10-27: a functional one-off and the nightly board-only
    build shared a name, and ESPHome's cache crashed the next compile."""
    from wirestudio.workbench.functional import device_name

    assert device_name("esp32-devkitc-v4", True) != device_name("esp32-devkitc-v4", False)
    # ESPHome caps a device name at 31 characters; the longest library board id must fit.
    from wirestudio.library import default_library

    longest = max((b.id for b in default_library().list_boards()), key=len)
    assert len(device_name(longest, False)) <= 31 and len(device_name(longest, True)) <= 31, longest


async def test_the_image_is_built_under_the_name_its_mode_uses(monkeypatch):
    from wirestudio.workbench import images

    pushed = []

    class Dash:
        def is_configured(self):
            return True

        async def push_device(self, name, yaml_text):
            pushed.append(name)
            raise images.ImageUnavailable("stop here")

    lib = __import__("wirestudio.library", fromlist=["default_library"]).default_library()
    board = lib.board("esp32-devkitc-v4")
    for pin in (None, "GPIO4"):
        with pytest.raises(images.ImageUnavailable):
            await images.image_for("esphome", board, lib, dashboard=Dash(), functional_pin=pin)
    assert pushed == ["hw-gate-esp32-devkitc-v4", "hw-fn-esp32-devkitc-v4"]
