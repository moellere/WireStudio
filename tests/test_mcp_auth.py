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
    # Two routes: /mcp (gated) and /public (bypassed). The middleware only
    # enforces auth on the prefix; everything else falls through. Mirrors
    # the production layout where the same FastAPI app serves both /mcp and
    # the unauthenticated SPA + /library/* surface.
    app = Starlette(
        routes=[
            Route("/mcp", _ok),
            Route("/public", _ok),
        ]
    )
    app.add_middleware(BearerTokenMiddleware, token=token)
    return app


async def test_middleware_rejects_missing_header():
    app = _build_app("secret-token")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/mcp")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")


async def test_middleware_rejects_wrong_token():
    app = _build_app("right")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/mcp", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


async def test_middleware_accepts_correct_token():
    app = _build_app("right")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/mcp", headers={"Authorization": "Bearer right"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


async def test_middleware_rejects_non_bearer_scheme():
    app = _build_app("right")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/mcp", headers={"Authorization": "Basic right"})
    assert r.status_code == 401


async def test_middleware_lets_non_mcp_paths_through():
    # The token only gates /mcp. Hitting an unrelated path with no auth
    # header must not 401 -- otherwise the SPA root, favicon, and the
    # /library + /design API surface all break behind a Bearer prompt
    # the browser can't satisfy.
    app = _build_app("secret-token")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/public")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


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
