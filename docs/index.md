# wirestudio documentation

Agent-driven IoT device design tool. Describe a goal (or pick parts);
get ESPHome YAML, an ASCII wiring diagram, and a BOM that compile
under upstream ESPHome.

## Documentation

- [User guide](user_guide.md) — the Web UI, inspector, header actions,
  the CLI, the HTTP API, and the bundled examples.
- [Deployment](deployment.md) — self-host with Docker or Kubernetes.
- [Integrations](integrations.md) — the agent, fleet handoff, enclosure
  search, and KiCad export, plus the env vars that gate each.
- [MCP server](mcp.md) — drive the studio from Claude Code / Desktop
  over the Model Context Protocol.
- [Library reference](library.md) — every board and component shipped
  in the library.
- [Library coverage](library-coverage.md) — which library entries are
  exercised by a bundled example.
- [Workbench integration](workbench.md) — hardware-truth layer on an
  Embedded AI Harness: remote flash and headless LoRaWAN bring-up
  (shipped), capability map, later phases, constraints.

## Architecture

```
   design.json  ── single source of truth (JSON-Schema-validated)
        │
        ▼
  ┌─ wirestudio.model         pydantic models mirroring the schema
  ├─ wirestudio.library       loads boards/ + components/ YAML
  ├─ wirestudio.generate      design + library → ESPHome YAML + ASCII
  ├─ wirestudio.targets       generation targets: esphome (wraps generate) + lorawan + tasmota
  ├─ wirestudio.csp           pin solver + port-compatibility checker
  ├─ wirestudio.recommend     deterministic capability ranking
  ├─ wirestudio.seed          board onboard-peripheral auto-placement
  ├─ wirestudio.intent        automation (trigger/action) validation + lowering, melody map;
  │                           display-content (`show`) lowering in wirestudio.generate
  ├─ wirestudio.inventory     owned-parts inventory store
  ├─ wirestudio.agent         Claude tool-using agent + session store
  ├─ wirestudio.designs       file-backed designs/<id>.json store
  ├─ wirestudio.fleet         fleet-for-esphome HTTP client
  ├─ wirestudio.enclosure     parametric OpenSCAD + Thingiverse search
  ├─ wirestudio.kicad         SKiDL schematic emitter, PCB emit/route, .kicad_sym importer
  ├─ wirestudio.jlcpcb        fab outputs (BOM / CPL / Gerber + drill)
  ├─ wirestudio.mcp           MCP server over the agent tool surface
  └─ wirestudio.api           FastAPI HTTP layer (mounts everything above,
                              plus the meshtastic + circuitpython firmware proxies)
                          serve.py adds the production wrapper:
                          API at /api/*, web bundle at /
```

Generators are pure functions of `design.json` + the static library — no
artifact-to-document round-trips. Library files in `wirestudio/library/components/`
carry the electrical metadata ESPHome doesn't (pin roles, voltage ranges,
current draw, decoupling caps, pull-up requirements) plus a Jinja2 template
that renders the ESPHome YAML for that component, an `enclosure:` block
the OpenSCAD generator reads, and a `kicad:` block the schematic exporter
reads.

## Layout

```
wirestudio/              python package — see Architecture above for the module map
wirestudio/schema/       JSON Schema for design.json (source of truth)
wirestudio/library/      board + component manifests (electrical, ESPHome, enclosure, kicad)
wirestudio/targets/      generation targets: esphome + lorawan (firmware gen, ChirpStack, compile) + tasmota (device template)
wirestudio/examples/     bundled design.json files (every one pinned by goldens)
web/                     React 19 + Vite + Tailwind v4 SPA
tests/                   pytest + golden artifacts; vitest tests under web/src
deploy/                  k8s.yaml, docker-compose.yml, nginx.conf for self-hosting
Dockerfile               multi-stage build for the published GHCR image
.github/workflows/       GHA workflow that publishes ghcr.io/.../wirestudio
scripts/                 dev helpers (currently: examples → `esphome config` gate)
docs/                    this documentation
CHANGELOG.md             per-release feature deltas
START.md                 vision, decisions, phase plan
CLAUDE.md                working conventions for both Claude and humans
CONTRIBUTING.md          substantive bar a change has to clear (the YAML gate, etc.)
```

