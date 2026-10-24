"""Community designs: browse, import and share through the catalogue repo.

The catalogue is a GitHub repository (moellere/wirestudio-designs unless
WIRESTUDIO_DESIGNS_REPO says otherwise; set it empty to turn this off).
Its CI publishes index.json to an `index` branch; browse reads that.
Import fetches a design only through an index entry, never a caller's
URL, and installs the user components and board it ships through the same
gates the library editor runs. Share packs a design as the folder the
catalogue's CI expects and leaves the upload and pull request to the user,
so the studio holds no GitHub token.

The catalogue also carries library entries, components and boards on
their own under `library/`, MIT rather than CC-BY. They are browsed,
installed and shared the same way.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import zipfile
from typing import Awaitable, Callable, Optional

import yaml
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from wirestudio.api.design_input import migrate_document, validate_document

DEFAULT_REPO = "moellere/wirestudio-designs"
LICENSE = "CC-BY-4.0"
LIBRARY_LICENSE = "MIT"
# Catalogue directory -> the file name an entry's YAML has inside its folder.
LIBRARY_FILES = {"components": "component.yaml", "boards": "board.yaml"}
INDEX_TTL_S = 300.0

_REPO = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$")
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_HANDLE = re.compile(r"^[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}$")
_TAG = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
_MAX_TAGS = 8
# What the catalogue's CI accepts; photos are re-encoded to fit.
MAX_PHOTOS = 4
PHOTO_PX = 2048
PHOTO_BYTES = 1024 * 1024
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
# The catalogue's CI refuses a literal value under any of these keys; refusing
# here first keeps a secret out of a public pull request.
_SECRET_KEY = re.compile(r"pass(word|phrase)?|secret|token|api_?key|app_?key|nwk_?key|psk|encryption",
                         re.IGNORECASE)

Fetch = Callable[[str], Awaitable[bytes]]


def catalogue_repo() -> Optional[str]:
    repo = os.environ.get("WIRESTUDIO_DESIGNS_REPO", DEFAULT_REPO).strip()
    return repo if _REPO.match(repo) else None


def _urls(repo: str) -> dict:
    return {
        "index_url": f"https://raw.githubusercontent.com/{repo}/index/index.json",
        "upload_url": f"https://github.com/{repo}/upload/main/designs",
        "library_upload_url": f"https://github.com/{repo}/upload/main/library",
        "contributing_url": f"https://github.com/{repo}/blob/main/CONTRIBUTING.md",
    }


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:64].rstrip("-")


def leaked_secrets(node, where: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            at = f"{where}.{k}" if where else str(k)
            if isinstance(v, str) and v and _SECRET_KEY.search(str(k)) and not v.startswith("!secret "):
                found.append(at)
            else:
                found += leaked_secrets(v, at)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += leaked_secrets(v, f"{where}[{i}]")
    return found


def clean_photo(data: bytes) -> bytes:
    """A JPEG the catalogue accepts: EXIF rotation applied, at most PHOTO_PX
    on the long side, under PHOTO_BYTES, and no metadata at all -- a phone
    photo's EXIF usually records where it was taken. Raises ValueError for
    anything that is not a still image."""
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(data)) as img:
            if getattr(img, "is_animated", False):
                raise ValueError("animated images are not accepted")
            img = ImageOps.exif_transpose(img).convert("RGB")
    except (OSError, Image.DecompressionBombError) as e:
        raise ValueError(f"not a readable image ({e})") from e
    img.thumbnail((PHOTO_PX, PHOTO_PX))
    for quality in (85, 75, 65, 55, 45):
        out = io.BytesIO()
        img.save(out, "JPEG", quality=quality, optimize=True)
        if out.tell() <= PHOTO_BYTES:
            return out.getvalue()
    raise ValueError("too detailed to fit 1 MB")


def _photos(raw) -> list[tuple[str, bytes]]:
    """[{name, data(base64)}] -> [(catalogue file name, cleaned JPEG)]."""
    if not raw:
        return []
    if not isinstance(raw, list) or len(raw) > MAX_PHOTOS:
        raise HTTPException(status_code=422, detail=f"`photos`: at most {MAX_PHOTOS}")
    out: list[tuple[str, bytes]] = []
    for i, p in enumerate(raw):
        label = str(p.get("name") or f"photo {i + 1}") if isinstance(p, dict) else f"photo {i + 1}"
        try:
            data = base64.b64decode(p["data"], validate=True)
        except (KeyError, TypeError, ValueError) as e:
            raise HTTPException(status_code=422, detail=f"{label}: not base64 image data") from e
        if len(data) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=422, detail=f"{label}: over 20 MB")
        try:
            jpeg = clean_photo(data)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=f"{label}: {e}") from e
        stem = slugify(label.rsplit(".", 1)[0])[:60] or "photo"
        taken = {n for n, _ in out}
        name, n = f"{stem}.jpg", 2
        while name in taken:
            name, n = f"{stem}-{n}.jpg", n + 1
        out.append((name, jpeg))
    return out


async def _http_fetch(url: str) -> bytes:
    import httpx

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


def router(library, fetch: Optional[Fetch] = None) -> APIRouter:
    fetch = fetch or _http_fetch
    api = APIRouter(tags=["community"])
    cache: dict = {}

    def require_repo() -> str:
        repo = catalogue_repo()
        if repo is None:
            raise HTTPException(status_code=503,
                                detail="community designs are off (WIRESTUDIO_DESIGNS_REPO is empty or invalid)")
        return repo

    async def load_index(repo: str) -> dict:
        hit = cache.get(repo)
        if hit and time.monotonic() - hit[0] < INDEX_TTL_S:
            return hit[1]
        from wirestudio.errors import describe

        try:
            index = json.loads(await fetch(_urls(repo)["index_url"]))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"catalogue index unavailable: {describe(e)}") from e
        if not isinstance(index, dict) or not isinstance(index.get("designs"), list):
            raise HTTPException(status_code=502, detail="catalogue index is malformed")
        cache[repo] = (time.monotonic(), index)
        return index

    @api.get("/status")
    def status() -> dict:
        repo = catalogue_repo()
        if repo is None:
            return {"enabled": False}
        return {"enabled": True, "repo": repo, "license": LICENSE, "library_license": LIBRARY_LICENSE,
                **_urls(repo)}

    @api.get("/designs")
    async def list_designs() -> dict:
        repo = require_repo()
        index = await load_index(repo)
        return {"repo": repo, "generated": index.get("generated"), "designs": index["designs"]}

    async def install(repo: str, kind: str, refs: list) -> list[str]:
        """Add catalogue components or boards to this studio's user library.
        One already here with the same text is left alone; one here with
        different text is a conflict the user resolves, never an overwrite."""
        from wirestudio.errors import describe
        from wirestudio.library.board_check import create_board
        from wirestudio.library.check import create_component

        noun = kind[:-1]
        source, current, create = (
            (library.board_source, library.board_yaml, create_board) if kind == "boards"
            else (library.component_source, library.component_yaml, create_component))
        installed: list[str] = []
        for ref in refs:
            lid, url = str(ref.get("id") or ""), str(ref.get("url") or "")
            if not url.startswith(f"https://raw.githubusercontent.com/{repo}/"):
                raise HTTPException(status_code=502, detail=f"{noun} '{lid}' points outside {repo}")
            try:
                text = (await fetch(url)).decode()
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"could not fetch {noun} '{lid}': {describe(e)}") from e
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError:
                data = None
            declared = data.get("id") if isinstance(data, dict) else None
            if declared is not None and declared != lid:
                raise HTTPException(status_code=502, detail=f"{noun} '{lid}' declares id '{declared}'")
            where = source(lid)
            if where and current(lid) == text:
                continue
            if where:
                raise HTTPException(status_code=409, detail=(
                    f"your library already has a different {noun} '{lid}'"
                    + ("" if where == "bundled" else "; rename or delete yours first")))
            report = create(text, library)
            if not report.ok:
                raise HTTPException(status_code=502, detail=f"{noun} '{lid}': " + "; ".join(report.errors))
            installed.append(lid)
        return installed

    @api.post("/designs/{slug}/import")
    async def import_design(slug: str) -> dict:
        """The design, migrated to this studio's schema, with `origin`
        stamped so its author stays credited after it is edited, and its
        user components installed."""
        from wirestudio.errors import describe

        repo = require_repo()
        index = await load_index(repo)
        entry = next((d for d in index["designs"] if isinstance(d, dict) and d.get("slug") == slug), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"no design '{slug}' in {repo}")
        url = str(entry.get("design_url") or "")
        if not url.startswith(f"https://raw.githubusercontent.com/{repo}/"):
            raise HTTPException(status_code=502, detail=f"index entry '{slug}' points outside {repo}")
        try:
            raw = json.loads(await fetch(url))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"could not fetch '{slug}': {describe(e)}") from e
        installed_boards = await install(repo, "boards", entry.get("user_boards") or [])
        installed = await install(repo, "components", entry.get("user_components") or [])
        try:
            document = migrate_document(raw, library)
            validate_document(document, library)
        except HTTPException as e:
            raise HTTPException(status_code=502, detail=f"'{slug}' does not load here: {e.detail}") from e
        document["origin"] = {
            "catalogue": repo,
            "slug": slug,
            "author": str(entry.get("author", "")),
            "license": str(entry.get("license", LICENSE)),
        }
        return {"design": document, "entry": entry, "installed_components": installed,
                "installed_boards": installed_boards}

    @api.post("/share")
    def share(body: dict = Body(...)) -> Response:
        """A zip of `<slug>/design.json` + `meta.yaml` (+ `README.md`, + up to
        four `photos/*.jpg`, re-encoded without metadata, + the user
        components and board the design uses), ready to drag onto the
        catalogue's upload page."""
        repo = require_repo()
        design = body.get("design")
        if not isinstance(design, dict):
            raise HTTPException(status_code=422, detail="`design` is required")
        author = str(body.get("author") or "").strip().lstrip("@")
        if not _HANDLE.match(author):
            raise HTTPException(status_code=422, detail="`author` must be your GitHub handle")
        tags = body.get("tags") or []
        if (not isinstance(tags, list) or len(tags) > _MAX_TAGS
                or not all(isinstance(t, str) and _TAG.match(t) for t in tags)):
            raise HTTPException(status_code=422,
                                detail=f"`tags`: at most {_MAX_TAGS} lowercase words (a-z, 0-9, -)")
        slug = str(body.get("slug") or "") or slugify(str(design.get("id") or design.get("name") or ""))
        if not _SLUG.match(slug):
            raise HTTPException(status_code=422,
                                detail=f"'{slug}' is not a usable name: lowercase a-z, 0-9 and -, at most 64")

        document = migrate_document(design, library)
        validate_document(document, library)
        leaked = leaked_secrets(document)
        if leaked:
            raise HTTPException(status_code=422,
                                detail="literal credentials at " + ", ".join(leaked)
                                + " -- replace them with `!secret name` references before sharing")
        photos = _photos(body.get("photos"))
        origin = document.pop("origin", None) or {}
        document["id"] = slug

        meta: dict = {"author": author}
        if tags:
            meta["tags"] = tags
        if origin.get("catalogue") == repo and origin.get("slug") not in (None, slug):
            meta["derived_from"] = origin["slug"]

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{slug}/design.json", json.dumps(document, indent=2) + "\n")
            z.writestr(f"{slug}/meta.yaml", yaml.safe_dump(meta, sort_keys=False))
            notes = str(body.get("notes") or "").strip()
            if notes:
                z.writestr(f"{slug}/README.md", notes + "\n")
            for name, jpeg in photos:
                z.writestr(f"{slug}/photos/{name}", jpeg)
            for cid in sorted({c.get("library_id") for c in document.get("components") or []}):
                if cid and library.component_source(cid) == "user":
                    z.writestr(f"{slug}/components/{cid}.yaml", library.component_yaml(cid))
            bid = (document.get("board") or {}).get("library_id")
            if bid and library.board_source(bid) == "user":
                z.writestr(f"{slug}/boards/{bid}.yaml", library.board_yaml(bid))
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'},
        )

    def require_kind(kind: str) -> str:
        if kind not in LIBRARY_FILES:
            raise HTTPException(status_code=404, detail=f"no library kind '{kind}'; components or boards")
        return kind

    def library_entries(index: dict, kind: str) -> list[dict]:
        entries = index.get(kind) or []
        return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []

    @api.get("/library")
    async def list_library() -> dict:
        """The catalogue's components and boards, each marked with whether
        this studio already has that id and where."""
        repo = require_repo()
        index = await load_index(repo)
        out: dict = {"repo": repo, "generated": index.get("generated")}
        for kind in LIBRARY_FILES:
            source = library.board_source if kind == "boards" else library.component_source
            out[kind] = [{**e, "installed": source(str(e.get("id") or ""))} for e in library_entries(index, kind)]
        return out

    @api.post("/library/{kind}/{library_id}/install")
    async def install_library_entry(kind: str, library_id: str) -> dict:
        """Install one catalogue component or board through its gate. The
        URL comes from the index entry, never the caller."""
        require_kind(kind)
        repo = require_repo()
        index = await load_index(repo)
        entry = next((e for e in library_entries(index, kind) if e.get("id") == library_id), None)
        if entry is None:
            raise HTTPException(status_code=404, detail=f"no {kind[:-1]} '{library_id}' in {repo}")
        installed = await install(repo, kind, [entry])
        return {"kind": kind, "id": library_id, "installed": bool(installed), "entry": entry}

    @api.post("/library/share")
    def share_library_entry(body: dict = Body(...)) -> Response:
        """A zip of `<id>/component.yaml` or `<id>/board.yaml` + `meta.yaml`
        (+ `README.md`), ready to drag onto the catalogue's library upload
        page for its kind. Only a user-library entry is shared, and only
        while it still passes its gate."""
        from wirestudio.library.board_check import check_board_yaml
        from wirestudio.library.check import check_component_yaml

        require_repo()
        kind = require_kind(str(body.get("kind") or ""))
        lid = str(body.get("id") or "")
        source, current, check = (
            (library.board_source, library.board_yaml, check_board_yaml) if kind == "boards"
            else (library.component_source, library.component_yaml, check_component_yaml))
        if source(lid) != "user":
            raise HTTPException(status_code=422, detail=f"'{lid}' is not a {kind[:-1]} in your user library")
        author = str(body.get("author") or "").strip().lstrip("@")
        if not _HANDLE.match(author):
            raise HTTPException(status_code=422, detail="`author` must be your GitHub handle")
        tags = body.get("tags") or []
        if (not isinstance(tags, list) or len(tags) > _MAX_TAGS
                or not all(isinstance(t, str) and _TAG.match(t) for t in tags)):
            raise HTTPException(status_code=422,
                                detail=f"`tags`: at most {_MAX_TAGS} lowercase words (a-z, 0-9, -)")
        link = str(body.get("source") or "").strip()
        if link and not link.startswith("https://"):
            raise HTTPException(status_code=422, detail="`source` must be an https:// URL (a datasheet or product page)")
        text = current(lid)
        report = check(text, library)
        if not report.ok:
            raise HTTPException(status_code=422, detail=f"'{lid}' no longer passes its gate: " + "; ".join(report.errors))
        leaked = leaked_secrets(yaml.safe_load(text))
        if leaked:
            raise HTTPException(status_code=422, detail="literal credentials at " + ", ".join(leaked))

        meta: dict = {"author": author}
        if tags:
            meta["tags"] = tags
        if link:
            meta["source"] = link
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"{lid}/{LIBRARY_FILES[kind]}", text)
            z.writestr(f"{lid}/meta.yaml", yaml.safe_dump(meta, sort_keys=False))
            notes = str(body.get("notes") or "").strip()
            if notes:
                z.writestr(f"{lid}/README.md", notes + "\n")
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{lid}.zip"'},
        )

    return api
