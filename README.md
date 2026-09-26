# wirestudio

Hardware design tool for ESPHome devices. A single `design.json`
(board + components + connections) drives every artifact: solved pin
assignments, electrical validation, compile-clean ESPHome YAML, an
ASCII wiring diagram, a KiCad schematic and placed PCB, a JLCPCB fab
bundle (BOM / CPL / Gerber / drill), and a parametric OpenSCAD
enclosure. Drive it from the web UI, the built-in agent, or any MCP
client.

Stock ESPHome's Device Builder covers picking a board and adding
components. wirestudio works below the YAML: the component library
carries electrical metadata ESPHome doesn't model (voltage rails,
current draw, pull-ups, per-pin capabilities), a CSP solver assigns
legal pins from it, a validator catches boot-strap / ADC2-WiFi /
voltage conflicts, and the same design fans out to the physical
artifacts — wiring, schematic, PCB, enclosure. The bundled boards span
the ESP32 family (original, C3, S3, C6) and ESP8266; nothing is
ESP32-specific — any board ESPHome supports can be added with a library
file ([integration spec](docs/integration_spec.md)).

Below the module level the library also carries **subcircuits**: a
component built from discrete parts (an H-bridge, a MOSFET low-side
driver, an LED indicator, a voltage divider, a level shifter) expands
into real symbols and footprints on the schematic and PCB, into the BOM
and CPL, and into the inventory check. Blocks declare the electrical
rule they are held to, and `validate` runs it with the instance's
params and the rails it is wired to. Components can be authored in the
studio (or by the agent) and pass the same gate the bundled ones do.
An **inventory** of what is on hand -- library modules and a drawer of
discrete parts, imported from a spreadsheet -- is cross-checked against
a design's BOM: shortfalls come back with same-package substitutes and
their caveats, an accepted substitute changes what every fab output
prints, and the report ends in a pick list by drawer location and a
buy list priced on JLCPCB.

