"""Workbench phase 4: does the flashed ESPHome firmware behave?

`boot` proves the firmware started. This proves the device generated
from a design works the way Home Assistant will use it: it joined the
WiFi named in the dashboard's secrets, its native API answers under the
design's name, the switch the design declares is listed, and commanding
that switch on and off over the API comes back as state.

The gate's ESPHome image gains WiFi, the API and one `gpio_output` switch
on a free pin when the roster entry sets `functional: true`; nothing is
wired to the pin, so the switch is a pure firmware round trip. The API is
unencrypted: the device lives for one night on the bench network and the
gate would otherwise need the dashboard's key.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

SWITCH_ID = "gate_switch"
SWITCH_LABEL = "Gate switch"
API_PORT = 6053

_IP = re.compile(r"IP Address: (\d{1,3}(?:\.\d{1,3}){3})")
# ESPHome's scan list: "- 'ssid' (bssid) ▂▄▆█ Ch:11 -97dB".
_RSSI = re.compile(r"Ch:\s*\d+\s+(-\d+)\s*dB")
# A free pin carries none of these: they boot-strap the chip, belong to the
# console or a default bus, or cannot drive an output.
_RESERVED = ("strap", "boot", "serial", "uart", "input_only", "spi", "i2c", "usb", "psram", "flash")


class FunctionalError(Exception):
    pass


def device_name(board_id: str, functional: bool) -> str:
    """The ESPHome name the gate builds under. The functional build gets its
    own: ESPHome keys its build cache on the name and clears it when the
    config changes, and on 2026-10-26 a one-off functional build followed
    by the nightly board-only build under one name crashed that compile on
    a cache file the first had removed."""
    return f"{'hw-fn' if functional else 'hw-gate'}-{board_id}"


def free_pin(gpio_capabilities: dict[str, list[str]]) -> str:
    for pin, tags in gpio_capabilities.items():
        if "gpio" in tags and not any(t.startswith(_RESERVED) for t in tags):
            return pin
    raise FunctionalError("no free GPIO on this board for the gate switch; set `functional_pin`")


def design_fields(pin: str) -> dict:
    """What the functional gate adds to the gate's otherwise empty design."""
    return {
        "fleet": {"secrets_ref": {"wifi_ssid": "!secret wifi_ssid", "wifi_password": "!secret wifi_password"}},
        "components": [{"id": SWITCH_ID, "library_id": "gpio_output", "label": SWITCH_LABEL, "params": {}}],
        "connections": [{"component_id": SWITCH_ID, "pin_role": "OUT", "target": {"kind": "gpio", "pin": pin}}],
    }


async def wait_for_ip(client, slot: str, since: float, timeout_s: float = 60.0) -> str | None:
    """The address the firmware logged when it joined WiFi, from the slot's recorder."""
    deadline = time.monotonic() + timeout_s
    while True:
        for line in await client.output(slot, lines=1000, since=since):
            m = _IP.search(str(line.get("text", line) if isinstance(line, dict) else line))
            if m:
                return m.group(1)
        if time.monotonic() >= deadline:
            return None
        await asyncio.sleep(2)


async def last_rssi(client, slot: str, since: float) -> int | None:
    """The newest signal level the firmware logged from a WiFi scan."""
    rssi = None
    for line in await client.output(slot, lines=1000, since=since):
        m = _RSSI.search(str(line.get("text", line) if isinstance(line, dict) else line))
        if m:
            rssi = int(m.group(1))
    return rssi


@dataclass
class Result:
    ok: bool
    detail: str


async def verify(host: str, expected_name: str, *, api_factory=None, timeout_s: float = 30.0) -> Result:
    """Connect to the device's native API and round-trip the gate switch."""
    if api_factory is None:
        from aioesphomeapi import APIClient

        api_factory = APIClient
    api = api_factory(host, API_PORT, "")
    try:
        await asyncio.wait_for(api.connect(login=True), timeout_s)
    except TimeoutError:
        return Result(False, f"native API at {host}:{API_PORT} did not answer within {int(timeout_s)}s")
    except Exception as e:
        from wirestudio.errors import describe

        return Result(False, f"native API at {host}:{API_PORT} did not answer: {describe(e)}")
    try:
        info = await api.device_info()
        if info.name != expected_name:
            return Result(False, f"API at {host} answers as {info.name!r}, expected {expected_name!r}")
        entities, _ = await api.list_entities_services()
        switch = next((e for e in entities if getattr(e, "object_id", None) == SWITCH_ID
                       or getattr(e, "name", None) == SWITCH_LABEL), None)
        if switch is None:
            names = ", ".join(sorted(getattr(e, "name", "?") for e in entities)) or "none"
            return Result(False, f"no {SWITCH_LABEL!r} entity; the device lists {names}")

        states: dict[int, bool] = {}
        changed = asyncio.Event()

        def on_state(state) -> None:
            if getattr(state, "key", None) == switch.key:
                states[switch.key] = bool(state.state)
                changed.set()

        api.subscribe_states(on_state)
        for target in (True, False):
            changed.clear()
            api.switch_command(switch.key, target)
            try:
                async with asyncio.timeout(5):
                    while states.get(switch.key) is not target:
                        await changed.wait()
                        changed.clear()
            except TimeoutError:
                return Result(False, f"{SWITCH_LABEL} commanded {'on' if target else 'off'}, state stayed "
                                     f"{states.get(switch.key, 'unreported')}")
        return Result(True, f"api at {host} as {info.name}, esphome {info.esphome_version}; "
                            f"{SWITCH_LABEL} on -> off")
    finally:
        await api.disconnect()
