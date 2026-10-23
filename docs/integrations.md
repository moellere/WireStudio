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

### Eval harness

`wirestudio/agent/eval_tasks.yaml` is a fixed list of natural-language
asks against the bundled examples, each with a tool-call budget and a
reference solution. `python -m wirestudio.agent.eval` runs them against
the agent (the key above; `--model` to pick another model) and scores
the design it hands back on three things: it validates (every pin bound
and on the board, no pin shared, every bus complete, and `esphome
config` accepts the render), the task's `expect` block holds, and the
turn stayed within budget. A task passes when all three hold. The run
prints a row per task, writes a markdown summary (`--summary`, or the
job summary under GitHub Actions) and `--out results.json`, and exits 1
when fewer than `gate.min_pass` tasks pass.

`--solutions` replays each task's reference tool calls instead of
calling the model, which proves the task is solvable within its budget
and needs no key. `--tasks a,b` runs a subset; `--no-esphome` skips the
ESPHome check for a quick local pass.

`--driver claude-code` sends each ask through Claude Code instead of the
embedded agent: the studio serves its MCP endpoint on a local port,
`claude -p` connects with every built-in tool off and only the
wirestudio tools allowed, and the design those tools leave in the store
is scored the same way. It needs the `claude` CLI and either
`CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`, which bills a
Claude subscription) or `ANTHROPIC_API_KEY`. It is held to
`gate.claude_code_min_pass`.

The `agent-eval` workflow runs the replay on every PR that touches the
agent, and nightly runs the Claude Code driver with the
`CLAUDE_CODE_OAUTH_TOKEN` repository secret and the embedded agent with
`ANTHROPIC_API_KEY` when that secret is set.

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

## ESPHome dashboard

