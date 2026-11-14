"""Commit a design's YAML to a GitHub repository of ESPHome configs.

For a setup where the configs live in git and something else (a sync job,
a dashboard reading the checkout) carries them to the builder. The YAML
goes in as `<device>.yaml` through the GitHub contents API; nothing is
compiled here.

Env:
  ESPHOME_REPO          owner/name
  ESPHOME_REPO_TOKEN    token with contents read/write on that repository
  ESPHOME_REPO_BRANCH   branch to commit to (default: main)
  ESPHOME_REPO_PATH     directory inside the repository (default: the root)
"""
from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Optional

import httpx

from wirestudio.fleet.client import _validate_filename

COMMIT_PREFIX = "wirestudio: "
NOT_CONFIGURED = "ESPHOME_REPO and ESPHOME_REPO_TOKEN not set"


class RepoUnavailable(RuntimeError):
    pass


class RepoFileExists(RuntimeError):
    """The file is in the repository and its last commit is not ours."""


@dataclass
class RepoPushResult:
    filename: str
    created: bool
    changed: bool
    commit: Optional[str]
    url: Optional[str]


class RepoClient:
    def __init__(
        self,
        repo: Optional[str] = None,
        token: Optional[str] = None,
        branch: Optional[str] = None,
        path: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        api_url: str = "https://api.github.com",
    ) -> None:
        env = os.environ
        self.repo = (repo if repo is not None else env.get("ESPHOME_REPO", "")).strip().strip("/")
        self.token = token if token is not None else env.get("ESPHOME_REPO_TOKEN", "")
        self.branch = (branch if branch is not None else env.get("ESPHOME_REPO_BRANCH", "")).strip() or "main"
        self.path = (path if path is not None else env.get("ESPHOME_REPO_PATH", "")).strip().strip("/")
        self._transport = transport
        self._api_url = api_url

    def is_configured(self) -> bool:
        return bool(self.repo and self.token)

    @property
    def url(self) -> Optional[str]:
        if not self.repo:
            return None
        base = f"https://github.com/{self.repo}/tree/{self.branch}"
        return f"{base}/{self.path}" if self.path else base

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._api_url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20.0,
            transport=self._transport,
        )

    def _file_path(self, filename: str) -> str:
        return f"{self.path}/{filename}" if self.path else filename

    async def is_available(self) -> tuple[bool, Optional[str]]:
        if not self.is_configured():
            return False, NOT_CONFIGURED
        try:
            async with self._client() as c:
                r = await c.get(f"/repos/{self.repo}/branches/{self.branch}")
        except httpx.HTTPError as e:
            return False, f"GitHub unreachable: {e.__class__.__name__}"
        if r.status_code in (401, 403):
            return False, "unauthorized (check ESPHOME_REPO_TOKEN)"
        if r.status_code == 404:
            return False, f"{self.repo} or its branch {self.branch} not found (or the token cannot see it)"
        if r.status_code != 200:
            return False, f"GitHub answered HTTP {r.status_code}"
        return True, None

    async def push_device(
        self, name: str, yaml_text: str, *, overwrite: bool = False, design_id: Optional[str] = None,
    ) -> RepoPushResult:
        """Commit `yaml_text` as <name>.yaml. A file whose last commit was
        not made here is replaced only with `overwrite`."""
        if not self.is_configured():
            raise RepoUnavailable(NOT_CONFIGURED)
        filename = f"{_validate_filename(name)}.yaml"
        path = self._file_path(filename)
        contents = f"/repos/{self.repo}/contents/{path}"
        try:
            async with self._client() as c:
                r = await c.get(contents, params={"ref": self.branch})
                sha = None
                if r.status_code == 200:
                    current = r.json()
                    sha = current["sha"]
                    if base64.b64decode(current.get("content") or "").decode("utf-8", "replace") == yaml_text:
                        return RepoPushResult(filename, created=False, changed=False, commit=None,
                                              url=current.get("html_url"))
                    if not overwrite and not await self._last_commit_is_ours(c, path):
                        raise RepoFileExists(
                            f"{path} is already in {self.repo} and was last changed outside WireStudio; "
                            "pass overwrite to replace it"
                        )
                elif r.status_code != 404:
                    raise RepoUnavailable(_describe(r))
                body = {
                    "message": f"{COMMIT_PREFIX}{'update' if sha else 'add'} {filename}"
                               + (f" from design {design_id}" if design_id else ""),
                    "content": base64.b64encode(yaml_text.encode()).decode(),
                    "branch": self.branch,
                }
                if sha:
                    body["sha"] = sha
                w = await c.put(contents, json=body)
        except httpx.HTTPError as e:
            raise RepoUnavailable(f"GitHub unreachable: {e.__class__.__name__}") from e
        if w.status_code not in (200, 201):
            raise RepoUnavailable(_describe(w))
        done = w.json()
        return RepoPushResult(
            filename, created=sha is None, changed=True,
            commit=(done.get("commit") or {}).get("sha"),
            url=(done.get("content") or {}).get("html_url"),
        )

    async def _last_commit_is_ours(self, c: httpx.AsyncClient, path: str) -> bool:
        r = await c.get(f"/repos/{self.repo}/commits", params={"path": path, "sha": self.branch, "per_page": 1})
        if r.status_code != 200:
            raise RepoUnavailable(_describe(r))
        commits = r.json()
        return bool(commits) and commits[0]["commit"]["message"].startswith(COMMIT_PREFIX)


def _describe(r: httpx.Response) -> str:
    try:
        message = r.json().get("message")
    except ValueError:
        message = None
    return f"GitHub answered HTTP {r.status_code}" + (f": {message}" if message else "")
