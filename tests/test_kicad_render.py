from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.kicad import render as R
from wirestudio.kicad.render import (
    RenderError,
    RenderUnavailable,
    pcb_render_status,
    render_pcb,
    render_schematic,
    render_status,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GARAGE = REPO_ROOT / "wirestudio" / "examples" / "garage-motion.json"


def _proc(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _fake_run(cmd, **kw):
    """subprocess.run stand-in that writes the file kicad-cli would."""
    if cmd[0] == "kicad-cli":
        out_dir = Path(cmd[cmd.index("--output") + 1])
        (out_dir / "schematic.svg").write_bytes(b"<svg>ok</svg>")
    return _proc(cmd)


SYMBOLS_OK = {"available": True, "symbol_dir": "/libs", "reason": None}
SYMBOLS_MISSING = {"available": False, "symbol_dir": None,
                   "reason": "symbol libraries not found (set KICAD8_SYMBOL_DIR)"}


def _writer_ok(monkeypatch):
    """The sheet writer stands in for the real one: these tests are about
    the pipeline around it, and it needs the KiCad libraries."""
    monkeypatch.setattr(R, "sch_status", lambda: SYMBOLS_OK)
    monkeypatch.setattr(R, "generate_kicad_sch", lambda d, lib: "(kicad_sch)")


# --- render_status ----------------------------------------------------------

def test_render_status_available_when_tools_present(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "sch_status", lambda: SYMBOLS_OK)
    monkeypatch.setattr(R, "_png_converter", lambda: "cairosvg")
    assert render_status() == {
        "available": True, "kicad_cli": True, "symbols": True,
        "png": True, "reason": None,
    }


def test_render_status_reports_missing_tools(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda exe: None)
    monkeypatch.setattr(R, "sch_status", lambda: SYMBOLS_MISSING)
    monkeypatch.setattr(R, "_png_converter", lambda: None)
    s = render_status()
    assert s["available"] is False
    assert "kicad-cli" in s["reason"] and "symbol libraries" in s["reason"]


# --- render_schematic gating ------------------------------------------------

def test_render_unavailable_without_kicad_cli(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: None)
    monkeypatch.setattr(R, "sch_status", lambda: SYMBOLS_OK)
    with pytest.raises(RenderUnavailable, match="kicad-cli"):
        render_schematic(garage_motion_design, library)


def test_render_unavailable_without_symbol_libraries(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/kicad-cli")
    monkeypatch.setattr(R, "sch_status", lambda: SYMBOLS_MISSING)
    with pytest.raises(RenderUnavailable, match="symbol libraries"):
        render_schematic(garage_motion_design, library)


def test_render_png_needs_a_converter(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    _writer_ok(monkeypatch)
    monkeypatch.setattr(R, "_png_converter", lambda: None)
    with pytest.raises(RenderUnavailable, match="PNG"):
        render_schematic(garage_motion_design, library, fmt="png")


def test_render_rejects_bad_format(garage_motion_design, library):
    with pytest.raises(ValueError, match="fmt"):
        render_schematic(garage_motion_design, library, fmt="jpeg")


# --- render_schematic pipeline (mocked subprocess) --------------------------

def test_render_svg_happy_path(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    _writer_ok(monkeypatch)
    monkeypatch.setattr(R.subprocess, "run", _fake_run)
    assert render_schematic(garage_motion_design, library, fmt="svg") == b"<svg>ok</svg>"


def test_render_png_happy_path(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    _writer_ok(monkeypatch)
    monkeypatch.setattr(R, "_png_converter", lambda: "rsvg-convert")
    monkeypatch.setattr(R.subprocess, "run", _fake_run)
    monkeypatch.setattr(R, "_svg_to_png", lambda svg: b"PNG:" + svg)
    assert render_schematic(garage_motion_design, library, fmt="png") == b"PNG:<svg>ok</svg>"


def test_render_surfaces_a_missing_symbol(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "sch_status", lambda: SYMBOLS_OK)

    def no_symbol(d, lib):
        raise FileNotFoundError("no symbol 'ESP32-WROOM-32' in KiCad library RF_Module")

    monkeypatch.setattr(R, "generate_kicad_sch", no_symbol)
    with pytest.raises(FileNotFoundError, match="RF_Module"):
        render_schematic(garage_motion_design, library)


def test_render_surfaces_kicad_cli_failure(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    _writer_ok(monkeypatch)
    monkeypatch.setattr(
        R.subprocess, "run",
        lambda cmd, **kw: _proc(cmd, returncode=1, stderr="bad symbol lib"),
    )
    with pytest.raises(RenderError, match="kicad-cli failed"):
        render_schematic(garage_motion_design, library)


# --- render_pcb -------------------------------------------------------------

def test_pcb_render_status_needs_cli_and_libraries(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda exe: None)
    monkeypatch.setattr(R, "pcb_status", lambda: {"available": False, "reason": "no libs"})
    s = pcb_render_status()
    assert s["available"] is False
    assert "kicad-cli" in s["reason"] and "no libs" in s["reason"]


def test_pcb_render_status_available(monkeypatch):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "pcb_status", lambda: {"available": True, "reason": None})
    assert pcb_render_status() == {
        "available": True, "kicad_cli": True, "libraries": True, "reason": None,
    }


def test_render_pcb_unavailable_without_tools(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: None)
    monkeypatch.setattr(R, "pcb_status", lambda: {"available": False, "reason": "no libs"})
    with pytest.raises(RenderUnavailable, match="kicad-cli"):
        render_pcb(garage_motion_design, library)


def test_render_pcb_happy_path(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "pcb_status", lambda: {"available": True, "reason": None})
    monkeypatch.setattr(R, "generate_kicad_pcb", lambda d, lib: "(kicad_pcb)")

    def run(cmd, **kw):
        Path(cmd[cmd.index("--output") + 1]).write_bytes(b"<svg>pcb</svg>")
        return _proc(cmd)

    monkeypatch.setattr(R.subprocess, "run", run)
    assert render_pcb(garage_motion_design, library) == b"<svg>pcb</svg>"


def test_render_pcb_surfaces_cli_failure(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "pcb_status", lambda: {"available": True, "reason": None})
    monkeypatch.setattr(R, "generate_kicad_pcb", lambda d, lib: "(kicad_pcb)")
    monkeypatch.setattr(
        R.subprocess, "run",
        lambda cmd, **kw: _proc(cmd, returncode=1, stderr="bad layer"),
    )
    with pytest.raises(RenderError, match="kicad-cli failed"):
        render_pcb(garage_motion_design, library)


# --- CLI --------------------------------------------------------------------

def test_main_status_prints_json(capsys):
    assert R.main(["--status"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"available", "kicad_cli", "symbols", "png", "reason"}


def test_main_requires_a_design_without_status():
    with pytest.raises(SystemExit):
        R.main([])


# --- API --------------------------------------------------------------------

def test_render_status_endpoint():
    client = TestClient(create_app())
    r = client.get("/design/kicad/render/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"available", "kicad_cli", "symbols", "png", "reason"}
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


def test_pcb_render_status_endpoint():
    client = TestClient(create_app())
    r = client.get("/design/kicad/pcb/render/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"available", "kicad_cli", "libraries", "reason"}
    assert isinstance(body["available"], bool)


def test_pcb_render_endpoint_503_when_unavailable(monkeypatch):
    import wirestudio.api.app as appmod

    def unavailable(d, lib):
        raise RenderUnavailable("kicad-cli not on PATH")

    monkeypatch.setattr(appmod, "render_pcb", unavailable)
    client = TestClient(create_app())
    r = client.post("/design/kicad/pcb/render", json=json.loads(GARAGE.read_text()))
    assert r.status_code == 503
    assert "kicad-cli" in r.json()["detail"]


def test_pcb_render_endpoint_returns_svg(monkeypatch):
    import wirestudio.api.app as appmod
    monkeypatch.setattr(appmod, "render_pcb", lambda d, lib: b"<svg>pcb</svg>")
    client = TestClient(create_app())
    r = client.post("/design/kicad/pcb/render", json=json.loads(GARAGE.read_text()))
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/svg+xml"
    assert r.content == b"<svg>pcb</svg>"
