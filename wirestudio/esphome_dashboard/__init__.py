"""Compile through an ESPHome Device Builder (the dashboard shipped with
ESPHome 2026.6 and later, the HA add-on, or `esphome dashboard`), as a
second build path beside fleet-for-esphome.

The Device Builder schedules its own build workers; the studio only
submits. Everything but the artifact download rides its single `/ws`
WebSocket: push writes the rendered YAML as `<device>.yaml` with
`devices/create`, compile queues `firmware/compile` and relays the line
events of `firmware/follow_job`, and the artifact names come from
`firmware/get_binaries` (ESP32 builds ship a factory and an OTA image,
ESP8266 a single `.bin`). The image itself is a plain HTTP GET with a
single-use token from `firmware/download_token`. A password-protected
builder announces `requires_auth` on connect and takes `auth/login`
in band. The wire details are the constants and small methods below,
validated against ESPHome 2026.10.0 with and without a password. The
legacy Tornado dashboard (`/login`, `/edit`, `/download.bin`) is gone
upstream and not spoken here.

Jobs are in-process: the studio runs each compile as a task, buffers
the log, and hands out a run_id that the same log / status / firmware
routes the fleet path uses can poll. A studio restart forgets running
jobs; the builder keeps compiling, and a re-push starts a fresh one.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from wirestudio.errors import describe

WS_PATH = "/ws"
DOWNLOAD_PATH = "/api/firmware/download"

_TIMEOUT = 15.0
_ARTIFACT_TIMEOUT = 120.0


class DashboardUnavailable(RuntimeError):
    """The dashboard is not configured, not reachable, or answered with
    something other than what the studio expects."""


@dataclass
class PushResult:
    filename: str
    created: bool


@dataclass
class JobLogChunk:
    log: str
    offset: int
    finished: bool


WsConnect = Callable[[str, dict[str, str]], Awaitable[object]]


class _Conn:
    """One authenticated WebSocket: request/response commands and streams,
    matched to their replies by message_id."""

    def __init__(self, ws: Any) -> None:
        self._ws = ws
        self._next = 0

    async def _send(self, command: str, args: dict) -> str:
        self._next += 1
        mid = str(self._next)
        await self._ws.send(json.dumps({"command": command, "message_id": mid, "args": args}))
        return mid

    async def _frames(self, mid: str) -> AsyncIterator[dict]:
        async for raw in self._ws:
            try:
                frame = json.loads(raw)
            except (TypeError, ValueError):
                continue
            if isinstance(frame, dict) and frame.get("message_id") == mid:
                if "error_code" in frame:
                    raise _CommandError(str(frame["error_code"]), str(frame.get("details", "")))
                yield frame
        raise _Closed("dashboard closed the websocket mid-command")

    async def call(self, command: str, args: Optional[dict] = None) -> Any:
        mid = await self._send(command, args or {})
        async for frame in self._frames(mid):
            if "result" in frame:
                return frame["result"]
        return None

    async def stream(self, command: str, args: dict) -> AsyncIterator[dict]:
        """Yield the `output` / `result` event frames of a streaming command."""
        mid = await self._send(command, args)
        async for frame in self._frames(mid):
            if frame.get("event") in ("output", "result"):
                yield frame
                if frame["event"] == "result":
                    return

    async def close(self) -> None:
        try:
            await self._ws.close()
        except Exception:
            pass


class _Closed(DashboardUnavailable):
    pass


class _CommandError(Exception):
    def __init__(self, code: str, details: str) -> None:
        super().__init__(f"{code}: {details}" if details else code)
        self.code = code


class DashboardClient:
    """Thin client over the Device Builder's WebSocket command API.

    `transport` injects an httpx transport for the artifact download in
    tests; `ws_connect` injects the websocket connector (defaults to the
    `websockets` package) so the command channel is testable without a
    socket.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        username: Optional[str] = None,
        password: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        ws_connect: Optional[WsConnect] = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else os.environ.get("ESPHOME_DASHBOARD_URL", "")).rstrip("/")
        self.username = username if username is not None else os.environ.get("ESPHOME_DASHBOARD_USERNAME")
        self.password = password if password is not None else os.environ.get("ESPHOME_DASHBOARD_PASSWORD")
        self._transport = transport
        self._ws_connect = ws_connect

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def _ws_url(self) -> str:
        return self.base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + WS_PATH

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[_Conn]:
        """Connect, read the server-info frame, log in when it asks."""
        connect = self._ws_connect or _default_ws_connect
        try:
            ws = await asyncio.wait_for(connect(self._ws_url(), {}), _TIMEOUT)
        except Exception as e:
            raise DashboardUnavailable(f"dashboard websocket failed: {describe(e)}") from e
        conn = _Conn(ws)
        try:
            try:
                info = json.loads(await asyncio.wait_for(ws.recv(), _TIMEOUT))
            except Exception as e:
                raise DashboardUnavailable(
                    f"dashboard sent no server info on {WS_PATH}; is the URL an ESPHome Device Builder? ({describe(e)})"
                ) from e
            if not isinstance(info, dict) or "requires_auth" not in info:
                raise DashboardUnavailable(f"unexpected greeting on {WS_PATH}; is the URL an ESPHome Device Builder?")
            if info["requires_auth"]:
                if not (self.username and self.password):
                    raise DashboardUnavailable(
                        "dashboard requires a login; set ESPHOME_DASHBOARD_USERNAME and ESPHOME_DASHBOARD_PASSWORD"
                    )
                try:
                    await conn.call("auth/login", {"username": self.username, "password": self.password})
                except _CommandError as e:
                    raise DashboardUnavailable("dashboard rejected ESPHOME_DASHBOARD_USERNAME / PASSWORD") from e
            yield conn
        except _CommandError as e:
            raise DashboardUnavailable(f"dashboard refused the command: {e}") from e
        except DashboardUnavailable:
            raise
        except (OSError, asyncio.TimeoutError) as e:
            raise DashboardUnavailable(f"dashboard unreachable: {describe(e)}") from e
        except Exception as e:
            if type(e).__module__.startswith("websockets"):
                raise DashboardUnavailable(f"dashboard websocket failed: {describe(e)}") from e
            raise
        finally:
            await conn.close()

    async def list_devices(self) -> list[str]:
        """Config filenames the dashboard knows (`x.yaml`)."""
        async with self._session() as c:
            body = await c.call("devices/list")
        configured = body.get("configured") if isinstance(body, dict) else None
        if not isinstance(configured, list):
            raise DashboardUnavailable("unexpected devices/list shape from the dashboard")
        return [str(d["configuration"]) for d in configured if isinstance(d, dict) and d.get("configuration")]

    async def is_available(self) -> tuple[bool, Optional[str]]:
        try:
            await self.list_devices()
        except DashboardUnavailable as e:
            return False, str(e)
        return True, None

    async def push_device(self, device_name: str, yaml: str) -> PushResult:
        name = _validate_name(device_name)
        async with self._session() as c:
            body = await c.call("devices/list")
            existing = {
                str(d.get("configuration")) for d in (body.get("configured") or []) if isinstance(d, dict)
            } if isinstance(body, dict) else set()
            try:
                made = await c.call(
                    "devices/create",
                    {"name": name, "friendly_name": name, "file_content": yaml, "overwrite": True},
                )
            except _CommandError as e:
                if e.code == "invalid_args":
                    raise ValueError(str(e)) from e
                raise
        filename = str(made.get("configuration")) if isinstance(made, dict) and made.get("configuration") else f"{name}.yaml"
        return PushResult(filename=filename, created=filename not in existing)

    async def compile(self, filename: str) -> AsyncIterator[dict]:
        """Yield {"type": "log", "data": line} per output line, then
        {"type": "done", "ok": bool, "code": int}."""
        async with self._session() as c:
            job = await c.call("firmware/compile", {"configuration": filename})
            job_id = job.get("job_id") if isinstance(job, dict) else None
            if not job_id:
                raise DashboardUnavailable("dashboard did not return a job id for firmware/compile")
            try:
                async for frame in c.stream("firmware/follow_job", {"job_id": job_id}):
                    if frame["event"] == "output":
                        yield {"type": "log", "data": str(frame.get("data", ""))}
                        continue
                    data = frame.get("data") if isinstance(frame.get("data"), dict) else {}
                    code = data.get("exit_code")
                    ok = data.get("status") == "completed" and code in (0, None)
                    yield {"type": "done", "ok": ok, "code": code if isinstance(code, int) else (0 if ok else 1)}
                    return
            except _Closed:
                pass
        yield {"type": "done", "ok": False, "code": -1, "reason": "dashboard closed the stream before the job finished"}

    async def downloads(self, filename: str) -> list[dict]:
        """The dashboard's artifact list for a built config (`title`,
        `file`, `type` per entry); empty when nothing was built."""
        async with self._session() as c:
            try:
                body = await c.call("firmware/get_binaries", {"configuration": filename})
            except _CommandError as e:
                if e.code == "not_found":
                    return []
                raise
        return [d for d in body if isinstance(d, dict) and d.get("file")] if isinstance(body, list) else []

    async def firmware(self, filename: str, *, factory: bool = False) -> Optional[bytes]:
        """The built image, or None when the dashboard has none for it.
        `factory` picks the merged image (flash at 0x0) over the OTA one;
        a platform with a single artifact returns that one either way."""
        async with self._session() as c:
            try:
                entries = await c.call("firmware/get_binaries", {"configuration": filename})
            except _CommandError as e:
                if e.code == "not_found":
                    return None
                raise
            entries = [d for d in entries if isinstance(d, dict) and d.get("file")] if isinstance(entries, list) else []
            images = [d for d in entries if d.get("type") != "elf"]
            if not images:
                return None
            want = "factory" if factory else "ota"
            chosen = next((d for d in images if d.get("type") == want or want in str(d["file"])), images[0])
            minted = await c.call("firmware/download_token", {"configuration": filename, "file": chosen["file"]})
        token = minted.get("token") if isinstance(minted, dict) else None
        if not token:
            raise DashboardUnavailable("dashboard did not mint a download token")
        async with httpx.AsyncClient(
            base_url=self.base_url, timeout=_ARTIFACT_TIMEOUT, transport=self._transport, follow_redirects=False,
        ) as h:
            try:
                resp = await h.get(DOWNLOAD_PATH, params={"token": token})
            except httpx.HTTPError as e:
                raise DashboardUnavailable(f"dashboard unreachable: {describe(e)}") from e
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise DashboardUnavailable(f"dashboard answered HTTP {resp.status_code} on {DOWNLOAD_PATH}")
        return resp.content or None


