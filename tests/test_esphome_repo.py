"""Commit a design's YAML to a GitHub repository: client, routes, MCP."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from wirestudio.agent.session import FileSessionStore
from wirestudio.api.app import create_app
from wirestudio.designs.store import FileDesignStore
from wirestudio.esphome_repo import RepoClient, RepoFileExists, RepoUnavailable

pytestmark = pytest.mark.anyio

EXAMPLES = Path(__file__).resolve().parent.parent / "wirestudio" / "examples"


class FakeGitHub:
    """The three contents-API calls the client makes, for one repository
    and branch: files as {path: (text, last commit message)}."""

    def __init__(self, files=None, token="tok"):
        self.files = dict(files or {})
        self.token = token
        self.puts: list[dict] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"message": "Bad credentials"})
        path = request.url.path
        if path == "/repos/me/esphome/branches/main":
            return httpx.Response(200, json={"name": "main"})
        if path == "/repos/me/esphome/commits":
            f = self.files.get(request.url.params["path"])
            return httpx.Response(200, json=[{"commit": {"message": f[1]}}] if f else [])
        prefix = "/repos/me/esphome/contents/"
        if not path.startswith(prefix):
            return httpx.Response(404, json={"message": "Not Found"})
        name = path[len(prefix):]
        if request.method == "GET":
            if name not in self.files:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={
                "sha": f"sha-{name}", "html_url": f"https://github.com/me/esphome/blob/main/{name}",
                "content": base64.encodebytes(self.files[name][0].encode()).decode(),
            })
        body = json.loads(request.content)
        if (name in self.files) != ("sha" in body):
            return httpx.Response(409, json={"message": "sha mismatch"})
        self.puts.append(body)
        created = name not in self.files
        self.files[name] = (base64.b64decode(body["content"]).decode(), body["message"])
        return httpx.Response(201 if created else 200, json={
            "content": {"html_url": f"https://github.com/me/esphome/blob/main/{name}"},
            "commit": {"sha": f"c{len(self.puts)}"},
        })

    def client(self, **kw) -> RepoClient:
        kw.setdefault("repo", "me/esphome")
        kw.setdefault("token", self.token)
        kw.setdefault("branch", "")
        kw.setdefault("path", "")
        return RepoClient(transport=httpx.MockTransport(self.handler), **kw)


async def test_status():
    gh = FakeGitHub()
    assert await gh.client().is_available() == (True, None)
    assert await gh.client(token="wrong").is_available() == (False, "unauthorized (check ESPHOME_REPO_TOKEN)")
    assert await RepoClient(repo="", token="").is_available() == (False, "ESPHOME_REPO and ESPHOME_REPO_TOKEN not set")
    assert gh.client(path="devices/").url == "https://github.com/me/esphome/tree/main/devices"


async def test_push_creates_then_updates_its_own_file():
    gh = FakeGitHub()
    rc = gh.client()
    first = await rc.push_device("porch", "a: 1\n", design_id="porch-light")
    assert (first.filename, first.created, first.changed, first.commit) == ("porch.yaml", True, True, "c1")
    assert gh.puts[0]["message"] == "wirestudio: add porch.yaml from design porch-light"
    assert gh.puts[0]["branch"] == "main" and "sha" not in gh.puts[0]

    same = await rc.push_device("porch", "a: 1\n")
    assert (same.created, same.changed, same.commit) == (False, False, None) and len(gh.puts) == 1

    again = await rc.push_device("porch", "a: 2\n")
    assert (again.created, again.changed) == (False, True)
    assert gh.puts[1]["sha"] == "sha-porch.yaml" and gh.files["porch.yaml"][0] == "a: 2\n"


async def test_push_leaves_a_hand_written_file_alone():
    gh = FakeGitHub(files={"devices/rover32.yaml": ("hand: written\n", "rover32: bumpers")})
    rc = gh.client(path="devices")
    with pytest.raises(RepoFileExists, match="devices/rover32.yaml"):
        await rc.push_device("rover32", "a: 1\n")
    assert not gh.puts
    done = await rc.push_device("rover32", "a: 1\n", overwrite=True)
    assert done.changed and gh.files["devices/rover32.yaml"][0] == "a: 1\n"
    # Ours from here on.
    await rc.push_device("rover32", "a: 2\n")


async def test_push_errors():
    gh = FakeGitHub()
    with pytest.raises(ValueError):
        await gh.client().push_device("../etc", "a: 1\n")
    with pytest.raises(RepoUnavailable, match="401: Bad credentials"):
        await gh.client(token="wrong").push_device("porch", "a: 1\n")
    with pytest.raises(RepoUnavailable, match="not set"):
        await RepoClient(repo="", token="").push_device("porch", "a: 1\n")


def _app(tmp_path, factory):
    return TestClient(create_app(
        sessions=FileSessionStore(root=tmp_path / "sessions"),
        designs=FileDesignStore(root=tmp_path / "designs"),
        repo_client_factory=factory,
    ))


async def test_routes(tmp_path):
    gh = FakeGitHub(files={"taken.yaml": ("hand: written\n", "by hand")})
    client = _app(tmp_path, gh.client)
    assert client.get("/esphome-repo/status").json() == {
        "available": True, "reason": None, "repo": "me/esphome", "branch": "main",
        "url": "https://github.com/me/esphome/tree/main",
    }
    design = json.loads((EXAMPLES / "garage-motion.json").read_text())
    r = client.post("/esphome-repo/push", json={"design": design})
    assert r.status_code == 200, r.text
    assert r.json() == {"filename": "garage-motion.yaml", "created": True, "changed": True, "commit": "c1",
                        "url": "https://github.com/me/esphome/blob/main/garage-motion.yaml"}
    assert gh.files["garage-motion.yaml"][0].startswith("esphome:")

    r = client.post("/esphome-repo/push", json={"design": design, "device_name": "taken"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "file_exists"
    r = client.post("/esphome-repo/push", json={"design": design, "device_name": "taken", "overwrite": True})
    assert r.status_code == 200 and r.json()["created"] is False

    assert client.post("/esphome-repo/push", json={"design": design, "device_name": "Bad Name"}).status_code == 422


async def test_routes_unconfigured(tmp_path):
    client = _app(tmp_path, lambda: RepoClient(repo="", token=""))
    status = client.get("/esphome-repo/status").json()
    assert status["available"] is False and status["repo"] is None and status["url"] is None
    design = json.loads((EXAMPLES / "garage-motion.json").read_text())
    assert client.post("/esphome-repo/push", json={"design": design}).status_code == 503


async def test_mcp_repo_tools(tmp_path):
    from wirestudio.inventory.store import FileInventoryStore
    from wirestudio.library import default_library
    from wirestudio.mcp.server import build_mcp_server

    gh = FakeGitHub(files={"taken.yaml": ("hand: written\n", "by hand")})
    store = FileDesignStore(root=tmp_path / "designs")
    design = json.loads((EXAMPLES / "garage-motion.json").read_text())
    store.save(design, design_id="garage-motion")
    server = build_mcp_server(
        default_library(), store,
        inventory=FileInventoryStore(path=tmp_path / "inventory.json"),
        repo_factory=gh.client,
    )

    def payload(result):
        return json.loads(result.content[0].text)

    assert payload(await server.call_tool("esphome_repo_status", {}))["available"] is True
    pushed = payload(await server.call_tool("esphome_repo_push", {"design_id": "garage-motion"}))
    assert pushed["ok"] and pushed["filename"] == "garage-motion.yaml" and pushed["commit"] == "c1"
    refused = payload(await server.call_tool(
        "esphome_repo_push", {"design_id": "garage-motion", "device_name": "taken"}))
    assert refused["ok"] is False and "last changed outside WireStudio" in refused["error"]
