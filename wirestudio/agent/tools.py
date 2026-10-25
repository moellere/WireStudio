"""Constrained tool surface the agent can call.

Each tool is a pair: a Claude-shaped JSON schema + a Python implementation
that mutates a single `design` dict in place. Tools never call the network,
never load files outside the library, and never execute user-provided code.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any, Callable, Optional

from wirestudio.csp.compatibility import check_pin_compatibility, strict_blockers
from wirestudio.csp.pin_solver import solve_pins as _solve_pins
from wirestudio.designs.seed import add_component_with_connections
from wirestudio.generate.ascii_gen import render_ascii
from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.kicad import generate_skidl
from wirestudio.kicad.fab import fab_status, generate_bom, generate_cpl
from wirestudio.kicad.pcb import PcbUnavailable, generate_kicad_pcb
from wirestudio.library import Library
from wirestudio.library.board_check import check_board_yaml, create_board
from wirestudio.library.check import check_component_yaml, create_component
from wirestudio.model import BUS_PIN_GROUPS, RESERVED_BUS_IDS, Design, generated_bus_id, missing_bus_pins
from wirestudio.recommend.recommender import Constraints, recommend_components
from wirestudio.validate import (
    check_board_flash, check_board_revision, check_electrical, check_esphome_ids, check_net_targets,
    check_part_overrides,
)


# ---------------------------------------------------------------------------
# Tool schemas (Claude wire format)
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_components",
        "description": (
            "Fuzzy-search the component library by name, category, use_case, or "
            "alias. Returns up to 10 matches, best first, each with its "
            "library_id, name, category and match score. Use this before "
            "calling add_component so you never invent a library_id; call "
            "library_detail for a part's pins, params and electrical data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text query."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_boards",
        "description": "List every board in the library with its mcu, chip_variant, framework, and platformio_board.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "set_board",
        "description": (
            "Replace the design's board. Looks up the library board by id and "
            "updates `design.board.{library_id, mcu, framework}`. Does NOT "
            "translate existing pin references (e.g. native GPIO names) -- "
            "those will surface as warnings if the new board can't accept them. "
            "`revision` picks one of the board's hardware revisions when "
            "list_boards shows any (the Heltec V4's PA pin differs by revision)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "library_id": {"type": "string", "description": "Board library id, e.g. esp32-devkitc-v4."},
                "revision": {"type": "string", "description": "A revision the board lists, e.g. 4.3; omit for the board file's wiring."},
            },
            "required": ["library_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_component",
        "description": (
            "Add a component instance to the design. Auto-generates a unique "
            "instance_id (or use `instance_id_hint` to suggest one; a hint that "
            "is taken, or that ESPHome refuses because it names an integration "
            "the design loads, is suffixed and `note` says so), sets "
            "`label` (default = library component name), copies any provided "
            "`params`, and creates one connection per pin in the library "
            "entry. Power pins go to a matching rail by voltage; bus pins "
            "(I2C/SPI/UART/I2S) link to the first matching bus in the design; "
            "GPIO pins get a free board pin, as solve_pins would. Returns the "
            "new instance_id, `assigned` (pin role -> target) and `unbound`: "
            "pins it could not bind, which need add_bus or set_connection."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "library_id": {"type": "string"},
                "label": {"type": "string"},
                "instance_id_hint": {"type": "string"},
                "params": {"type": "object", "additionalProperties": True},
            },
            "required": ["library_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "remove_component",
        "description": (
            "Remove a component instance and all connections originating from "
            "it. Connections that *target* this instance via expander_id are "
            "left as orphans (they surface in the design but have no owner)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string"},
            },
            "required": ["instance_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_param",
        "description": (
            "Set a single param on a component instance. Pass `value: null` to "
            "delete the param entirely. The schema for each component's params "
            "lives in the library entry's `params_schema` -- inspect with "
            "search_components or get_component first if unsure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instance_id": {"type": "string"},
                "key": {"type": "string"},
                "value": {"description": "Any JSON value, or null to delete the key."},
            },
            "required": ["instance_id", "key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_connection",
        "description": (
            "Set the target of a single connection identified by "
            "`component_id` + `pin_role`. The `target` shape mirrors the "
            "design.json schema: rail = {kind:'rail', rail:'5V'}, gpio = "
            "{kind:'gpio', pin:'GPIO13'}, bus = {kind:'bus', bus_id:'i2c0'}, "
            "expander_pin = {kind:'expander_pin', expander_id:'mcp_hub', "
            "number:0, mode:'INPUT_PULLUP', inverted:true}, net = "
            "{kind:'net', component_id:'bridge', net:'out_a'} (a passthrough "
            "connector pin landing on another component's connected role or "
            "subcircuit node)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "component_id": {"type": "string"},
                "pin_role": {"type": "string"},
                "target": {"type": "object"},
            },
            "required": ["component_id", "pin_role", "target"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_strict",
        "description": (
            "Toggle the design's strict mode. When enabled, render and "
            "validate refuse a design that still has warn/error compatibility "
            "entries or design warnings, instead of surfacing them as "
            "non-blocking guidance. Permissive (the default) always generates. "
            "The setting persists on the design."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "description": "True for strict, false for permissive."},
            },
            "required": ["enabled"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_bus",
        "description": (
            "Add a bus to the design. `type` must be one of i2c / spi / uart "
            "/ 1wire / i2s. Other fields depend on the type: i2c needs "
            "sda + scl, spi needs clk + miso? + mosi?, uart needs rx + tx + "
            "baud_rate (+ parity?), 1wire needs pin, i2s needs lrclk + bclk. "
            "ESPHome reserves the ids uart0-uart2 and spi0-spi1; pick a "
            "descriptive id such as co2_uart."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Bus id, e.g. i2c0."},
                "type": {"type": "string", "enum": ["i2c", "spi", "uart", "1wire", "i2s"]},
                "sda": {"type": "string"},
                "scl": {"type": "string"},
                "frequency_hz": {"type": "integer"},
                "miso": {"type": "string"},
                "mosi": {"type": "string"},
                "clk": {"type": "string"},
                "cs": {"type": "string"},
                "rx": {"type": "string"},
                "tx": {"type": "string"},
                "baud_rate": {"type": "integer"},
                "lrclk": {"type": "string"},
                "bclk": {"type": "string"},
                "pin": {"type": "string", "description": "1-wire data pin."},
                "parity": {"type": "string", "enum": ["NONE", "EVEN", "ODD"]},
            },
            "required": ["id", "type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "render",
        "description": (
            "Render the current design to ESPHome YAML + ASCII diagram. "
            "Returns both as strings. Read-only. Use this to verify your "
            "edits before wrapping up the turn."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "validate",
        "description": (
            "Validate the design against the JSON schema and library. "
            "Returns ok=true plus a summary, or ok=false with the failing "
            "field path + message. Read-only."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "recommend",
        "description": (
            "Rank library components against a free-text capability query "
            "(e.g. 'motion detection', 'temperature humidity', 'rfid'). "
            "Returns up to `limit` candidates with their electrical "
            "metadata, an in-examples count (a proxy for battle-tested), "
            "and a one-line rationale per pick. Read-only -- doesn't add "
            "anything to the design. Use this when the user asks for "
            "open-ended component suggestions; for known library_ids use "
            "search_components or add_component directly. Optionally pass "
            "constraints (voltage rail, max peak current, required bus, "
            "excluded categories) to filter before ranking."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25, "default": 10},
                "constraints": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "voltage": {"type": "number", "description": "Rail voltage the part will run on."},
                        "max_current_ma_peak": {"type": "number"},
                        "required_bus": {"type": "string", "enum": ["i2c", "spi", "uart", "1wire", "i2s"]},
                        "excluded_categories": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "solve_pins",
        "description": (
            "Auto-assign every unbound connection: gpio with empty pin -> "
            "a board GPIO matching the library pin's capability; bus with "
            "empty bus_id -> first matching design bus; expander_pin with "
            "empty expander_id -> next free pin on the first io_expander. "
            "Doesn't reassign already-bound pins. Returns the count of "
            "assignments made, any unresolved connections, and any "
            "conflict / current-budget warnings the solver detected. "
            "Mutates the design."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "kicad_schematic",
        "description": (
            "Emit the design's KiCad schematic as a SKiDL Python script. The "
            "caller runs it locally (pip install skidl; python <design>.skidl.py) "
            "to produce a .kicad_sch. Read-only."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "kicad_sch",
        "description": (
            "Write the design's KiCad 8 .kicad_sch: board, peripherals and "
            "subcircuit blocks placed, every pin labelled, flagged or wired. "
            "Returns a summary (size_bytes, symbols, labels, notes); the file "
            "is downloaded via POST /design/kicad/sch. Needs the KiCad symbol "
            "libraries on the server -- returns ok=false, available=false "
            "otherwise. Read-only."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "kicad_pcb",
        "description": (
            "Emit the design's KiCad .kicad_pcb board (footprints placed + nets "
            "bound, no routing). Returns a summary (size_bytes, footprints, nets, "
            "routed); the actual board file is downloaded via the "
            "POST /design/kicad/pcb endpoint. Needs the KiCad libraries on the "
            "server -- returns ok=false, available=false otherwise. Read-only."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "route_pcb",
        "description": (
            "Autoroute the design's .kicad_pcb with Freerouting and return a "
            "summary (routed, segments, vias, cache_key); the routed board file "
            "is downloaded via GET /design/kicad/route/{cache_key}. Results are "
            "cached, so re-routing an unchanged design is instant. Needs the "
            "route toolchain on the server (pcbnew + java + the Freerouting "
            "jar) -- returns ok=false, available=false otherwise. Can take a "
            "minute or two on a dense board. The summary carries KiCad's DRC of "
            "the routed board. Optional via_costs (higher trades vias for "
            "longer tracks) and keepouts ({x, y, w, h} rectangles in the "
            "emitted board's millimetres). Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "via_costs": {"type": "integer", "minimum": 0, "maximum": 10000},
                "keepouts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "number"}, "y": {"type": "number"},
                            "w": {"type": "number"}, "h": {"type": "number"},
                            "tracks": {"type": "boolean"}, "vias": {"type": "boolean"},
                        },
                        "required": ["x", "y", "w", "h"],
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "fab_status",
        "description": (
            "What fab outputs the server can produce: BOM is always available, "
            "CPL needs the footprint libraries, Gerbers need kicad-cli, routed "
            "Gerbers also need the Freerouting toolchain (`route`). Read-only."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "fab_bom",
        "description": (
            "Emit the design's JLCPCB BOM (CSV; grouped by part). Pure -- always "
            "works. Returns the CSV text + row count. Read-only."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "fab_cpl",
        "description": (
            "Emit the design's JLCPCB CPL (pick-and-place, CSV); positions match "
            "the .kicad_pcb. Needs the footprint libraries -- returns ok=false, "
            "available=false otherwise. Read-only."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "library_detail",
        "description": (
            "Fetch the full library card for one component or board by id. "
            "Returns electrical metadata, params_schema, ESPHome template, "
            "kicad block, and pin definitions -- everything the system-prompt "
            "index leaves out. Use it once you've picked an id from the index "
            "or search_components. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "library_id": {
                    "type": "string",
                    "description": "The component or board id to look up.",
                },
                "kind": {
                    "type": "string",
                    "enum": ["component", "board"],
                    "description": "Which catalog to look in. Defaults to 'component'.",
                },
            },
            "required": ["library_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "set_part_override",
        "description": (
            "Accept a drawer substitution for one subcircuit part: set "
            "part_overrides['<component id>.<part id>'] to an MPN so the BOM, "
            "CPL and schematic print that part instead of the library's. Only "
            "the value changes; symbol and footprint stay, so the substitute "
            "must be the same package. Use the keys and substitutes an "
            "inventory_check line reports. Pass an empty mpn to remove."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "'<component id>.<part id>' from inventory_check `keys`."},
                "mpn": {"type": "string", "description": "Substitute MPN, or '' to remove the override."},
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "component_check",
        "description": (
            "Check a draft library component (full YAML text, same shape as "
            "wirestudio/library/components/*.yaml) before saving it: the file "
            "validates, subcircuit nets hang together, the ESPHome template "
            "renders, and -- when KiCad libraries are installed -- every symbol, "
            "pin name and footprint exists. Returns errors, warnings, what could "
            "not be verified here, and what is never checked (nothing is "
            "simulated). Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "yaml": {"type": "string", "description": "The component YAML text."},
            },
            "required": ["yaml"],
            "additionalProperties": False,
        },
    },
    {
        "name": "component_create",
        "description": (
            "Run component_check and, if it passes, save the YAML into the user "
            "library so the component can be added to designs. Refuses a bundled "
            "id; refuses an existing user id unless overwrite is true. Relay the "
            "warnings and not_checked list to the user: this proves the file is "
            "well-formed and its parts exist, not that the circuit works."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "yaml": {"type": "string", "description": "The component YAML text."},
                "overwrite": {
                    "type": "boolean",
                    "description": "Replace an existing user-library component with the same id.",
                },
            },
            "required": ["yaml"],
            "additionalProperties": False,
        },
    },
    {
        "name": "component_delete",
        "description": (
            "Remove a component from the user library. Refuses a bundled id. "
            "Designs that reference the id stop rendering until it is recreated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "library_id": {"type": "string", "description": "The user component id to remove."},
            },
            "required": ["library_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "board_check",
        "description": (
            "Check a draft library board (full YAML text, same shape as "
            "wirestudio/library/boards/*.yaml) before saving it: the file "
            "validates, every pin a default bus, onboard peripheral or radio "
            "names is in gpio_capabilities, the KiCad symbol has the pins "
            "kicad.pin_map binds, the enclosure's ports and holes sit on the "
            "PCB, and the onboard peripherals render to ESPHome YAML. Returns "
            "errors, warnings, what could not be verified here, and what is "
            "never checked (the pinout against the datasheet). Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "yaml": {"type": "string", "description": "The board YAML text."},
            },
            "required": ["yaml"],
            "additionalProperties": False,
        },
    },
    {
        "name": "board_create",
        "description": (
            "Run board_check and, if it passes, save the YAML into the user "
            "library so designs can target the board. Refuses a bundled id; "
            "refuses an existing user id unless overwrite is true. Relay the "
            "warnings and not_checked list to the user."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "yaml": {"type": "string", "description": "The board YAML text."},
                "overwrite": {
                    "type": "boolean",
                    "description": "Replace an existing user-library board with the same id.",
                },
            },
            "required": ["yaml"],
            "additionalProperties": False,
        },
    },
    {
        "name": "board_delete",
        "description": (
            "Remove a board from the user library. Refuses a bundled id. "
            "Designs on the board stop rendering until it is recreated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "library_id": {"type": "string", "description": "The user board id to remove."},
            },
            "required": ["library_id"],
            "additionalProperties": False,
        },
    },
]


# ---------------------------------------------------------------------------
# Implementations: each takes (design, library, **input) and returns a value
# the agent should see as the tool result. Mutates `design` in place when
# applicable.
# ---------------------------------------------------------------------------


def _search_score(c, q: str) -> int:
    """How well a component matches a query: an exact id or alias first,
    then a hit in the id, an alias, the name, a use case, the category."""
    ident, aliases = c.id.lower(), [a.lower() for a in c.aliases]
    if q == ident:
        return 100
    if q in aliases:
        return 90
    if q in ident:
        return 70
    if any(q in a for a in aliases):
        return 60
    if q in c.name.lower():
        return 50
    if any(q in u.lower() for u in c.use_cases):
        return 30
    if q in c.category.lower():
        return 10
    return 0


def _query_score(c, q: str) -> int:
    """The whole query's score, or else the sum over its words -- "remote
    receiver 433 rf" matches no single field, but each word matches some."""
    whole = _search_score(c, q)
    words = q.split()
    if whole or len(words) < 2:
        return whole
    return sum(_search_score(c, w) for w in words)


