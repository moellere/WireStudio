"""WIRESTUDIO_API_TOKEN gates the REST surface: header or cookie, with
/health and /mcp left open."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.api.auth import COOKIE_NAME
from wirestudio.api.serve import create_serve_app


def test_open_when_no_token_is_configured(monkeypatch):
    monkeypatch.delenv("WIRESTUDIO_API_TOKEN", raising=False)
    client = TestClient(create_app())
    assert client.get("/library/boards").status_code == 200


def test_token_gates_everything_but_health_and_mcp():
    client = TestClient(create_app(api_token="s3cret"))
    assert client.get("/health").status_code == 200
    r = client.get("/library/boards")
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")
    assert r.json()["detail"] == "missing or invalid API token"
    assert client.get("/library/boards", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/library/boards", headers={"Authorization": "Basic s3cret"}).status_code == 401
    assert client.get("/library/boards", headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.post("/design/render", json={}, headers={"Authorization": "Bearer s3cret"}).status_code != 401
    # the MCP endpoint keeps its own token; the API token does not stack on it
    assert client.post("/mcp", json={}).status_code == 401
    assert client.post("/mcp", json={}).headers["www-authenticate"] != 'Bearer realm="wirestudio-api"'
    # the token reveal for MCP is API surface, so it is gated
    assert client.get("/mcp/token").status_code == 401
    assert client.get("/mcp/token", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_cookie_carries_the_token_for_event_source():
    client = TestClient(create_app(api_token="s3cret"))
    assert client.get("/examples", cookies={COOKIE_NAME: "nope"}).status_code == 401
    assert client.get("/examples", cookies={COOKIE_NAME: "s3cret"}).status_code == 200


def test_preflight_is_not_gated():
    client = TestClient(create_app(api_token="s3cret"))
    r = client.options(
        "/library/boards",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_env_var_configures_the_token(monkeypatch):
    monkeypatch.setenv("WIRESTUDIO_API_TOKEN", "from-env")
    client = TestClient(create_app())
    assert client.get("/examples").status_code == 401
    assert client.get("/examples", headers={"Authorization": "Bearer from-env"}).status_code == 200


def test_serve_wrapper_gates_the_api_but_not_the_bundle(monkeypatch, tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>studio</title>")
    monkeypatch.setenv("WIRESTUDIO_API_TOKEN", "s3cret")
    client = TestClient(create_serve_app(dist))
    assert client.get("/").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/examples").status_code == 401
    assert client.get("/api/examples", headers={"Authorization": "Bearer s3cret"}).status_code == 200
