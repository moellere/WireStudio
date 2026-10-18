"""Library coverage matrix: which library entries have a passing example.

Walks every library component + board, cross-references the bundled
examples (`wirestudio/examples/*.json`), and emits a markdown report
with two checkbox tables.

A "passing example" is one that ships in `wirestudio/examples/` -- which
implicitly means it round-trips through `esphome config` against the
pinned ESPHome (the merge gate at `.github/workflows/esphome-config.yml`
fails the PR otherwise). So coverage = referenced in any bundled example.

Components / boards with zero examples are flagged: they're library
entries that have never been exercised end-to-end through real ESPHome.
That's not a bug -- some entries are useful but niche -- but it's worth
seeing the gap.

Usage:
    python scripts/coverage_matrix.py                  # write docs/library-coverage.md
    python scripts/coverage_matrix.py --stdout         # print to stdout
    python scripts/coverage_matrix.py --output path.md # write elsewhere
    python scripts/coverage_matrix.py --strict         # CI gate: no drift from baseline

In `--strict` mode the script compares today's uncovered set against
`scripts/coverage_baseline.yaml` and exits 1 if either:
  - a library entry has no example and is not listed in the baseline
    (a new uncovered entry slipped in), or
  - a baseline entry now has an example (the baseline is stale and must
    shrink to reflect the closed gap).

The other frameworks are held to the same bar per component block.
A component is covered on a framework when that framework's generator
can use it: a `circuitpython:` / `micropython:` block, or membership in
the tasmota / lorawan target's `component_ids` (Tasmota autodetects I2C
parts, so they count without a block). Every gap needs an entry in
`scripts/framework_baseline.yaml` whose reason starts with one of
`no driver upstream`, `no meaning on this framework` or `deferred:`;
`--strict` fails on an unexplained gap, a stale entry, or a reason
outside those three.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from wirestudio.library import default_library

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "library-coverage.md"
DEFAULT_BASELINE = REPO_ROOT / "scripts" / "coverage_baseline.yaml"
DEFAULT_FRAMEWORK_BASELINE = REPO_ROOT / "scripts" / "framework_baseline.yaml"

FRAMEWORKS = ("circuitpython", "micropython", "tasmota", "lorawan")
REASON_PREFIXES = ("no driver upstream", "no meaning on this framework", "deferred:")


def _framework_coverage(library) -> dict[str, set[str]]:
    """Component ids each framework's generator can use."""
    from wirestudio.targets import get_target

    components = library.list_components()
    return {
        "circuitpython": {c.id for c in components if c.circuitpython is not None},
        "micropython": {c.id for c in components if c.micropython is not None},
        "tasmota": set(get_target("tasmota").component_ids(library)),
        "lorawan": set(get_target("lorawan").component_ids(library)),
    }


def _framework_gaps(library) -> dict[str, set[str]]:
    covered = _framework_coverage(library)
    ids = {c.id for c in library.list_components()}
    return {fw: ids - covered[fw] for fw in FRAMEWORKS}


def _load_framework_baseline(path: Path) -> dict[str, dict[str, str]]:
    raw = yaml.safe_load(path.read_text()) or {}
    return {fw: dict(raw.get(fw) or {}) for fw in FRAMEWORKS}


def _examples_using_component(examples: dict[str, dict]) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = defaultdict(list)
    for ex_id, ex in examples.items():
        for c in ex.get("components") or []:
            lib_id = c.get("library_id")
            if lib_id:
                refs[lib_id].append(ex_id)
    # Stable ordering: alphabetical example ids per component.
    return {k: sorted(set(v)) for k, v in refs.items()}


def _examples_using_board(examples: dict[str, dict]) -> dict[str, list[str]]:
    refs: dict[str, list[str]] = defaultdict(list)
    for ex_id, ex in examples.items():
        board = (ex.get("board") or {}).get("library_id")
        if board:
            refs[board].append(ex_id)
    return {k: sorted(set(v)) for k, v in refs.items()}


def _load_examples() -> dict[str, dict]:
    """Map file-stem -> design dict. The file stem (not the design's
    own ``id`` field) is what the rest of the toolchain uses to refer
    to examples -- ``check_examples.py garage-motion`` finds
    ``garage-motion.json`` regardless of its inner id, and the README
    examples table links by stem too. So the matrix matches that."""
    out: dict[str, dict] = {}
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        try:
            doc = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"skipping {path.name}: {e}", file=sys.stderr)
            continue
        out[path.stem] = doc
    return out