def _run_search_components(design: dict, library: Library, *, query: str) -> dict:
    q = query.strip().lower()
    scored = [(_query_score(c, q), c) for c in library.list_components()]
    hits = sorted(((s, c) for s, c in scored if s), key=lambda sc: (-sc[0], sc[1].id))
    return {
        "matches": [
            {"library_id": c.id, "name": c.name, "category": c.category, "score": s}
            for s, c in hits[:10]
        ],
        "total": len(hits),
    }


def _run_list_boards(design: dict, library: Library) -> dict:
    return {
        "boards": [
            {
                "library_id": b.id,
                "name": b.name,
                "mcu": b.mcu,
                "chip_variant": b.chip_variant,
                "framework": b.framework,
                "platformio_board": b.platformio_board,
                "flash_size_mb": b.flash_size_mb,
                "revisions": sorted(b.revisions),
                "source": library.board_source(b.id),
            }
            for b in library.list_boards()
        ]
    }


def _run_set_board(design: dict, library: Library, *, library_id: str, revision: str | None = None) -> dict:
    board = library.board(library_id)  # raises FileNotFoundError if unknown
    if revision is not None and revision not in board.revisions:
        raise ValueError(
            f"board {board.id!r} has no revision {revision!r}; "
            f"it lists {', '.join(sorted(board.revisions)) or 'none'}"
        )
    kept = dict(design.get("board") or {})
    # A flash size measured on the old board says nothing about the new one,
    # and carrying it over is the direction that boot-loops. A revision
    # names the old board's wiring.
    kept.pop("flash_size_mb", None)
    kept.pop("revision", None)
    design["board"] = {
        **kept,
        "library_id": board.id,
        "mcu": board.mcu,
        "framework": board.framework,
        **({"revision": revision} if revision is not None else {}),
    }
    return {"ok": True, "board": {"library_id": board.id, "mcu": board.mcu, "revision": revision}}


