"""HTTP endpoints for the LoRaWAN target, mounted under ``/lorawan``.

    GET  /lorawan/compile/status      PlatformIO availability probe
    POST /lorawan/compile             build a design's firmware; SSE log stream
    GET  /lorawan/firmware/{key}      download a cached firmware.bin
    GET  /lorawan/chirpstack/status   ChirpStack reachability + auth probe (read-only)
    POST /lorawan/provision           register a device in ChirpStack; issue an AppKey
    GET  /lorawan/activation/{eui}    has the device joined? (ChirpStack GetActivation)
    POST /lorawan/codec               set the board's decodeUplink codec on the device's profile

The compile stream mirrors the fleet log-stream shape: a sequence of
``data: {...}`` SSE frames (``{"type":"log"}`` chunks, a final
``{"type":"done", ...}``), or an ``event: error`` frame. Build artifacts are
content-addressed by ``cache_key``; a warm cache streams instantly and the bin
is fetched from ``/lorawan/firmware/{key}``.

``/provision`` is the backend half of serial provisioning: the browser sends the
device's DevEUI (derived from its eFuse MAC during flashing), this registers it
in ChirpStack with a freshly-issued AppKey and flushes its DevNonces, and returns
the band/sub-band/EUIs/AppKey the host then writes into LoRaWAN_ESP32's serial
prompt (``Enter band`` / ``subband`` / ``joinEUI`` / ``devEUI`` / ``appKey``).
"""
from __future__ import annotations

import json
import re
import secrets

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import ValidationError

from wirestudio.library import Library
from wirestudio.model import Design
from wirestudio.targets.build_backend import BuildBackend, BuildUnavailable
from wirestudio.targets.lorawan.firmware_gen import generate_firmware

