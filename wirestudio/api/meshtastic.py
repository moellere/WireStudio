"""Meshtastic firmware proxy.

Not a target plugin: Meshtastic devices run stock firmware, so nothing
is generated from the design -- the design only tells us which board is
being flashed. Release binaries are individual files on
meshtastic.github.io (the same host the official web flasher uses). Since
2.7 the clean-install image is `firmware-<env>-<ver>.bin` (the old
`.factory.bin`) and flashes at 0x0 with a full erase; `-update.bin` is the
app-only OTA image.

Post-flash configuration (region, channels) is protobuf over serial,
not a text console, so there is no serial config push here -- the UI
links to client.meshtastic.org instead.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from wirestudio.errors import describe

_RELEASE_LIST = "https://api.meshtastic.org/github/firmware/list"
_FILES_BASE = "https://raw.githubusercontent.com/meshtastic/meshtastic.github.io/master"

# Library board id -> PlatformIO env name (the firmware filename stem),
# from the [env:...] sections in meshtastic/firmware's variants/. Only
# boards whose image the stable releases still publish: the Heltec V1/V2
# and TTGO LoRa32 V1 envs are marked not actively supported upstream and
# have no image on meshtastic.github.io.
_VARIANTS: dict[str, str] = {
    "heltec-wifi-lora32-v3": "heltec-v3",
    "heltec-wifi-lora32-v4": "heltec-v4",
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


def release_url(board: str, version: str | None = None) -> tuple[str, str]:
    """(download URL, version) of the Meshtastic factory image for a
    library board; the newest stable unless `version` pins one. The image
    flashes at 0x0 with a full erase."""
    variant = _VARIANTS.get(board)
    if variant is None:
        raise LookupError(f"no Meshtastic firmware mapping for board '{board}'")
    ver = (version or _latest_stable()).lstrip("v")
    filename = f"firmware-{variant}-{ver}.bin"
    return f"{_FILES_BASE}/firmware-{ver}/{filename}", ver


def firmware_status() -> dict:
    try:
        version = _latest_stable()
        available, reason = True, None
    except Exception as e:
        version, available, reason = None, False, f"release list unreachable: {describe(e)}"
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
        if board not in _VARIANTS:
            raise HTTPException(
                status_code=422,
                detail=f"no Meshtastic firmware mapping for board '{board}'",
            )
        try:
            url, _ = release_url(board, version)
            filename = url.rsplit("/", 1)[-1]
            data = _fetch_firmware(url)
        except Exception as e:
            raise HTTPException(
                status_code=502, detail=f"could not fetch firmware: {describe(e)}"
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
