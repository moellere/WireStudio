"""Wrapper around `esphome config` for dry-run validation.

Stub for 0.1 — only checks for binary presence and shells out. The CSP layer
in 0.3 will run this before declaring a design valid.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


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
