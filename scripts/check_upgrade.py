"""Upgrade test: what a released wirestudio wrote loads and renders under this checkout.

Two phases against one data directory, each run under a different install:

    python scripts/check_upgrade.py seed DATA     # under the previous release
    python scripts/check_upgrade.py verify DATA   # under this checkout

`seed` drives the installed release through its own REST API, in both
store layouts (the JSON directories and the SQLite files): it saves every
example that release bundles, a user component authored through
`/library/components` and a design that uses it, inventory rows, and an
agent session. It writes what it saved to DATA/manifest.json, including
what that release rendered for each design.

`verify` opens the same directory with this checkout and fails unless
every saved design is listed and loads at the current schema, renders
exactly as the original document does when handed to this checkout fresh
(so the store round trip and the migration change nothing), the user
component is in the library, the inventory and sessions read back
unchanged, and each SQLite store is at its current schema version. How
far the renders moved from what the previous release produced is
reported, not failed: generator output changes between releases on
purpose.

The script imports whatever `wirestudio` is installed, so run it with
the interpreter of the install under test; run as a file, the checkout
is not on its import path.
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT = REPO_ROOT / "tests" / "fixtures" / "components" / "led_driver_npn.yaml"
USER_DESIGN_ID = "upgrade-user-component"
SESSION_ID = "upgrade-session"
SESSION = [("user", "add a status LED"), ("assistant", "Added it on GPIO14.")]
INVENTORY = {"bme280": {"quantity": 3, "location": "drawer A"}}
PARTS = {"2N3904": {"quantity": 25, "family": "bjt", "polarity": "npn", "package": "TO-92"}}

LAYOUTS = {
    "files": {"DESIGNS_DIR": "designs", "SESSIONS_DIR": "sessions"},
    "sqlite": {"DESIGNS_DB": "designs.db", "SESSIONS_DB": "sessions.db"},
}


def _client(data: Path, layout: str):
    for key in ("DESIGNS_DIR", "SESSIONS_DIR", "DESIGNS_DB", "SESSIONS_DB", "WIRESTUDIO_API_TOKEN"):
        os.environ.pop(key, None)
    for key, rel in LAYOUTS[layout].items():
        os.environ[key] = str(data / rel)
    os.environ["LIBRARY_USER_DIR"] = str(data / "library")
    os.environ["INVENTORY_PATH"] = str(data / "inventory.json")
    os.environ["WIRESTUDIO_MCP_TOKEN"] = "upgrade-test"
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from fastapi.testclient import TestClient

    from wirestudio.api.app import create_app
    return TestClient(create_app())


def _ok(response, what: str) -> dict:
    if response.status_code >= 300:
        raise SystemExit(f"{what}: HTTP {response.status_code}: {response.text[:500]}")
    return response.json()


def _user_design(examples: dict[str, dict]) -> dict:
    """garage-motion plus the user component, wired by the release's own
    helpers, so the design is one that release could have saved."""
    from wirestudio.csp.pin_solver import solve_pins
    from wirestudio.designs.seed import add_component_with_connections
    from wirestudio.library import default_library

    design = copy.deepcopy(examples["garage-motion"])
    design["id"] = USER_DESIGN_ID
    design["name"] = "Upgrade test: user component"
    library = default_library()
    add_component_with_connections(design, library, library_id="led_driver_npn",
                                   instance_id_hint="status_led")
    return solve_pins(design, library).design


def seed(data: Path) -> int:
    import wirestudio
    from wirestudio.agent.session import FileSessionStore, SqliteSessionStore

    if data.exists() and any(data.iterdir()):
        raise SystemExit(f"{data} is not empty")
    data.mkdir(parents=True, exist_ok=True)
    examples_dir = Path(wirestudio.__file__).parent / "examples"
    examples = {p.stem: json.loads(p.read_text()) for p in sorted(examples_dir.glob("*.json"))}

    client = _client(data, "files")
    _ok(client.post("/library/components", json={"yaml": COMPONENT.read_text()}), "create user component")
    for library_id, body in INVENTORY.items():
        _ok(client.put(f"/inventory/{library_id}", json=body), f"inventory {library_id}")
    for mpn, body in PARTS.items():
        _ok(client.put(f"/inventory/parts/{mpn}", json=body), f"inventory part {mpn}")
    inventory = _ok(client.get("/inventory"), "list inventory")

    designs = dict(examples)
    designs[USER_DESIGN_ID] = _user_design(examples)
    saved: dict[str, dict] = {}
    rendered: dict[str, str] = {}
    for layout in LAYOUTS:
        client = _client(data, layout)
        for stem, document in designs.items():
            design_id = _ok(client.post("/designs", json={"design": document}), f"save {stem}")["id"]
            saved[design_id] = document
            rendered[design_id] = _ok(client.post("/design/render", json=document), f"render {stem}")["yaml"]
        store = (FileSessionStore(root=data / "sessions") if layout == "files"
                 else SqliteSessionStore(data / "sessions.db"))
        for role, content in SESSION:
            store.append(SESSION_ID, role, content)

    (data / "manifest.json").write_text(json.dumps({
        "from": wirestudio.__version__,
        "designs": saved,
        "rendered": rendered,
        "inventory": inventory,
    }, indent=1))
    print(f"seeded {len(saved)} designs in {len(LAYOUTS)} layouts with wirestudio {wirestudio.__version__}")
    return 0


def verify(data: Path, summary: Path | None = None) -> int:
    import wirestudio
    from wirestudio import sqlite_store
    from wirestudio.agent.session import SqliteSessionStore
    from wirestudio.designs.store import SqliteDesignStore
    from wirestudio.migrate import CURRENT_SCHEMA_VERSION

    manifest = json.loads((data / "manifest.json").read_text())
    failures: list[str] = []
    drift: list[str] = []
    checked = 0
    fresh: dict[str, object] = {}
    for layout in LAYOUTS:
        client = _client(data, layout)
        listed = {d["id"] for d in _ok(client.get("/designs"), f"{layout}: list designs")}
        for design_id in sorted(set(manifest["designs"]) - listed):
            failures.append(f"{layout}: {design_id} not listed")
        for design_id, original in sorted(manifest["designs"].items()):
            got = client.get(f"/designs/{design_id}")
            if got.status_code != 200:
                failures.append(f"{layout}: {design_id} does not load: HTTP {got.status_code} {got.text[:200]}")
                continue
            stored = got.json()
            if stored.get("schema_version") != CURRENT_SCHEMA_VERSION:
                failures.append(f"{layout}: {design_id} loads at schema {stored.get('schema_version')}")
            a = client.post("/design/render", json=stored)
            if design_id not in fresh:
                fresh[design_id] = client.post("/design/render", json=original)
            b = fresh[design_id]
            if a.status_code != 200 or b.status_code != 200:
                failures.append(f"{layout}: {design_id} does not render: HTTP {a.status_code}/{b.status_code} "
                                f"{(a.text if a.status_code != 200 else b.text)[:300]}")
                continue
            a, b = a.json(), b.json()
            if a["yaml"] != b["yaml"] or a["ascii"] != b["ascii"]:
                failures.append(f"{layout}: {design_id} renders differently from its original document")
            if layout == "files" and a["yaml"] != manifest["rendered"].get(design_id):
                drift.append(design_id)
            checked += 1
        session = client.get(f"/agent/sessions/{SESSION_ID}")
        messages = [(m["role"], m["content"]) for m in session.json().get("messages", [])] \
            if session.status_code == 200 else None
        if messages != SESSION:
            failures.append(f"{layout}: session reads back as {messages}")

    client = _client(data, "files")
    if client.get("/library/components/led_driver_npn").status_code != 200:
        failures.append("user component led_driver_npn is not in the library")
    if _ok(client.get("/inventory"), "list inventory") != manifest["inventory"]:
        failures.append("inventory does not read back unchanged")
    for name, store in (("designs.db", SqliteDesignStore), ("sessions.db", SqliteSessionStore)):
        version = sqlite_store.schema_version(data / name)
        if version != len(store.SCHEMA):
            failures.append(f"{name} at schema {version}, expected {len(store.SCHEMA)}")

    lines = [
        f"## Upgrade {manifest['from']} -> checkout ({wirestudio.__version__}): "
        f"{'FAIL' if failures else 'pass'}",
        "",
        f"{checked} design loads rendered across {len(LAYOUTS)} store layouts; "
        f"{len(drift)} of {len(manifest['designs'])} designs render differently "
        f"from {manifest['from']} (generator changes, reported only).",
        "",
    ]
    lines += [f"- {f}" for f in failures]
    text = "\n".join(lines) + "\n"
    print(text)
    if summary:
        with summary.open("a") as f:
            f.write(text)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed", help="write data with the installed (previous) release").add_argument("data", type=Path)
    p_verify = sub.add_parser("verify", help="read it back with the installed (candidate) release")
    p_verify.add_argument("data", type=Path)
    p_verify.add_argument("--summary", type=Path, default=None,
                          help="append the report here (default: $GITHUB_STEP_SUMMARY if set)")
    args = parser.parse_args(argv)
    if args.cmd == "seed":
        return seed(args.data)
    summary = args.summary or (Path(os.environ["GITHUB_STEP_SUMMARY"])
                               if os.environ.get("GITHUB_STEP_SUMMARY") else None)
    return verify(args.data, summary)


if __name__ == "__main__":
    sys.exit(main())
