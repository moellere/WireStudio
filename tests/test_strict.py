"""Strict mode: the design-level toggle that makes warnings block generation.

Permissive (default) surfaces electrical/CSP violations in warnings but still
generates. Strict (`design.strict: true`, or a per-call override) refuses to
generate while any warn/error compatibility entry or design warning remains.
Covers the shared blocker helper plus every generation surface that honors it:
the MCP/agent render + validate tools and the CLI.
"""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from wirestudio.agent.tools import _run_render, _run_validate
from wirestudio.csp.compatibility import strict_blockers
from wirestudio.generate.__main__ import main as generate_main
from wirestudio.library import default_library
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


@pytest.fixture
def lib():
    return default_library()


def _clean() -> dict:
    """solder-fan is warn/error-clean (it carries one info-level A0
    voltage_limit, which must never block)."""
    return json.loads((EXAMPLES_DIR / "solder-fan.json").read_text())


def _dirty_compat() -> dict:
    """Reroute the fan's PWM to D0 (no_pwm) -> a function_unsupported error."""
    d = _clean()
    for c in d["connections"]:
        if c["component_id"] == "fan" and c["pin_role"] == "PWM":
            c["target"] = {"kind": "gpio", "pin": "D0"}
    return d


# --- model / schema ---------------------------------------------------------

def test_design_defaults_to_permissive():
    d = Design.model_validate(_clean())
    assert d.strict is False


def test_schema_accepts_strict_flag():
    schema = json.loads((REPO_ROOT / "wirestudio" / "schema" / "design.schema.json").read_text())
    design = _clean()
    design["strict"] = True
    jsonschema.validate(design, schema)  # must not raise


# --- strict_blockers helper -------------------------------------------------

def test_strict_blockers_empty_for_clean_design(lib):
    assert strict_blockers(_clean(), lib) == []


def test_strict_blockers_flags_compat_warn_error(lib):
    blockers = strict_blockers(_dirty_compat(), lib)
    assert len(blockers) == 1
    assert blockers[0].kind == "compatibility"
    assert blockers[0].severity == "error"
    assert blockers[0].code == "function_unsupported"


def test_strict_blockers_includes_design_warnings(lib):
    d = _clean()
    d["warnings"] = [
        {"level": "error", "code": "demo", "text": "electrical violation"},
        {"level": "info", "code": "note", "text": "just fyi"},
    ]
    blockers = strict_blockers(d, lib)
    # error-level design warning blocks; info-level does not.
    kinds = [(b.kind, b.severity, b.code) for b in blockers]
    assert ("design", "error", "demo") in kinds
    assert all(b.severity != "info" for b in blockers)


def test_strict_blockers_ignores_info_severity(lib):
    """The solder-fan pot on A0 emits an info voltage_limit -- never a blocker."""
    from wirestudio.csp.compatibility import check_pin_compatibility
    compat = check_pin_compatibility(_clean(), lib)
    assert any(w.severity == "info" for w in compat)  # the A0 ceiling note
    assert strict_blockers(_clean(), lib) == []


# --- MCP/agent render tool --------------------------------------------------

def test_render_permissive_generates_despite_blockers(lib):
    d = _dirty_compat()
    d["strict"] = False
    assert _run_render(d, lib)["ok"] is True


def test_render_strict_blocks_on_dirty_design(lib):
    d = _dirty_compat()
    d["strict"] = True
    r = _run_render(d, lib)
    assert r["ok"] is False
    assert r["strict_blocked"] is True
    assert len(r["blockers"]) == 1


def test_render_strict_passes_clean_design(lib):
    d = _clean()
    d["strict"] = True
    r = _run_render(d, lib)
    assert r["ok"] is True
    assert r["yaml"].startswith("esphome:")


# --- MCP/agent validate tool ------------------------------------------------

def test_validate_permissive_ok_but_surfaces_blockers(lib):
    d = _dirty_compat()
    d["strict"] = False
    r = _run_validate(d, lib)
    assert r["ok"] is True          # permissive validate stays ok
    assert r["strict"] is False
    assert len(r["blockers"]) == 1  # but the blocker is still shown


def test_validate_strict_fails_on_blockers(lib):
    d = _dirty_compat()
    d["strict"] = True
    r = _run_validate(d, lib)
    assert r["ok"] is False
    assert r["strict"] is True
    assert len(r["blockers"]) == 1


# --- CLI --------------------------------------------------------------------

def _write(tmp_path: Path, design: dict) -> Path:
    p = tmp_path / "design.json"
    p.write_text(json.dumps(design))
    return p


def test_cli_strict_design_blocks(tmp_path):
    d = _dirty_compat()
    d["strict"] = True
    assert generate_main([str(_write(tmp_path, d))]) == 1


def test_cli_strict_flag_overrides_permissive_design(tmp_path):
    d = _dirty_compat()
    d["strict"] = False
    assert generate_main([str(_write(tmp_path, d)), "--strict"]) == 1


def test_cli_clean_strict_design_generates(tmp_path, capsys):
    d = _clean()
    d["strict"] = True
    assert generate_main([str(_write(tmp_path, d))]) == 0
    assert "esphome:" in capsys.readouterr().out
