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

from wirestudio.library import Library
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
