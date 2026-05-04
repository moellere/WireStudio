"""HTTP client for the distributed-esphome ha-addon (ESPHome Fleet).

The addon exposes a /ui/api/* surface guarded by a Bearer token. We need
three of those endpoints to push a rendered YAML and (optionally) kick
off a build:

  GET  /ui/api/targets                     -> list existing device files
  POST /ui/api/targets                     -> create a staged ".pending.<name>.yaml"
  POST /ui/api/targets/{name}/content      -> write content (renames .pending. -> final)
  POST /ui/api/compile                     -> enqueue a compile run

Auth is a shared static Bearer token (FLEET_TOKEN). The base URL points at
the addon's HTTP listener (FLEET_URL, e.g. http://homeassistant.local:8765).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Optional

import httpx


_FILENAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_PENDING_PREFIX = ".pending."


@dataclass
class PushResult:
    """Outcome of a push_device call."""
    filename: str
    created: bool  # True if the device file was newly created on the fleet
    run_id: Optional[str] = None  # set when compile=True succeeded
    enqueued: int = 0


@dataclass
class JobLogChunk:
    """Slice of a build log returned by the addon's HTTP poll endpoint."""
    log: str          # the new bytes since the requested offset
    offset: int       # the next offset to ask for
    finished: bool    # True once the job is in a terminal state


class FleetUnavailable(RuntimeError):
    """Raised when the fleet endpoint is missing config or unreachable."""


