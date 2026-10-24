"""Promote a community library entry into the bundled library.

Reads `library/<kind>/<id>/` from a local checkout of the community
catalogue (moellere/wirestudio-designs), checks it the way the catalogue
does, and shows the file it would add. Nothing is written without
`--write`: promotion is the maintainer's call, made per entry, and lands
as a pull request like any other library change.

With `--write` it adds:
  - `wirestudio/library/<kind>/<id>.yaml`, the entry's text under a header
    crediting its author, the catalogue path, the MIT license and the
    datasheet it was written from;
  - a CHANGELOG line under [Unreleased] / Added naming the author;
  - the entries `coverage_matrix.py --strict` needs for a part with no
    example and no framework blocks, as `deferred:` gaps to close later.

Then it prints what is left by hand: the docs/library.md line, an
example if there is one to write, and the catalogue files the next
pin-bump pull request there removes (the entry, and any design's copy of
it), since the catalogue refuses a bundled id.

Usage:
    python scripts/promote_library.py ../wirestudio-designs boards/lolin-s2-mini
    python scripts/promote_library.py ../wirestudio-designs boards/lolin-s2-mini --write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CATALOGUE = "moellere/wirestudio-designs"
KINDS = {"components": "component.yaml", "boards": "board.yaml"}
_HANDLE = re.compile(r"^[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}$")


def read_entry(catalogue: Path, kind: str, lid: str) -> tuple[str, dict, list[str]]:
    """(text, meta, errors) for one catalogue entry."""
    d = catalogue / "library" / kind / lid
    src, meta_path = d / KINDS[kind], d / "meta.yaml"
    if not src.is_file() or not meta_path.is_file():
        return "", {}, [f"{d} has no {KINDS[kind]} and meta.yaml"]
    meta = yaml.safe_load(meta_path.read_text()) or {}
    errors = []
    if not isinstance(meta.get("author"), str) or not _HANDLE.match(meta["author"]):
        errors.append("meta.yaml: no GitHub handle in `author` to credit")
    if meta.get("license", "MIT") != "MIT":
        errors.append(f"meta.yaml: license {meta['license']!r}; only MIT entries can be bundled")
    if not str(meta.get("source", "")).startswith("https://"):
        errors.append("meta.yaml: no https `source` to cite")
    return src.read_text(), meta, errors


def credited(text: str, kind: str, lid: str, meta: dict) -> str:
    return (
        f"# Contributed by @{meta['author']} through the WireStudio community library\n"
        f"# ({CATALOGUE}, library/{kind}/{lid}), MIT.\n"
        f"# Written from: {meta['source']}\n"
        + text
    )


def gate(text: str, kind: str, library):
    from wirestudio.library.board_check import check_board_yaml
    from wirestudio.library.check import check_component_yaml

    return (check_board_yaml if kind == "boards" else check_component_yaml)(text, library)


def changelog_line(kind: str, lid: str, name: str, author: str) -> str:
    noun = kind[:-1]
    return (f"- **{name}** (`{lid}`), a community {noun} by @{author}, promoted from the\n"
            f"  catalogue's library into the bundled one.\n")


def add_changelog(path: Path, line: str) -> None:
    text = path.read_text()
    head = text.index("## [Unreleased]\n")
    nxt = text.find("\n## [", head + 1)
    section = text[head:nxt if nxt != -1 else len(text)]
    if "### Added\n" in section:
        at = head + section.index("### Added\n") + len("### Added\n\n")
    else:
        at = head + len("## [Unreleased]\n\n")
        line = "### Added\n\n" + line + "\n"
    path.write_text(text[:at] + line + text[at:])


def _append_to_list(text: str, key: str, item: str) -> str:
    """Add `item` to the top-level YAML list `key`, keeping comments."""
    empty = re.search(rf"^{key}: \[\]\s*$", text, re.MULTILINE)
    if empty:
        return text[:empty.start()] + f"{key}:\n  - {item}\n" + text[empty.end():].lstrip("\n")
    m = re.search(rf"^{key}:\n((?:  - .*\n|\s*#.*\n)*)", text, re.MULTILINE)
    if m is None:
        return text.rstrip("\n") + f"\n{key}:\n  - {item}\n"
    return text[:m.end()] + f"  - {item}\n" + text[m.end():]


def _append_to_map(text: str, key: str, item: str, value: str) -> str:
    """Add `item: value` at the end of the top-level YAML mapping `key`."""
    m = re.search(rf"^{key}:\n((?:  .*\n|\s*\n)*)", text, re.MULTILINE)
    entry = f"  {item}: {json.dumps(value)}\n"
    if m is None:
        return text.rstrip("\n") + f"\n\n{key}:\n" + entry
    body = m.group(1).rstrip("\n") + "\n"
    end = m.start(1) + len(body)
    return text[:end] + entry + text[end:]


def update_baselines(repo: Path, kind: str, lid: str) -> list[str]:
    """Add the baseline entries --strict will demand for the new part, and
    say which. The part is in the library tree by now."""
    sys.path.insert(0, str(repo / "scripts"))
    import coverage_matrix as cm
    from wirestudio.library import Library

    library = Library(repo / "wirestudio" / "library")
    examples = {p.stem: json.loads(p.read_text()) for p in sorted((repo / "wirestudio" / "examples").glob("*.json"))}
    added = []
    uncovered_c, uncovered_b = cm._uncovered_ids(library, examples)
    if lid in (uncovered_b if kind == "boards" else uncovered_c):
        path = repo / "scripts" / "coverage_baseline.yaml"
        path.write_text(_append_to_list(path.read_text(), kind, lid))
        added.append(f"scripts/coverage_baseline.yaml: {kind}: {lid} (no bundled example yet)")
    if kind == "components":
        path = repo / "scripts" / "framework_baseline.yaml"
        text = path.read_text()
        for fw, gaps in cm._framework_gaps(library).items():
            if lid in gaps:
                text = _append_to_map(text, fw, lid,
                                      f"deferred: promoted from the community library without a {fw} block")
                added.append(f"scripts/framework_baseline.yaml: {fw}: {lid}")
        path.write_text(text)
    return added


def catalogue_cleanup(catalogue: Path, kind: str, lid: str) -> list[str]:
    paths = [f"library/{kind}/{lid}/"]
    designs = catalogue / "designs"
    if designs.is_dir():
        paths += [f"designs/{d.name}/{kind}/{lid}.yaml" for d in sorted(designs.iterdir())
                  if (d / kind / f"{lid}.yaml").is_file()]
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("catalogue", type=Path, help="a local checkout of the community catalogue")
    ap.add_argument("entry", help="components/<id> or boards/<id>")
    ap.add_argument("--write", action="store_true", help="add it to the bundled library")
    ap.add_argument("--repo", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    from wirestudio.library import Library

    kind, _, lid = args.entry.partition("/")
    if kind not in KINDS or not lid:
        print("entry must be components/<id> or boards/<id>", file=sys.stderr)
        return 2
    text, meta, errors = read_entry(args.catalogue, kind, lid)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    library = Library(args.repo / "wirestudio" / "library")
    target = args.repo / "wirestudio" / "library" / kind / f"{lid}.yaml"
    if target.exists():
        print(f"{target.relative_to(args.repo)} already exists: {lid} is bundled", file=sys.stderr)
        return 1

    final = credited(text, kind, lid, meta)
    report = gate(final, kind, library)
    if not report.ok or report.library_id != lid:
        problems = report.errors or [f"its id is '{report.library_id}', not '{lid}'"]
        print(f"{args.entry} does not pass the {kind[:-1]} gate here:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    for w in report.warnings:
        print(f"warning: {w}")
    for u in report.unverified:
        print(f"unverified here: {u}")

    if not args.write:
        print(f"\n--- would add wirestudio/library/{kind}/{lid}.yaml ---\n{final}")
        print("Dry run; nothing written. Pass --write to promote it.")
        return 0

    target.write_text(final)
    name = (yaml.safe_load(text) or {}).get("name", lid)
    add_changelog(args.repo / "CHANGELOG.md", changelog_line(kind, lid, name, meta["author"]))
    print(f"added wirestudio/library/{kind}/{lid}.yaml")
    print("added a CHANGELOG line under [Unreleased] / Added")
    for line in update_baselines(args.repo, kind, lid):
        print(f"added {line}")
    print("\nLeft by hand:")
    print(f"  - docs/library.md: a line for `{lid}` under its {'board list' if kind == 'boards' else 'category'}")
    print("  - an example under wirestudio/examples/ that uses it, if one is worth having;"
          " it closes the coverage baseline entry")
    print("  - python scripts/coverage_matrix.py, to regenerate docs/library-coverage.md")
    print(f"  - after the WireStudio release that bundles it, the {CATALOGUE} pull request"
          " that bumps the pin removes:")
    for path in catalogue_cleanup(args.catalogue, kind, lid):
        print(f"      {path}")
    print(f"    (promoted {date.today().isoformat()}; the catalogue refuses a bundled id)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
