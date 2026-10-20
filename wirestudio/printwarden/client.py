"""HTTP + MCP client for a print-warden instance.

  PRINT_WARDEN_URL    base URL of the warden (e.g. http://10.0.0.29:8710)
  PRINT_WARDEN_TOKEN  its PRINT_WARDEN_TOKEN, sent as a bearer when set

The warden's contract is its MCP tool surface (submit_job, job_status,
list_printers); the only REST piece this client touches is `/upload`,
which is how a model gets onto the warden before `submit_job` names it.
Speaking MCP keeps the warden's trust gradient intact: wirestudio can
slice and queue, and nothing here can start a print -- that remains the
operator's phone tap (or the warden's own auto_start policy).

PRINT_WARDEN_URL is the gate, as with the workbench: the token is
optional because the warden runs open when its own token is unset.
"""
from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

from wirestudio.enclosure import generate_scad
from wirestudio.errors import describe
from wirestudio.library import Library
from wirestudio.model import Design


class PrintWardenUnavailable(RuntimeError):
    """Raised when the warden is missing config, unreachable, or refuses."""


class PrintWardenRejected(ValueError):
    """Raised when the warden took the request and said no: unknown printer
    or material, a model that does not fit, a tool error. The message is
    the warden's own text."""


# Top-level assignments in the generated .scad that `openscad -D` may
# override. Anything else is refused at the boundary: these values are
# passed to a process on another host.
TUNABLES = frozenset({
    "wall", "floor", "lid_t", "clearance", "standoff_h", "standoff_d",
    "standoff_hole", "port_clearance", "component_h", "ridge_h",
})


