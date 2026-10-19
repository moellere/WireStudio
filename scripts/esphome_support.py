"""The per-release ESPHome support table, from the example gate's verdicts.

`check_examples.py --json` records what one ESPHome release made of every
bundled example. This merges those files, one per release, into
docs/esphome-support.md: the releases every example validates on, and for
each failure elsewhere the library components the error names, so a
failing release reads as "`max98357a` needs 2026.6+" rather than as a
list of examples.

The esphome-matrix workflow writes one file per release it sweeps;
`scripts/esphome_support/` holds the files the committed table was
built from, and tests/test_esphome_support.py holds the table to them.
To refresh: download the sweep's artifacts into that directory, then

    python scripts/esphome_support.py

Attribution reads ESPHome's error excerpt: the `id:` lines in it name
the instance the generator emitted, and the section header names the
platform; a failure that names neither is charged to every component of
the example and marked so.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from wirestudio.library import default_library

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"
RESULTS_DIR = REPO_ROOT / "scripts" / "esphome_support"
TABLE_PATH = REPO_ROOT / "docs" / "esphome-support.md"
PIN_PATH = REPO_ROOT / ".github" / "workflows" / "esphome-config.yml"

_ID_RE = re.compile(r"^\s*(?:-\s*)?id:\s*(\S+)", re.M)
_HEADER_RE = re.compile(r"^([a-z0-9_]+)(?:\.([a-z0-9_]+))?:\s*\[source", re.M)
_PLATFORM_RE = re.compile(r"platform:\s*([a-z0-9_]+)")


def version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def minor(v: str) -> str:
    return ".".join(v.split(".")[:2])


def pinned_version() -> str:
    m = re.search(r"esphome==(\d+\.\d+\.\d+)", PIN_PATH.read_text())
    if not m:
        raise SystemExit(f"no esphome pin in {PIN_PATH}")
    return m.group(1)


def load_results(paths: list[Path]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for p in paths:
        data = json.loads(p.read_text())
        for key in ("esphome", "examples"):
            if key not in data:
                raise SystemExit(f"{p}: no {key!r}; not a check_examples.py --json file")
        out[data["esphome"]] = data
    return out


def _platforms(component) -> set[str]:
    return set(component.esphome.required_components) | set(
        _PLATFORM_RE.findall(component.esphome.yaml_template or ""))


def attribute(stem: str, detail: str, library) -> tuple[list[str], bool]:
    """Library ids the failure names, and whether it named them (False when
    the whole example is charged for want of a clue)."""
    example = json.loads((EXAMPLES_DIR / f"{stem}.json").read_text())
    components = example.get("components") or []
    ids = set(_ID_RE.findall(detail))
    hit = [c["library_id"] for c in components
           if any(i == c["id"] or i.startswith(c["id"] + "_") for i in ids)]
    if not hit:
        platforms = {p for _, p in _HEADER_RE.findall(detail) if p}
        if platforms:
            hit = [c["library_id"] for c in components
                   if platforms & _platforms(library.component(c["library_id"]))]
    if hit:
        return sorted(set(hit)), True
    return sorted({c["library_id"] for c in components}), False


def first_error_line(detail: str) -> str:
    lines = detail.splitlines()
    start = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("Failed config")), 0)
    body = [ln.strip() for ln in lines[start:] if ln.strip() and not ln.startswith("INFO")]
    # The message sits between the section header and the YAML it quotes.
    for ln in body[1:]:
        if not re.match(r"^[a-z0-9_.-]+:", ln) or " " in ln.split(":")[0]:
            return ln
    return body[0] if body else detail.strip().splitlines()[-1] if detail.strip() else "(no output)"


def analyse(results: dict[str, dict], library) -> dict:
    versions = sorted(results, key=version_key)
    pin = pinned_version()
    rows = []
    per_component: dict[str, dict[str, str]] = {}
    for v in versions:
        examples = results[v]["examples"]
        failing = []
        for stem in sorted(examples):
            verdict = examples[stem]
            if verdict.get("ok"):
                continue
            detail = verdict.get("detail", "")
            comps, named = attribute(stem, detail, library)
            line = first_error_line(detail)
            failing.append({"example": stem, "components": comps, "named": named, "error": line})
            for c in comps:
                per_component.setdefault(c, {})[v] = line
        rows.append({
            "version": v, "date": results[v].get("date", ""),
            "total": len(examples), "passing": sum(1 for x in examples.values() if x.get("ok")),
            "failing": failing,
        })
    clean = [r["version"] for r in rows if not r["failing"]]
    supported: list[str] = []
    if pin in clean:
        i = versions.index(pin)
        lo = i
        while lo > 0 and versions[lo - 1] in clean:
            lo -= 1
        hi = i
        while hi + 1 < len(versions) and versions[hi + 1] in clean:
            hi += 1
        supported = versions[lo:hi + 1]
    needs: dict[str, str] = {}
    breaks: dict[str, str] = {}
    for comp, fails in per_component.items():
        failing_versions = sorted(fails, key=version_key)
        newest_fail = failing_versions[-1]
        later = [v for v in versions if version_key(v) > version_key(newest_fail)]
        if later:
            needs[comp] = later[0]
        else:
            oldest_fail = failing_versions[0]
            breaks[comp] = oldest_fail
    return {"versions": versions, "pin": pin, "rows": rows, "supported": supported,
            "per_component": per_component, "needs": needs, "breaks": breaks}


def summary_line(a: dict) -> str:
    if not a["supported"]:
        return (f"The pinned ESPHome {a['pin']} is not in the sweep, or fails it; "
                "no supported range can be stated.")
    lo, hi = a["supported"][0], a["supported"][-1]
    text = (f"Supports ESPHome {minor(lo)} through {minor(hi)}" if lo != hi
            else f"Supports ESPHome {minor(lo)}")
    text += f" (every bundled example validates; the pin is {a['pin']})."
    notes = [f"`{c}` needs {minor(v)}+" for c, v in sorted(a["needs"].items())]
    notes += [f"`{c}` breaks from {minor(v)}" for c, v in sorted(a["breaks"].items())]
    if notes:
        text += " " + "; ".join(notes) + "."
    return text


def render(a: dict) -> str:
    lines = [
        "# ESPHome support",
        "",
        "Which ESPHome releases the studio's output validates on, from the",
        "`esphome-matrix` sweep: every bundled example through `esphome config`",
        "on each release, failures charged to the library components the error",
        "names. Generated by `python scripts/esphome_support.py` from",
        "`scripts/esphome_support/*.json`; do not edit by hand.",
        "",
        f"**{summary_line(a)}**",
        "",
        "| ESPHome | swept | examples validating | failures |",
        "|---|---|---|---|",
    ]
    for r in reversed(a["rows"]):
        cells = []
        for f in r["failing"]:
            comps = ", ".join(f"`{c}`" for c in f["components"])
            if not f["named"]:
                comps += " (unattributed)"
            cells.append(f"{f['example']}: {comps}")
        lines.append(f"| {r['version']} | {r['date']} | {r['passing']}/{r['total']} | "
                     f"{'; '.join(cells)} |")
    if a["per_component"]:
        lines += ["", "## By component", "",
                  "| component | fails on | what ESPHome says |", "|---|---|---|"]
        for comp in sorted(a["per_component"]):
            fails = a["per_component"][comp]
            versions = ", ".join(sorted(fails, key=version_key))
            newest = sorted(fails, key=version_key)[-1]
            what = fails[newest].replace("|", "\\|")
            lines.append(f"| `{comp}` | {versions} | {what} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="*", type=Path,
                        help=f"check_examples.py --json files (default: {RESULTS_DIR.relative_to(REPO_ROOT)}/*.json)")
    parser.add_argument("--out", type=Path, default=TABLE_PATH)
    parser.add_argument("--check", action="store_true",
                        help="exit 1 when --out differs from what the results produce")
    parser.add_argument("--summary", type=Path, default=None,
                        help="append the table to this file as well (a job summary)")
    args = parser.parse_args(argv)
    paths = args.results or sorted(RESULTS_DIR.glob("*.json"))
    if not paths:
        print("no result files", file=sys.stderr)
        return 2
    a = analyse(load_results(paths), default_library())
    text = render(a)
    print(summary_line(a))
    if args.summary:
        with args.summary.open("a") as f:
            f.write(text)
    if args.check:
        current = args.out.read_text() if args.out.exists() else ""
        if current != text:
            print(f"{args.out} is stale; run python scripts/esphome_support.py", file=sys.stderr)
            return 1
        return 0
    args.out.write_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