def _run_add_component(
    design: dict, library: Library, *,
    library_id: str,
    label: str | None = None,
    instance_id_hint: str | None = None,
    params: dict | None = None,
) -> dict:
    before = {b.get("id") for b in design.get("buses") or []}
    ids_before = {c.get("id") for c in design.get("components") or []}
    instance_id, _ = add_component_with_connections(
        design, library,
        library_id=library_id,
        label=label,
        instance_id_hint=instance_id_hint,
        params=params,
    )
    # A bus seeded without pins (no board default for its type) cannot be
    # filled in from here -- add_bus only adds -- so drop it and let the
    # pin report as unbound; add_bus then solve_pins finishes the part.
    empty = {b["id"] for b in design.get("buses") or []
             if b.get("id") not in before and missing_bus_pins(b)}
    if empty:
        design["buses"] = [b for b in design["buses"] if b.get("id") not in empty]
        for c in design.get("connections") or []:
            if c["target"].get("kind") == "bus" and c["target"].get("bus_id") in empty:
                c["target"] = {"kind": "bus", "bus_id": ""}
    # Bind the new part's pins the way solve_pins would, without touching
    # anything the design already had unbound.
    solved = _solve_pins(design, library)
    targets = {c["pin_role"]: c["target"] for c in solved.design.get("connections", [])
               if c.get("component_id") == instance_id}
    for c in design.get("connections") or []:
        if c.get("component_id") == instance_id and c["pin_role"] in targets:
            c["target"] = targets[c["pin_role"]]
    out: dict = {"ok": True, "instance_id": instance_id}
    if instance_id_hint and instance_id != instance_id_hint:
        why = ("is already in use" if instance_id_hint in ids_before else
               "names an ESPHome integration this design loads, which ESPHome refuses as an id")
        out["note"] = f"instance_id_hint {instance_id_hint!r} {why}; the new part is {instance_id!r}"
    assigned = {a.pin_role: a.new_target for a in solved.assigned if a.component_id == instance_id}
    if assigned:
        out["assigned"] = assigned
    unbound = [w.text for w in solved.unresolved if w.text.startswith(f"{instance_id}.")]
    if unbound:
        out["unbound"] = unbound
    return out


