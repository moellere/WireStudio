"""CircuitPython firmware proxy + starter code.py.

Not a target plugin: like Meshtastic, nothing is compiled from the design.
Release binaries live on downloads.circuitpython.org (S3), one combined
image per board id that flashes at 0x0 with a full erase; the newest
stable version comes from the adafruit/circuitpython GitHub releases API.

Builds are per-board and curated upstream, so the map below carries two
tiers: boards with an official build for the exact hardware, and boards
that fall back to a pin-compatible generic image (`exact: False` --
surfaced in the status response so the UI can warn that pin names and
flash/PSRAM sizing may differ). ESP8266 boards are absent: CircuitPython
dropped that port years ago.

A bare CircuitPython flash boots to an empty REPL, so `GET /code` also
serves a starter code.py generated from the board's library metadata
(LED blink, Vext power-up, I2C scan) for the user to drop onto the
CIRCUITPY drive.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from wirestudio.library import Library, LibraryBoard

_RELEASES_LATEST = "https://api.github.com/repos/adafruit/circuitpython/releases/latest"
_BIN_BASE = "https://downloads.circuitpython.org/bin"
_LANG = "en_US"

# Library board id -> CircuitPython board id (the directory name under
# ports/espressif/boards). exact=False marks a pin-compatible fallback
# image rather than a build for this precise board. Every id verified
# against downloads.circuitpython.org.
_BOARDS: dict[str, dict] = {
    "esp32-devkitc-v4":      {"image": "espressif_esp32_devkitc_v4_wroom_32e", "exact": True},
    "esp32-wrover-cam":      {"image": "espressif_esp32_devkitc_v4_wrover", "exact": False},
    "esp32cam-ai-thinker":   {"image": "espressif_esp32_devkitc_v4_wrover", "exact": False},
    "heltec-wifi-lora32-v2": {"image": "espressif_esp32_devkitc_v4_wroom_32e", "exact": False},
    "m5stack-atom":          {"image": "m5stack_atom_lite", "exact": True},
    "m5stack-atom-echo":     {"image": "m5stack_atom_echo", "exact": True},
    "m5stack-atom-matrix":   {"image": "m5stack_atom_matrix", "exact": True},
    "m5stack-atomu":         {"image": "m5stack_atom_u", "exact": True},
    "nodemcu-32s":           {"image": "espressif_esp32_devkitc_v4_wroom_32e", "exact": False},
    "ttgo-lora32-v1":        {"image": "espressif_esp32_devkitc_v4_wroom_32e", "exact": False},
    "ttgo-lora32-v2":        {"image": "espressif_esp32_devkitc_v4_wroom_32e", "exact": False},
    "ttgo-t-beam":           {"image": "espressif_esp32_devkitc_v4_wroom_32e", "exact": False},
    "esp32-c3-devkitm-1":    {"image": "espressif_esp32c3_devkitm_1_n4", "exact": True},
    "esp32-c3-supermini":    {"image": "makergo_esp32c3_supermini", "exact": True},
    "seeed-xiao-esp32c3":    {"image": "seeed_xiao_esp32c3", "exact": True},
    "esp32-c6-supermini":    {"image": "makergo_esp32c6_supermini", "exact": True},
    "esp32-s3-devkitc-1":    {"image": "espressif_esp32s3_devkitc_1_n8", "exact": True},
    "esp32-s3-supermini":    {"image": "espressif_esp32s3_devkitc_1_n8", "exact": False},
    "heltec-wifi-lora32-v3": {"image": "heltec_esp32s3_wifi_lora_v3", "exact": True},
    # Same V3-for-V4 substitution as the PlatformIO board key: no upstream
    # V4 build yet, and the V3 image boots the V4's S3 core.
    "heltec-wifi-lora32-v4": {"image": "heltec_esp32s3_wifi_lora_v3", "exact": False},
    "m5stack-atoms3":        {"image": "m5stack_atoms3", "exact": True},
    "m5stack-atoms3-lite":   {"image": "m5stack_atoms3_lite", "exact": True},
}

_FIRMWARE_TIMEOUT = 120  # seconds; combined images are ~2 MB


def _latest_stable() -> str:
    """Newest stable release tag (e.g. '10.2.1') from GitHub."""
    import httpx

    resp = httpx.get(_RELEASES_LATEST, timeout=15, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()["tag_name"].lstrip("v")


def _fetch_firmware(url: str) -> bytes:
    import httpx

    resp = httpx.get(url, timeout=_FIRMWARE_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def firmware_status() -> dict:
    try:
        version = _latest_stable()
        available, reason = True, None
    except Exception as e:
        version, available, reason = None, False, f"release lookup failed: {e}"
    return {
        "available": available,
        "version": version,
        "boards": sorted(_BOARDS),
        "generic": sorted(b for b, m in _BOARDS.items() if not m["exact"]),
        "images": {b: m["image"] for b, m in sorted(_BOARDS.items())},
        "reason": reason,
    }


def _pin_num(pin: object) -> str | None:
    s = str(pin or "")
    return s.removeprefix("GPIO") if s.startswith("GPIO") else None


def starter_code(board: LibraryBoard, exact: bool) -> str:
    """A dependency-free code.py (core modules only) from the board's
    library metadata: Vext power-up, LED blink, I2C scan, pin listing.
    Pin attributes vary per build, so lookups go through find_pin()."""
    onboard = board.onboard_peripherals or {}
    led = _pin_num((onboard.get("led") or {}).get("pin"))
    vext = onboard.get("vext") or {}
    vext_pin = _pin_num(vext.get("pin"))
    i2c = (board.default_buses or {}).get("i2c") or {}
    sda, scl = _pin_num(i2c.get("sda")), _pin_num(i2c.get("scl"))

    lines: list[str] = [
        f'"""{board.name} -- CircuitPython starter, generated by wirestudio.',
        "",
        "Copy this file to the CIRCUITPY drive as code.py. Output appears on",
        "the serial console (any serial terminal, or the REPL in Thonny/Mu).",
    ]
    if not exact:
        lines += [
            "",
            "NOTE: no official CircuitPython build exists for this exact board;",
            "the flashed image targets pin-compatible hardware. Pin names may",
            "differ -- the pin listing printed at boot shows what this build has.",
        ]
    if onboard:
        lines += ["", "Onboard peripherals (from the wirestudio board library):"]
        for key, params in onboard.items():
            lines.append(f"  {key}: {params}")
    lines += ['"""', "import time", "", "import board", "import digitalio", ""]

    lines += [
        "",
        "def find_pin(*names):",
        "    for n in names:",
        "        p = getattr(board, n, None)",
        "        if p is not None:",
        "            return p",
        "    return None",
        "",
    ]

    if vext_pin:
        polarity = "False" if vext.get("inverted") else "True"
        lines += [
            "",
            f"# Vext gates the onboard peripherals ({'active low' if vext.get('inverted') else 'active high'}) -- switch it on.",
            f'vext = find_pin("VEXT", "IO{vext_pin}", "GPIO{vext_pin}")',
            "if vext is not None:",
            "    vext_out = digitalio.DigitalInOut(vext)",
            "    vext_out.direction = digitalio.Direction.OUTPUT",
            f"    vext_out.value = {polarity}",
            "",
        ]

    if led:
        lines += [
            "",
            f"# Onboard LED (GPIO{led} in the wirestudio board library).",
            f'led_pin = find_pin("LED", "IO{led}", "GPIO{led}", "D{led}")',
            "led = None",
            "if led_pin is not None:",
            "    led = digitalio.DigitalInOut(led_pin)",
            "    led.direction = digitalio.Direction.OUTPUT",
            "",
        ]

    if sda and scl:
        lines += [
            "",
            f"# Default I2C bus (SDA=GPIO{sda}, SCL=GPIO{scl}): scan for devices.",
            "try:",
            "    import busio",
            "",
            f'    sda = find_pin("SDA", "IO{sda}", "GPIO{sda}", "D{sda}")',
            f'    scl = find_pin("SCL", "IO{scl}", "GPIO{scl}", "D{scl}")',
            "    if sda is not None and scl is not None:",
            "        i2c = busio.I2C(scl, sda)",
            "        if i2c.try_lock():",
            '            print("I2C scan:", [hex(a) for a in i2c.scan()])',
            "            i2c.unlock()",
            "except Exception as e:",
            '    print("I2C scan failed:", e)',
            "",
        ]

    lines += [
        "",
        'print("Pins this build exposes:")',
        'print(" ".join(n for n in sorted(dir(board)) if not n.startswith("_")))',
        "",
        "n = 0",
        "while True:",
    ]
    if led:
        lines += [
            "    if led is not None:",
            "        led.value = not led.value",
            "    else:",
            '        print("heartbeat", n)',
            "        n += 1",
        ]
    else:
        lines += ['    print("heartbeat", n)', "    n += 1"]
    lines += ["    time.sleep(1)", ""]
    return "\n".join(lines)