## Roadmap

Ordered by how much it raises the floor on whether the studio is
actually useful. Per-release deltas live in
[`CHANGELOG.md`](../CHANGELOG.md); decisions + phase scope in
[`START.md`](../START.md).

**Priority 1 — YAML production correctness.** *Active.* The single
non-negotiable bar: every artifact the studio emits round-trips
through upstream `esphome config`. Shipped: the `esphome config` CI
gate over every bundled example; a nightly `esphome compile` smoke;
the component-coverage matrix ([`library-coverage.md`](library-coverage.md))
with a `--strict` no-regression gate holding **zero unexplained gaps** —
every board and every component but one is exercised (esphome examples,
or the lorawan firmware build for radio boards); the sole exception,
`axp192`, is a permanent baseline entry, since the T-Beam's PMIC has no
standalone ESPHome platform and is materialized implicitly by the
LoRaWAN generator rather than named by any example — see
[`library-coverage.md`](library-coverage.md) for the live counts; a
pinned ESPHome version called out in the README + workflow; an
[`esphome-matrix`](../.github/workflows/esphome-matrix.yml) compatibility
report that runs the gate across the pin + latest stables so a pin bump
is evidence-driven; CONTRIBUTING.md establishes the gate as the merge
bar. Next: attribute matrix failures to specific components so support
can be stated per ESPHome release.

**Priority 2 — Wiring schema correctness.** *Verified.* SKiDL
emitter, 100% library `kicad:` coverage, and a `.kicad_sym` symbol
importer (`python -m wirestudio.kicad.import`) shipped. The
[`kicad-schematic`](../.github/workflows/kicad-schematic.yml) gate runs
every bundled example's SKiDL script against the pinned upstream KiCad
symbol libraries and fails the PR unless it builds a netlist with no
unresolved symbols or pins; parts KiCad ships no stock symbol for
render as labeled generic headers. The
[`kicad-render`](../.github/workflows/kicad-render.yml) gate carries the
pipeline the rest of the way — SKiDL script → `.kicad_sch` →
`kicad-cli sch export svg` on real KiCad 8 — catching what only
kicad-cli's parser sees (schematic grammar, embedded `lib_symbols`,
toolchain env), which the netlist gate cannot. Next: ERC on the
generated netlist; pin-solver property tests on randomized designs;
compatibility-checker fuzzing.

