"""The hardware gate's LoRaWAN flash: build, write, register, join, uplink.

A `lorawan` entry in a device's `flash:` list writes the standalone LoRaWAN
firmware for its board, registers the board in ChirpStack under a DevEUI
taken from its eFuse MAC, answers the firmware's key prompts over the slot's
serial port, and then asserts two things the device cannot claim for
itself: ChirpStack holds a session for it, and ChirpStack logged an uplink
from it after the join -- the frame went out over the air, through a
gateway in range, into the network server.

The flash, register and prompt steps are `provision_events`, the same flow
the studio's bench provisioning uses. It flushes the device's DevNonces at
registration, which is what makes a nightly erase-and-rejoin legal: the
erase restarts the device's nonce counter, and without the flush
ChirpStack would reject the replayed nonce and the join would fail with
nothing on the wire to say why.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

UPLINK_TIMEOUT_S = 180.0


@dataclass
class Row:
    stage: str
    ok: bool
    detail: str


def gate_design(board):
    from wirestudio.model import Design

    return Design.model_validate({
        "schema_version": "1.0", "id": f"hw-lora-{board.id}", "name": f"Hardware gate ({board.name})",
        "target": "lorawan", "lorawan": {},
        "board": {"library_id": board.id, "mcu": board.mcu},
        "power": {"supply": "usb", "rail_voltage_v": 3.3},
    })


def factory_image(design, library) -> bytes:
    """The blank-board image (bootloader, partitions, app) a full erase needs."""
    from wirestudio.targets.lorawan.compile import compile_firmware_events
    from wirestudio.workbench.images import ImageUnavailable

    tail: list[str] = []
    done: dict = {}
    for event in compile_firmware_events(design, library):
        if event["type"] == "log":
            tail = (tail + [event["data"]])[-5:]
        elif event["type"] == "done":
            done = event
    if not done.get("ok"):
        raise ImageUnavailable("LoRaWAN compile failed: " + " | ".join(t.strip() for t in tail))
    if not done.get("factory"):
        raise ImageUnavailable("LoRaWAN compile produced no factory image")
    return Path(done["factory"]).read_bytes()


def uplinks_since_join(chirpstack, dev_eui: str) -> int:
    """The session's uplink frame counter: 0 straight after a join, counting
    from the first data uplink. A join request can refresh a device's
    last-seen time, so that cannot tell a joined device from an uplinking one."""
    act = chirpstack.get_activation(dev_eui) or {}
    return int(act.get("f_cnt_up") or 0)


def run(dev: dict, board, library, *, workbench, chirpstack, image: bytes | None = None,
        uplink_timeout_s: float = UPLINK_TIMEOUT_S, poll_s: float = 10.0) -> list[Row]:
    """Synchronous: `provision_events` drives the bench and the serial port
    with blocking calls, so the gate runs this in a thread."""
    from wirestudio.errors import describe
    from wirestudio.targets.lorawan.workbench_provision import provision_events
    from wirestudio.workbench.images import ImageUnavailable

    design = gate_design(board)
    if image is None:
        try:
            image = factory_image(design, library)
        except ImageUnavailable as e:
            return [Row("flash", False, str(e))]
        except Exception as e:
            return [Row("flash", False, f"LoRaWAN compile: {describe(e)}")]

    rows: list[Row] = []
    phase = "flash"
    done: dict = {}
    tail: list[str] = []
    try:
        for event in provision_events(
            design, library, slot=dev["slot"], workbench=workbench, chirpstack=chirpstack,
            images=[(0x0, image)], erase=True,
            band=dev.get("band", "US915"), sub_band=int(dev.get("sub_band", 2)),
        ):
            if event["type"] == "phase":
                if event["phase"] == "detect":
                    rows.append(Row("flash", True, f"{len(image)} bytes at 0x0, DevEUI {event['dev_eui']}"))
                phase = {"register": "register", "provision": "join", "verify": "join"}.get(event["phase"], phase)
            elif event["type"] == "log" and phase == "join":
                line = str(event.get("data", "")).strip()
                if line:
                    tail = (tail + [line])[-6:]
            elif event["type"] == "done":
                done = event
    except Exception as e:
        # The serial dialogue is where a join goes quiet: unanswered prompts,
        # a radio that never transmits, a gateway that never hears it. What
        # the device last printed tells them apart; the prompt driver has
        # already redacted the key from these lines.
        said = f"; the device last printed: {' | '.join(tail)}" if phase == "join" and tail else ""
        rows.append(Row(phase, False, describe(e) + said))
        return rows

    joined_at = time.monotonic()
    rows.append(Row("join", True, f"DevAddr {done.get('dev_addr')}, session in ChirpStack"))

    dev_eui = done["dev_eui"]
    deadline = joined_at + uplink_timeout_s
    while True:
        try:
            count = uplinks_since_join(chirpstack, dev_eui)
        except Exception as e:
            rows.append(Row("uplink", False, describe(e)))
            return rows
        if count >= 1:
            rows.append(Row("uplink", True, f"ChirpStack counted {count} uplink(s) from {dev_eui} "
                                            f"{int(time.monotonic() - joined_at)}s after the join"))
            return rows
        if time.monotonic() >= deadline:
            rows.append(Row("uplink", False, f"joined, but ChirpStack counted no uplink from {dev_eui} "
                                             f"within {int(uplink_timeout_s)}s"))
            return rows
        time.sleep(poll_s)
