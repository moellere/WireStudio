"""Workbench routes — remote flash transport (phase 1).

Not a target plugin: the workbench is a place to put firmware, not a
thing that generates it. The image comes from whichever framework proxy
already serves it; this module only moves it to a slot.
"""
from __future__ import annotations

import json
import time
from typing import Callable, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse

from wirestudio.workbench import WorkbenchClient, WorkbenchUnavailable

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _parse_images(raw: list[dict]) -> list[tuple[int, bytes]]:
    """[{offset, data}] -> [(int, bytes)]. `data` is base64.

    Offsets arrive as strings like "0x10000" from the browser, so they
    are parsed with base=0 rather than assumed decimal.
    """
    import base64

    if not raw:
        raise ValueError("no images supplied")
    out: list[tuple[int, bytes]] = []
    for i, img in enumerate(raw):
        try:
            offset = int(str(img["offset"]), 0)
            data = base64.b64decode(img["data"], validate=True)
        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(f"image {i}: {e}") from e
        if offset < 0:
            raise ValueError(f"image {i}: negative offset")
        if not data:
            raise ValueError(f"image {i}: empty payload")
        out.append((offset, data))
    return out


def router(client_factory: Optional[Callable[[], WorkbenchClient]] = None) -> APIRouter:
    router = APIRouter(tags=["workbench"])
    make_client = client_factory or WorkbenchClient

    @router.get("/status")
    async def workbench_status() -> dict:
        wc = make_client()
        ok, reason = await wc.is_available()
        return {
            "available": ok,
            "reason": reason,
            "url": wc.base_url or None,
            "configure_hint": (
                "Export WORKBENCH_URL=http://<pi>:8080 to flash boards on a remote "
                "bench. WORKBENCH_TOKEN is optional -- set it only if the bench "
                "sits behind something that authenticates."
                if not ok
                else None
            ),
        }

    @router.get("/slots")
    async def workbench_slots() -> dict:
        wc = make_client()
        if not wc.is_configured():
            raise HTTPException(
                status_code=503,
                detail="workbench not configured (set WORKBENCH_URL)",
            )
        try:
            slots = await wc.slots()
        except WorkbenchUnavailable as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return {
            "slots": [
                {
                    "label": s.label,
                    "state": s.state,
                    "present": s.present,
                    "chip": s.chip,
                    "product": s.product,
                    "serial_url": s.serial_url,
                    "flapping": s.flapping,
                    "last_error": s.last_error,
                    "flashable": s.flashable[0],
                    "blocked_reason": s.flashable[1],
                }
                for s in slots
            ],
        }

    @router.get("/slots/{slot}/output")
    async def workbench_slot_output(slot: str, since: float = 0, lines: int = 500) -> dict:
        """Lines the bench's recorder captured on `slot` after `since`
        (epoch seconds). Read-only: the recorder taps the port without
        touching the device."""
        wc = make_client()
        if not wc.is_configured():
            raise HTTPException(status_code=503, detail="workbench not configured (set WORKBENCH_URL)")
        try:
            entries = await wc.output(slot, lines=lines, since=since)
        except WorkbenchUnavailable as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return {"slot": slot, "lines": [
            {"ts": e.get("ts"), "text": str(e.get("text", ""))} for e in entries if isinstance(e, dict)
        ]}

    @router.get("/slots/{slot}/stream")
    async def workbench_slot_stream(
        request: Request,
        slot: str,
        since: Optional[float] = None,
        seconds: float = 120.0,
        idle: float = 30.0,
    ) -> StreamingResponse:
        """Relay `slot`'s serial live as SSE, in the shape `/flash` uses:
        each line the recorder captured after `since` (default: now) as it
        lands, then a `done` event. Read-only through the recorder, so it
        never takes the port. Bounded: it ends after `seconds` (at most
        600) or `idle` seconds without a line, and stops when the client
        goes away. A bench that refuses the read answers as an `error`
        event carrying its own words."""
        wc = make_client()
        if not wc.is_configured():
            raise HTTPException(status_code=503, detail="workbench not configured (set WORKBENCH_URL)")
        try:
            await wc.slot(slot)
        except WorkbenchUnavailable as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        start = time.time() if since is None else since
        seconds = min(max(seconds, 1.0), 600.0)
        idle = max(idle, 0.0)

        async def events():
            try:
                async for event in wc.stream_output(
                    slot, start, seconds=seconds, idle=idle, stop=request.is_disconnected,
                ):
                    if event["type"] == "ping":
                        yield ": ping\n\n"
                    else:
                        yield f"data: {json.dumps(event)}\n\n"
            except WorkbenchUnavailable as e:
                yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream", headers=_SSE_HEADERS
        )

    @router.post("/verify-boot")
    async def workbench_verify_boot(body: dict = Body(...)) -> dict:
        """Assert the firmware on a slot booted: watch its serial for the
        framework's boot marker, searching what the recorder already
        captured since `since` before waiting on new output. `reset`
        restarts the board through the bench first, which a check straight
        after a flash needs. A board that flashed but did not boot is a
        result, not an error."""
        from wirestudio.workbench.boot import verify_boot

        slot = str(body.get("slot") or "")
        framework = str(body.get("framework") or "")
        if not slot or not framework:
            raise HTTPException(status_code=422, detail="slot and framework are required")
        since = body.get("since")
        wc = make_client()
        if not wc.is_configured():
            raise HTTPException(status_code=503, detail="workbench not configured (set WORKBENCH_URL)")
        try:
            return await verify_boot(
                wc, slot, framework,
                since=float(since) if since is not None else None,
                check_join=bool(body.get("check_join", False)),
                reset=bool(body.get("reset", False)),
            )
        except WorkbenchUnavailable as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    @router.post("/flash")
    async def workbench_flash(body: dict = Body(...)) -> StreamingResponse:
        """Flash a slot, streaming the bench's esptool output as SSE.

        Everything checkable up front (config, slot health, payload
        shape) is validated before the stream opens, since SSE cannot
        carry a status change once it has.
        """
        wc = make_client()
        if not wc.is_configured():
            raise HTTPException(
                status_code=503,
                detail="workbench not configured (set WORKBENCH_URL)",
            )

        slot = body.get("slot")
        if not slot or not isinstance(slot, str):
            raise HTTPException(status_code=422, detail="slot is required")
        try:
            images = _parse_images(body.get("images") or [])
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

        try:
            ok, reason = (await wc.slot(slot)).flashable
        except WorkbenchUnavailable as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        if not ok:
            raise HTTPException(status_code=409, detail=reason)

        async def events():
            try:
                async for event in wc.flash(
                    slot=slot,
                    images=images,
                    chip=body.get("chip", "esp32"),
                    erase=bool(body.get("erase", False)),
                    baud=int(body.get("baud", 921600)),
                ):
                    yield f"data: {json.dumps(event)}\n\n"
            except WorkbenchUnavailable as e:
                yield f"event: error\ndata: {json.dumps({'message': str(e)})}\n\n"

        return StreamingResponse(
            events(), media_type="text/event-stream", headers=_SSE_HEADERS
        )

    return router
