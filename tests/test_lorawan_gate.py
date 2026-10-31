"""The hardware gate's LoRaWAN flash: register, join, and an uplink ChirpStack counted."""
from __future__ import annotations

import pytest

from wirestudio.library import default_library
from wirestudio.workbench import gate, lorawan_gate

pytestmark = pytest.mark.anyio

FLASH_LOG = ["Chip type: ESP32-D0WDQ6 (revision v1.0)", "MAC: 10:52:1c:66:b6:e0", "Hash of data verified."]
DEV = {"slot": "AUTO-2", "board": "ttgo-lora32-v2", "flash": ["lorawan", "meshtastic"]}


@pytest.fixture
def anyio_backend():
    return "asyncio"


class Bench:
    def __init__(self, log=FLASH_LOG):
        self.log, self.flashed = log, []

    def flash_sync(self, *, slot, images, erase, **kw):
        self.flashed.append({"slot": slot, "offsets": [o for o, _ in images], "erase": erase})
        for line in self.log:
            yield {"type": "log", "data": line}
        yield {"type": "done", "ok": True}

    def slot_sync(self, label):
        from wirestudio.workbench import Slot

        return Slot(label, "idle", True, None, None, "rfc2217://bench:4002", False, None)


class Chirp:
    """`uplinks` lists the frame counter each successive activation read returns."""

    def __init__(self, uplinks=(0, 1), activated=True):
        self.uplinks, self.activated, self.provisioned = list(uplinks), activated, []

    def is_configured(self):
        return True

    def provision_device(self, **kw):
        self.provisioned.append(kw)
        return {"application_id": "app", "device_profile_id": "dp"}

    def get_activation(self, dev_eui):
        if not self.activated:
            return None
        f = self.uplinks.pop(0) if len(self.uplinks) > 1 else self.uplinks[0]
        return {"dev_addr": "0136e110", "f_cnt_up": f}


@pytest.fixture
def joins(monkeypatch):
    """The serial prompt driver, scripted: what the firmware finally prints."""
    from wirestudio.targets.lorawan import workbench_provision

    outcome = {"matched": "JOINED"}

    def answer_prompts(url, rules, *, done, secrets, timeout, min_interval):
        yield {"type": "log", "data": "Enter LoRaWAN band"}
        yield {"type": "done", "matched": outcome["matched"]}

    monkeypatch.setattr(workbench_provision, "answer_prompts", answer_prompts)
    return outcome


def _run(chirp, bench=None, **kw):
    lib = default_library()
    return lorawan_gate.run(DEV, lib.board(DEV["board"]), lib, workbench=bench or Bench(), chirpstack=chirp,
                            image=b"factory", poll_s=0, **kw)


def test_a_join_and_an_uplink_pass(joins):
    bench, chirp = Bench(), Chirp(uplinks=(0, 0, 1))
    rows = _run(chirp, bench)
    assert [(r.stage, r.ok) for r in rows] == [("flash", True), ("join", True), ("uplink", True)]
    assert "10521cfffe66b6e0" in rows[0].detail
    assert bench.flashed == [{"slot": "AUTO-2", "offsets": [0], "erase": True}]
    assert chirp.provisioned[0]["dev_eui"] == "10521cfffe66b6e0"
    assert chirp.provisioned[0]["tags"] == {"slot": "AUTO-2"}


def test_a_device_that_reports_join_failed_fails_the_join(joins):
    joins["matched"] = "JOIN FAILED"
    rows = _run(Chirp())
    assert rows[-1].stage == "join" and not rows[-1].ok and "JOIN FAILED" in rows[-1].detail


def test_joined_without_a_chirpstack_session_fails_the_join(joins):
    rows = _run(Chirp(activated=False))
    assert rows[-1].stage == "join" and not rows[-1].ok and "no activation" in rows[-1].detail


def test_a_join_with_no_uplink_fails_the_uplink(joins):
    """A join request alone can refresh last-seen; only the frame counter
    proves a data frame reached the network server."""
    rows = _run(Chirp(uplinks=(0,)), uplink_timeout_s=0)
    assert rows[-1].stage == "uplink" and not rows[-1].ok and "counted no uplink" in rows[-1].detail


def test_no_mac_in_the_flash_log_fails_the_flash(joins):
    rows = _run(Chirp(), Bench(log=["Hash of data verified."]))
    assert rows == [lorawan_gate.Row("flash", False, rows[0].detail)] and "MAC" in rows[0].detail


def test_a_compile_failure_fails_the_flash(monkeypatch):
    from wirestudio.workbench.images import ImageUnavailable

    def boom(design, library):
        raise ImageUnavailable("LoRaWAN compile failed: undefined reference")

    monkeypatch.setattr(lorawan_gate, "factory_image", boom)
    lib = default_library()
    rows = lorawan_gate.run(DEV, lib.board(DEV["board"]), lib, workbench=Bench(), chirpstack=Chirp())
    assert [(r.stage, r.ok) for r in rows] == [("flash", False)] and "undefined reference" in rows[0].detail


def test_the_gate_design_targets_lorawan_on_the_board():
    lib = default_library()
    d = lorawan_gate.gate_design(lib.board("ttgo-lora32-v2"))
    assert d.target == "lorawan" and d.board.library_id == "ttgo-lora32-v2" and d.id == "hw-lora-ttgo-lora32-v2"


# --- in the gate ---------------------------------------------------------

class GateBench:
    def __init__(self):
        from tests.test_hardware_gate import FakeSlot

        self._slots = [FakeSlot("AUTO-2")]

    async def info(self):
        return {"hostname": "fake"}

    async def slots(self):
        return self._slots


async def test_the_gate_reports_each_lorawan_row():
    report = gate.Report()

    def runner(dev, board, library, *, workbench, chirpstack):
        return [lorawan_gate.Row("flash", True, "ok"), lorawan_gate.Row("join", True, "DevAddr x"),
                lorawan_gate.Row("uplink", False, "counted no uplink")]

    cfg = {"devices": [dict(DEV, flash=["lorawan"])]}
    await gate.run(cfg, report, client=GateBench(), chirp=Chirp(), lorawan=runner)
    assert [r[:3] for r in report.rows if r[1] == "AUTO-2/lorawan"] == [
        ("flash", "AUTO-2/lorawan", True), ("join", "AUTO-2/lorawan", True), ("uplink", "AUTO-2/lorawan", False)]


async def test_a_lorawan_flash_needs_chirpstack():
    class Off(Chirp):
        def is_configured(self):
            return False

    report = gate.Report()
    await gate.run({"devices": [dict(DEV, flash=["lorawan"])]}, report, client=GateBench(), chirp=Off(),
                   lorawan=lambda *a, **k: pytest.fail("ran without ChirpStack"))
    [row] = [r for r in report.rows if r[1] == "AUTO-2/lorawan"]
    assert not row[2] and "CHIRPSTACK_API_URL" in row[3]


def test_lorawan_on_a_board_without_a_radio_is_rejected(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("devices:\n  - slot: AUTO-1\n    board: esp32-devkitc-v4\n    flash: [lorawan]\n")
    with pytest.raises(gate.ConfigError, match="no LoRa radio"):
        gate._load_config(p)


def test_lorawan_on_a_radio_board_loads(tmp_path):
    p = tmp_path / "r.yaml"
    p.write_text("devices:\n  - slot: AUTO-2\n    board: ttgo-lora32-v2\n    flash: [lorawan, meshtastic]\n")
    assert gate._load_config(p)["devices"][0]["flash"] == ["lorawan", "meshtastic"]