def _run_remove_component(design: dict, library: Library, *, instance_id: str) -> dict:
    components = design.get("components") or []
    if not any(c["id"] == instance_id for c in components):
        return {"ok": False, "error": f"unknown instance_id '{instance_id}'"}
    design["components"] = [c for c in components if c["id"] != instance_id]
    design["connections"] = [
        c for c in (design.get("connections") or []) if c.get("component_id") != instance_id
    ]
    return {"ok": True}


def _run_set_param(
    design: dict, library: Library, *, instance_id: str, key: str, value: Any = None,
) -> dict:
    components = design.get("components") or []
    target = next((c for c in components if c["id"] == instance_id), None)
    if target is None:
        return {"ok": False, "error": f"unknown instance_id '{instance_id}'"}
    params = target.setdefault("params", {})
    if value is None:
        params.pop(key, None)
        return {"ok": True, "deleted": key}
    params[key] = value
    return {"ok": True, "set": {key: value}}


def _run_set_connection(
    design: dict, library: Library, *, component_id: str, pin_role: str, target: dict,
) -> dict:
    connections = design.get("connections") or []
    for c in connections:
        if c.get("component_id") == component_id and c.get("pin_role") == pin_role:
            c["target"] = target
            return {"ok": True, "updated": True}
    # No existing connection -- append a new one.
    connections.append({"component_id": component_id, "pin_role": pin_role, "target": target})
    design["connections"] = connections
    return {"ok": True, "created": True}


