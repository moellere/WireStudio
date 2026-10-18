"""Verify every bundled example renders YAML that upstream ESPHome accepts.

Walks examples/*.json, renders each through wirestudio.generate.yaml_gen, writes a
sibling secrets.yaml stub for any !secret references, then invokes
`esphome config <yaml>` and reports the result.

Run locally:
    pip install -e .[dev]
    pip install esphome
    python scripts/check_examples.py

Run for one example:
    python scripts/check_examples.py garage-motion

Exit code 0 = every example passed, 1 = at least one failed. CI consumes the
exit code as the merge gate.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.library import Library, default_library
from wirestudio.library.check import create_component, synthetic_design
from wirestudio.model import Design

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"

# Valid 32-byte base64 string -- ESPHome's api.encryption.key validator rejects
# anything else, even though the value is never used to encrypt traffic during
# `esphome config`.
STUB_API_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="

_SECRET_RE = re.compile(r"!secret\s+([A-Za-z0-9_]+)")


def _stub_value(name: str) -> str:
    if name.endswith("api_key") or name == "api_key":
        return STUB_API_KEY
    if name == "wifi_ssid":
        return "stub-ssid"
    if name == "wifi_password":
        return "stub-password-1234"
    if name == "ota_password":
        return "stub-ota-password"
    # LoRaWAN keys carried in secrets.yaml for the external-component path
    # (lorawan-for-esphome). The component's schema validates them as hex,
    # so a plain `stub-<name>` would fail `esphome config`.
    if name in ("dev_eui", "join_eui"):
        return "0123456789abcdef"  # 16 hex chars (EUI-64)
    if name == "app_key":
        return "00112233445566778899aabbccddeeff"  # 32 hex chars (128-bit AES key)
    return f"stub-{name}"


def _write_secrets(yaml_text: str, dest: Path) -> None:
    names = sorted(set(_SECRET_RE.findall(yaml_text)))
    lines = [f"{n}: {json.dumps(_stub_value(n))}" for n in names]
    dest.write_text("\n".join(lines) + ("\n" if lines else ""))


def _check_one(example: Path, workdir: Path, subcommand: str) -> tuple[bool, str]:
    design = Design.model_validate(json.loads(example.read_text()))
    return _check_design(example.stem, design, default_library(), workdir, subcommand)


def _user_component(path: Path, workdir: Path) -> tuple[str, Design, Library]:
    """A component YAML as a user would author it, through the same gate
    `component_create` runs, placed on the synthetic design the gate
    renders it against. The user library lives under `workdir`."""
    library = Library(default_library().root, workdir / "user-library")
    report = create_component(path.read_text(), library)
    if not report.ok:
        raise SystemExit(f"{path}: component_check failed:\n  " + "\n  ".join(report.errors))
    design = synthetic_design(library.component(report.library_id), library, on_buses=True)
    return f"component-{report.library_id}", design, library


def _check_design(
    name: str, design: Design, library: Library, workdir: Path, subcommand: str,
) -> tuple[bool, str]:
    yaml_text = render_yaml(design, library)

    out_dir = workdir / name
    out_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = out_dir / f"{name}.yaml"
    yaml_path.write_text(yaml_text)
    _write_secrets(yaml_text, out_dir / "secrets.yaml")

    try:
        result = subprocess.run(
            ["esphome", subcommand, str(yaml_path)],
            capture_output=True,
            text=True,
            cwd=out_dir,
        )
    except FileNotFoundError:
        print(
            "esphome CLI not found. Install with: pip install 'esphome==2025.12.7'",
            file=sys.stderr,
        )
        sys.exit(2)
    if result.returncode == 0:
        return True, ""
    tail = (result.stdout + result.stderr).strip().splitlines()[-40:]
    return False, "\n".join(tail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "names",
        nargs="*",
        help="example stems to check (default: all in examples/)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="leave the generated YAML + secrets.yaml on disk for inspection",
    )
    parser.add_argument(
        "--compile",
        action="store_true",
        help=(
            "run `esphome compile` instead of `esphome config` (slow -- "
            "first-time toolchain download is several minutes; intended "
            "for the nightly compile-smoke job, not per-PR)."
        ),
    )
    parser.add_argument(
        "--component",
        type=Path,
        action="append",
        default=[],
        metavar="YAML",
        help=(
            "instead of examples: a user component YAML, run through "
            "component_check and placed on the gate's synthetic design"
        ),
    )
    args = parser.parse_args(argv)
    subcommand = "compile" if args.compile else "config"

    if args.component:
        if args.names:
            print("--component takes no example names", file=sys.stderr)
            return 2
        with tempfile.TemporaryDirectory() as tmp:
            failures = []
            for path in args.component:
                name, design, library = _user_component(path, Path(tmp))
                ok, detail = _check_design(name, design, library, Path(tmp), subcommand)
                print(f"  {'PASS' if ok else 'FAIL'}  {path}")
                if not ok:
                    failures.append((str(path), detail))
        for name, detail in failures:
            print(f"\n--- {name} ---\n{detail}")
        return 1 if failures else 0

    if args.names:
        examples = [EXAMPLES_DIR / f"{n}.json" for n in args.names]
        missing = [p for p in examples if not p.exists()]
        if missing:
            print(f"unknown example(s): {[p.stem for p in missing]}", file=sys.stderr)
            return 2
    else:
        examples = sorted(EXAMPLES_DIR.glob("*.json"))

    if not examples:
        print("no examples found", file=sys.stderr)
        return 2

    workdir_ctx = (
        tempfile.TemporaryDirectory()
        if not args.keep
        else None
    )
    workdir = Path(workdir_ctx.name) if workdir_ctx else REPO_ROOT / "build" / "esphome-config"
    if args.keep:
        workdir.mkdir(parents=True, exist_ok=True)

    failures: list[tuple[str, str]] = []
    for example in examples:
        ok, detail = _check_one(example, workdir, subcommand)
        marker = "PASS" if ok else "FAIL"
        print(f"  {marker}  {example.stem}")
        if not ok:
            failures.append((example.stem, detail))

    if workdir_ctx is not None:
        workdir_ctx.cleanup()

    print()
    if failures:
        print(f"{len(failures)} of {len(examples)} examples failed:")
        for name, detail in failures:
            print(f"\n--- {name} ---")
            print(detail)
        return 1

    verb = "compile" if args.compile else "validate"
    print(f"all {len(examples)} examples {verb} under upstream ESPHome.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
