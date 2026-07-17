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
artifacts — wiring, schematic, PCB, enclosure.

Two LoRaWAN paths share the studio. The standalone target builds and
flashes RadioLib + LoRaWAN_ESP32 firmware over WebSerial. The newer
external-component path emits ESPHome YAML referencing
[`lorawan-for-esphome`](https://github.com/moellere/lorawan-for-esphome),
so the LoRaWAN device joins the same ESPHome / fleet-for-esphome build
pipeline as every other device — provisioning, key handling, and
join-status polling all from the web UI. Both paths target US915 radio
boards (TTGO T-Beam / LoRa32, Heltec WiFi LoRa 32 V2 / V3) and
provision against ChirpStack.

Not affiliated with the ESPHome project — see
[`weirded/fleet-for-esphome`](https://github.com/weirded/fleet-for-esphome)
for the OTA-deploy companion this studio's **Push to fleet** flow
talks to.

## Documentation

Detailed docs live in [`docs/`](docs/):

- [Documentation index](docs/index.md) — architecture, repo layout, roadmap.
- [User guide](docs/user_guide.md) — Web UI, inspector, header actions, HTTP API, examples.
- [Deployment](docs/deployment.md) — self-host with Docker or Kubernetes.
- [Integrations](docs/integrations.md) — agent, fleet handoff, enclosure search, KiCad.
- [MCP server](docs/mcp.md) — drive the studio from Claude Code / Desktop.
- [Library reference](docs/library.md) — every board and component.
- [LoRaWAN target](docs/lorawan/) — build + flash LoRaWAN firmware, provision against ChirpStack.

## Status

`v0.19.0` — on PyPI (`pip install wirestudio`). The studio has wide
surface area (YAML, schematic, PCB + fab outputs, enclosure, agent,
MCP server, fleet handoff, web UI, two LoRaWAN flash/provision paths —
standalone Arduino and an external-component path that emits ESPHome
YAML referencing `lorawan-for-esphome`) and a set of things actually
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
| **Verified** | KiCad schematic | emit a SKiDL Python script the user runs locally to produce a `.kicad_sch` | every bundled example builds a KiCad netlist against the pinned upstream symbol libraries, every PR ([gate](.github/workflows/kicad-schematic.yml)) — no unresolved symbols or pins. Parts KiCad ships no symbol for (sensor/module breakouts) render as labeled generic headers |
| **Verified** | KiCad PCB layout | emit a placed, unrouted `.kicad_pcb` — footprints, nets, ratsnest, edge cuts | every bundled example emits a structurally sound board, every PR ([gate](.github/workflows/pcb-layout.yml)); a DRC tier opens each board in real KiCad ([gate](.github/workflows/pcb-drc.yml)) |
| **Verified** | Fab outputs | JLCPCB upload bundle — BOM, CPL, Gerber + drill (`/design/fab/*`) | CPL positions match the `.kicad_pcb` placement; the DRC tier smoke-tests the Gerber export. Boards are unrouted until the Freerouting step, so Gerbers carry pads but no traces (`is_routed` flags it) |
| **Verified** | Parametric enclosure | OpenSCAD `.scad` from board mount-hole metadata | every enclosure-capable board renders through real OpenSCAD to a non-empty, manifold (closed, printable) solid, every PR ([gate](.github/workflows/enclosure-render.yml)) |
| **Works (hardware-validated)** | LoRaWAN target | build RadioLib + LoRaWAN_ESP32 firmware for US915 radio boards, flash over WebSerial, provision against ChirpStack | every radio board's firmware builds in CI ([gate](.github/workflows/lorawan-firmware.yml)); validated end-to-end on a TTGO T-Beam against live ChirpStack 4.17 — no automated live-device gate |
| **Works (lighter checks)** | MCP server | drive the design tools from Claude Code / Desktop over the Model Context Protocol | tool / auth / resource tests in `tests/test_mcp_*.py`; not exercised against a live MCP client in CI |
| **Experimental** | Thingiverse search relay | rank community models for a board | smoke-tested; depends on a third-party search API that ranks unevenly |
| **Experimental** | Agent (Claude tool-using) | natural-language design driving | works in practice; tool surface is small; no auto-eval against task list yet |
| **Verified** | PCB autorouting | Freerouting roundtrip — board → Specctra DSN → routed → SES import; SSE route endpoint, `route_pcb` MCP/agent tool, web-UI Route button, `?route=true` fab exports, `-pcb` image variant | representative examples route with zero unconnected items and pass routed DRC ([gate](.github/workflows/pcb-route.yml)) |

The **Verified** tier is the bar the project is asking to be judged
on. Everything else is offered with the caveat that's spelled out in
the table.

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the bar a change has to
clear before merging, [`CHANGELOG.md`](CHANGELOG.md) for per-release
deltas, and [`START.md`](START.md) for the longer-form design notes.

Tested against ESPHome **`==2025.12.7`** (pinned in
`.github/workflows/esphome-config.yml` + bumped deliberately). When
that pin moves, this line moves with it.

## Quickstart

### Docker

```sh
docker run --rm -p 8765:8765 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -v wirestudio-data:/data \
  ghcr.io/moellere/wirestudio:0.19.0
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
python -m pytest                          # ~680 cases
python -m ruff check .                    # lint
cd web && npx vitest run                  # vitest + jsdom
pip install 'esphome==2025.12.7'
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
