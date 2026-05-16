from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.kicad import render as R
from wirestudio.kicad.render import (
    RenderError,
    RenderUnavailable,
    render_schematic,
    render_status,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GARAGE = REPO_ROOT / "wirestudio" / "examples" / "garage-motion.json"


def _proc(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _fake_run(cmd, **kw):
    """subprocess.run stand-in that writes the files each pipeline step expects."""
    if cmd[0] == sys.executable:
        Path(kw["cwd"], "schematic.kicad_sch").write_text("(kicad_sch)")
    elif cmd[0] == "kicad-cli":
        out_dir = Path(cmd[cmd.index("--output") + 1])
        (out_dir / "schematic.svg").write_bytes(b"<svg>ok</svg>")
    return _proc(cmd)


# --- render_status ----------------------------------------------------------

def test_render_status_available_when_tools_present(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "_skidl_importable", lambda: True)
    monkeypatch.setattr(R, "_png_converter", lambda: "cairosvg")
    assert render_status() == {
        "available": True, "kicad_cli": True, "skidl": True,
        "png": True, "reason": None,
    }


def test_render_status_reports_missing_tools(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda exe: None)
    monkeypatch.setattr(R, "_skidl_importable", lambda: False)
    monkeypatch.setattr(R, "_png_converter", lambda: None)
    s = render_status()
    assert s["available"] is False
    assert "kicad-cli" in s["reason"] and "skidl" in s["reason"]


# --- render_schematic gating ------------------------------------------------

def test_render_unavailable_without_kicad_cli(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: None)
    monkeypatch.setattr(R, "_skidl_importable", lambda: True)
    with pytest.raises(RenderUnavailable, match="kicad-cli"):
        render_schematic(garage_motion_design, library)


def test_render_unavailable_without_skidl(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/kicad-cli")
    monkeypatch.setattr(R, "_skidl_importable", lambda: False)
    with pytest.raises(RenderUnavailable, match="skidl"):
        render_schematic(garage_motion_design, library)


def test_render_png_needs_a_converter(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "_skidl_importable", lambda: True)
    monkeypatch.setattr(R, "_png_converter", lambda: None)
    with pytest.raises(RenderUnavailable, match="PNG"):
        render_schematic(garage_motion_design, library, fmt="png")


def test_render_rejects_bad_format(garage_motion_design, library):
    with pytest.raises(ValueError, match="fmt"):
        render_schematic(garage_motion_design, library, fmt="jpeg")


# --- render_schematic pipeline (mocked subprocess) --------------------------

def test_render_svg_happy_path(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "_skidl_importable", lambda: True)
    monkeypatch.setattr(R.subprocess, "run", _fake_run)
    assert render_schematic(garage_motion_design, library, fmt="svg") == b"<svg>ok</svg>"


def test_render_png_happy_path(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "_skidl_importable", lambda: True)
    monkeypatch.setattr(R, "_png_converter", lambda: "rsvg-convert")
    monkeypatch.setattr(R.subprocess, "run", _fake_run)
    monkeypatch.setattr(R, "_svg_to_png", lambda svg: b"PNG:" + svg)
    assert render_schematic(garage_motion_design, library, fmt="png") == b"PNG:<svg>ok</svg>"


def test_render_surfaces_skidl_failure(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "_skidl_importable", lambda: True)
    monkeypatch.setattr(
        R.subprocess, "run",
        lambda cmd, **kw: _proc(cmd, returncode=1, stderr="ImportError: skidl"),
    )
    with pytest.raises(RenderError, match="SKiDL script failed"):
        render_schematic(garage_motion_design, library)


def test_render_surfaces_kicad_cli_failure(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "_skidl_importable", lambda: True)

    def run(cmd, **kw):
        if cmd[0] == sys.executable:
            Path(kw["cwd"], "schematic.kicad_sch").write_text("(kicad_sch)")
            return _proc(cmd)
        return _proc(cmd, returncode=1, stderr="bad symbol lib")

    monkeypatch.setattr(R.subprocess, "run", run)
    with pytest.raises(RenderError, match="kicad-cli failed"):
        render_schematic(garage_motion_design, library)


# --- CLI --------------------------------------------------------------------

def test_main_status_prints_json(capsys):
    assert R.main(["--status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"available", "kicad_cli", "skidl", "png", "reason"}


def test_main_requires_a_design_without_status():
    with pytest.raises(SystemExit):
        R.main([])


# --- API --------------------------------------------------------------------

def test_render_status_endpoint():
    client = TestClient(create_app())
    r = client.get("/design/kicad/render/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"available", "kicad_cli", "skidl", "png", "reason"}
    assert isinstance(body["available"], bool)


def test_render_endpoint_503_when_unavailable(monkeypatch):
    import wirestudio.api.app as appmod

    def unavailable(d, lib, *, fmt="svg"):
        raise RenderUnavailable("kicad-cli not found on PATH")

    monkeypatch.setattr(appmod, "render_schematic", unavailable)
    client = TestClient(create_app())
    r = client.post("/design/kicad/render", json=json.loads(GARAGE.read_text()))
    assert r.status_code == 503
    assert "kicad-cli" in r.json()["detail"]


def test_render_endpoint_rejects_bad_format():
    client = TestClient(create_app())
    r = client.post(
        "/design/kicad/render?format=jpeg", json=json.loads(GARAGE.read_text())
    )
    assert r.status_code == 422


def test_render_endpoint_returns_svg(monkeypatch):
    import wirestudio.api.app as appmod
    monkeypatch.setattr(appmod, "render_schematic", lambda d, lib, *, fmt="svg": b"<svg/>")
    client = TestClient(create_app())
    r = client.post("/design/kicad/render", json=json.loads(GARAGE.read_text()))
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/svg+xml"
    assert r.content == b"<svg/>"