**Priority 3 — Enclosures.** *Verified.* Parametric OpenSCAD
generator + Thingiverse search relay shipped. The
[`enclosure-render`](../.github/workflows/enclosure-render.yml) gate
renders every enclosure-capable board's `.scad` through real OpenSCAD
and fails the PR unless it produces a non-empty, manifold solid. Open
question: keep investing in the in-house generator, or outsource to
e.g. [YAPP_Box](https://github.com/mrWheel/YAPP_Box) and integrate
instead of reimplementing? Next: more boards' `enclosure:` metadata
(only 5 carry it today); a lid + snap-fit; slicer-side print validation.

**Priority 4 — PCB layout.** *Verified (routed).* Shipped in three
steps: the footprint-coverage gate (every component + board names a
real KiCad footprint that resolves in the pinned libraries, 0.13), the
`.kicad_pcb` emit (footprints placed, pads bound to nets, `Edge.Cuts`
outline, 0.14), and the fab outputs (BOM / CPL / Gerber + drill via
`/design/fab/*`, packaged for JLCPCB upload, 0.15). The
[`pcb-layout`](../.github/workflows/pcb-layout.yml) gate proves every
bundled example emits a structurally sound board, and
[`pcb-drc`](../.github/workflows/pcb-drc.yml) opens each board in real
KiCad and runs DRC (unrouted airwires expected). The Freerouting
autoroute step now closes the routing gap:
`python -m wirestudio.kicad.route` runs board → Specctra DSN (pcbnew
bridge) → `freerouting.jar` → SES import, and the
[`pcb-route`](../.github/workflows/pcb-route.yml) gate holds
representative examples to the routed bar (copper present, zero
unconnected items, routed DRC clean). Routing is surfaced everywhere the
board is: `POST /design/kicad/route` (SSE), the `route_pcb` MCP/agent
tool, the web UI's Autoroute section, `?route=true` on the fab exports,
and the `-pcb` image variant that carries the toolchain. Next: routed
DRC feedback in the UI, via-cost/keepout tuning, and copper pours for
power nets.

**Tasmota target (0.22).** *Works.* Emits a Tasmota device template --
a pure mapping of solved pins to Tasmota GPIO function ids -- via
`POST /tasmota/template`, the target seam, and
`python -m wirestudio.targets.tasmota`. Function ids and per-chip
template layouts are sourced from `tasmota_template.h`; unit tests pin
the Sonoff S31 convention for the smart-plug example. Library
components opt in with a `tasmota:` block; I2C sensors ride the bus
pins via Tasmota autodetection, and UART-attached parts (MH-Z19,
PMS5003, LD2410, CSE7766) map their bus pins to the matching Tx/Rx
functions. ESP8266 D-labels resolve to real GPIO numbers.

**Meshtastic flashing (0.23).** *Works.* The unified flash dialog
fetches the official Meshtastic release factory image through the
server proxy (`GET /meshtastic/firmware`, board-to-variant map for
Heltec V2/V3/V4, T-Beam, TTGO LoRa32) and flashes it at 0x0 over the
same WebSerial path. Not a target plugin -- devices run stock firmware,
nothing is generated from the design. Region/channel config is protobuf
over serial, so the dialog links to client.meshtastic.org; an in-studio
config push via `@meshtastic/js` stays in the backlog.

**CircuitPython flashing (0.24).** *Works.* The unified flash
dialog gains a CircuitPython framework: `GET /circuitpython/firmware`
proxies the official release image from downloads.circuitpython.org
(combined binary at 0x0, full erase), resolving the newest stable from
the adafruit/circuitpython releases API. Every ESP32/S3/C3/C6 board
maps to a verified build — exact where upstream has one, a
pin-compatible generic image otherwise (flagged in the status response
and warned about in the UI); ESP8266 has no CircuitPython port.
`GET /circuitpython/code` serves a starter code.py generated from the
board's library metadata (Vext power-up, LED blink, I2C scan, pin
listing) with save-to-CIRCUITPY and download buttons post-flash.

**CircuitPython codegen.** *Works.* Full code.py generation from the
design — the LoRaWAN-fragment pattern applied to Python. 36 library
components carry a `circuitpython:` block (explicit imports, Adafruit
bundle deps, Jinja2 setup/loop fragments); the generator resolves
buses to busio objects, renders each component's wiring, lists the
bundle libraries to copy to CIRCUITPY/lib, and ast-validates the
output. `POST /circuitpython/code` returns {code, deps, warnings};
the flash dialog prefers design code over the board starter and
surfaces deps + unmapped-component warnings. Unmapped parts degrade
to a comment, never a broken file.

