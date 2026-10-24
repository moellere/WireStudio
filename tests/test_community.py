"""Community designs: browse and import go through the catalogue's index
only, and share refuses what the catalogue's CI would."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app

REPO = "moellere/wirestudio-designs"
RAW = f"https://raw.githubusercontent.com/{REPO}"
EXAMPLE = json.loads((Path(__file__).resolve().parent.parent / "wirestudio" / "examples"
                      / "garage-motion.json").read_text())


def _entry(slug, **over):
    return {"slug": slug, "name": "Porch motion", "author": "octocat", "license": "CC-BY-4.0",
            "design_url": f"{RAW}/main/designs/{slug}/design.json", **over}


@pytest.fixture
def studio(monkeypatch):
    monkeypatch.delenv("WIRESTUDIO_DESIGNS_REPO", raising=False)
    files: dict[str, bytes] = {}
    fetched: list[str] = []

    async def fetch(url):
        fetched.append(url)
        if url not in files:
            raise RuntimeError(f"404 {url}")
        return files[url]

    def publish(*entries, designs=None):
        files[f"{RAW}/index/index.json"] = json.dumps(
            {"version": 1, "generated": "2026-10-23T00:00:00+00:00", "designs": list(entries)}).encode()
        for slug, doc in (designs or {}).items():
            files[f"{RAW}/main/designs/{slug}/design.json"] = json.dumps(doc).encode()

    app = TestClient(create_app(community_fetch=fetch))
    return app, publish, fetched


def test_status_names_the_catalogue(studio):
    app, _, _ = studio
    s = app.get("/community/status").json()
    assert s["enabled"] and s["repo"] == REPO
    assert s["upload_url"] == f"https://github.com/{REPO}/upload/main/designs"


def test_empty_repo_setting_turns_it_off(studio, monkeypatch):
    app, _, _ = studio
    monkeypatch.setenv("WIRESTUDIO_DESIGNS_REPO", "")
    assert app.get("/community/status").json() == {"enabled": False}
    assert app.get("/community/designs").status_code == 503


def test_browse_lists_the_index_and_caches_it(studio):
    app, publish, fetched = studio
    publish(_entry("porch-motion"))
    assert [d["slug"] for d in app.get("/community/designs").json()["designs"]] == ["porch-motion"]
    app.get("/community/designs")
    assert fetched.count(f"{RAW}/index/index.json") == 1


def test_an_unreachable_index_is_a_502(studio):
    app, _, _ = studio
    r = app.get("/community/designs")
    assert r.status_code == 502 and "index unavailable" in r.json()["detail"]


def test_import_stamps_the_origin(studio):
    app, publish, _ = studio
    publish(_entry("porch-motion"), designs={"porch-motion": {**EXAMPLE, "id": "porch-motion"}})
    body = app.get("/community/designs/porch-motion").json()
    assert body["design"]["origin"] == {"catalogue": REPO, "slug": "porch-motion",
                                        "author": "octocat", "license": "CC-BY-4.0"}
    assert app.post("/design/validate", json=body["design"]).status_code == 200


def test_import_only_follows_urls_inside_the_catalogue(studio):
    app, publish, fetched = studio
    publish(_entry("evil", design_url="http://169.254.169.254/latest/meta-data"))
    assert app.get("/community/designs/evil").status_code == 502
    assert not any("169.254" in u for u in fetched)


def test_import_of_an_unknown_slug_is_a_404(studio):
    app, publish, _ = studio
    publish()
    assert app.get("/community/designs/nope").status_code == 404


def _share(app, **over):
    body = {"design": {**EXAMPLE, "id": "Porch Motion v2"}, "author": "@octocat", "tags": ["motion"], **over}
    return app.post("/community/share", json=body)


def test_share_packs_the_folder_the_catalogue_expects(studio):
    app, _, _ = studio
    r = _share(app, notes="Built on a DevKitC.")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert sorted(z.namelist()) == ["porch-motion-v2/README.md", "porch-motion-v2/design.json",
                                    "porch-motion-v2/meta.yaml"]
    assert json.loads(z.read("porch-motion-v2/design.json"))["id"] == "porch-motion-v2"
    assert yaml.safe_load(z.read("porch-motion-v2/meta.yaml")) == {"author": "octocat", "tags": ["motion"]}


def test_share_credits_the_design_it_was_imported_from(studio):
    app, _, _ = studio
    origin = {"catalogue": REPO, "slug": "porch-motion", "author": "someone", "license": "CC-BY-4.0"}
    r = _share(app, design={**EXAMPLE, "id": "porch-motion-v2", "origin": origin})
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert yaml.safe_load(z.read("porch-motion-v2/meta.yaml"))["derived_from"] == "porch-motion"
    assert "origin" not in json.loads(z.read("porch-motion-v2/design.json"))


def test_resharing_your_own_design_does_not_derive_from_itself(studio):
    app, _, _ = studio
    origin = {"catalogue": REPO, "slug": "porch-motion", "author": "octocat", "license": "CC-BY-4.0"}
    r = _share(app, design={**EXAMPLE, "id": "porch-motion", "origin": origin})
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "derived_from" not in yaml.safe_load(z.read("porch-motion/meta.yaml"))


def test_share_refuses_a_literal_credential(studio):
    app, _, _ = studio
    design = json.loads(json.dumps(EXAMPLE))
    design["fleet"]["secrets_ref"]["wifi_password"] = "hunter22"
    r = _share(app, design=design)
    assert r.status_code == 422 and "fleet.secrets_ref.wifi_password" in r.json()["detail"]


@pytest.mark.parametrize("over, match", [
    ({"author": "not a handle"}, "GitHub handle"),
    ({"tags": ["Has Space"]}, "tags"),
    ({"slug": "Bad_Slug"}, "not a usable name"),
])
def test_share_refuses_what_the_catalogue_would(studio, over, match):
    app, _, _ = studio
    r = _share(app, **over)
    assert r.status_code == 422 and match in r.json()["detail"]


def _jpeg(size=(3000, 2000), exif=True, fmt="JPEG") -> str:
    import base64

    from PIL import Image

    img = Image.new("RGB", size, (200, 80, 40))
    kwargs = {}
    if exif:
        e = Image.Exif()
        e[0x010F] = "PhoneMaker"
        e[0x0112] = 6  # Orientation: rotate 90 CW on display
        kwargs["exif"] = e
    buf = io.BytesIO()
    img.save(buf, fmt, **kwargs)
    return base64.b64encode(buf.getvalue()).decode()


def test_share_re_encodes_photos_without_metadata(studio):
    from PIL import Image

    app, _, _ = studio
    r = _share(app, photos=[{"name": "IMG_0042.JPG", "data": _jpeg()},
                            {"name": "IMG_0042.JPG", "data": _jpeg(fmt="PNG", exif=False)}])
    assert r.status_code == 200, r.text
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = sorted(n for n in z.namelist() if "/photos/" in n)
    assert names == ["porch-motion-v2/photos/img-0042-2.jpg", "porch-motion-v2/photos/img-0042.jpg"]
    with Image.open(io.BytesIO(z.read("porch-motion-v2/photos/img-0042.jpg"))) as img:
        assert img.format == "JPEG" and not img.getexif()
        assert img.size == (1365, 2048), "the EXIF rotation is applied before EXIF is dropped"
    assert all(z.getinfo(n).file_size <= 1024 * 1024 for n in names)


def test_share_refuses_what_is_not_a_photo(studio):
    import base64

    app, _, _ = studio
    r = _share(app, photos=[{"name": "notes.txt", "data": base64.b64encode(b"hello").decode()}])
    assert r.status_code == 422 and "not a readable image" in r.json()["detail"]
    r = _share(app, photos=[{"name": f"p{i}.jpg", "data": _jpeg((10, 10))} for i in range(5)])
    assert r.status_code == 422 and "at most 4" in r.json()["detail"]
