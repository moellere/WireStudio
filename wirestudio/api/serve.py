"""Production-deployment wrapper for the studio API.

In dev the studio API listens at root paths (`/library/boards`,
`/design/render`, etc.) and the Vite dev server proxies `/api/*` to it
after stripping the prefix. In a single-image production deployment we
don't run Vite -- the built bundle is served as static files alongside
the API. To keep the same `/api/*` URL space the SPA already calls,
this wrapper mounts the studio app under `/api` and the static bundle
at `/`.

The wrapper activates only when `WIRESTUDIO_STATIC_DIR` is set and points
at a real directory (the built `web/dist/`); otherwise we fall back to
the bare API at root, so `python -m wirestudio.api` keeps working for dev.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from wirestudio.api.app import create_app


def _make_app() -> FastAPI:
    static = os.environ.get("WIRESTUDIO_STATIC_DIR")
    if not static or not Path(static).is_dir():
        # Dev path: bare API at root. The web client uses Vite's proxy
        # to translate `/api/*` -> root.
        return create_app()
    return create_serve_app(static)


def create_serve_app(static_dir: str | Path) -> FastAPI:
    """Build the deployment wrapper: studio API at `/api`, static
    bundle at `/`. Pure factory; tests inject any static_dir they
    want without touching env vars."""
    static_path = Path(static_dir)
    if not static_path.is_dir():
        raise FileNotFoundError(f"static_dir does not exist: {static_path}")
    studio_app = create_app()
    parent = FastAPI(
        title=studio_app.title,
        version=studio_app.version,
        description=(
            f"{studio_app.description or ''} "
            f"(deployment wrapper -- API mounted at /api, "
            f"web bundle at /)"
        ).strip(),
        docs_url=None,
    )
    parent.mount("/api", studio_app)
    # html=True turns `/` into the bundle's index.html and serves any
    # other static asset under its actual path. The SPA doesn't use
    # client-side deep links today; if it ever does we'll need a
    # catchall that falls back to index.html for non-asset paths.
    parent.mount(
        "/",
        StaticFiles(directory=str(static_path), html=True),
        name="ui",
    )
    return parent


# Module-level app for `uvicorn wirestudio.api.serve:app` import strings.
app = _make_app()
