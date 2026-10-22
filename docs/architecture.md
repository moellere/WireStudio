# Design decisions

The decisions every change is held to, with the reasoning that settled
them. The field-by-field document shape is in
[`design-schema.md`](design-schema.md); what is still to land is in
[`roadmap.md`](roadmap.md).

## What the studio is

A device design tool. The user describes a goal or picks parts; the
studio produces firmware configuration (ESPHome YAML, LoRaWAN firmware,
a Tasmota template and the other frameworks' outputs), a wiring
diagram, a schematic and PCB, an enclosure and a BOM, and hands the
device to [fleet-for-esphome](https://github.com/weirded/fleet-for-esphome)
or a bench for build and flash. Its knowledge is ESPHome's own schema
plus a hand-curated electrical library.

## The document

- **`design.json` is the single source of truth.** Versioned and
  JSON-Schema validated. Every artifact (YAML, ASCII, BOM, schematic,
  PCB, enclosure) is derived from it and the library. Nothing is
  parsed back from an artifact into the document, which is also why
  reverse import of existing ESPHome YAML is out of scope.
- **Conversation stays out of the document.** Agent history lives in
  the session store (`sessions/<id>.jsonl` or SQLite), so `design.json`
  stays clean and diffable.
- **Secrets never go in `design.json`.** Designs reference
  fleet-for-esphome's `secrets.yaml` through `!secret name`.
- **Permissive by default.** Electrical and constraint violations land
  in `warnings[]` and generation proceeds. `strict: true` on a design
  turns warn and error entries into a block.
- **Versioned with a migrator.** Older documents load through
  `wirestudio.migrate`, one step per version; a breaking change ships
  only with its step.

## Reasoning layers

1. **The agent** (Claude, tool-using, or any MCP client): elicitation,
   recommendation, explanation. It edits the design through a fixed
   tool surface and nothing else.
2. **The constraint solver**: pin, bus and power-budget assignment.
3. **Generators**: pure functions of `design.json` and the library.

## No LLM in a compile path

The studio is the compile engine for its ESPHome, KiCad, OpenSCAD and
BOM outputs. It owns `design.json` and the deterministic generators. No
LLM sits in a compile or fetch path; MCP is a chat surface over the
design-editing tools only. An LLM interprets natural language into
design edits, proposes library entries from upstream lookups, and
explains things; it never emits an artifact.

The contrast is a server that makes the LLM the schematic engine, every
placement and wire a tool call: the same prompt gives a different
schematic across runs, every edit costs tokens, and the bug lives in a
chat instead of a function. Here the same `design.json` gives the same
`.kicad_sch` every time, diffable in git.

For the same reason the studio reads KiCad's symbol and footprint
libraries, JLCPCB's part search and `kicad-cli` directly, as in-process
importers, instead of going through another MCP server.

## MCP transport and auth

- **Streamable HTTP, mounted at `/mcp`** in the same FastAPI process.
  STDIO would start a second studio process per chat session, with its
  own library and stores racing the daemon over the same files.
- **A bearer token is always required on `/mcp`**, from
  `WIRESTUDIO_MCP_TOKEN` or generated on first start into
  `~/.config/wirestudio/mcp-token` (mode 0600). The shape is a daemon on
  a server and a client on a laptop, so loopback-only without auth
  would break the first use. OAuth 2.1 is for multi-user hosted
  servers and is not planned. Setup is in [`mcp.md`](mcp.md).
- **The embedded agent stays.** `/agent/turn` and `/agent/stream` use
  the operator's Anthropic key and serve users without a Claude
  subscription.

## Three independent axes

`Design.target` selects a **framework**: the firmware or runtime a
device compiles to (`esphome`, `lorawan`; the Tasmota, WLED,
CircuitPython and MicroPython outputs are exports of the same design,
not target values). Two more roles
sit beside it and are chosen separately:

- the **build backend**, artifact to binary or validated config:
  in-pod PlatformIO, a remote bench, or the fleet-for-esphome handoff;
- the **network-server backend**, provision and monitor: for LoRaWAN,
  ChirpStack today, TTN or Helium later with the same firmware and a
  different registration and codec upload.

Keeping the three apart makes a new framework or network server
additive. TTN is not a peer of `esphome` and `lorawan`; it is a
network-server backend under `lorawan`.

LoRaWAN builds stay in the studio's own compile worker
(`targets/lorawan/compile.py`). fleet-for-esphome's worker has
PlatformIO only beneath ESPHome and every job is an ESPHome project;
teaching it a second job type is deferred until in-pod compile is a
bottleneck.

## The library: shared core, per-framework blocks

A `wirestudio/library/components/<id>.yaml` splits into a framework-agnostic core
(`electrical:`, `kicad:`, `params_schema`, `use_cases`, `aliases`) and
one codegen block per framework (`esphome:`, `lorawan:`, `tasmota:`,
…). Selection, the pin solver, enclosure and PCB read only the core, so
select, wire, enclose and lay out are framework-neutral; only generate,
build and flash branch on the target. A component without a block for
a framework is not offered for it, and
`scripts/framework_baseline.yaml` records why.

Library data is derived, never vendored: ESPHome's configuration shape,
PlatformIO's board JSON, vendor pinouts cited by repository and commit.
Every source and its licence is in [`LICENSES.md`](../LICENSES.md); how
the library is sourced is in [`library.md`](library.md#sourcing).