def _run_set_strict(design: dict, library: Library, *, enabled: bool) -> dict:
    design["strict"] = enabled
    return {"ok": True, "strict": enabled}


_BUS_PIN_KEYS = tuple(k for groups in BUS_PIN_GROUPS.values() for group in groups for k in group) + ("cs",)


def _run_add_bus(design: dict, library: Library, **fields: Any) -> dict:
    buses = design.setdefault("buses", [])
    if fields["id"] in RESERVED_BUS_IDS:
        return {"ok": False, "error": f"bus id '{fields['id']}' is reserved by ESPHome; "
                                      f"pick another, e.g. '{generated_bus_id(fields.get('type', 'bus'), 0)}'"}
    if any(b.get("id") == fields["id"] for b in buses):
        return {"ok": False, "error": f"bus id '{fields['id']}' already exists"}

    # User-provided fields win; whatever's missing is filled from the
    # board's default_buses[type] map (e.g. for esp32-devkitc-v4,
    # i2c default = {sda: GPIO21, scl: GPIO22}). The LLM almost never
    # remembers the right pins for every board variant, and ESPHome
    # refuses to compile an I2C bus with null sda/scl, so the previous
    # behavior of "store exactly what was passed" silently produced
    # uncompilable designs.
    bus_type = fields.get("type")
    defaults: dict = {}
    board_id = (design.get("board") or {}).get("library_id")
    if board_id and bus_type:
        try:
            board = library.board(board_id)
        except FileNotFoundError:
            board = None
        if board is not None:
            defaults = (getattr(board, "default_buses", None) or {}).get(bus_type, {}) or {}

    new_bus: dict[str, Any] = {**defaults}
    for k, v in fields.items():
        if v is not None:
            new_bus[k] = v
    wanted = {str(new_bus[k]) for k in _BUS_PIN_KEYS if new_bus.get(k)}
    for other in buses:
        shared = sorted(wanted & {str(other[k]) for k in _BUS_PIN_KEYS if other.get(k)})
        if shared:
            return {"ok": False, "existing_bus_id": other.get("id"),
                    "error": f"bus '{other.get('id')}' already runs on {', '.join(shared)}; "
                             "connect the part to it instead of adding another bus"}
    buses.append(new_bus)
    applied_defaults = sorted(k for k, v in defaults.items() if fields.get(k) is None)
    out: dict[str, Any] = {"ok": True}
    if applied_defaults:
        out["board_defaults_applied"] = applied_defaults
    return out


