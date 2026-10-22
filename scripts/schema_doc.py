"""The design.json field reference, from `design.schema.json`.

Walks the schema and writes docs/design-schema.md: one row per field
path with its type, whether it is required, its default or allowed
values, and the schema's own description. tests/test_schema_doc.py holds
the committed page to the schema, so a schema change that skips this
script fails the PR. To refresh:

    python scripts/schema_doc.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "wirestudio" / "schema" / "design.schema.json"
DOC_PATH = REPO_ROOT / "docs" / "design-schema.md"

_HEADER = """\
# design.json reference

Generated from [`design.schema.json`](../wirestudio/schema/design.schema.json)
by `scripts/schema_doc.py`; do not edit by hand. A field path ending in
`[]` is an array element; `{{}}` is a map value. A connection `target`
is one of several shapes, listed under its `kind`.

Current `schema_version`: **{version}**. Older documents are accepted
and migrated on load (`wirestudio.migrate`); see
[`roadmap.md`](roadmap.md) section 1 for the freeze.

| Field | Type | Required | Values | Description |
|---|---|---|---|---|
"""


def _type(node: dict) -> str:
    if "const" in node:
        return "const"
    if "enum" in node:
        return "enum"
    if "oneOf" in node or "anyOf" in node:
        return "one of"
    t = node.get("type", "")
    return " \\| ".join(t) if isinstance(t, list) else t


def _values(node: dict) -> str:
    if "const" in node:
        return f"`{json.dumps(node['const'])}`"
    if "enum" in node:
        return ", ".join(f"`{json.dumps(v)}`" for v in node["enum"])
    if "default" in node:
        return f"default `{json.dumps(node['default'])}`"
    return ""


def _cell(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def _variant_label(variant: dict) -> str:
    kind = variant.get("properties", {}).get("kind", {})
    return f"kind={kind['const']}" if "const" in kind else ""


def rows(node: dict, path: str, required: bool) -> list[str]:
    out = []
    if path:
        out.append(f"| `{path}` | {_type(node)} | {'yes' if required else ''} | "
                   f"{_cell(_values(node))} | {_cell(node.get('description', ''))} |")
    for key, child in node.get("properties", {}).items():
        out += rows(child, f"{path}.{key}" if path else key, key in node.get("required", []))
    if isinstance(node.get("items"), dict):
        out += rows(node["items"], f"{path}[]", False)
    if isinstance(node.get("additionalProperties"), dict):
        out += rows(node["additionalProperties"], f"{path}{{}}", False)
    for variant in node.get("oneOf", []) + node.get("anyOf", []):
        label = _variant_label(variant)
        prefix = f"{path}<{label}>" if label else path
        for key, child in variant.get("properties", {}).items():
            out += rows(child, f"{prefix}.{key}", key in variant.get("required", []))
        if isinstance(variant.get("items"), dict):
            out += rows(variant["items"], f"{prefix}[]", False)
    return out


def render(schema: dict) -> str:
    version = schema["properties"]["schema_version"]
    current = version.get("default") or version.get("const") or version["enum"][-1]
    return _HEADER.format(version=current) + "\n".join(rows(schema, "", False)) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DOC_PATH)
    args = parser.parse_args(argv)
    args.out.write_text(render(json.loads(SCHEMA_PATH.read_text())))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