The other compile path. **Push to ESPHome dashboard** writes the
rendered YAML as `<device>.yaml` to a running
[ESPHome Device Builder](https://github.com/esphome/device-builder) --
the dashboard that ships with ESPHome 2026.6 and later, as the Home
Assistant add-on with its port exposed, the `ghcr.io/esphome/esphome`
image, or `esphome-device-builder` from PyPI -- and starts a compile
there; the builder dispatches to its own build workers, the studio only
submits. The log streams back over the builder's WebSocket API and the
dialog shows the same passed / failed verdict the fleet path does. The
push dialog offers both paths when both are configured and defaults to
whichever one is.

```sh
export ESPHOME_DASHBOARD_URL=http://device-builder:6052
# only if the builder has a username/password set:
export ESPHOME_DASHBOARD_USERNAME=... ESPHOME_DASHBOARD_PASSWORD=...
python -m wirestudio.api
```

A builder started with `ESPHOME_USERNAME` / `ESPHOME_PASSWORD` (for
example `docker run -e ESPHOME_USERNAME=... -e ESPHOME_PASSWORD=...
ghcr.io/esphome/esphome dashboard /config`) wants the same pair in
`ESPHOME_DASHBOARD_USERNAME` / `_PASSWORD`. The URL is the builder's
own, with no path: the studio connects to `/ws` under it.

`GET /esphome/status` probes `devices/list`; `POST /esphome/push` returns
a studio-local `run_id` that `GET /esphome/jobs/{run_id}`,
`.../log`, `.../log/stream` (SSE) and `.../firmware` poll -- the same
shapes as the fleet routes, so a client can follow either. Run ids do
not survive a studio restart: the builder keeps compiling, and a
re-push starts a fresh run. A builder behind HA ingress alone (no
exposed port) is not reachable this way, because ingress needs an HA
session.

The legacy Tornado dashboard (`/login`, `/edit`, `/download.bin`) was
removed in ESPHome 2026.10 and the studio no longer speaks it; the
legacy `/compile` route is not used either.

The wire format is validated against ESPHome 2026.10.0 with Device
Builder 1.25.0, open and password-protected. Everything but the image
download is one WebSocket at `/ws`: the server announces
`requires_auth` on connect and takes `auth/login` in band;
`devices/list` names configs by `configuration`; `devices/create` with
`file_content` and `overwrite` writes the YAML as `<name>.yaml`;
`firmware/compile` returns a job and `firmware/follow_job` streams its
`output` lines and a final `result` (`status`, `exit_code`);
`firmware/get_binaries` lists the artifacts with a `type` tag (ESP32
builds ship `factory` and `ota` images, ESP8266 a single `bin`), and a
single-use `firmware/download_token` is redeemed with
`GET /api/firmware/download?token=`. Every command and path is named in
one place (`wirestudio/esphome_dashboard/__init__.py`).

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

### Printing it through print-warden

With a [print-warden](https://github.com/moellere/print-warden) reachable,
the Enclosure dialog's **Print** tab (and the `print_enclosure` MCP tool,
`POST /design/enclosure/print`) hands the same shell straight to the
printer: wirestudio uploads the `.scad` to the warden, which renders it
(fit tunables become OpenSCAD `-D` overrides), slices it for the chosen
printer or location, runs its bed/temperature checks and queues the job.

```sh
export PRINT_WARDEN_URL=http://10.0.0.29:8710
export PRINT_WARDEN_TOKEN=...   # only if the warden has PRINT_WARDEN_TOKEN set
python -m wirestudio.api
```

The warden's trust gradient is kept intact: wirestudio speaks the warden's
own MCP surface (`list_printers`, `submit_job`, `job_status`) and never
calls a start. The job is offered to the operator's phone, or starts under
the warden's `auto_start` policy; `GET /enclosure/print/jobs/{id}` and
`print_job_status` show its state and the start-policy verdict.
`GET /enclosure/print/status` lists the printers and locations usable as
`where`.

## KiCad export

`POST /design/kicad/sch` (and the **Download schematic** button) writes
the design as a KiCad 8 `.kicad_sch` the studio draws itself: the board
on the left with every pin labelled, flagged no-connect or on a rail
symbol; the peripherals in columns beside it; and each subcircuit as a
block. A subcircuit whose library entry carries a `schematic:` layout
(part placements, wire polylines and ports, in 1.27 mm grid units) is
drawn as a circuit — the MOSFET H-bridge comes out as two legs with the
motor between them — and one without is stacked with labels. A port on
one of a layout's internal nodes is drawn only when something outside
the block uses that net (a connector pin with a `net` target); a shared
node the layout has no port for is labelled at one of its pins. Symbols
are embedded from the pinned KiCad library, so the file opens with no
library setup; output is deterministic down to the UUIDs, so a diff
means the design changed. `/design/kicad/render` and `/design/kicad/erc`
run kicad-cli on this file. `GET /design/kicad/sch/status` says whether
the server has the symbol libraries it needs (`KICAD8_SYMBOL_DIR`).

`POST /design/kicad/schematic` (and the **Download script** button)
still emits the SKiDL Python script for the same design — the path that
needs no libraries on the server and the one the netlist gate runs.
`python -m wirestudio.kicad.import --symbol Lib:Symbol` drafts the
`kicad:` block for a library component from a KiCad `.kicad_sym`
library.

PCB layout and routing are server-side: `POST /design/kicad/pcb` emits
the placed board, `POST /design/kicad/route` autoroutes it with
Freerouting (SSE log stream; fetch the routed board from
`GET /design/kicad/route/{cache_key}`), and the fab endpoints accept
`?route=true` to route before exporting Gerbers. The route step needs
pcbnew, a JRE, and the Freerouting jar on the server — set
`WIRESTUDIO_PCBNEW_PYTHON`, `WIRESTUDIO_JAVA`, and
`WIRESTUDIO_FREEROUTING_JAR`, or run the `-pcb` image variant which
bakes all three in. `GET /design/kicad/route/status` reports what's
missing.

The output is gate-verified three ways. The
[`kicad-schematic`](../.github/workflows/kicad-schematic.yml) workflow
runs every bundled example's SKiDL script against the pinned upstream
KiCad symbol libraries and asserts it builds a netlist with no
unresolved symbols or pins (`scripts/check_schematics.py`). The
[`kicad-render`](../.github/workflows/kicad-render.yml) workflow has
kicad-cli read the netlist back from every written sheet's geometry and
compares it with the design's (`scripts/check_sch.py`: a wire that
misses a pin or a missing junction shows up as a split net), then runs
ERC against `scripts/erc_baseline.yaml`. Parts KiCad ships no stock
symbol for — most sensor/module breakouts — render as labeled generic
headers (`Connector_Generic`) with the part name as the value, rather
than a fictional symbol; everything with a real upstream symbol (ICs,
modules, boards' onboard MCUs) maps to it with a verified pin map.

The board's own pins are wired through its `kicad.pin_map` (board role
→ symbol pin, e.g. `GPIO36: SENSOR_VP`, `D2: SDA/D2`, `3V3: VDD`):
every gpio, rail and bus connection in the design lands on the board
symbol in both the schematic and the PCB. A role the symbol has no pin
for (a bare module's 5V) is noted rather than invented. Boards drawn as
generic headers have no pin map yet and float; add one to
`library/boards/<id>.yaml` to wire them.

## LoRaWAN / ChirpStack

Two paths for US915 radio boards — TTGO LoRa32 / T-Beam (SX1276), Heltec
WiFi LoRa 32 V2 (SX1276) / V3 / V4 (SX1262).

### Standalone Arduino path (`Design.target: "lorawan"`)

The **Flash LoRaWAN firmware** header button (advanced mode) drives the
full loop in the browser:

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
drift.

### External-component path (`Design.target: "esphome"` + `lorawan.payload`)

The newer path emits ESPHome YAML referencing
[`lorawan-for-esphome`](https://github.com/moellere/lorawan-for-esphome),
so the LoRaWAN device joins the same ESPHome / fleet-for-esphome
pipeline as every other device. When `design.lorawan.payload` is
non-empty, the renderer adds an `external_components:` block pinned to
a ref, a `lorawan:` config (radio block from the board library, region,
keys via `!secret`), and one `sensor: - platform: lorawan` binding per
payload field. The **Provision LoRaWAN device** header button (key
icon) drives the orchestration loop:

1. **Detect** — "Detect from chip" reads the eFuse MAC over WebSerial
   and derives the EUI-64 DevEUI (`detectChip()` + `macToEui64()`).
   Manual override remains.
2. **Provision** — `POST /lorawan/provision-esphome` mints an AppKey,
   registers the device against a path-specific device profile
   (`wirestudio-esphome-<region>-sub<n>`), flushes its DevNonces, and
   returns the three keys formatted for `secrets.yaml`. The AppKey is
   ephemeral and never persisted to `design.json`.
3. **Push** — "Push to fleet" forwards the rendered YAML to
   fleet-for-esphome with the minted secrets inlined into the
   `lorawan:` block (via the `lorawan_secrets` field on
   `POST /fleet/push`), so the fleet's `secrets.yaml` doesn't need a
   separate write. Compile is enqueued in the same call. When fleet is
   not configured but an ESPHome dashboard is, the button reads "Push to
   dashboard" and does the same through `POST /esphome/push`, which
   takes the same `lorawan_secrets` field.
4. **Join** — the dialog polls `GET /lorawan/activation/{dev_eui}`
   every few seconds; the join indicator flips when ChirpStack reports
   the OTAA join landed.

Both paths share ChirpStack config: `CHIRPSTACK_API_URL` +
`CHIRPSTACK_API_TOKEN` (a UI-generated API token, never the JWT signing
secret).

Heavy deps (`grpcio`, `chirpstack-api`, `platformio`) live behind a
`pip install wirestudio[lorawan]` extra and are lazy-imported, so a plain
install stays light. Background + the live ChirpStack setup are in
[`docs/lorawan/`](lorawan/) — `esphome-component-pivot.md` covers the
architecture decision, `workflow-integration.md` the orchestration steps.

**Limitations (current).** Both paths are **US915 sub-band 2 only** and
**ChirpStack only** in practice — the IR accepts EU868 / AU915 / AS923
on the external-component path, but the device-side support and the
ChirpStack profile naming have only been exercised end to end on US915
sub-2. Multi-region is a tracked backlog item (safety-sensitive, so
it's not half-shipped). The network server is ChirpStack v4 over gRPC;
TTN / other servers aren't wired yet. The external-component path is
hardware-join-verified pending a live test against a real gateway.

## Firmware proxies (Tasmota / Meshtastic / CircuitPython)

The unified flash dialog's non-ESPHome frameworks need no configuration
— the server proxies the official upstream release images so the
browser can flash them over WebSerial without CORS trouble:

- **Tasmota** — `GET /tasmota/firmware?chip=` streams the release image
  from ota.tasmota.com for the design's chip variant.
- **Meshtastic** — `GET /meshtastic/firmware?board=` streams the factory
  image from meshtastic.github.io for the mapped radio boards.
- **CircuitPython** — `GET /circuitpython/firmware?board=` streams the
  release image from downloads.circuitpython.org for ESP32/S3/C3/C6
  boards; `GET /circuitpython/code?board=` serves a generated starter
  `code.py`.

Each has a `/firmware/status` endpoint reporting upstream reachability
(and, for CircuitPython, which boards fall back to a pin-compatible
generic image); the UI gates its flash buttons on it.

## MCP server

The design-editing tools are exposed over the Model Context Protocol
at `/mcp` — point Claude Code or Claude Desktop at the daemon and the
model drives the studio on your Claude subscription. See the dedicated
[MCP server guide](mcp.md) for the end-to-end setup.