def _run_render(design: dict, library: Library) -> dict:
    try:
        d = Design.model_validate(design)
    except Exception as e:
        return {"ok": False, "error": f"design failed validation: {e}"}
    if d.strict:
        blockers = strict_blockers(design, library)
        if blockers:
            return {
                "ok": False,
                "error": (
                    f"strict mode blocked the render: {len(blockers)} issue"
                    f"{'s' if len(blockers) != 1 else ''} need attention"
                ),
                "strict_blocked": True,
                "blockers": [asdict(b) for b in blockers],
            }
    try:
        return {"ok": True, "yaml": render_yaml(d, library), "ascii": render_ascii(d, library)}
    except (FileNotFoundError, ValueError) as e:
        return {"ok": False, "error": str(e)}


def _run_recommend(
    design: dict, library: Library, *,
    query: str,
    limit: int = 10,
    constraints: dict | None = None,
) -> dict:
    cobj = Constraints(**(constraints or {}))
    results = recommend_components(library, query, constraints=cobj, limit=limit)
    return {
        "ok": True,
        "query": query,
        "matches": [
            {
                "library_id": r.library_id,
                "name": r.name,
                "category": r.category,
                "use_cases": r.use_cases,
                "required_components": r.required_components,
                "current_ma_typical": r.current_ma_typical,
                "current_ma_peak": r.current_ma_peak,
                "vcc_min": r.vcc_min,
                "vcc_max": r.vcc_max,
                "score": r.score,
                "in_examples": r.in_examples,
                "rationale": r.rationale,
                "notes": r.notes,
            }
            for r in results
        ],
    }


def _run_solve_pins(design: dict, library: Library) -> dict:
    result = _solve_pins(design, library)
    # Mutate the caller's dict in place to mirror the result design.
    design.clear()
    design.update(result.design)
    return {
        "ok": True,
        "assigned": [
            {
                "component_id": a.component_id,
                "pin_role": a.pin_role,
                "old_target": a.old_target,
                "new_target": a.new_target,
            }
            for a in result.assigned
        ],
        "unresolved": [{"code": w.code, "text": w.text} for w in result.unresolved],
        "warnings": [{"level": w.level, "code": w.code, "text": w.text} for w in result.warnings],
    }


def _run_validate(design: dict, library: Library) -> dict:
    try:
        d = Design.model_validate(design)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    # Try a render to surface unrenderable-but-validating designs (e.g. missing bus).
    try:
        render_yaml(d, library)
    except (FileNotFoundError, ValueError) as e:
        return {"ok": False, "error": str(e), "schema_ok": True}
    compat = check_pin_compatibility(design, library)
    board_warnings = (check_board_flash(d, library) + check_board_revision(d, library)
                      + check_part_overrides(d, library) + check_esphome_ids(d, library)
                      + check_electrical(d, library) + check_net_targets(d, library))
    # Strict blockers are surfaced regardless of mode so the caller can see
    # what *would* block; in strict mode their presence also flips ok=False.
    blockers = strict_blockers(design, library)
    return {
        "ok": not (d.strict and blockers),
        "strict": d.strict,
        "design_id": d.id,
        "name": d.name,
        "components": len(d.components),
        "buses": len(d.buses),
        "connections": len(d.connections),
        "warnings": [w.model_dump() for w in list(d.warnings) + board_warnings],
        "compatibility_warnings": [
            {
                "severity": w.severity, "code": w.code, "pin": w.pin,
                "component_id": w.component_id, "pin_role": w.pin_role,
                "message": w.message,
            }
            for w in compat
        ],
        "blockers": [asdict(b) for b in blockers],
    }


def _run_kicad_schematic(design: dict, library: Library) -> dict:
    try:
        d = Design.model_validate(design)
    except Exception as e:
        return {"ok": False, "error": f"design failed validation: {e}"}
    try:
        return {"ok": True, "script": generate_skidl(d, library)}
    except (FileNotFoundError, ValueError) as e:
        return {"ok": False, "error": str(e)}


