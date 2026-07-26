"""Meshtastic firmware proxy.

Not a target plugin: Meshtastic devices run stock firmware, so nothing
is generated from the design -- the design only tells us which board is
being flashed. Release binaries are individual files on
meshtastic.github.io (the same host the official web flasher uses); the
`.factory.bin` clean-install image flashes at 0x0 with a full erase.

Post-flash configuration (region, channels) is protobuf over serial,
not a text console, so there is no serial config push here -- the UI
links to client.meshtastic.org instead.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

_RELEASE_LIST = "https://api.meshtastic.org/github/firmware/list"
_FILES_BASE = "https://raw.githubusercontent.com/meshtastic/meshtastic.github.io/master"

# Library board id -> PlatformIO env name (the firmware filename stem),
# from the [env:...] sections in meshtastic/firmware's variants/.
_VARIANTS: dict[str, str] = {
    "heltec-wifi-lora32-v2": "heltec-v2_1",
    "heltec-wifi-lora32-v3": "heltec-v3",
    "heltec-wifi-lora32-v4": "heltec-v4",
    "ttgo-lora32-v1": "tlora-v1",
    "ttgo-lora32-v2": "tlora-v2-1-1_6",
    "ttgo-t-beam": "tbeam",
}

_FIRMWARE_TIMEOUT = 120  # seconds; factory images are ~4 MB


def _latest_stable() -> str:
    """Newest stable release id (e.g. 'v2.6.11.60ec05e') from the same
    release-list API the official web flasher uses."""
    import httpx

    resp = httpx.get(_RELEASE_LIST, timeout=15, follow_redirects=True)
    resp.raise_for_status()
    stable = resp.json()["releases"]["stable"]
    if not stable:
        raise RuntimeError("release list contains no stable releases")
    return stable[0]["id"]


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
        version, available, reason = None, False, f"release list unreachable: {e}"
    return {
        "available": available,
        "version": version,
        "boards": sorted(_VARIANTS),
        "reason": reason,
    }


def router() -> APIRouter:
    router = APIRouter(tags=["meshtastic"])

    @router.get("/firmware/status")
    def meshtastic_firmware_status() -> dict:
        return firmware_status()

    # No return annotation: `from __future__ import annotations` turns it
    # into a string OpenAPI generation can't resolve.
    @router.get("/firmware", response_class=Response)
    def meshtastic_firmware(board: str, version: str | None = None):
        variant = _VARIANTS.get(board)
        if variant is None:
            raise HTTPException(
                status_code=422,
                detail=f"no Meshtastic firmware mapping for board '{board}'",
            )
        try:
            ver = (version or _latest_stable()).lstrip("v")
            filename = f"firmware-{variant}-{ver}.factory.bin"
            url = f"{_FILES_BASE}/firmware-{ver}/{filename}"
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

    return router
