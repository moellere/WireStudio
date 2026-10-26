"""Firmware images for the hardware gate's flash stage.

One image per framework for a library board: ESPHome is compiled from a
board-only design through the configured ESPHome dashboard (no wifi, so
no secrets); CircuitPython, MicroPython and Meshtastic are the newest
stable release images the studio's flash dialog already serves. Every
image is written with a full erase, because a gate board switches
frameworks every night and each one leaves its own filesystem behind.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from wirestudio.library import Library, LibraryBoard

FRAMEWORKS = ("esphome", "circuitpython", "micropython", "meshtastic")


class ImageUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Image:
    framework: str
    offset: int
    data: bytes
    version: str


def _fetch(url: str) -> bytes:
    import httpx

    resp = httpx.get(url, timeout=180, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _release(framework: str, board: LibraryBoard) -> tuple[str, int, str]:
    """(url, offset, version) of a release image; raises LookupError when
    the framework has no image for the board."""
    if framework == "circuitpython":
        from wirestudio.api.circuitpython import release_url
        url, version = release_url(board.id)
        return url, 0x0, version
    if framework == "micropython":
        from wirestudio.api.micropython import image_for, latest_stable
        entry = image_for(board)
        if entry is None:
            raise LookupError(f"no MicroPython port for chip '{board.chip_variant}'")
        port, variant, offset = entry
        url, version = latest_stable(port, variant)
        return url, offset, version
    raise LookupError(f"'{framework}' is not a release-image framework")


async def _esphome(board: LibraryBoard, library: Library, dashboard, functional_pin: str | None) -> Image:
    from wirestudio.esphome_dashboard import DashboardUnavailable
    from wirestudio.generate.yaml_gen import render_yaml
    from wirestudio.mcp.hardware import is_merged_image
    from wirestudio.model import Design
    from wirestudio.workbench.functional import design_fields

    if dashboard is None or not dashboard.is_configured():
        raise ImageUnavailable("ESPHome needs ESPHOME_DASHBOARD_URL to compile")
    name = f"hw-gate-{board.id}"
    design = Design.model_validate({
        "schema_version": "1.0", "id": name, "name": f"Hardware gate ({board.name})",
        "board": {"library_id": board.id, "mcu": board.mcu, "framework": board.framework},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0},
        "components": [], "buses": [], "connections": [],
        **(design_fields(functional_pin) if functional_pin else {}),
    })
    try:
        pushed = await dashboard.push_device(name, render_yaml(design, library))
        tail: list[str] = []
        done = None
        async for event in dashboard.compile(pushed.filename):
            if event["type"] == "log":
                tail = (tail + [event["data"]])[-20:]
            else:
                done = event
        if not done or not done.get("ok"):
            raise ImageUnavailable("ESPHome compile failed: " + " | ".join(t.strip() for t in tail[-5:]))
        blob = await dashboard.firmware(pushed.filename, factory=True)
    except DashboardUnavailable as e:
        raise ImageUnavailable(f"ESPHome dashboard: {e}") from None
    if not blob or not is_merged_image(blob):
        raise ImageUnavailable("dashboard returned no merged factory image")
    return Image("esphome", 0x0, blob, "dashboard build")


async def image_for(framework: str, board: LibraryBoard, library: Library, *, dashboard=None,
                    functional_pin: str | None = None) -> Image:
    """The image the gate writes to `board` for `framework`. With
    `functional_pin`, the ESPHome image also carries WiFi, the API and the
    phase-4 gate switch on that pin."""
    if framework == "esphome":
        return await _esphome(board, library, dashboard, functional_pin)
    try:
        if framework == "meshtastic":
            from wirestudio.api.meshtastic import install_image
            data, _, version = await asyncio.to_thread(install_image, board.id)
            return Image(framework, 0x0, data, version)
        url, offset, version = await asyncio.to_thread(_release, framework, board)
        data = await asyncio.to_thread(_fetch, url)
    except LookupError as e:
        raise ImageUnavailable(str(e)) from None
    except Exception as e:
        from wirestudio.errors import describe
        raise ImageUnavailable(f"{framework} release download failed: {describe(e)}") from None
    return Image(framework, offset, data, version)