Two LoRaWAN paths share the studio. The standalone target builds and
flashes RadioLib + LoRaWAN_ESP32 firmware over WebSerial. The newer
external-component path emits ESPHome YAML referencing
[`lorawan-for-esphome`](https://github.com/moellere/lorawan-for-esphome),
so the LoRaWAN device joins the same ESPHome / fleet-for-esphome build
pipeline as every other device — provisioning, key handling, and
join-status polling all from the web UI. Both paths target US915 radio
boards (TTGO T-Beam / LoRa32, Heltec WiFi LoRa 32 V2 / V3 / V4) and
provision against ChirpStack.

One flash dialog covers six firmware frameworks over the same
WebSerial + esptool-js mechanism: **ESPHome** (built by
fleet-for-esphome or by an ESPHome dashboard, then OTA), **Tasmota**
(official release image + template push over serial), **LoRaWAN**
(compiled RadioLib firmware), **Meshtastic** (official release factory
image for the radio boards, then region, preset, owner and channel
pushed over the same port), **CircuitPython** (official release image
plus a generated `code.py` for the CIRCUITPY drive), and
**MicroPython** (official release image for every board's chip, plus a
`main.py` generated from the design and pushed over the same port
through the raw REPL).

WebSerial needs the board on the end of a cable. A **remote workbench**
removes that: point the studio at a
[SensorsIot Embedded AI Harness](https://github.com/SensorsIot/Embedded-AI-Harness)
— a Raspberry Pi exposing every USB-attached board as a network
resource — and flashing, LoRaWAN key provisioning and join verification
all run against a slot on a bench somewhere else
([workbench](docs/workbench.md)). The MCP server carries the same
reach: alongside the design tools it exposes workbench, ChirpStack and
fleet-build tools, so a headless client can take a design from
`design.json` to a joined device without dropping to HTTP
([MCP](docs/mcp.md)).

Not affiliated with the ESPHome project. **Push to fleet** talks to
[`weirded/fleet-for-esphome`](https://github.com/weirded/fleet-for-esphome),
the OTA-deploy companion; **Push to ESPHome dashboard** talks to a
plain ESPHome dashboard (the Home Assistant add-on or a standalone
one), which dispatches the compile to its own workers.

## Documentation

Detailed docs live in [`docs/`](docs/):

- [Documentation index](docs/index.md) — architecture, repo layout, roadmap.
- [User guide](docs/user_guide.md) — Web UI, inspector, header actions, HTTP API, examples.
- [Deployment](docs/deployment.md) — self-host with Docker or Kubernetes.
- [Integrations](docs/integrations.md) — agent, fleet handoff, enclosure search, KiCad.
- [MCP server](docs/mcp.md) — drive the studio from Claude Code / Desktop.
- [Workbench](docs/workbench.md) — flash and provision boards on a remote bench.
- [Library reference](docs/library.md) — every board and component.
- [LoRaWAN target](docs/lorawan/) — build + flash LoRaWAN firmware, provision against ChirpStack.

## Status

`v0.35.0` — on PyPI (`pip install wirestudio`). The studio has wide
surface area (YAML, schematic, PCB + fab outputs, enclosure,
subcircuits with electrical rules, inventory matching, component
authoring, agent, MCP server, two ESPHome build paths, remote
workbench, web UI, two LoRaWAN flash/provision paths — standalone
Arduino and an external-component path that emits ESPHome YAML
referencing `lorawan-for-esphome`) and a set of things actually
verified against upstream tools. The YAML, schematic, PCB, and
enclosure paths are gated in CI, and **every library component and
board is exercised by a bundled example** that passes those gates. This section is honest about which is which, ordered
by how much it matters that it works.

Tiers, in priority order:

| Tier | Area | What it does | Verified by |
|---|---|---|---|
| **Verified** | ESPHome YAML production | render `design.json` → ESPHome YAML | `esphome config` passes on every bundled example, every PR ([gate](.github/workflows/esphome-config.yml)); nightly `esphome compile` smoke against a representative example ([compile](.github/workflows/esphome-compile.yml)) |
| **Verified** | CSP pin solver + compat checker | assign legal pins, surface boot-strap / ADC2-WiFi / voltage / locked-pin issues | unit tests + property checks in `tests/test_pin_solver.py` + `tests/test_compatibility.py` |
| **Verified** | Fleet handoff | push YAML to `fleet-for-esphome` ha-addon, optional compile + log relay | round-trip tests in `tests/test_fleet.py` |
| **Verified** | KiCad schematic | emit a SKiDL Python script the user runs locally to produce a `.kicad_sch` | every bundled example builds a KiCad netlist against the pinned upstream symbol libraries, every PR ([gate](.github/workflows/kicad-schematic.yml)) — no unresolved symbols or pins; `kicad-cli sch erc` runs on representative rendered schematics against a baseline of the violation types the generator cannot avoid ([gate](.github/workflows/kicad-render.yml)). Parts KiCad ships no symbol for (sensor/module breakouts) render as labeled generic headers |
| **Verified** | KiCad PCB layout | emit a placed, unrouted `.kicad_pcb` — footprints, nets, ratsnest, edge cuts | every bundled example emits a structurally sound board, every PR ([gate](.github/workflows/pcb-layout.yml)); a DRC tier opens each board in real KiCad ([gate](.github/workflows/pcb-drc.yml)) |
| **Verified** | Fab outputs | JLCPCB upload bundle — BOM, CPL, Gerber + drill (`/design/fab/*`) | CPL positions match the `.kicad_pcb` placement; the DRC tier smoke-tests the Gerber export. Boards are unrouted until the Freerouting step, so Gerbers carry pads but no traces (`is_routed` flags it) |
| **Verified** | Subcircuits + building blocks | a component built from discrete parts (five bundled blocks, two H-bridges) expands into the schematic, PCB, BOM, CPL and inventory check; part values are parametric; each block's `verify.checks` rule runs at `validate` with the real params and rails | goldens for every subcircuit example pin YAML + BOM; `component_check` fails a block whose defaults break its own rule (`tests/test_electrical.py`); the schematic and PCB gates cover the expanded parts like any other |
| **Verified** | Inventory check | cross-check a design's BOM against the drawer (library modules + discrete parts), propose same-package substitutes with caveats, accept one as a `part_override` that every fab output honours, pick list by location, buy list priced on JLCPCB | matching, substitution and coverage tests in `tests/test_inventory.py` against the real drawer CSV; JLCPCB pricing is mocked and degrades to an unpriced list when the parts API is down |
| **Verified** | Parametric enclosure | OpenSCAD `.scad` from board mount-hole metadata | every enclosure-capable board renders through real OpenSCAD to a non-empty, manifold (closed, printable) solid, every PR ([gate](.github/workflows/enclosure-render.yml)) |
| **Works (hardware-validated)** | LoRaWAN target | build RadioLib + LoRaWAN_ESP32 firmware for US915 radio boards, flash over WebSerial, provision against ChirpStack | every radio board's firmware builds in CI ([gate](.github/workflows/lorawan-firmware.yml)); validated end-to-end on a TTGO T-Beam and Heltec WiFi LoRa 32 V2 and V3 against live ChirpStack 4.17 — no automated live-device gate |
| **Works (hardware-validated)** | LoRaWAN external-component path | emit ESPHome YAML referencing `lorawan-for-esphome`, provision keys into `secrets.yaml`, build through fleet | validated end-to-end on a Heltec WiFi LoRa 32 V4 (SX1262 + external PA): joined, uplinked and decoded against live ChirpStack. Payloads over 11 bytes need the data rate asserted per uplink — US915 DR0 caps at 11 and ADR drives to DR0 on a strong link. No automated live-device gate |
| **Works (hardware-validated)** | Remote workbench | flash a board on a bench slot, and run the whole LoRaWAN bring-up (flash → register → key push → verify) headlessly | wire format verified against a reference bench; flashing and LoRaWAN bring-up exercised repeatedly on a live Pi bench with an ESP32-S3. Transport tests in `tests/test_workbench.py` use wire-level fakes; no automated live-bench gate |
| **Verified** | Tasmota target | emit a Tasmota device template (`/tasmota/template`) mapping solved pins to Tasmota GPIO function ids | function ids + per-chip layouts sourced from `tasmota_template.h`; unit tests pin the Sonoff S31 template convention for the smart-plug example |
| **Works (lighter checks)** | Meshtastic flashing + config | proxy the official release factory image (`/meshtastic/firmware`) for the radio boards, flash it via the unified WebSerial dialog, then push region, modem preset, owner and primary channel as protobufs over the same port | endpoint tests with mocked upstream; board-to-variant map checked against `meshtastic/firmware` variants; config push tested against a fake device; no live-flash gate |
| **Works (lighter checks)** | MicroPython flashing + main.py | proxy the official release image for the board's chip (`/micropython/firmware`; every library board maps to a generic port image, ESP8266 included), flash via the unified dialog, generate `main.py` from the design over the `machine` API (`/micropython/code`) and push it through the raw REPL over the same serial port | endpoint tests with a captured download page; every board's starter and every example's main.py parse as Python; the raw-REPL push is tested against a fake board; the micropython.org page format could not be fetched from the build session, so the first live flash validates it; no live-flash gate |
| **Works (lighter checks)** | Component authoring | write a component YAML in the studio or through `component_create`; the same gate as `component_check` (schema, subcircuit nets, template render, KiCad symbols / pins / footprint) before it lands in the user library | gate tests in `tests/test_library_check.py`; KiCad resolution runs only where the toolchain is present; a user component is not compiled through `esphome config` in CI |
| **Works (lighter checks)** | ESPHome dashboard compile | push the rendered YAML to a running ESPHome dashboard (`/esphome/push`), start a compile there, stream the log and serve the firmware, with the same job shapes as the fleet path | client + route tests against a fake dashboard in `tests/test_esphome_dashboard.py` that mirrors `esphome dashboard` 2026.6.5, open and password-protected, after the client was run against both live; no live dashboard in CI |
| **Works (lighter checks)** | CircuitPython flashing | proxy the official release image (`/circuitpython/firmware`) for ESP32/S3/C3/C6 boards, flash via the unified dialog, serve a generated starter `code.py` (`/circuitpython/code`) | endpoint tests with mocked upstream; every board-id mapping verified against downloads.circuitpython.org; generated starters parse as valid Python; no live-flash gate |
| **Works (lighter checks)** | MCP server | 53 tools over the Model Context Protocol: 31 design / library / inventory / fab, plus 22 that reach hardware — workbench flash and boot verification, LoRaWAN compile / provision / activation, fleet and dashboard push + build status, and job polling for the long ones | tool / auth / resource tests in `tests/test_mcp_*.py`; the hardware tools drive the real clients against wire-level fakes, and were exercised against a live bench, ChirpStack and fleet during bring-up. Not run against a live MCP client in CI |
| **Experimental** | Thingiverse search relay | rank community models for a board | smoke-tested; depends on a third-party search API that ranks unevenly |
| **Experimental** | Agent (Claude tool-using) | natural-language design driving | works in practice; tool surface is small; no auto-eval against task list yet |
| **Verified** | PCB autorouting | Freerouting roundtrip — board → Specctra DSN → routed → SES import; SSE route endpoint, `route_pcb` MCP/agent tool, web-UI Route button, `?route=true` fab exports, `-pcb` image variant | representative examples route with zero unconnected items and pass routed DRC ([gate](.github/workflows/pcb-route.yml)) |

The **Verified** tier is the bar the project is asking to be judged
on. Everything else is offered with the caveat that's spelled out in
the table.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the bar a change has to
clear before merging, [`CHANGELOG.md`](CHANGELOG.md) for per-release
deltas, and [`START.md`](START.md) for the longer-form design notes.

Tested against ESPHome **`==2026.6.5`** (pinned in
`.github/workflows/esphome-config.yml` + bumped deliberately). When
that pin moves, this line moves with it.

## Quickstart

### Docker

```sh
docker run --rm -p 8765:8765 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v wirestudio-data:/data \
  ghcr.io/moellere/wirestudio:0.35.0
```

Open <http://localhost:8765>. The image bundles the FastAPI server +
the built web UI in one process. See [Deployment](docs/deployment.md)
for image tags, env vars, and the Kubernetes manifest.

### CLI

```sh
pip install wirestudio                       # from PyPI
# ...or, for a dev checkout:  pip install -e .[dev]
python -m wirestudio.generate wirestudio/examples/garage-motion.json
```

Prints rendered YAML and the ASCII wiring block to stdout.

### HTTP API

```sh
python -m wirestudio.api                    # localhost:8765
python -m wirestudio.api --reload           # dev mode (auto-reload on edits)
```

Browse the auto-generated OpenAPI docs at <http://127.0.0.1:8765/docs>.
The agent, fleet handoff, and MCP surfaces are each gated by an env
var — see [Integrations](docs/integrations.md).

### Web UI (dev)

```sh
# In one terminal:
python -m wirestudio.api
# In another:
cd web && npm install && npm run dev
```

Open <http://localhost:5173>; Vite proxies `/api/*` to the studio API.
The [User guide](docs/user_guide.md) walks the panes and header actions.

## Tests

```sh
python -m pytest                          # ~1220 cases
python -m ruff check .                    # lint
cd web && npx vitest run                  # vitest + jsdom
pip install 'esphome==2026.6.5'
python scripts/check_examples.py          # the YAML gate -- every example through `esphome config`
```

The `esphome config` gate is the headline test: it renders every
bundled example through the studio and runs upstream ESPHome's own
validator against the output. The GitHub Actions workflow runs the
YAML gate + the full suite + multi-arch image build on every PR and
merge to `main`. A nightly compile-smoke runs `esphome compile`
against a representative example. To run the gate before every push:

```sh
pip install pre-commit
pre-commit install --hook-type pre-push
```

## Contributing

[`CONTRIBUTING.md`](CONTRIBUTING.md) is the substantive bar — what
"working" means for the artifacts the studio produces, including
the `esphome config` gate every PR has to clear. [`CLAUDE.md`](CLAUDE.md)
covers the prose / commit / comment conventions (concise, no emojis,
default-to-no-comments, boundary-only validation, no premature
abstraction).

## License

MIT. See [`LICENSE`](LICENSE).
