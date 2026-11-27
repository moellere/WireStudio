"""Workbench phase 4: provisioning a fresh device over its captive portal.

The gate builds an ESPHome image with no WiFi credentials at all: only a
fallback hotspot named after the board, `captive_portal:` and a web server.
After the boot check, the bench's `enter-portal` flow joins that hotspot,
submits a network name and password made up for this run to ESPHome's
`/wifisave` form, leaves, and brings up its own access point with those
credentials. The check passes when the device joins the bench's access point
and its web page answers through the bench's HTTP relay -- the path a person
takes with a new device and a phone.

The credentials are throwaway and live for one run; nothing is read from a
secrets file.
"""
from __future__ import annotations

import asyncio
import base64
import secrets
import time
from dataclasses import dataclass


def ap_ssid(board_id: str) -> str:
    """The device's fallback hotspot, also its ESPHome name. WiFi SSIDs cap at 32 bytes."""
    return f"hw-ap-{board_id}"[:32]


def design_fields(hotspot: str) -> dict:
    """What the provisioning gate adds to the gate's otherwise empty design."""
    return {"esphome_extras": {
        "wifi": {"ap": {"ssid": hotspot}},
        "captive_portal": {},
        "web_server": {"port": 80},
    }}


@dataclass
class Result:
    ok: bool
    detail: str


async def run(client, hotspot: str, *, join_timeout_s: float = 120.0, poll_s: float = 3.0) -> Result:
    ssid = f"wsgate-{secrets.token_hex(3)}"
    password = secrets.token_urlsafe(12)
    try:
        started = await client.enter_portal(
            portal_ssid=hotspot, ssid=ssid, password=password,
            save_path="/wifisave", field_ssid="ssid", field_password="psk", method="POST",
        )
    except Exception as e:
        from wirestudio.errors import describe
        return Result(False, f"bench could not start the portal flow: {describe(e)}")
    if not started.get("ok", True):
        return Result(False, f"bench refused the portal flow: {started.get('error', started)}")
    try:
        station = None
        deadline = time.monotonic() + join_timeout_s
        last: dict = {}
        while time.monotonic() < deadline:
            last = await client.wifi_ap_status()
            if last.get("active") and last.get("ssid") == ssid and last.get("stations"):
                station = last["stations"][0]
                break
            await asyncio.sleep(poll_s)
        if station is None:
            if not last.get("active") or last.get("ssid") != ssid:
                return Result(False, f"the bench never brought up {ssid!r}; the portal flow did not reach "
                                     f"its last step (was the hotspot {hotspot!r} visible?)")
            return Result(False, f"the device did not join the bench's {ssid!r} within "
                                 f"{int(join_timeout_s)}s of the credentials being submitted")
        ip = station.get("ip")
        if not ip:
            return Result(False, f"a station joined {ssid!r} ({station.get('mac')}) but took no address")
        page = await client.wifi_http(f"http://{ip}/")
        status = page.get("status")
        if status != 200:
            return Result(False, f"device at {ip} joined {ssid!r} but its web page answered {status}: "
                                 f"{page.get('error', '')}".rstrip(": "))
        body = base64.b64decode(page.get("body") or b"").decode(errors="replace")
        named = " and names itself" if hotspot in body else ""
        return Result(True, f"provisioned over the {hotspot!r} portal; joined {ssid!r} as {ip}, "
                            f"web page answers{named}")
    finally:
        try:
            await client.wifi_ap_stop()
        except Exception:
            pass