def _run_kicad_sch(design: dict, library: Library) -> dict:
    from wirestudio.kicad.schematic import SchematicUnavailable, build_sheet, render_sheet

    try:
        d = Design.model_validate(design)
    except Exception as e:
        return {"ok": False, "error": f"design failed validation: {e}"}
    try:
        sheet = build_sheet(d, library)
    except SchematicUnavailable as e:
        return {"ok": False, "available": False, "error": str(e)}
    except (FileNotFoundError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    text = render_sheet(sheet)
    return {
        "ok": True,
        "available": True,
        "size_bytes": len(text.encode()),
        "symbols": sum(1 for s in sheet.symbols if not s.power),
        "labels": len(sheet.labels),
        "wires": len(sheet.wires),
        "notes": sheet.notes,
    }


def _run_kicad_pcb(design: dict, library: Library) -> dict:
    """Return a summary of the emitted board, not the megabyte board text."""
    try:
        d = Design.model_validate(design)
    except Exception as e:
        return {"ok": False, "error": f"design failed validation: {e}"}
    try:
        board = generate_kicad_pcb(d, library)
    except PcbUnavailable as e:
        return {"ok": False, "available": False, "error": str(e)}
    except (FileNotFoundError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "size_bytes": len(board),
        "footprints": board.count('(footprint "'),
        "nets": len(re.findall(r'^\t\(net \d+ "', board, re.M)),
        "routed": bool(re.search(r"\((?:segment|via)\b", board)),
    }


def _run_route_pcb(
    design: dict, library: Library, *,
    via_costs: Optional[int] = None, keepouts: Optional[list[dict]] = None,
) -> dict:
    """Route and return a summary, not the board text (that's the artifact
    endpoint's job). A cache hit makes repeat calls instant."""
    from wirestudio.kicad.route import (
        Keepout,
        RouteError,
        RouteParams,
        RouteUnavailable,
        route_board,
        route_cache_key,
        routed_drc,
    )

    try:
        d = Design.model_validate(design)
    except Exception as e:
        return {"ok": False, "error": f"design failed validation: {e}"}
    try:
        params = RouteParams(via_costs=via_costs, keepouts=tuple(Keepout(**k) for k in keepouts or []))
    except (TypeError, ValueError) as e:
        return {"ok": False, "error": f"bad route parameters: {e}"}
    try:
        board = generate_kicad_pcb(d, library)
    except PcbUnavailable as e:
        return {"ok": False, "available": False, "error": str(e)}
    except (FileNotFoundError, ValueError) as e:
        return {"ok": False, "error": str(e)}
    try:
        routed = route_board(board, params)
    except RouteUnavailable as e:
        return {"ok": False, "available": False, "error": str(e)}
    except RouteError as e:
        return {"ok": False, "error": str(e)[-2000:]}
    key = route_cache_key(board, params)
    return {
        "ok": True,
        "routed": True,
        "segments": len(re.findall(r"^\t\(segment$", routed, re.M)),
        "vias": len(re.findall(r"^\t\(via$", routed, re.M)),
        "cache_key": key,
        "drc": _drc_brief(routed_drc(key)),
    }


def _drc_brief(summary: Optional[dict]) -> Optional[dict]:
    """The routed DRC without every violation's items: counts per type,
    and the first descriptions of anything not waived."""
    if not summary or "error" in summary:
        return summary
    return {
        **{k: summary[k] for k in ("ok", "unconnected", "errors", "warnings", "waived")},
        "groups": [
            {"type": g["type"], "severity": g["severity"], "count": g["count"], "waived": g["waived"],
             **({} if g["waived"] else {"examples": [v["description"] for v in g["violations"][:3]]})}
            for g in summary["groups"]
        ],
    }


def _run_fab_status(_design: dict, _library: Library) -> dict:
    """Server-side capability probe; the design/library are ignored."""
    return fab_status()


def _run_fab_bom(design: dict, library: Library) -> dict:
    try:
        d = Design.model_validate(design)
    except Exception as e:
        return {"ok": False, "error": f"design failed validation: {e}"}
    csv_text = generate_bom(d, library)
    return {"ok": True, "csv": csv_text, "rows": max(csv_text.count("\n") - 1, 0)}


def _run_library_detail(
    _design: dict, library: Library, *, library_id: str, kind: str = "component",
) -> dict:
    """Full library card on demand -- the heavy data the system-prompt index
    leaves out. design is ignored (library lookup is global)."""
    try:
        if kind == "board":
            entry = library.board(library_id)
        elif kind == "component":
            entry = library.component(library_id)
        else:
            return {"ok": False, "error": f"kind must be 'component' or 'board', got {kind!r}"}
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "kind": kind, "library_id": library_id, "detail": entry.model_dump()}