def validate_tunables(tunables: Optional[dict[str, Any]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in (tunables or {}).items():
        if key not in TUNABLES:
            raise ValueError(
                f"unknown tunable {key!r}; expected one of {', '.join(sorted(TUNABLES))}"
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"tunable {key!r} must be a number, got {value!r}")
        if not value >= 0:
            raise ValueError(f"tunable {key!r} must be >= 0, got {value!r}")
        out[key] = float(value)
    return out


class PrintWardenClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 120.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self.base_url = (
            base_url if base_url is not None else os.environ.get("PRINT_WARDEN_URL", "")
        ).rstrip("/")
        self.token = token if token is not None else os.environ.get("PRINT_WARDEN_TOKEN", "")
        self.timeout = timeout
        self._transport = transport

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def _client(self, status: Optional[_LastStatus] = None) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        return httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=self.timeout,
            transport=self._transport,
            follow_redirects=True,
            event_hooks={"response": [status]} if status else None,
        )

    async def is_available(self) -> tuple[bool, Optional[str], Optional[str]]:
        """(ok, reason, warden version). Probes `/healthz`, which is open,
        so this says reachable -- not that the token is right."""
        if not self.base_url:
            return False, "PRINT_WARDEN_URL not set", None
        try:
            async with self._client() as c:
                r = await c.get("/healthz")
        except httpx.HTTPError as e:
            return False, f"unreachable: {describe(e)}", None
        if r.status_code >= 400:
            return False, f"http {r.status_code}", None
        try:
            body = r.json()
        except ValueError:
            return False, "healthz did not return JSON", None
        if not isinstance(body, dict) or not body.get("ok"):
            return False, "healthz reports not ok", None
        return True, None, body.get("version")

    async def upload(self, name: str, data: bytes) -> str:
        """POST a model to `/upload`; returns the name the warden stored it
        under, which is what `submit_job` takes as `model`."""
        if not self.base_url:
            raise PrintWardenUnavailable("PRINT_WARDEN_URL not set")
        try:
            async with self._client() as c:
                r = await c.post("/upload", files={"file": (name, data, "application/octet-stream")})
        except httpx.HTTPError as e:
            raise PrintWardenUnavailable(f"unreachable: {describe(e)}") from e
        if r.status_code == 401:
            raise PrintWardenUnavailable("unauthorized (check PRINT_WARDEN_TOKEN)")
        if r.status_code >= 400:
            raise PrintWardenRejected(_error_text(r))
        body = r.json()
        return str(body.get("model") or name)

    @asynccontextmanager
    async def _session(self, status: _LastStatus) -> AsyncIterator[ClientSession]:
        async with self._client(status) as http:
            async with streamable_http_client(f"{self.base_url}/mcp", http_client=http) as (read, write, *_):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session

    async def call(self, tool: str, arguments: Optional[dict[str, Any]] = None) -> Any:
        """Call one warden MCP tool and return its JSON result.

        FastMCP puts a tool's return value in `structured_content`
        (wrapped as {"result": ...} when it is not an object) and the
        same JSON as the first text block; a raised exception comes back
        as `is_error` with the message in the text block.
        """
        if not self.base_url:
            raise PrintWardenUnavailable("PRINT_WARDEN_URL not set")
        # The transport folds an HTTP failure into a generic MCPError
        # inside a task group, so the status is read off the wire instead.
        status = _LastStatus()
        try:
            async with self._session(status) as session:
                result = await session.call_tool(tool, arguments or {})
        except (httpx.HTTPError, OSError, RuntimeError, ExceptionGroup) as e:
            if status.code == 401:
                raise PrintWardenUnavailable("unauthorized (check PRINT_WARDEN_TOKEN)") from e
            if status.code and status.code >= 400:
                raise PrintWardenUnavailable(f"http {status.code}") from e
            leaf = _first_leaf(e)
            if isinstance(leaf, httpx.HTTPError):
                raise PrintWardenUnavailable(f"unreachable: {describe(leaf)}") from e
            raise PrintWardenUnavailable(f"mcp failed: {describe(leaf)}") from e
        if not isinstance(result, CallToolResult):
            raise PrintWardenUnavailable(f"{tool}: unexpected MCP result {type(result).__name__}")
        text = next((getattr(b, "text", None) for b in result.content if getattr(b, "text", None)), None)
        if result.is_error:
            raise PrintWardenRejected(text or f"{tool} failed")
        if result.structured_content is not None:
            sc = result.structured_content
            if isinstance(sc, dict) and set(sc) == {"result"}:
                return sc["result"]
            return sc
        if text is None:
            return None
        try:
            return json.loads(text)
        except ValueError:
            return text

    async def list_printers(self) -> list[dict[str, Any]]:
        out = await self.call("list_printers")
        return out if isinstance(out, list) else []

    async def job_status(self, job_id: str) -> dict[str, Any]:
        out = await self.call("job_status", {"job_id": job_id})
        if not isinstance(out, dict):
            raise PrintWardenUnavailable(f"job_status returned {type(out).__name__}")
        return out


def _error_text(r: httpx.Response) -> str:
    try:
        body = r.json()
        if isinstance(body, dict) and body.get("error"):
            return f"http {r.status_code}: {body['error']}"
    except ValueError:
        pass
    return f"http {r.status_code}: {r.text[:200]}"


class _LastStatus:
    code: Optional[int] = None

    async def __call__(self, response: httpx.Response) -> None:
        self.code = response.status_code


def _first_leaf(exc: BaseException) -> BaseException:
    while isinstance(exc, ExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def enclosure_model_name(design: Design) -> str:
    return f"{design.id}-enclosure.scad"


async def submit_enclosure(
    client: PrintWardenClient,
    design: Design,
    library: Library,
    *,
    where: str,
    material: str,
    quality: str = "standard",
    tunables: Optional[dict[str, Any]] = None,
    copies: int = 1,
    offer: bool = True,
) -> dict[str, Any]:
    """Generate the design's enclosure shell, upload it to the warden and
    stage it as a job: the warden renders the .scad with the tunables as
    `-D` overrides, slices, checks and queues it. The job is offered to
    the operator's phone; nothing here starts it.

    Raises EnclosureUnavailable (board has no enclosure block), ValueError
    (bad tunables), PrintWardenUnavailable, PrintWardenRejected.
    """
    defines = validate_tunables(tunables)
    if copies < 1:
        raise ValueError("copies must be >= 1")
    scad = generate_scad(design, library)
    model = await client.upload(enclosure_model_name(design), scad.encode())
    args: dict[str, Any] = {
        "printer": where,
        "model": model,
        "material": material,
        "quality": quality,
        "name": f"{design.id}-enclosure",
        "copies": copies,
        "offer": offer,
    }
    if defines:
        args["scad_defines"] = defines
    job = await client.call("submit_job", args)
    if not isinstance(job, dict):
        raise PrintWardenUnavailable(f"submit_job returned {type(job).__name__}")
    return job
