import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import wirestudio.api.app as A
import wirestudio.kicad.render as R
from wirestudio.api.app import create_app
from wirestudio.kicad.erc import erc_status, run_erc, summarize
from wirestudio.kicad.render import RenderError, RenderUnavailable

REPO_ROOT = Path(__file__).resolve().parent.parent

REPORT = {
    "kicad_version": "8.0.9",
    "sheets": [{
        "path": "/",
        "violations": [
            {"type": "power_pin_not_driven", "severity": "error", "description": "Input Power pin not driven by any Output Power pins",
             "items": [{"description": "Symbol U1 Pin 3 [VCC, Power input]"}], "excluded": False},
            {"type": "pin_not_connected", "severity": "warning", "description": "Pin not connected",
             "items": [{"description": "Symbol J2 Pin 4"}], "excluded": False},
            {"type": "pin_not_connected", "severity": "warning", "description": "Pin not connected",
             "items": [{"description": "Symbol J2 Pin 5"}], "excluded": True},
            {"type": "pin_to_pin", "severity": "error", "description": "Pins of type Output and Output are connected",
             "items": [{"description": "Symbol U1 Pin 7"}, {"description": "Symbol U2 Pin 2"}], "excluded": False},
        ],
    }],
}


def _proc(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _fake_run(cmd, **kw):
    if cmd[0] == sys.executable:
        Path(kw["cwd"], "schematic.kicad_sch").write_text("(kicad_sch)")
    elif cmd[0] == "kicad-cli":
        assert cmd[1:4] == ["sch", "erc", "--format"]
        Path(cmd[cmd.index("--output") + 1]).write_text(json.dumps(REPORT))
    return _proc(cmd)


def test_summarize_flattens_counts_and_drops_exclusions():
    out = summarize(REPORT)
    assert out["kicad_version"] == "8.0.9"
    assert out["counts"] == {"pin_not_connected": 1, "pin_to_pin": 1, "power_pin_not_driven": 1}
    assert out["errors"] == 2 and out["warnings"] == 1
    assert out["violations"][0]["items"] == ["Symbol U1 Pin 3 [VCC, Power input]"]
    assert summarize({}) == {"kicad_version": None, "violations": [], "counts": {}, "errors": 0, "warnings": 0}


def test_run_erc_happy_path(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(R, "_skidl_importable", lambda: True)
    monkeypatch.setattr(subprocess, "run", _fake_run)
    out = run_erc(garage_motion_design, library)
    assert out["counts"]["pin_to_pin"] == 1


def test_run_erc_gates_on_tools_and_surfaces_failures(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: None)
    monkeypatch.setattr(R, "_skidl_importable", lambda: True)
    assert erc_status()["available"] is False
    with pytest.raises(RenderUnavailable, match="kicad-cli"):
        run_erc(garage_motion_design, library)
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)

    def no_report(cmd, **kw):
        if cmd[0] == sys.executable:
            Path(kw["cwd"], "schematic.kicad_sch").write_text("(kicad_sch)")
            return _proc(cmd)
        return _proc(cmd, returncode=1, stderr="unknown option --severity-all")
    monkeypatch.setattr(subprocess, "run", no_report)
    with pytest.raises(RenderError, match="kicad-cli erc failed"):
        run_erc(garage_motion_design, library)


def test_erc_routes(monkeypatch, garage_motion_design):
    client = TestClient(create_app())
    monkeypatch.setattr(A, "run_erc", lambda d, lib: summarize(REPORT))
    body = client.post("/design/kicad/erc", json=garage_motion_design.model_dump(mode="json")).json()
    assert body["errors"] == 2 and "pin_to_pin" in body["counts"]

    def unavailable(d, lib):
        raise RenderUnavailable("kicad-cli not found on PATH")
    monkeypatch.setattr(A, "run_erc", unavailable)
    assert client.post("/design/kicad/erc", json=garage_motion_design.model_dump(mode="json")).status_code == 503
    assert set(client.get("/design/kicad/erc/status").json()) == {"available", "kicad_cli", "skidl", "reason"}


def _load_script():
    spec = importlib.util.spec_from_file_location("check_erc", REPO_ROOT / "scripts" / "check_erc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gate_judges_against_the_baseline():
    mod = _load_script()
    allowed = mod.load_baseline()
    assert {"power_pin_not_driven", "pin_not_connected"} <= set(allowed)
    results = {"garage-motion": summarize(REPORT)}
    failures, stale = mod.judge(results, allowed, check_stale=True)
    assert failures == ["garage-motion: [error] pin_to_pin: Pins of type Output and Output are connected (Symbol U1 Pin 7)"]
    assert stale == sorted(set(allowed) - {"power_pin_not_driven", "pin_not_connected"})
    only_power = {"x": summarize({"sheets": [{"path": "/", "violations": [REPORT["sheets"][0]["violations"][0]]}]})}
    failures, stale = mod.judge(only_power, allowed, check_stale=True)
    assert failures == [] and stale == sorted(set(allowed) - {"power_pin_not_driven"})
    assert mod.judge(only_power, allowed, check_stale=False) == ([], [])


def test_gate_default_examples_exist():
    mod = _load_script()
    for stem in mod.DEFAULT_STEMS:
        assert (mod.EXAMPLES_DIR / f"{stem}.json").exists(), stem