def _render(library, examples: dict[str, dict], framework_baseline: dict[str, dict[str, str]]) -> str:
    component_refs = _examples_using_component(examples)
    board_refs = _examples_using_board(examples)
    covered = _framework_coverage(library)

    components = sorted(library.list_components(), key=lambda c: (c.category, c.id))
    boards = sorted(library.list_boards(), key=lambda b: b.id)

    component_total = len(components)
    component_covered = sum(1 for c in components if component_refs.get(c.id))
    board_total = len(boards)
    board_covered = sum(1 for b in boards if board_refs.get(b.id) or b.has_radio)

    lines: list[str] = []
    lines.append("# Library coverage")
    lines.append("")
    lines.append(
        "Generated by `scripts/coverage_matrix.py`. Each entry's checkbox flips "
        "based on whether at least one bundled example in `wirestudio/examples/` "
        "uses it. Bundled examples are validated against pinned ESPHome by the "
        "[esphome-config gate](../.github/workflows/esphome-config.yml), so a "
        "✅ here means that library entry round-trips end-to-end through real "
        "ESPHome -- not just that the YAML template renders. Radio (LoRaWAN) "
        "boards are exercised instead by the lorawan firmware build."
    )
    lines.append("")
    lines.append(
        f"**Summary:** components {component_covered}/{component_total} "
        f"({100 * component_covered // component_total}%), "
        f"boards {board_covered}/{board_total} "
        f"({100 * board_covered // board_total}%); "
        + ", ".join(f"{fw} {len(covered[fw])}/{component_total}" for fw in FRAMEWORKS)
        + " component blocks, every gap explained below."
    )
    lines.append("")

    lines.append("## Components")
    lines.append("")
    lines.append(
        "The framework columns say which generators can use the component: "
        "a `circuitpython:` / `micropython:` block, or the tasmota / lorawan "
        "target listing it (Tasmota autodetects I2C parts without a block)."
    )
    lines.append("")
    lines.append("| | Library id | Category | Examples | " + " | ".join(FRAMEWORKS) + " |")
    lines.append("|---|---|---|---|" + "---|" * len(FRAMEWORKS))
    for c in components:
        refs = component_refs.get(c.id, [])
        check = "✅" if refs else "⬜"
        ex_links = ", ".join(
            f"[`{e}`](../wirestudio/examples/{e}.json)" for e in refs
        ) or "_(none)_"
        marks = " | ".join("✅" if c.id in covered[fw] else "⬜" for fw in FRAMEWORKS)
        lines.append(f"| {check} | `{c.id}` | {c.category} | {ex_links} | {marks} |")
    lines.append("")

    lines.append("## Boards")
    lines.append("")
    lines.append("| | Library id | Chip | Examples |")
    lines.append("|---|---|---|---|")
    for b in boards:
        refs = board_refs.get(b.id, [])
        check = "✅" if (refs or b.has_radio) else "⬜"
        if refs:
            ex_links = ", ".join(f"[`{e}`](../wirestudio/examples/{e}.json)" for e in refs)
        elif b.has_radio:
            ex_links = "_(lorawan firmware build)_"
        else:
            ex_links = "_(none)_"
        chip = getattr(b, "chip_variant", None) or getattr(b, "mcu", "?")
        lines.append(f"| {check} | `{b.id}` | {chip} | {ex_links} |")
    lines.append("")

    uncovered_components = [c.id for c in components if not component_refs.get(c.id)]
    uncovered_boards = [b.id for b in boards if not board_refs.get(b.id) and not b.has_radio]
    if uncovered_components or uncovered_boards:
        lines.append("## Coverage gaps")
        lines.append("")
        if uncovered_components:
            lines.append(
                f"Components without an example ({len(uncovered_components)}): "
                + ", ".join(f"`{i}`" for i in uncovered_components)
                + "."
            )
            lines.append("")
        if uncovered_boards:
            lines.append(
                f"Boards without an example ({len(uncovered_boards)}): "
                + ", ".join(f"`{i}`" for i in uncovered_boards)
                + "."
            )
            lines.append("")
        lines.append(
            "Adding an example for any of these earns the ✅ on the next "
            "regeneration. The new example also has to pass the "
            "`esphome config` gate."
        )
        lines.append("")

    lines.append("## Framework gaps")
    lines.append("")
    lines.append(
        "Every component a framework cannot use, with the reason from "
        "`scripts/framework_baseline.yaml`. `deferred:` names the fragment "
        "or template rule still to write; `no driver upstream` means the "
        "framework's own library has nothing to wrap; `no meaning on this "
        "framework` means the part has no code on that framework at all. "
        "A gap with no reason fails `--strict`."
    )
    lines.append("")
    by_id = {c.id: c for c in components}
    for fw in FRAMEWORKS:
        gaps = sorted(set(by_id) - covered[fw], key=lambda i: (by_id[i].category, i))
        kinds = {p: sum(1 for i in gaps if framework_baseline[fw].get(i, "").startswith(p))
                 for p in REASON_PREFIXES}
        lines.append(f"### {fw}: {len(gaps)} of {component_total} without a block")
        lines.append("")
        lines.append(", ".join(f"{n} {p.rstrip(':')}" for p, n in kinds.items()) + ".")
        lines.append("")
        for cid in gaps:
            lines.append(f"- `{cid}` ({by_id[cid].category}): {framework_baseline[fw].get(cid, '_(unexplained)_')}")
        lines.append("")

    return "\n".join(lines)