# A build job id, used as a single path segment to address the artifact. The
# local backend's id is a hex cache key; a remote worker's is its own handle, so
# this stays format-agnostic -- alphanumeric start, then word/.-_ chars, no '/'
# and can't begin with '.', which blocks path traversal.
_KEY_RE = re.compile(r"^[0-9A-Za-z][0-9A-Za-z._-]{0,127}$")
_EUI_RE = re.compile(r"^[0-9a-fA-F]{16}$")
_ZERO_EUI = "0000000000000000"
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def build_router(library: Library, backend: BuildBackend) -> APIRouter:
    """`backend` is the build path the compile/firmware routes drive. The
    endpoints know nothing about PlatformIO -- swapping in a remote build worker
    is a different `backend`, not an endpoint change."""
    router = APIRouter(tags=["lorawan"])

    @router.get("/compile/status")
    def compile_status() -> dict:
        return backend.status()

    @router.post("/compile")
    def compile(design: dict) -> StreamingResponse:
        """Build the design's firmware, streaming the build log as SSE.

        Validates eagerly (422 on a bad design or a non-radio board) so failures
        surface before the stream opens.
        """
        try:
            d = Design.model_validate(design)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc
        try:
            generate_firmware(d, library)  # eager validate: board + radio block
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        job_id = backend.enqueue(d, library)

        def events():
            try:
                for event in backend.stream(job_id, d, library):
                    yield f"data: {json.dumps(event)}\n\n"
            except BuildUnavailable as exc:
                yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream", headers=_SSE_HEADERS)

    @router.get("/chirpstack/status")
    def chirpstack_status() -> dict:
        """Read-only ChirpStack probe (token + reachability). Lets the UI / a
        curl verify provisioning will work before flashing. Never mutates."""
        from wirestudio.targets.lorawan import chirpstack as cs

        return cs.chirpstack_status()

    @router.post("/provision")
    def provision(body: dict) -> dict:
        """Register the device in ChirpStack and issue its AppKey.

        The browser supplies the DevEUI (derived from the chip's eFuse MAC). We
        generate the AppKey server-side, register the device (US915 sub-2),
        flush its DevNonces, and return the values the host writes into the
        device's serial provisioning prompt. The AppKey is ephemeral and never
        persisted to design.json.
        """
        dev_eui = str(body.get("dev_eui", "")).lower()
        if not _EUI_RE.match(dev_eui):
            raise HTTPException(status_code=422, detail="dev_eui must be 16 hex characters")
        try:
            design = Design.model_validate(body["design"]) if body.get("design") else None
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        # Per-payload-shape profile + matching codec, derived from the design, so
        # different device types (and sensor sets) don't share one codec.
        from wirestudio.targets.lorawan import chirpstack as cs
        from wirestudio.targets.lorawan.codec import generate_codec, profile_name

        device_profile_name = profile_name(design, library) if design else "wirestudio-us915-sub2"
        codec = generate_codec(design, library) if design else None
        join_eui = (design.lorawan.join_eui if (design and design.lorawan and design.lorawan.join_eui) else None)
        application_name = str(body.get("application_name") or "wirestudio")

        client = cs.ChirpStackClient()
        if not client.is_configured():
            raise HTTPException(
                status_code=503,
                detail="ChirpStack not configured (set CHIRPSTACK_API_TOKEN / CHIRPSTACK_API_URL)",
            )
        app_key = secrets.token_hex(16)  # 16 bytes; server-issued, pushed to the device over serial
        try:
            result = client.provision_device(
                dev_eui=dev_eui,
                app_key=app_key,
                application_name=application_name,
                device_profile_name=device_profile_name,
                join_eui=join_eui,
                codec=codec,
            )
        except cs.ChirpStackUnavailable as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "dev_eui": dev_eui,
            "join_eui": join_eui or _ZERO_EUI,
            "band": "US915",
            "sub_band": 2,
            "app_key": app_key,
            "application_id": result["application_id"],
            "device_profile_id": result["device_profile_id"],
        }

    @router.get("/activation/{dev_eui}")
    def activation(dev_eui: str) -> dict:
        """Has the device joined? Reads ChirpStack's GetActivation. Read-only;
        the UI polls this after provisioning to confirm the OTAA join landed."""
        dev_eui = dev_eui.lower()
        if not _EUI_RE.match(dev_eui):
            raise HTTPException(status_code=422, detail="dev_eui must be 16 hex characters")
        from wirestudio.targets.lorawan import chirpstack as cs

        client = cs.ChirpStackClient()
        if not client.is_configured():
            raise HTTPException(status_code=503, detail="ChirpStack not configured")
        try:
            act = client.get_activation(dev_eui)
        except cs.ChirpStackUnavailable as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"dev_eui": dev_eui, "joined": act is not None, **(act or {})}

    @router.post("/codec")
    def set_codec(body: dict) -> dict:
        """Set the design's decodeUplink codec on the device's ChirpStack profile,
        so its uplinks decode into named ``object`` fields. Takes the design (so an
        external GPS in lorawan.gps is reflected). Works for an already provisioned
        device too (no re-provision needed)."""
        dev_eui = str(body.get("dev_eui", "")).lower()
        if not _EUI_RE.match(dev_eui):
            raise HTTPException(status_code=422, detail="dev_eui must be 16 hex characters")
        try:
            design = Design.model_validate(body["design"]) if body.get("design") else None
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()) from exc

        from wirestudio.targets.lorawan import chirpstack as cs
        from wirestudio.targets.lorawan.codec import generate_codec

        client = cs.ChirpStackClient()
        if not client.is_configured():
            raise HTTPException(status_code=503, detail="ChirpStack not configured")
        try:
            profile_id = client.set_device_codec(dev_eui, generate_codec(design, library))
        except cs.ChirpStackUnavailable as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"dev_eui": dev_eui, "device_profile_id": profile_id, "codec_set": True}

    @router.get("/codec/{dev_eui}")
    def get_codec(dev_eui: str) -> dict:
        """Read-only: report the codec on the device's ChirpStack profile, to
        verify decoding will happen (vs. an empty ``object``)."""
        dev_eui = dev_eui.lower()
        if not _EUI_RE.match(dev_eui):
            raise HTTPException(status_code=422, detail="dev_eui must be 16 hex characters")
        from wirestudio.targets.lorawan import chirpstack as cs

        client = cs.ChirpStackClient()
        if not client.is_configured():
            raise HTTPException(status_code=503, detail="ChirpStack not configured")
        try:
            return client.get_device_codec(dev_eui)
        except cs.ChirpStackUnavailable as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/firmware/{cache_key}")
    def firmware(cache_key: str) -> Response:
        if not _KEY_RE.match(cache_key):
            raise HTTPException(status_code=404, detail="unknown firmware")
        data = backend.artifact(cache_key)
        if data is None:
            raise HTTPException(status_code=404, detail="firmware not built; POST /lorawan/compile first")
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{cache_key}.bin"'},
        )

    @router.get("/firmware/{cache_key}/factory")
    def firmware_factory(cache_key: str) -> Response:
        """Merged bootloader+partitions+app image for flashing a blank board at
        offset 0x0. 404 when the build didn't produce one (e.g. esptool missing
        on a cache-hit-only worker) -- the app-region path is the fallback."""
        if not _KEY_RE.match(cache_key):
            raise HTTPException(status_code=404, detail="unknown firmware")
        data = backend.artifact(cache_key, "factory.bin")
        if data is None:
            raise HTTPException(status_code=404, detail="no factory image for this build")
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{cache_key}-factory.bin"'},
        )

    return router