async def _default_ws_connect(url: str, headers: dict[str, str]):
    import websockets
    return await websockets.connect(url, additional_headers=headers, max_size=None)


def _validate_name(name: str) -> str:
    cleaned = (name or "").strip().lower()
    if not cleaned or len(cleaned) > 64 or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in cleaned):
        raise ValueError("device name must be 1-64 lowercase letters, digits, '-' or '_'")
    return cleaned


@dataclass
class DashboardJob:
    run_id: str
    filename: str
    started_at: str
    log: str = ""
    finished: bool = False
    ok: Optional[bool] = None
    error: Optional[str] = None
    task: Optional[asyncio.Task] = field(default=None, repr=False)

    @property
    def verdict(self) -> str:
        if not self.finished:
            return "running"
        return "passed" if self.ok else "failed"


class DashboardJobs:
    """In-process compile jobs; one entry per push-with-compile."""

    def __init__(self) -> None:
        self._jobs: dict[str, DashboardJob] = {}

    def get(self, run_id: str) -> Optional[DashboardJob]:
        return self._jobs.get(run_id)

    def start(self, client: DashboardClient, filename: str) -> DashboardJob:
        job = DashboardJob(
            run_id=secrets.token_urlsafe(8), filename=filename,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._jobs[job.run_id] = job
        job.task = asyncio.create_task(self._run(client, job))
        return job

    async def _run(self, client: DashboardClient, job: DashboardJob) -> None:
        try:
            async for event in client.compile(job.filename):
                if event["type"] == "log":
                    job.log += event["data"] if event["data"].endswith("\n") else event["data"] + "\n"
                else:
                    job.ok = bool(event["ok"])
                    if event.get("reason"):
                        job.error = str(event["reason"])
        except DashboardUnavailable as e:
            job.ok, job.error = False, str(e)
            job.log += f"\n[{e}]\n"
        except Exception as e:  # a bug in the relay must not hang the job
            job.ok, job.error = False, describe(e)
            job.log += f"\n[compile relay failed: {describe(e)}]\n"
        finally:
            if job.ok is None:
                job.ok = False
            job.finished = True

    def log(self, run_id: str, offset: int = 0) -> Optional[JobLogChunk]:
        job = self._jobs.get(run_id)
        if job is None:
            return None
        text = job.log[max(offset, 0):]
        return JobLogChunk(log=text, offset=len(job.log), finished=job.finished)
