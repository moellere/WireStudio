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