def _run_set_part_override(design: dict, library: Library, *, key: str, mpn: str = "") -> dict:
    component_id, _, part_id = key.partition(".")
    comp = next((c for c in design.get("components") or [] if c["id"] == component_id), None)
    if comp is None:
        return {"ok": False, "error": f"unknown component '{component_id}' in key {key!r}"}
    try:
        sub = library.component(comp["library_id"]).subcircuit
    except FileNotFoundError as e:
        return {"ok": False, "error": str(e)}
    part = next((p for p in (sub.parts if sub else []) if p.id == part_id), None)
    if part is None:
        return {"ok": False, "error": f"'{comp['library_id']}' has no subcircuit part '{part_id}'"}
    overrides = design.setdefault("part_overrides", {})
    if not mpn:
        overrides.pop(key, None)
        return {"ok": True, "removed": key, "value": part.kicad.value}
    overrides[key] = mpn
    return {"ok": True, "set": {key: mpn}, "substituted_for": part.kicad.value}


def _run_component_delete(_design: dict, library: Library, *, library_id: str) -> dict:
    try:
        library.delete_component(library_id)
    except (PermissionError, FileNotFoundError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "deleted": library_id}


def _run_component_check(_design: dict, library: Library, *, yaml: str) -> dict:
    return check_component_yaml(yaml, library).as_dict()


def _run_component_create(
    _design: dict, library: Library, *, yaml: str, overwrite: bool = False,
) -> dict:
    return create_component(yaml, library, overwrite=overwrite).as_dict()


def _run_board_delete(_design: dict, library: Library, *, library_id: str) -> dict:
    try:
        library.delete_board(library_id)
    except (PermissionError, FileNotFoundError) as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "deleted": library_id}


def _run_board_check(_design: dict, library: Library, *, yaml: str) -> dict:
    return check_board_yaml(yaml, library).as_dict()


def _run_board_create(
    _design: dict, library: Library, *, yaml: str, overwrite: bool = False,
) -> dict:
    return create_board(yaml, library, overwrite=overwrite).as_dict()


def _run_fab_cpl(design: dict, library: Library) -> dict:
    try:
        d = Design.model_validate(design)
    except Exception as e:
        return {"ok": False, "error": f"design failed validation: {e}"}
    try:
        csv_text = generate_cpl(d, library)
    except PcbUnavailable as e:
        return {"ok": False, "available": False, "error": str(e)}
    return {"ok": True, "csv": csv_text, "rows": max(csv_text.count("\n") - 1, 0)}


TOOL_HANDLERS: dict[str, Callable[..., Any]] = {
    "search_components": _run_search_components,
    "list_boards": _run_list_boards,
    "set_board": _run_set_board,
    "add_component": _run_add_component,
    "remove_component": _run_remove_component,
    "set_param": _run_set_param,
    "set_connection": _run_set_connection,
    "set_strict": _run_set_strict,
    "add_bus": _run_add_bus,
    "render": _run_render,
    "validate": _run_validate,
    "recommend": _run_recommend,
    "solve_pins": _run_solve_pins,
    "kicad_schematic": _run_kicad_schematic,
    "kicad_sch": _run_kicad_sch,
    "kicad_pcb": _run_kicad_pcb,
    "route_pcb": _run_route_pcb,
    "fab_status": _run_fab_status,
    "fab_bom": _run_fab_bom,
    "fab_cpl": _run_fab_cpl,
    "library_detail": _run_library_detail,
    "set_part_override": _run_set_part_override,
    "component_check": _run_component_check,
    "component_create": _run_component_create,
    "component_delete": _run_component_delete,
    "board_check": _run_board_check,
    "board_create": _run_board_create,
    "board_delete": _run_board_delete,
}


def execute_tool(name: str, tool_input: dict, design: dict, library: Library) -> tuple[str, bool]:
    """Dispatch a single tool call. Returns (json_str_for_claude, is_error).

    `design` is mutated in place by mutating tools. Errors (unknown tool,
    library miss, validation failure) come back as `is_error=True` so the
    model knows to recover or apologize instead of pressing on.
    """
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return json.dumps({"error": f"unknown tool: {name}"}), True
    try:
        result = handler(design, library, **tool_input)
    except (FileNotFoundError, ValueError) as e:
        return json.dumps({"error": str(e)}), True
    except TypeError as e:
        return json.dumps({"error": f"bad arguments: {e}"}), True
    return json.dumps(result, default=str), False