**Target backlog.** Next: Meshtastic config push (`@meshtastic/js`
region/channel/key setup over the existing serial session), then
MicroPython (the CircuitPython pattern applied upstream: proxy the
micropython.org release port per chip, flash via the unified dialog,
generate a main.py scaffold — differs in stdlib/driver sourcing, since
there is no single blessed bundle like Adafruit's).
Deliberately deferred: generic Arduino/PlatformIO scaffolds (per-driver
maintenance sinkhole), Zephyr, Zigbee/Thread on the C6.

**MCP tool surface — hardware gap (closed).** The design/KiCad/fab tools
used to stop at the artifact: an MCP client could produce a design and a
schematic, then had to hand off to HTTP to put it on a board. That
workaround was worse than it looked, because the two surfaces are not
equivalently exposed — `/mcp` authenticates with `WIRESTUDIO_MCP_TOKEN`
while the REST endpoints authenticate with nothing, so publishing those
instead meant publishing unauthenticated flashing and provisioning.

Seventeen tools now cover the rest of the path: `workbench_status` /
`workbench_slots` / `workbench_flash`, the `lorawan_*` compile,
provision and activation tools, the `fleet_*` push/status/log tools, and
`job_status` / `job_events` / `job_list`.

The open question was how a long SSE compile maps onto a call that
returns once. It doesn't, so the streaming operations return a `job_id`
and the client polls. Fleet builds are the deliberate exception: their
`run_id` belongs to the addon's GitHub run and outlives this process, so
they keep it rather than being wrapped in the in-memory registry — which
also means a `job_id` and a `run_id` are not interchangeable. Firmware
bytes stay server-side: `workbench_flash` takes a `fleet_run_id` and
fetches the artifact itself.

Still open, and worth doing regardless: the REST surface has no auth at
all. `/workbench/flash` and `/lorawan/provision` are reachable by
anything that can route to the pod. That is survivable while the only
exposure is a cluster-internal Service, and is the reason the ingress
publishes `/mcp` alone.

**Workbench featureset (phases 1–3 shipped).** Integrate an
[Embedded AI Harness](https://github.com/SensorsIot/Embedded-AI-Harness)
(Raspberry Pi exposing RFC2217 network serial per USB slot, a JSON HTTP
API, a WiFi AP tester, an MQTT broker, UDP logging, GPIO boot/reset
control, and an optional RTL-SDR) as the studio's hardware truth layer.
The studio verifies artifacts against upstream tools; nothing today
verifies them against silicon — flashing is WebSerial-only (Chrome,
local USB, human present), and the Meshtastic / CircuitPython /
LoRaWAN-join tiers all carry a "no live-flash gate" caveat. The
workbench closes that gap. Client-side only: the studio talks to the
workbench API behind a `WORKBENCH_URL` env gate (the usual integration
seam), never re-implements slots/serial/RF. Full capability map and
design constraints in [workbench.md](workbench.md).

Phases, each independently shippable. Note the payoff is not evenly
distributed: phase 1 is what makes a remote bench reachable at all,
and it is phase 3's *flashing* half that retires the "no live-flash
gate" caveats above — which is the half not yet enabled, so those
caveats still stand.

1. **Remote flash transport — shipped in 0.25.0**, extended in 0.26.0
   with the headless LoRaWAN bring-up
   (`/lorawan/workbench/provision`: flash → register → push keys over
   the slot's serial prompt → verify the join) and in 0.27.0 with the
   MCP tools that drive both. `/workbench/status`, `/workbench/slots`
   and `/workbench/flash`: the server fetches the framework image
   exactly as today, uploads it to the bench, and streams progress over
   SSE while the Pi runs esptool against its own USB. The flash dialog
   gains a Local USB / Workbench-slot target toggle. Flashing is
   delegated rather than driven over RFC2217 from the studio — esptool's
   block protocol is round-trip bound, so one bulk upload plus a local
   flash survives the very link that makes this phase necessary.
   This is not merely a convenience over WebSerial — it removes
   the requirement that the developer be in the same room as the board.
   The motivating case is LoRaWAN: a radio board has to be flashed
   where it can actually reach a gateway, so when the bench and the
   ChirpStack instance sit at one site and the developer at another,
   WebSerial cannot close the loop at all. Remote flash makes the
   provision → flash → join cycle runnable against the real network
   from anywhere, and is the prerequisite for every headless/MCP-driven
   use of the bench.
2. **Boot-marker verification — server side shipped in 0.29.0.** The
   `workbench_verify_boot` tool watches a slot for a line the running
   firmware emits, upgrading "flashed" to "flashed and booted" — the
   failure class CI can't see, since a wrong flash size or an undriven
   front end flashes perfectly and then fails at start-up. Supports
   `esphome`, `lorawan` and `lorawan-esphome`; Meshtastic and
   CircuitPython are explicitly unsupported with the reason rather than
   approximated. Joining is a separate opt-in check, because the first
   join after a flash reliably fails and only the retry succeeds.
   Still to do: stream that serial into the flash dialog so a human
   watches the boot.
3. **Nightly hardware gate — shipped in 0.30.0.** A scheduled job
   asserts the bench and every board on it: the portal answers, each
   configured slot is present and flashable, its serial recorder is
   capturing, and ChirpStack saw its DevEUI recently. Exits non-zero on
   any failure.

   It runs from a **cluster CronJob, not a self-hosted runner** as this
   roadmap first assumed. WireStudio is a public repository, and
   `pull_request` runs fork-authored workflows by design, so a runner on
   a network that reaches the bench would let any fork's pull request
   execute code there. Scheduling from inside the perimeter keeps the
   reach and removes the inbound execution path; the cost is that the
   gate cannot annotate a PR, so a failed Job is the report.

   The **flashing** half — a representative example per framework
   flashed to a dedicated slot, which is what would let the "Works
   (lighter checks)" tiers hold hardware-validated status continuously
   — is deliberately not enabled yet. It needs a board nothing else
   depends on: every device on the reference bench carries real traffic,
   and a nightly reflash costs a rejoin, a DevNonce and about ten
   minutes off air each time. Details in
   [workbench.md](workbench.md#the-gate).
4. **Functional loop + RF truth.** Flash generated ESPHome firmware,
   provision against the workbench's AP, assert the device's API/MQTT
   entities appear; for radio boards, an SDR power-spectrum capture
   during TX catches deaf-radio wiring bugs (e.g. undriven FEM pins)
   that serial output cannot.

**LoRaWAN target (0.13 standalone, 0.16+ external-component).** *Works —
hardware-validated on the standalone path; external-component path
shipped, hardware join verification in progress.* Two paths share the
`wirestudio.targets` plugin seam:

- **Standalone Arduino path** (`target: "lorawan"`). Builds RadioLib +
  LoRaWAN_ESP32 firmware for US915 radio boards (TTGO LoRa32 / T-Beam,
  Heltec WiFi LoRa 32 V2/V3/V4), flashes it over WebSerial from the
  browser, and provisions the device against ChirpStack. Every radio
  board's firmware builds in CI
  ([`lorawan-firmware`](../.github/workflows/lorawan-firmware.yml));
  validated end-to-end on a TTGO T-Beam and Heltec WiFi LoRa 32 V2 and
  V3 against live ChirpStack 4.17.
- **External-component path** (`target: "esphome"` + `lorawan.payload`).
  When `design.lorawan.payload` is set, the YAML generator emits an
  `external_components: github://moellere/lorawan-for-esphome@<ref>`
  block plus a `lorawan:` config (radio block, region, keys via
  `!secret`, payload sensor bindings). The device joins the same
  ESPHome / fleet-for-esphome pipeline as every other device.
  Provisioning is one endpoint
  (`POST /lorawan/provision-esphome`) that mints an AppKey, registers
  the device in ChirpStack, flushes its DevNonces, and returns the
  three secrets ready for `secrets.yaml`. The web flasher has a
  one-click flow: detect chip → derive DevEUI from eFuse MAC → provision
  → push to fleet (secrets inlined) → poll activation. See the
  [LoRaWAN docs](lorawan/) — `esphome-component-pivot.md` for the
  architecture, `workflow-integration.md` for the orchestration.

Both paths sit behind a `[lorawan]` install extra. The uplink payload
and the ChirpStack `decodeUplink` codec are generated from one field
spec so they stay in lockstep.

**Plumbing — already shipped.** API (`0.2`), web UI (`0.3` +
`0.6+`), USB bootstrap (`0.4`), agent (`0.5` + streaming), CSP
solver (`0.6`), fleet handoff (`0.7`), enclosure (`0.8`), KiCad
schematic (`0.9`), MCP server + KiCad symbol importer (`0.10`),
Docker single-image deploy + K8s manifest.

**Future** — an agent eval harness scoring tool-use against a fixed
task list (to promote the agent from Experimental); a multi-writer
state backend so the studio can run as a HA replica; attributing
`esphome-matrix` failures to specific components for per-release
support tables.

**Retired debt** — `mcp` was pinned to `<2` from 0.24.1, because mcp
2.0.0 removed the `mcp.server.fastmcp` import path the server is built
on and images built against it crashed at boot. Migrated in #225: the
package became `mcp.server.mcpserver` and the class `MCPServer`, with
three real breaks beyond the rename — `Settings` dropped
`transport_security` (now an argument to `streamable_http_app()`),
`call_tool` returns a `CallToolResult` rather than a content sequence,
and the model fields are snake_case. Verified on staging, where the
image has served for days without a restart.

Note mcp 2.x pulls **httpx2**, a distribution separate from httpx. The
import names differ, so it coexists with the studio's own httpx usage
rather than replacing it — at the cost of a second HTTP stack in the
image.
