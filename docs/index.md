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

## Architecture

```
   design.json  ── single source of truth (JSON-Schema-validated)
        │
        ▼
  ┌─ wirestudio.model         pydantic models mirroring the schema
  ├─ wirestudio.library       loads boards/ + components/ YAML
  ├─ wirestudio.generate      design + library → ESPHome YAML + ASCII
  ├─ wirestudio.targets       generation targets: esphome (wraps generate) + lorawan
  ├─ wirestudio.csp           pin solver + port-compatibility checker
  ├─ wirestudio.recommend     deterministic capability ranking
  ├─ wirestudio.agent         Claude tool-using agent + session store
  ├─ wirestudio.designs       file-backed designs/<id>.json store
  ├─ wirestudio.fleet         fleet-for-esphome HTTP client
  ├─ wirestudio.enclosure     parametric OpenSCAD + Thingiverse search
  ├─ wirestudio.kicad         SKiDL schematic emitter + .kicad_sym importer
  ├─ wirestudio.mcp           MCP server over the agent tool surface
  └─ wirestudio.api           FastAPI HTTP layer (mounts everything above)
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
wirestudio/targets/      generation targets: esphome + lorawan (firmware gen, ChirpStack, compile)
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
with a `--strict` no-regression gate now at **zero uncovered** (every
one of the 60 components and 23 boards is exercised (esphome examples,
or the lorawan firmware build for radio boards); a pinned ESPHome version called
out in the README + workflow; an
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
render as labeled generic headers. Next: ERC on the generated netlist;
a full `.kicad_sch` render in CI; pin-solver property tests on
randomized designs; compatibility-checker fuzzing.

**Priority 3 — Enclosures.** *Verified.* Parametric OpenSCAD
generator + Thingiverse search relay shipped. The
[`enclosure-render`](../.github/workflows/enclosure-render.yml) gate
renders every enclosure-capable board's `.scad` through real OpenSCAD
and fails the PR unless it produces a non-empty, manifold solid. Open
question: keep investing in the in-house generator, or outsource to
e.g. [YAPP_Box](https://github.com/mrWheel/YAPP_Box) and integrate
instead of reimplementing? Next: more boards' `enclosure:` metadata
(only 5 carry it today); a lid + snap-fit; slicer-side print validation.

**Priority 4 — PCB layout.** *Verified (unrouted).* Shipped in three
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
unconnected items, routed DRC clean). Next: wire routing into the fab
endpoints/MCP/web UI and ship a toolchain image so the default deploy
can route.

**LoRaWAN target (0.13 standalone, 0.16+ external-component).** *Works —
hardware-validated on the standalone path; external-component path
shipped, hardware join verification in progress.* Two paths share the
`wirestudio.targets` plugin seam:

- **Standalone Arduino path** (`target: "lorawan"`). Builds RadioLib +
  LoRaWAN_ESP32 firmware for US915 radio boards (TTGO LoRa32 / T-Beam,
  Heltec WiFi LoRa 32 V2/V3), flashes it over WebSerial from the
  browser, and provisions the device against ChirpStack. Every radio
  board's firmware builds in CI
  ([`lorawan-firmware`](../.github/workflows/lorawan-firmware.yml));
  validated end-to-end on a TTGO T-Beam against live ChirpStack 4.17.
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

**Future** — PCB layout (Priority 4): SKiDL → KiCad PCB, Freerouting,
Gerber + JLCPCB export, now that the schematic is Verified; an agent
eval harness scoring tool-use against a fixed task list (to promote the
agent from Experimental); a multi-writer state backend so the studio
can run as a HA replica; attributing `esphome-matrix` failures to
specific components for per-release support tables.
