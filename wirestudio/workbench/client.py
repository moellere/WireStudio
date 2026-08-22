"""HTTP client for a Universal Embedded Workbench.

  WORKBENCH_URL    base URL of the Pi's portal (e.g. http://10.0.0.44:8080)
  WORKBENCH_TOKEN  optional bearer token, sent when set

The stock portal does not authenticate, so the token is sent only for
benches fronted by something that does (a reverse proxy, say). It is not
required, and requiring it bought nothing: anyone able to set the URL can
set a token too, so it gated nothing while implying a credential that does
not exist.

WORKBENCH_URL is therefore the gate, and it is a real one -- the server
uploads firmware to whatever host it names. Point it only at a bench you
control. See docs/workbench.md.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import AsyncIterator, Iterator, Optional

import httpx
from wirestudio.errors import describe


class WorkbenchUnavailable(RuntimeError):
    """Raised when the workbench is missing config, unreachable, or refuses."""


def _error_text(r: httpx.Response) -> str:
    """The portal answers failures as {"ok": false, "error": "..."}.

    Falls back to the raw body: an error surfaced to an operator staring
    at a bench in another town should carry the bench's own words.
    """
    try:
        body = r.json()
        if isinstance(body, dict) and body.get("error"):
            return f"http {r.status_code}: {body['error']}"
    except ValueError:
        pass
    return f"http {r.status_code}: {r.text[:200]}"


def _last_meaningful(output: str) -> Optional[str]:
    """Last non-progress line of an esptool log.

    esptool's failures land after a wall of progress bars, so the tail is
    the part worth putting in front of an operator.
    """
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line and "[" not in line and not line.startswith("Writing at"):
            return line
    return None


@dataclass
class Slot:
    """A USB slot on the bench.

    `state` is the bench's own word for it -- "idle", "absent",
    "flashing", "monitoring". `busy` collapses that plus the health
    flags into the single question a caller has: can I flash here now?
    """

    label: str
    state: str
    present: bool
    chip: Optional[str]
    product: Optional[str]
    serial_url: Optional[str]
    flapping: bool
    last_error: Optional[str]

    @property
    def busy(self) -> bool:
        return self.state not in ("idle", "absent")

    @property
    def flashable(self) -> tuple[bool, Optional[str]]:
        """(ok, reason) -- the pre-flight the bench cannot answer for us.

        Refusing a flash onto a flapping slot is deliberate: a slot whose
        USB link is dropping produces failures that read as firmware
        faults, which is the confusion a hardware gate must not create.
        """
        if not self.present:
            # `present` tracks the serial devnode, so a slot holding a
            # non-serial peripheral (an SDR dongle, say) reads as absent.
            # Saying "empty" there sends the operator to look at the wrong
            # slot.
            if self.product:
                return False, f"{self.label} has no serial device ({self.product} attached)"
            return False, f"{self.label} is empty"
        if self.flapping:
            return False, f"{self.label} USB link is flapping ({self.last_error or 'unstable'})"
        if self.busy:
            return False, f"{self.label} is {self.state}"
        return True, None

    @classmethod
    def from_api(cls, d: dict) -> "Slot":
        usb = d.get("usb_devices") or []
        return cls(
            label=d.get("label", "?"),
            state=d.get("state", "unknown"),
            present=bool(d.get("present")),
            chip=d.get("detected_chip"),
            product=(usb[0].get("product") if usb else None),
            serial_url=d.get("url"),
            flapping=bool(d.get("flapping")),
            last_error=d.get("last_error"),
        )


class WorkbenchClient:
    """Talks to a workbench portal over HTTP.

    Configured from the environment by default so the API layer stays
    process-state-free. is_available() returns (ok, reason) so callers
    can surface the specific gap rather than a generic failure.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
        flash_timeout: float = 300.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.base_url = (
            base_url if base_url is not None else os.environ.get("WORKBENCH_URL", "")
        ).rstrip("/")
        self.token = token if token is not None else os.environ.get("WORKBENCH_TOKEN", "")
        self.timeout = timeout
        self.flash_timeout = flash_timeout
        self._transport = transport

    def _client(self, timeout: Optional[float] = None) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout or self.timeout,
            headers=headers,
            transport=self._transport,
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def unconfigured_reason(self) -> Optional[str]:
        if not self.base_url:
            return "WORKBENCH_URL not set"
        return None

    async def is_available(self) -> tuple[bool, Optional[str]]:
        """Cheap readiness probe against GET /api/info. Never raises."""
        reason = self.unconfigured_reason()
        if reason:
            return False, reason
        try:
            async with self._client() as c:
                r = await c.get("/api/info")
        except httpx.HTTPError as e:
            return False, f"unreachable: {describe(e)}"
        if r.status_code == 401:
            return False, "unauthorized (check WORKBENCH_TOKEN)"
        if r.status_code >= 400:
            return False, f"http {r.status_code}"
        return True, None

    async def info(self) -> dict:
        return await self._get_json("/api/info")

    async def slots(self) -> list[Slot]:
        data = await self._get_json("/api/devices")
        return [Slot.from_api(s) for s in data.get("slots", [])]

    async def slot(self, label: str) -> Slot:
        for s in await self.slots():
            if s.label == label:
                return s
        raise WorkbenchUnavailable(f"no such slot '{label}'")

    async def _get_json(self, path: str) -> dict:
        if not self.is_configured():
            raise WorkbenchUnavailable(
                self.unconfigured_reason() or "workbench not configured"
            )
        try:
            async with self._client() as c:
                r = await c.get(path)
        except httpx.HTTPError as e:
            raise WorkbenchUnavailable(f"unreachable: {describe(e)}") from e
        if r.status_code == 401:
            raise WorkbenchUnavailable("unauthorized (check WORKBENCH_TOKEN)")
        if r.status_code >= 400:
            raise WorkbenchUnavailable(f"{path}: http {r.status_code}")
        return r.json()

    # ------------------------------------------------------------------
    # Flash
    # ------------------------------------------------------------------

    async def flash(
        self,
        slot: str,
        images: list[tuple[int, bytes]],
        chip: str = "esp32",
        erase: bool = False,
        baud: int = 921600,
    ) -> AsyncIterator[dict]:
        """Upload images and stream the bench's flash progress.

        `images` is [(offset, bytes)]. Yields {"type": "log"|"done", ...}
        so the API layer only has to JSON-encode. The bench runs esptool
        against its own USB, so the payload crosses the network once
        instead of once per block.
        """
        if not self.is_configured():
            raise WorkbenchUnavailable(
                self.unconfigured_reason() or "workbench not configured"
            )
        if not images:
            raise WorkbenchUnavailable("no images to flash")

        ok, reason = (await self.slot(slot)).flashable
        if not ok:
            raise WorkbenchUnavailable(reason or f"{slot} is not flashable")

        form, files = _flash_payload(slot, images, chip, erase, baud)

        try:
            async with self._client(timeout=self.flash_timeout) as c:
                r = await c.post("/api/flash", data=form, files=files)
        except httpx.HTTPError as e:
            raise WorkbenchUnavailable(f"flash transport failed: {describe(e)}") from e

        for event in _flash_events(r, slot):
            yield event

    # ------------------------------------------------------------------
    # Synchronous variants
    #
    # The LoRaWAN target is synchronous (grpc + subprocess), so its routes
    # are plain `def` and FastAPI runs them in a threadpool. Awaiting from
    # there would need a nested event loop; these share the async path's
    # payload building and response handling.
    # ------------------------------------------------------------------

    def _sync_client(self, timeout: Optional[float] = None) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return httpx.Client(
            base_url=self.base_url, timeout=timeout or self.timeout, headers=headers
        )

    def slots_sync(self) -> list[Slot]:
        if not self.is_configured():
            raise WorkbenchUnavailable(
                self.unconfigured_reason() or "workbench not configured"
            )
        try:
            with self._sync_client() as c:
                r = c.get("/api/devices")
        except httpx.HTTPError as e:
            raise WorkbenchUnavailable(f"unreachable: {describe(e)}") from e
        if r.status_code == 401:
            raise WorkbenchUnavailable("unauthorized (check WORKBENCH_TOKEN)")
        if r.status_code >= 400:
            raise WorkbenchUnavailable(f"/api/devices: http {r.status_code}")
        return [Slot.from_api(s) for s in r.json().get("slots", [])]

    def slot_sync(self, label: str) -> Slot:
        for s in self.slots_sync():
            if s.label == label:
                return s
        raise WorkbenchUnavailable(f"no such slot '{label}'")

    def flash_sync(
        self,
        slot: str,
        images: list[tuple[int, bytes]],
        chip: str = "esp32",
        erase: bool = False,
        baud: int = 921600,
    ) -> Iterator[dict]:
        if not self.is_configured():
            raise WorkbenchUnavailable(
                self.unconfigured_reason() or "workbench not configured"
            )
        if not images:
            raise WorkbenchUnavailable("no images to flash")

        ok, reason = self.slot_sync(slot).flashable
        if not ok:
            raise WorkbenchUnavailable(reason or f"{slot} is not flashable")

        form, files = _flash_payload(slot, images, chip, erase, baud)
        try:
            with self._sync_client(timeout=self.flash_timeout) as c:
                r = c.post("/api/flash", data=form, files=files)
        except httpx.HTTPError as e:
            raise WorkbenchUnavailable(f"flash transport failed: {describe(e)}") from e
        yield from _flash_events(r, slot)


