"""Compile through an ESPHome dashboard (the HA add-on or a standalone
`esphome dashboard`), as a second build path beside fleet-for-esphome.

The dashboard schedules its own build workers; the studio only submits.
Push writes the rendered YAML as `<device>.yaml` through the dashboard's
editor endpoint, compile opens its `/compile` websocket and relays the
line events, and the artifact comes back through `/download.bin`. The
wire details are the constants and the three small methods below, so a
dashboard that moves an endpoint is a one-line change here.

Jobs are in-process: the dashboard has no job id of its own, so the
studio runs each compile as a task, buffers the log, and hands out a
run_id that the same log / status / firmware routes the fleet path
uses can poll. A studio restart forgets running jobs; the dashboard
keeps compiling, and a re-push starts a fresh one.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx

from wirestudio.errors import describe

DEVICES_PATH = "/devices"
EDIT_PATH = "/edit"
COMPILE_WS_PATH = "/compile"
DOWNLOAD_PATH = "/download.bin"
LOGIN_PATH = "/login"

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


WsConnect = Callable[[str], Awaitable[object]]


class DashboardClient:
    """Thin client over the dashboard's HTTP + websocket surface.

    `transport` injects an httpx transport for tests; `ws_connect` injects
    the websocket connector (defaults to the `websockets` package) so the
    compile stream is testable without a socket.
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
        self._cookies = httpx.Cookies()

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base_url, timeout=_TIMEOUT, transport=self._transport,
            cookies=self._cookies, follow_redirects=False,
        )

    async def _login(self, c: httpx.AsyncClient) -> None:
        if not (self.username and self.password):
            return
        resp = await c.post(LOGIN_PATH, data={"username": self.username, "password": self.password})
        if resp.status_code >= 400:
            raise DashboardUnavailable(f"dashboard login failed: HTTP {resp.status_code}")
        self._cookies.update(c.cookies)

    async def list_devices(self) -> list[str]:
        """Filenames the dashboard knows (`x.yaml`)."""
        async with self._client() as c:
            await self._login(c)
            try:
                resp = await c.get(DEVICES_PATH)
            except httpx.HTTPError as e:
                raise DashboardUnavailable(f"dashboard unreachable: {describe(e)}") from e
            if resp.status_code != 200:
                raise DashboardUnavailable(f"dashboard answered HTTP {resp.status_code} on {DEVICES_PATH}")
            try:
                body = resp.json()
            except ValueError as e:
                raise DashboardUnavailable("dashboard did not answer JSON on /devices; is the URL the dashboard itself?") from e
        configured = body.get("configured") if isinstance(body, dict) else None
        if not isinstance(configured, list):
            raise DashboardUnavailable("unexpected /devices shape from the dashboard")
        return [str(d.get("filename") or d.get("name") or "") for d in configured if isinstance(d, dict)]

    async def is_available(self) -> tuple[bool, Optional[str]]:
        try:
            await self.list_devices()
        except DashboardUnavailable as e:
            return False, str(e)
        return True, None

    async def push_device(self, device_name: str, yaml: str) -> PushResult:
        filename = f"{_validate_name(device_name)}.yaml"
        existing = await self.list_devices()
        async with self._client() as c:
            await self._login(c)
            try:
                resp = await c.post(
                    EDIT_PATH, params={"configuration": filename},
                    content=yaml.encode(), headers={"content-type": "text/plain; charset=utf-8"},
                )
            except httpx.HTTPError as e:
                raise DashboardUnavailable(f"dashboard unreachable: {describe(e)}") from e
            if resp.status_code >= 400:
                raise DashboardUnavailable(f"dashboard refused the YAML: HTTP {resp.status_code}")
        return PushResult(filename=filename, created=filename not in existing)

    async def compile(self, filename: str) -> AsyncIterator[dict]:
        """Yield {"type": "log", "data": line} per output line, then
        {"type": "done", "ok": bool, "code": int}."""
        url = self.base_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + COMPILE_WS_PATH
        connect = self._ws_connect or _default_ws_connect
        try:
            ws = await connect(url)
        except Exception as e:
            raise DashboardUnavailable(f"dashboard websocket failed: {describe(e)}") from e
        try:
            await ws.send(json.dumps({"type": "spawn", "configuration": filename}))
            async for raw in ws:
                try:
                    frame = json.loads(raw)
                except (TypeError, ValueError):
                    continue
                event = frame.get("event")
                if event == "line":
                    yield {"type": "log", "data": str(frame.get("data", ""))}
                elif event == "exit":
                    code = int(frame.get("code", 1))
                    yield {"type": "done", "ok": code == 0, "code": code}
                    return
            yield {"type": "done", "ok": False, "code": -1, "reason": "dashboard closed the stream before exit"}
        finally:
            try:
                await ws.close()
            except Exception:
                pass

    async def firmware(self, filename: str, file: str = "firmware.bin") -> Optional[bytes]:
        """The built image, or None when the dashboard has none for it."""
        async with self._client() as c:
            await self._login(c)
            for param in ("file", "type"):
                try:
                    resp = await c.get(
                        DOWNLOAD_PATH, params={"configuration": filename, param: file},
                        timeout=_ARTIFACT_TIMEOUT,
                    )
                except httpx.HTTPError as e:
                    raise DashboardUnavailable(f"dashboard unreachable: {describe(e)}") from e
                if resp.status_code == 200 and resp.content:
                    return resp.content
                if resp.status_code not in (400, 404):
                    raise DashboardUnavailable(f"dashboard answered HTTP {resp.status_code} on {DOWNLOAD_PATH}")
        return None


async def _default_ws_connect(url: str):
    import websockets
    return await websockets.connect(url, max_size=None)


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
