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

The generated shell is gate-verified: the [`enclosure-render`](../.github/workflows/enclosure-render.yml)
workflow renders every enclosure-capable board's `.scad` through real
OpenSCAD (`scripts/check_enclosures.py`) and fails the PR unless it
produces a non-empty, manifold (closed, non-self-intersecting) solid.
The geometry is board-driven — it depends on the board's `enclosure:`
block, not the design's components — so the gate walks boards, not
examples. Boards without a clear PCB outline (modules like the ESP-01S)
have no `enclosure:` block and are skipped by design.

## KiCad export

`POST /design/kicad/schematic` (and the **Schematic** header button)
emits a SKiDL Python script the user runs locally to produce a
`.kicad_sch` — no LLM in the wire-routing path, fully diffable in git.
`python -m wirestudio.kicad.import --symbol Lib:Symbol` drafts the
`kicad:` block for a library component from a KiCad `.kicad_sym`
library. PCB layout (Freerouting + Gerber export) is on the 1.0+
roadmap.

The output is gate-verified: the [`kicad-schematic`](../.github/workflows/kicad-schematic.yml)
workflow runs every bundled example's SKiDL script against the pinned
upstream KiCad symbol libraries and asserts it builds a netlist with no
unresolved symbols or pins (`scripts/check_schematics.py`). Parts KiCad
ships no stock symbol for — most sensor/module breakouts — render as
labeled generic headers (`Connector_Generic`) with the part name as the
value, rather than a fictional symbol; everything with a real upstream
symbol (ICs, modules, boards' onboard MCUs) maps to it with a verified
pin map.

## LoRaWAN / ChirpStack

A second generation target (`Design.target: "lorawan"`) for US915 radio
boards — TTGO LoRa32 / T-Beam (SX1276) and Heltec WiFi LoRa 32 V2 (SX1276)
/ V3 (SX1262). The **Flash LoRaWAN firmware** header button (advanced
mode) drives the full loop in the browser:

1. **Build** — `POST /lorawan/compile` builds RadioLib + LoRaWAN_ESP32
   firmware in an in-pod PlatformIO worker, streaming the log over SSE
   and content-addressing the `firmware.bin`.
2. **Flash** — esptool-js writes the image over **WebSerial** (a secure
   context — `https://` or `http://localhost`; tunnel to a remote
   studio). The DevEUI is derived from the chip's eFuse MAC.
3. **Provision** — `POST /lorawan/provision` registers the device in
   ChirpStack with a freshly issued AppKey, flushes its DevNonces, and
   sets a per-payload `decodeUplink` codec on the device profile. The
   firmware's serial prompt is answered automatically; an offline-test
   mode writes throwaway keys so the sensor/OLED loop runs with no gateway.

The uplink payload packing (C++) and the ChirpStack JS codec come from
**one field spec** (`wirestudio/targets/lorawan/codec.py`), so they never
drift. ChirpStack access is configured by `CHIRPSTACK_API_URL` +
`CHIRPSTACK_API_TOKEN` (a UI-generated API token, never the JWT signing
secret); the AppKey is ephemeral and never written to `design.json`.

Heavy deps (`grpcio`, `chirpstack-api`, `platformio`) live behind a
`pip install wirestudio[lorawan]` extra and are lazy-imported, so a plain
install stays light. Background + the live ChirpStack setup are in
[`docs/lorawan/`](lorawan/).

**Limitations (current).** The LoRaWAN target is **US915 sub-band 2 only**
and **ChirpStack only**. Region/sub-band are hard-pinned end to end (the
device firmware's datarate caps, the ChirpStack device profile, and the
provisioning response), so a device built for any other band (EU868, AU915,
AS923, …) silently won't join — multi-region is a tracked backlog item
(safety-sensitive, so it's not half-shipped). The network server is
ChirpStack v4 over gRPC; TTN / other servers aren't wired yet.

## MCP server

The design-editing tools are exposed over the Model Context Protocol
at `/mcp` — point Claude Code or Claude Desktop at the daemon and the
model drives the studio on your Claude subscription. See the dedicated
[MCP server guide](mcp.md) for the end-to-end setup.