def _flash_payload(slot, images, chip, erase, baud):
    """Multipart body for /api/flash.

    The portal keys each part by `bin@<offset>`; any other name is silently
    ignored and the request fails as "no binaries to flash".
    """
    files = [
        (f"bin@{offset:#x}", (f"{offset:#x}.bin", data, "application/octet-stream"))
        for offset, data in images
    ]
    form = {
        "slot": slot,
        "chip": chip,
        "baud": str(baud),
        "erase": "true" if erase else "false",
    }
    return form, files


def _flash_events(r: httpx.Response, slot: str) -> Iterator[dict]:
    """Turn the portal's one buffered answer into log + done events.

    The portal buffers esptool and replies once as {ok, output, returncode},
    so the log arrives at completion rather than live -- and a non-zero
    returncode comes back under HTTP 200, which is why success is read from
    that field rather than the status code.
    """
    if r.status_code >= 400:
        raise WorkbenchUnavailable(f"flash rejected: {_error_text(r)}")
    try:
        body = r.json()
    except ValueError as e:
        raise WorkbenchUnavailable(f"flash: unparseable response: {r.text[:200]}") from e

    output = body.get("output") or ""
    for line in output.splitlines():
        if line.strip():
            yield {"type": "log", "data": line.rstrip()}

    rc = body.get("returncode")
    if not body.get("ok") or rc not in (0, None):
        detail = body.get("error") or _last_meaningful(output) or f"returncode {rc}"
        raise WorkbenchUnavailable(f"flash failed: {detail}")

    yield {"type": "done", "ok": True, "slot": slot, "returncode": rc}