class FleetClient:
    """Talks to a distributed-esphome ha-addon over HTTP.

    Configured from environment variables by default so the studio API
    can stay process-state-free:

      FLEET_URL    base URL of the addon HTTP listener
      FLEET_TOKEN  Bearer token from the addon's Settings drawer

    Both are required to be non-empty for the client to be considered
    configured. is_available() returns (ok, reason) so callers can
    surface the specific gap to the user.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else os.environ.get("FLEET_URL", "")).rstrip("/")
        self.token = token if token is not None else os.environ.get("FLEET_TOKEN", "")
        self.timeout = timeout
        self._transport = transport

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        return bool(self.base_url and self.token)

    def is_available(self) -> tuple[bool, Optional[str]]:
        """Cheap readiness probe.

        Returns ``(True, None)`` if the addon answers ``GET /ui/api/targets``
        with a 2xx, otherwise ``(False, "<reason>")``. Does NOT raise --
        callers wire the reason into a UI banner.
        """
        if not self.base_url:
            return False, "FLEET_URL not set"
        if not self.token:
            return False, "FLEET_TOKEN not set"
        try:
            with self._client() as c:
                r = c.get("/ui/api/targets")
        except httpx.HTTPError as e:
            return False, f"unreachable: {e}"
        if r.status_code == 401:
            return False, "unauthorized (check FLEET_TOKEN)"
        if r.status_code >= 400:
            return False, f"http {r.status_code}"
        return True, None

    # ------------------------------------------------------------------
    # Push
    # ------------------------------------------------------------------

    def push_device(
        self,
        device_name: str,
        yaml: str,
        *,
        compile: bool = False,
    ) -> PushResult:
        """Write ``yaml`` to ``<device_name>.yaml`` on the fleet.

        If the file already exists it is overwritten in place. If not,
        we use the addon's staged-create flow: POST /ui/api/targets to
        get a ``.pending.<name>.yaml`` placeholder, then POST the
        content to that path which the addon atomically renames to the
        final filename on first save.

        Pass ``compile=True`` to enqueue an OTA build for the just-pushed
        device; the result's ``run_id`` will be populated on success.
        """
        if not self.is_configured():
            raise FleetUnavailable("FLEET_URL or FLEET_TOKEN missing")

        name = _validate_filename(device_name)
        final_filename = f"{name}.yaml"

        with self._client() as c:
            existing = self._list_filenames(c)
            created = final_filename not in existing
            target_path = final_filename
            if created:
                # Stage a new file. The addon writes ".pending.<name>.yaml"
                # and returns it as the path to POST content to.
                resp = c.post("/ui/api/targets", json={"filename": name})
                if resp.status_code >= 400:
                    raise FleetUnavailable(
                        f"create_target failed: http {resp.status_code} {resp.text}"
                    )
                body = resp.json()
                target_path = body.get("target") or f"{_PENDING_PREFIX}{final_filename}"

            # Write content. For the staged path, the addon renames to
            # final_filename atomically and returns {"renamed_to": ...}.
            resp = c.post(
                f"/ui/api/targets/{target_path}/content",
                json={
                    "content": yaml,
                    "commit_message": f"esphome-studio: push {final_filename}",
                },
            )
            if resp.status_code >= 400:
                raise FleetUnavailable(
                    f"write content failed: http {resp.status_code} {resp.text}"
                )

            run_id = None
            enqueued = 0
            if compile:
                resp = c.post(
                    "/ui/api/compile",
                    json={"targets": [final_filename]},
                )
                if resp.status_code >= 400:
                    raise FleetUnavailable(
                        f"compile enqueue failed: http {resp.status_code} {resp.text}"
                    )
                body = resp.json()
                run_id = body.get("run_id")
                enqueued = int(body.get("enqueued", 0))

        return PushResult(
            filename=final_filename,
            created=created,
            run_id=run_id,
            enqueued=enqueued,
        )

    # ------------------------------------------------------------------
    # Build log polling
    # ------------------------------------------------------------------

    def get_job_log(self, run_id: str, offset: int = 0) -> JobLogChunk:
        """Fetch new bytes of a build log since ``offset``.

        Mirrors the addon's HTTP fallback at ``GET /ui/api/jobs/{id}/log``.
        Callers poll this until ``finished`` is True. 404s on the addon
        are surfaced as ``FleetUnavailable`` so the UI can stop polling.
        """
        if not self.is_configured():
            raise FleetUnavailable("FLEET_URL or FLEET_TOKEN missing")
        with self._client() as c:
            resp = c.get(f"/ui/api/jobs/{run_id}/log", params={"offset": offset})
        if resp.status_code == 404:
            raise FleetUnavailable(f"unknown run_id {run_id!r}")
        if resp.status_code >= 400:
            raise FleetUnavailable(
                f"job log fetch failed: http {resp.status_code} {resp.text}"
            )
        body = resp.json()
        return JobLogChunk(
            log=str(body.get("log", "")),
            offset=int(body.get("offset", offset)),
            finished=bool(body.get("finished", False)),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={"Authorization": f"Bearer {self.token}"},
            transport=self._transport,
        )

    def _list_filenames(self, c: httpx.Client) -> set[str]:
        resp = c.get("/ui/api/targets")
        if resp.status_code >= 400:
            raise FleetUnavailable(
                f"list targets failed: http {resp.status_code} {resp.text}"
            )
        body = resp.json()
        # The addon returns either {"targets": [...]} with each entry a
        # dict ({"filename": "..."}) or a bare list -- accept both.
        items = body.get("targets", body) if isinstance(body, dict) else body
        out: set[str] = set()
        for it in items or []:
            if isinstance(it, str):
                out.add(it)
            elif isinstance(it, dict):
                f = it.get("filename") or it.get("name")
                if isinstance(f, str):
                    out.add(f)
        return out


def _validate_filename(name: str) -> str:
    """Slug check matching the addon's _SLUG_RE.

    The addon rejects anything not ``^[a-z0-9][a-z0-9-]*$`` plus a 64-char
    cap. Mirror that here so we 422 the user before round-tripping over
    the network.
    """
    if not isinstance(name, str):
        raise ValueError("device name must be a string")
    n = name.strip()
    if n.lower().endswith(".yaml"):
        n = n[:-5]
    if not n:
        raise ValueError("device name must not be empty")
    if len(n) > 64:
        raise ValueError("device name too long (max 64 chars)")
    if not _FILENAME_RE.match(n):
        raise ValueError(
            "device name must be lowercase letters/digits/hyphens, "
            "starting with a letter or digit"
        )
    return n
