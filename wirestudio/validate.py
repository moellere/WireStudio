"""Design-level checks that aren't about pins, plus a wrapper around
`esphome config` for dry-run validation.

The dry-run half is a stub for 0.1 — only checks for binary presence and
shells out. The CSP layer in 0.3 will run this before declaring a design
valid.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from wirestudio.inventory.check import NOT_COMPARED
from wirestudio.inventory.match import family_for_ref
from wirestudio.kicad.netlist import assign_refs, part_key
from typing import Optional

from wirestudio.library import Library
from wirestudio.library.electrical import run_checks
from wirestudio.model import Design, DesignWarning


def check_board_flash(design: Design, library: Library) -> list[DesignWarning]:
    """Permissive checks on `design.board.flash_size_mb`, the per-design
    override of the library board file's flash size.

    Over-declaring is the direction that bricks: the bootloader asserts on a
    size mismatch and boot-loops before any sketch code runs. So raising the
    override above the board file's value warns; lowering it is safe and
    silent.
    """
    override = design.board.flash_size_mb
    if override is None:
        return []
    try:
        board = library.board(design.board.library_id)
    except FileNotFoundError:
        # An unknown board is surfaced by the core validators; not our job.
        return []

    if not board.chip_variant.startswith("esp32"):
        return [DesignWarning(
            level="warn",
            code="flash_size_override_ignored",
            text=(
                f"board.flash_size_mb is set to {override} but board "
                f"{board.id!r} is not an ESP32 family part; neither generator "
                "emits a flash size for it and the override does nothing"
            ),
        )]

    if board.flash_size_mb and override > board.flash_size_mb:
        return [DesignWarning(
            level="warn",
            code="flash_size_override_above_board",
            text=(
                f"board.flash_size_mb raises {board.id!r} from "
                f"{board.flash_size_mb}MB to {override}MB. Declaring more "
                "flash than the chip has boot-loops the board. Confirm the "
                "size on this unit first -- the ESP-IDF bootloader prints "
                "'SPI Flash Size' at boot, or run `esptool flash-id`."
            ),
        )]
    return []


def esphome_available() -> bool:
    return shutil.which("esphome") is not None


def dry_run(yaml_path: Path) -> tuple[bool, str]:
    if not esphome_available():
        return False, "esphome CLI not found; install esphome to validate."
    proc = subprocess.run(
        ["esphome", "config", str(yaml_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0, proc.stdout + proc.stderr


def check_part_overrides(design: Design, library: Library) -> list[DesignWarning]:
    """Every accepted substitution stays visible: an info line naming the
    designator, both parts and what the drawer comparison never covered.
    A key that names no subcircuit part is a warn, since the override
    then does nothing."""
    if not design.part_overrides:
        return []
    refs = assign_refs(design, library)
    parts = {}
    for c in design.components:
        try:
            sub = library.component(c.library_id).subcircuit
        except FileNotFoundError:
            continue
        if sub is not None:
            parts.update({part_key(c.id, p.id): p for p in sub.parts})
    out: list[DesignWarning] = []
    for key, mpn in design.part_overrides.items():
        part = parts.get(key)
        if part is None:
            out.append(DesignWarning(
                level="warn", code="part_override_unknown",
                text=f"part_overrides[{key!r}] names no subcircuit part; nothing is substituted",
            ))
            continue
        if not mpn or mpn == part.kicad.value:
            continue
        family = part.requires.family if part.requires else family_for_ref(part.ref_prefix)
        caveat = NOT_COMPARED.get(family, "only family, polarity, package and ratings compared")
        out.append(DesignWarning(
            level="info", code="part_substituted",
            text=f"{refs[key]} ({key}): {mpn} substituted for {part.kicad.value}; {caveat}",
        ))
    return out


def check_electrical(design: Design, library: Library) -> list[DesignWarning]:
    """Each instance's declared block rules with its real params and the
    rails it is wired to. A failing rule warns; one that cannot be
    evaluated says so at info level; a passing one is silent."""
    try:
        board = library.board(design.board.library_id)
    except FileNotFoundError:
        board = None
    rails = {r.name: r.voltage for r in board.rails} if board else {}
    out: list[DesignWarning] = []
    for comp in design.components:
        try:
            lib_comp = library.component(comp.library_id)
        except FileNotFoundError:
            continue
        if lib_comp.verify is None:
            continue
        declared = {p.role: p.voltage for p in lib_comp.electrical.pins}
        targets = {c.pin_role: c.target for c in design.connections if c.component_id == comp.id}

        def pin_voltage(role: str) -> Optional[float]:
            target = targets.get(role)
            if target is not None and target.kind == "rail":
                return rails.get(target.rail)
            return declared.get(role)

        results, unresolved = run_checks(lib_comp, comp.params, pin_voltage)
        for r in results:
            if not r.ok:
                out.append(DesignWarning(
                    level="warn", code=f"electrical_{r.kind}", text=f"{comp.id}: {r.text}"))
        for u in unresolved:
            out.append(DesignWarning(
                level="info", code="electrical_unresolved", text=f"{comp.id}: {u}"))
    return out
