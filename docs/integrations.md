# Integrations

[← docs index](index.md)

Every integration below is optional and gated by an env var (or, for
plain ESPHome, nothing). The studio runs without any of them — the
corresponding feature is just turned off, and the UI surfaces why.

## Agent (Claude tool-using)

To enable the agent endpoints (`/agent/turn`, `/agent/sessions/{id}`)
and the chat sidebar, export an Anthropic API key before starting the
server:

```sh
export ANTHROPIC_API_KEY=sk-ant-...
python -m wirestudio.api
```

Without a key, `/agent/status` reports `available: false` and the
agent sidebar shows a friendly notice instead of trying to talk.

For a key-free alternative that drives the design tools on your Claude
subscription, see the [MCP server](mcp.md).

## Fleet handoff

**Push to fleet** ships the rendered YAML to a running
[`weirded/fleet-for-esphome`](https://github.com/weirded/fleet-for-esphome)
ha-addon over Bearer-token HTTP; optional `compile: true` enqueues an
OTA build with live log streaming (Server-Sent Events). When the build
finishes, the dialog shows the aggregated compile verdict
(passed / failed / cancelled). **Strict mode** refuses the push when
warn/error compatibility issues remain.

```sh
export FLEET_URL=http://homeassistant.local:8765
export FLEET_TOKEN=$(grep -oP '(?<=token: )\S+' .../addon/secrets.yaml)
python -m wirestudio.api
```

`GET /fleet/status` reports `available: true` when both env vars are
set and the addon answers a probe; otherwise the UI surfaces the
specific reason (URL missing, unauthorized, unreachable).

## Enclosures

Generate a parametric `.scad` shell from the board's mount-hole +
USB-port metadata (no key needed), or search community-uploaded models
on Thingiverse:

```sh
export THINGIVERSE_API_KEY=...
python -m wirestudio.api
```

## KiCad export

`POST /design/kicad/schematic` (and the **Schematic** header button)
emits a SKiDL Python script the user runs locally to produce a
`.kicad_sch` — no LLM in the wire-routing path, fully diffable in git.
`python -m wirestudio.kicad.import --symbol Lib:Symbol` drafts the
`kicad:` block for a library component from a KiCad `.kicad_sym`
library. PCB layout (Freerouting + Gerber export) is on the 1.0+
roadmap.

## MCP server

The design-editing tools are exposed over the Model Context Protocol
at `/mcp` — point Claude Code or Claude Desktop at the daemon and the
model drives the studio on your Claude subscription. See the dedicated
[MCP server guide](mcp.md) for the end-to-end setup.
