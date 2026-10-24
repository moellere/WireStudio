import importlib.util
import json
import subprocess
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
            {"type": "pin_not_driven", "severity": "error", "description": "Input Power pin not driven by any Output Power pins",
             "items": [{"description": "Symbol U1 Pin 3 [VCC, Power input]"}], "excluded": False},
            {"type": "global_label_dangling", "severity": "warning", "description": "Pin not connected",
             "items": [{"description": "Symbol J2 Pin 4"}], "excluded": False},
            {"type": "global_label_dangling", "severity": "warning", "description": "Pin not connected",
             "items": [{"description": "Symbol J2 Pin 5"}], "excluded": True},
            {"type": "endpoint_off_grid", "severity": "error", "description": "Pins of type Output and Output are connected",
             "items": [{"description": "Symbol U1 Pin 7"}, {"description": "Symbol U2 Pin 2"}], "excluded": False},
        ],
    }],
}


def _proc(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _fake_run(cmd, **kw):
    if cmd[0] == "kicad-cli":
        assert cmd[1:4] == ["sch", "erc", "--format"]
        Path(cmd[cmd.index("--output") + 1]).write_text(json.dumps(REPORT))
    return _proc(cmd)


def _writer_ok(monkeypatch):
    monkeypatch.setattr(R, "sch_status", lambda: {"available": True, "symbol_dir": "/libs", "reason": None})
    monkeypatch.setattr(R, "generate_kicad_sch", lambda d, lib: "(kicad_sch)")


def test_summarize_flattens_counts_and_drops_exclusions():
    out = summarize(REPORT)
    assert out["kicad_version"] == "8.0.9"
    assert out["counts"] == {"global_label_dangling": 1, "endpoint_off_grid": 1, "pin_not_driven": 1}
    assert out["errors"] == 2 and out["warnings"] == 1
    assert out["violations"][0]["items"] == ["Symbol U1 Pin 3 [VCC, Power input]"]
    assert summarize({}) == {"kicad_version": None, "violations": [], "counts": {}, "errors": 0, "warnings": 0}


def test_run_erc_happy_path(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    _writer_ok(monkeypatch)
    monkeypatch.setattr(subprocess, "run", _fake_run)
    out = run_erc(garage_motion_design, library)
    assert out["counts"]["endpoint_off_grid"] == 1


def test_run_erc_gates_on_tools_and_surfaces_failures(monkeypatch, garage_motion_design, library):
    monkeypatch.setattr(R.shutil, "which", lambda exe: None)
    _writer_ok(monkeypatch)
    assert erc_status()["available"] is False
    with pytest.raises(RenderUnavailable, match="kicad-cli"):
        run_erc(garage_motion_design, library)
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)

    def no_report(cmd, **kw):
        return _proc(cmd, returncode=1, stderr="unknown option --severity-all")
    monkeypatch.setattr(subprocess, "run", no_report)
    with pytest.raises(RenderError, match="kicad-cli erc failed"):
        run_erc(garage_motion_design, library)


def test_erc_routes(monkeypatch, garage_motion_design):
    client = TestClient(create_app())
    monkeypatch.setattr(A, "run_erc", lambda d, lib: summarize(REPORT))
    body = client.post("/design/kicad/erc", json=garage_motion_design.model_dump(mode="json")).json()
    assert body["errors"] == 2 and "endpoint_off_grid" in body["counts"]

    def unavailable(d, lib):
        raise RenderUnavailable("kicad-cli not found on PATH")
    monkeypatch.setattr(A, "run_erc", unavailable)
    assert client.post("/design/kicad/erc", json=garage_motion_design.model_dump(mode="json")).status_code == 503
    assert set(client.get("/design/kicad/erc/status").json()) == {"available", "kicad_cli", "symbols", "reason"}


def _load_script():
    spec = importlib.util.spec_from_file_location("check_erc", REPO_ROOT / "scripts" / "check_erc.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gate_judges_against_the_baseline():
    mod = _load_script()
    allowed = mod.load_baseline()
    assert {"pin_not_driven", "global_label_dangling"} <= set(allowed)
    results = {"garage-motion": summarize(REPORT)}
    failures, stale = mod.judge(results, allowed, check_stale=True)
    assert failures == ["garage-motion: [error] endpoint_off_grid: Pins of type Output and Output are connected (Symbol U1 Pin 7)"]
    assert stale == sorted(set(allowed) - {"pin_not_driven", "global_label_dangling"})
    only_power = {"x": summarize({"sheets": [{"path": "/", "violations": [REPORT["sheets"][0]["violations"][0]]}]})}
    failures, stale = mod.judge(only_power, allowed, check_stale=True)
    assert failures == [] and stale == sorted(set(allowed) - {"pin_not_driven"})
    assert mod.judge(only_power, allowed, check_stale=False) == ([], [])


def test_gate_checks_every_example_by_default():
    mod = _load_script()
    paths = mod.example_paths([])
    assert len(paths) == len(list(mod.EXAMPLES_DIR.glob("*.json"))) > 50
    assert mod.example_paths(["garage-motion"]) == [mod.EXAMPLES_DIR / "garage-motion.json"]


def test_run_erc_checks_the_sheet_inside_a_project(monkeypatch, garage_motion_design, library, tmp_path):
    """kicad-cli reports every embedded symbol's library as not configured
    unless the sheet sits in a project whose sym-lib-table names it."""
    from wirestudio.kicad import erc as E

    (tmp_path / "Sensor.kicad_sym").write_text("(kicad_symbol_lib)")
    monkeypatch.setattr(E, "default_symbol_dirs", lambda: [tmp_path])
    monkeypatch.setattr(R.shutil, "which", lambda exe: "/usr/bin/" + exe)
    _writer_ok(monkeypatch)
    monkeypatch.setattr(R, "generate_kicad_sch", lambda d, lib: '(kicad_sch (symbol (lib_id "Sensor:BME280")) (symbol (lib_id "power:GND")))')
    seen = {}

    def run(cmd, **kw):
        sch = Path(cmd[-1])
        seen["table"] = (sch.parent / "sym-lib-table").read_text()
        seen["pro"] = sch.with_suffix(".kicad_pro").is_file()
        return _fake_run(cmd, **kw)
    monkeypatch.setattr(subprocess, "run", run)
    run_erc(garage_motion_design, library)
    assert seen["pro"]
    assert f'(name "Sensor")(type "KiCad")(uri "{tmp_path / "Sensor.kicad_sym"}")' in seen["table"]
    assert '"power"' not in seen["table"]  # no such library here, so no row
