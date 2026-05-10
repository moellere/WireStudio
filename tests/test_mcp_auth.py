"""Tests for the MCP bearer-token middleware + token resolution helper."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from wirestudio.mcp.auth import (
    DEFAULT_TOKEN_PATH,
    BearerTokenMiddleware,
    resolve_token,
)


pytestmark = pytest.mark.anyio


def _ok(_request):
    return JSONResponse({"ok": True})


def _build_app(token: str) -> Starlette:
    app = Starlette(routes=[Route("/probe", _ok)])
    app.add_middleware(BearerTokenMiddleware, token=token)
    return app


async def test_middleware_rejects_missing_header():
    app = _build_app("secret-token")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/probe")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")


async def test_middleware_rejects_wrong_token():
    app = _build_app("right")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/probe", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


async def test_middleware_accepts_correct_token():
    app = _build_app("right")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/probe", headers={"Authorization": "Bearer right"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_middleware_rejects_non_bearer_scheme():
    app = _build_app("right")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/probe", headers={"Authorization": "Basic right"})
    assert r.status_code == 401


def test_resolve_token_env_wins(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WIRESTUDIO_MCP_TOKEN", "from-env")
    file_path = tmp_path / "mcp-token"
    file_path.write_text("from-file")
    assert resolve_token(token_path=file_path) == "from-env"
    # Env-var path doesn't read or touch the file.
    assert file_path.read_text() == "from-file"


def test_resolve_token_reads_persisted_file(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("WIRESTUDIO_MCP_TOKEN", raising=False)
    file_path = tmp_path / "mcp-token"
    file_path.write_text("persisted")
    assert resolve_token(token_path=file_path) == "persisted"


def test_resolve_token_generates_and_persists(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("WIRESTUDIO_MCP_TOKEN", raising=False)
    file_path = tmp_path / "nested" / "mcp-token"
    assert not file_path.exists()
    token = resolve_token(token_path=file_path)
    assert token
    assert file_path.read_text() == token
    # 0600 because the file holds an auth secret.
    mode = file_path.stat().st_mode & 0o777
    assert mode == 0o600
    # Subsequent calls return the same value.
    assert resolve_token(token_path=file_path) == token


def test_default_token_path_is_under_user_config():
    # Anchored to ~/.config/wirestudio so operators know where to look
    # without grepping the source.
    assert DEFAULT_TOKEN_PATH.name == "mcp-token"
    assert "wirestudio" in DEFAULT_TOKEN_PATH.parts