def router(lib: Library) -> APIRouter:
    router = APIRouter(tags=["circuitpython"])

    @router.get("/firmware/status")
    def circuitpython_firmware_status() -> dict:
        return firmware_status()

    # No return annotation: `from __future__ import annotations` turns it
    # into a string OpenAPI generation can't resolve.
    @router.get("/firmware", response_class=Response)
    def circuitpython_firmware(board: str, version: str | None = None):
        entry = _BOARDS.get(board)
        if entry is None:
            raise HTTPException(
                status_code=422,
                detail=f"no CircuitPython build mapping for board '{board}'",
            )
        image = entry["image"]
        try:
            ver = (version or _latest_stable()).lstrip("v")
            filename = f"adafruit-circuitpython-{image}-{_LANG}-{ver}.bin"
            url = f"{_BIN_BASE}/{image}/{_LANG}/{filename}"
            data = _fetch_firmware(url)
        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"could not fetch firmware: {e}"
            ) from e
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={
                "X-Flash-Offset": "0",
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @router.get("/code", response_class=Response)
    def circuitpython_code(board: str):
        entry = _BOARDS.get(board)
        if entry is None:
            raise HTTPException(
                status_code=422,
                detail=f"no CircuitPython build mapping for board '{board}'",
            )
        try:
            lib_board = lib.board(board)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        return Response(
            content=starter_code(lib_board, exact=entry["exact"]),
            media_type="text/x-python",
            headers={"Content-Disposition": 'attachment; filename="code.py"'},
        )

    return router
