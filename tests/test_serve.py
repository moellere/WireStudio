"""Tests for the production-deployment wrapper (studio.api.serve).

Verify that:
  - When STUDIO_STATIC_DIR is unset, the bare API still serves at root.
  - With a static_dir, the studio API moves under /api/* and the
    static bundle's index.html is served at /.
  - Missing static_dir raises FileNotFoundError cleanly.

Build artefacts aren't available in CI, so we synthesise a tiny dist/
in tmp_path with an index.html + an asset and confirm both are served.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from studio.api.app import create_app
from studio.api.serve import create_serve_app


@pytest.fixture
def fake_dist(tmp_path: Path) -> Path:
    """A bare-bones built bundle: index.html + a JS asset under /assets/."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html>\n<title>studio</title>\n")
    assets = dist / "assets"
    assets.mkdir()
    (assets / "index-fake.js").write_text("// fake bundle\n")
    return dist


def test_bare_api_still_works_at_root():
    """The dev path (no static_dir) keeps API endpoints at root,
    matching the existing test surface and the Vite proxy contract."""
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200


def test_serve_wrapper_serves_index_html_at_root(fake_dist: Path):
    client = TestClient(create_serve_app(fake_dist))
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>studio</title>" in r.text


def test_serve_wrapper_serves_static_assets(fake_dist: Path):
    client = TestClient(create_serve_app(fake_dist))
    r = client.get("/assets/index-fake.js")
    assert r.status_code == 200
    assert "fake bundle" in r.text


def test_serve_wrapper_mounts_api_under_prefix(fake_dist: Path):
    """Studio API endpoints land under /api/* once the wrapper is in
    play -- that's the URL space the SPA's API_BASE = "/api" already
    expects."""
    client = TestClient(create_serve_app(fake_dist))
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_serve_wrapper_root_does_not_leak_api_routes(fake_dist: Path):
    """A request for /health (without /api) must not match the API --
    it should fall through to StaticFiles and 404 (we don't have a
    file by that name)."""
    client = TestClient(create_serve_app(fake_dist))
    r = client.get("/health")
    # StaticFiles 404s for a non-existent path; the API isn't reachable
    # at root anymore.
    assert r.status_code == 404


def test_serve_wrapper_rejects_missing_static_dir(tmp_path: Path):
    nonexistent = tmp_path / "does-not-exist"
    with pytest.raises(FileNotFoundError) as exc:
        create_serve_app(nonexistent)
    assert "does-not-exist" in str(exc.value)