def _uncovered_ids(library, examples: dict[str, dict]) -> tuple[set[str], set[str]]:
    component_refs = _examples_using_component(examples)
    board_refs = _examples_using_board(examples)
    components = {c.id for c in library.list_components() if not component_refs.get(c.id)}
    # Radio (LoRaWAN-target) boards are exercised end-to-end by the lorawan
    # firmware build (tests/test_firmware_gen.py + scripts/build_lorawan_firmware.py
    # + the lorawan-firmware CI gate), not by an esphome example -- count that.
    boards = {
        b.id
        for b in library.list_boards()
        if not board_refs.get(b.id) and not getattr(b, "has_radio", False)
    }
    return components, boards


def _framework_problems(library, baseline_path: Path) -> list[str]:
    gaps = _framework_gaps(library)
    baseline = _load_framework_baseline(baseline_path)
    rel = baseline_path.relative_to(REPO_ROOT) if baseline_path.is_relative_to(REPO_ROOT) else baseline_path
    problems: list[str] = []
    for fw in FRAMEWORKS:
        entries = baseline[fw]
        unexplained = gaps[fw] - set(entries)
        stale = set(entries) - gaps[fw]
        bad_reason = {cid for cid, reason in entries.items()
                      if not isinstance(reason, str) or not reason.startswith(REASON_PREFIXES)}
        if unexplained:
            problems.append(f"{fw}: components without a block and no entry in {rel}:")
            problems += [f"  - {cid}" for cid in sorted(unexplained)]
        if stale:
            problems.append(f"{fw}: baseline entries whose component now has a block (remove from {rel}):")
            problems += [f"  - {cid}" for cid in sorted(stale)]
        if bad_reason:
            problems.append(f"{fw}: reasons must start with one of {', '.join(repr(p) for p in REASON_PREFIXES)}:")
            problems += [f"  - {cid}: {entries[cid]!r}" for cid in sorted(bad_reason)]
    return problems


def _strict_check(library, examples: dict[str, dict], baseline_path: Path,
                  framework_baseline_path: Path) -> int:
    uncovered_components, uncovered_boards = _uncovered_ids(library, examples)
    baseline = yaml.safe_load(baseline_path.read_text()) or {}
    baseline_components = set(baseline.get("components") or [])
    baseline_boards = set(baseline.get("boards") or [])

    new_uncovered_c = uncovered_components - baseline_components
    new_uncovered_b = uncovered_boards - baseline_boards
    stale_c = baseline_components - uncovered_components
    stale_b = baseline_boards - uncovered_boards

    problems: list[str] = []
    if new_uncovered_c or new_uncovered_b:
        problems.append("New uncovered library entries (add an example or list in baseline):")
        for cid in sorted(new_uncovered_c):
            problems.append(f"  - component: {cid}")
        for bid in sorted(new_uncovered_b):
            problems.append(f"  - board: {bid}")
    if stale_c or stale_b:
        problems.append(
            "Baseline is stale (these now have an example -- remove from "
            f"{baseline_path.relative_to(REPO_ROOT)}):"
        )
        for cid in sorted(stale_c):
            problems.append(f"  - component: {cid}")
        for bid in sorted(stale_b):
            problems.append(f"  - board: {bid}")
    problems += _framework_problems(library, framework_baseline_path)

    if problems:
        sys.stderr.write("coverage_matrix --strict failed:\n")
        sys.stderr.write("\n".join(problems) + "\n")
        return 1

    gaps = _framework_gaps(library)
    print(
        f"coverage baseline OK: {len(uncovered_components)} components and "
        f"{len(uncovered_boards)} boards remain uncovered, matching baseline; "
        + ", ".join(f"{fw} {len(gaps[fw])}" for fw in FRAMEWORKS)
        + " framework gaps, every one explained.",
        file=sys.stderr,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"output file (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--stdout", action="store_true",
        help="print to stdout instead of writing a file",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="CI gate: fail when uncovered set drifts from coverage_baseline.yaml",
    )
    parser.add_argument(
        "--baseline", type=Path, default=DEFAULT_BASELINE,
        help=f"baseline file for --strict (default: {DEFAULT_BASELINE.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--framework-baseline", type=Path, default=DEFAULT_FRAMEWORK_BASELINE,
        help=("per-framework gap reasons for --strict and the report "
              f"(default: {DEFAULT_FRAMEWORK_BASELINE.relative_to(REPO_ROOT)})"),
    )
    args = parser.parse_args(argv)

    library = default_library()
    examples = _load_examples()

    if args.strict:
        return _strict_check(library, examples, args.baseline, args.framework_baseline)

    text = _render(library, examples, _load_framework_baseline(args.framework_baseline))
    if args.stdout:
        sys.stdout.write(text)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
        print(f"wrote {args.output.relative_to(REPO_ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
