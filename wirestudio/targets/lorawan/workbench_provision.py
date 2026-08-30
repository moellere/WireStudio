"""Headless LoRaWAN bring-up on a workbench slot.

Chains pieces that already exist -- compile, /workbench/flash,
ChirpStack `provision_device`, `get_activation` -- plus the serial prompt
driver, into one call. Before this the same sequence needed a browser at
the bench: WebSerial supplied the eFuse MAC and typed the keys into the
device's prompt.

Phase order is forced by the hardware, not by taste:

* Flash comes *before* registration, because esptool's own output is where
  the eFuse MAC (and therefore the DevEUI) comes from. The bench exposes no
  chip-detect endpoint, and esptool driven over RFC2217 cannot pull these
  boards into download mode at all.
* A full erase implies a DevNonce flush. Erasing empties NVS so the device
  re-prompts for keys, but it also restarts its DevNonce counter, and
  ChirpStack rejects a replayed nonce -- the join fails with nothing on the
  wire to explain it. `provision_device` flushes, so the registration step
  must follow the erase rather than precede it.
"""
from __future__ import annotations

import re
import secrets as _secrets
from typing import Iterator, Optional

from wirestudio.library import Library
from wirestudio.model import Design
from wirestudio.workbench import WorkbenchUnavailable
from wirestudio.workbench.serial import SerialUnavailable, answer_prompts

# LoRaWAN_ESP32's persist.manage() prompt set. Ordered: "sub-band" has to be
# tested before the bare "band" or it would answer the wrong question.
_PROMPT_RULES = [
    (re.compile(r"sub-?band", re.I), "sub_band"),
    (re.compile(r"\bband\b", re.I), "band"),
    (re.compile(r"dev\s?eui", re.I), "dev_eui"),
    (re.compile(r"join\s?eui|app\s?eui", re.I), "join_eui"),
    (re.compile(r"app\s?key", re.I), "app_key"),
    (re.compile(r"nwk\s?key|network key", re.I), "nwk_key"),
]

_DONE = re.compile(r"JOINED|JOIN FAILED")

_MAC_RE = re.compile(r"MAC:\s*((?:[0-9a-f]{2}:){5}[0-9a-f]{2})", re.I)


def dev_eui_from_mac(mac: str) -> str:
    """EUI-64 from a 48-bit MAC, the standard fffe insertion.

    Matches what the browser path derives, so a board keeps one identity
    whichever way it was provisioned.
    """
    raw = mac.replace(":", "").replace("-", "").lower()
    if len(raw) != 12 or not re.fullmatch(r"[0-9a-f]{12}", raw):
        raise ValueError(f"not a 48-bit MAC: {mac!r}")
    return raw[:6] + "fffe" + raw[6:]


def mac_from_flash_log(lines: list[str]) -> Optional[str]:
    """esptool prints `MAC: xx:xx:...` while flashing; that is the only
    chip identity the bench surfaces, so it is what we key the DevEUI on."""
    for line in lines:
        m = _MAC_RE.search(line)
        if m:
            return m.group(1).lower()
    return None


def provision_events(
    design: Design,
    library: Library,
    *,
    slot: str,
    workbench,
    chirpstack,
    images: list[tuple[int, bytes]],
    erase: bool = True,
    application_name: str = "wirestudio",
    band: str = "US915",
    sub_band: int = 2,
    serial_timeout: float = 180.0,
    serial_min_interval: float = 1.0,
) -> Iterator[dict]:
    """Flash, register, provision and verify one slot.

    Yields ``{"type": "phase"|"log"|"done", ...}``. Every failure surfaces as
    a raised WorkbenchUnavailable / SerialUnavailable / ChirpStackUnavailable
    so the caller can map it to one status code per cause.
    """
    from wirestudio.targets.lorawan import chirpstack as cs
    from wirestudio.targets.lorawan.codec import generate_codec, profile_name

    # ---- flash -------------------------------------------------------
    yield {"type": "phase", "phase": "flash", "slot": slot}
    flash_log: list[str] = []
    for event in workbench.flash_sync(slot=slot, images=images, erase=erase):
        if event.get("type") == "log":
            flash_log.append(event["data"])
            yield {"type": "log", "data": event["data"]}

    mac = mac_from_flash_log(flash_log)
    if mac is None:
        raise WorkbenchUnavailable(
            "esptool did not report a MAC; cannot derive the DevEUI "
            "(the bench exposes no separate chip-detect)"
        )
    dev_eui = dev_eui_from_mac(mac)
    yield {"type": "phase", "phase": "detect", "mac": mac, "dev_eui": dev_eui}

    # ---- register ----------------------------------------------------
    # After the erase, so provision_device's DevNonce flush lands on a device
    # whose counter has actually just restarted.
    yield {"type": "phase", "phase": "register", "dev_eui": dev_eui}
    app_key = _secrets.token_hex(16)
    join_eui = (
        design.lorawan.join_eui
        if (design.lorawan and design.lorawan.join_eui)
        else "0000000000000000"
    )
    result = chirpstack.provision_device(
        dev_eui=dev_eui,
        app_key=app_key,
        application_name=application_name,
        device_profile_name=profile_name(design, library),
        join_eui=join_eui,
        codec=generate_codec(design, library),
        # Records which slot this device physically sits in, at the one moment
        # that fact is known for certain. Without it the only slot->DevEUI map
        # is hand-maintained, and it goes stale silently the first time a board
        # is repurposed -- the device keeps uplinking under its new identity
        # while anything watching the old one reports dead hardware.
        tags={"slot": slot},
    )
    yield {
        "type": "phase",
        "phase": "registered",
        "application_id": result.get("application_id"),
        "device_profile_id": result.get("device_profile_id"),
    }

    # ---- serial provisioning ----------------------------------------
    slot_info = workbench.slot_sync(slot)
    if not slot_info.serial_url:
        raise SerialUnavailable(f"{slot} exposes no serial url")
    answers = {
        "band": band,
        "sub_band": str(sub_band),
        "dev_eui": dev_eui,
        "join_eui": join_eui,
        "app_key": app_key,
        "nwk_key": app_key,  # 1.0.x has one root key; both prompts take it
    }
    rules = [(pat, answers[key]) for pat, key in _PROMPT_RULES]

    yield {"type": "phase", "phase": "provision", "url": slot_info.serial_url}
    matched = None
    for event in answer_prompts(
        slot_info.serial_url,
        rules,
        done=_DONE,
        secrets=[app_key],
        timeout=serial_timeout,
        min_interval=serial_min_interval,
    ):
        if event["type"] == "log":
            yield event
        else:
            matched = event.get("matched")

    if matched != "JOINED":
        raise SerialUnavailable(f"device reported {matched or 'no join result'}")

    # ---- verify ------------------------------------------------------
    # "JOINED" is the device's own claim; the session in ChirpStack is the
    # independent one, and it is what an uplink will actually be decoded
    # against.
    yield {"type": "phase", "phase": "verify"}
    activation = chirpstack.get_activation(dev_eui)
    if not activation:
        raise cs.ChirpStackUnavailable(
            f"{dev_eui} reported JOINED but has no activation in ChirpStack"
        )

    yield {
        "type": "done",
        "ok": True,
        "dev_eui": dev_eui,
        "slot": slot,
        "dev_addr": activation.get("dev_addr"),
        "application_id": result.get("application_id"),
        "device_profile_id": result.get("device_profile_id"),
    }
