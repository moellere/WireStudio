# wirestudio

Agent-driven IoT device design tool. Describe a goal (or pick parts);
get ESPHome YAML, an ASCII wiring diagram, and a BOM that compile
under upstream ESPHome.

Produces ESPHome configs but is not affiliated with the ESPHome
project — see [`weirded/fleet-for-esphome`](https://github.com/weirded/fleet-for-esphome)
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

## Status

`v0.11.0` — on PyPI (`pip install wirestudio`). The studio has wide
surface area (YAML, schematic, enclosure, agent, MCP server, fleet
handoff, web UI) and a narrow set of things actually verified against
upstream tools. This section is honest about which is which, ordered
by how much it matters that it works.

Tiers, in priority order:

| Tier | Area | What it does | Verified by |
|---|---|---|---|
| **Verified** | ESPHome YAML production | render `design.json` → ESPHome YAML | `esphome config` passes on every bundled example, every PR ([gate](.github/workflows/esphome-config.yml)); nightly `esphome compile` smoke against a representative example ([compile](.github/workflows/esphome-compile.yml)) |
| **Verified** | CSP pin solver + compat checker | assign legal pins, surface boot-strap / ADC2-WiFi / voltage / locked-pin issues | unit tests + property checks in `tests/test_pin_solver.py` + `tests/test_compatibility.py` |
| **Verified** | Fleet handoff | push YAML to `fleet-for-esphome` ha-addon, optional compile + log relay | round-trip tests in `tests/test_fleet.py` |
| **Verified** | KiCad schematic | emit a SKiDL Python script the user runs locally to produce a `.kicad_sch` | every bundled example builds a KiCad netlist against the pinned upstream symbol libraries, every PR ([gate](.github/workflows/kicad-schematic.yml)) — no unresolved symbols or pins. Parts KiCad ships no symbol for (sensor/module breakouts) render as labeled generic headers |
| **Verified** | Parametric enclosure | OpenSCAD `.scad` from board mount-hole metadata | every enclosure-capable board renders through real OpenSCAD to a non-empty, manifold (closed, printable) solid, every PR ([gate](.github/workflows/enclosure-render.yml)) |
| **Works (lighter checks)** | MCP server | drive the design tools from Claude Code / Desktop over the Model Context Protocol | tool / auth / resource tests in `tests/test_mcp_*.py`; not exercised against a live MCP client in CI |
| **Experimental** | Thingiverse search relay | rank community models for a board | smoke-tested; depends on a third-party search API that ranks unevenly |
| **Experimental** | Agent (Claude tool-using) | natural-language design driving | works in practice; tool surface is small; no auto-eval against task list yet |
| **Deferred** | KiCad PCB layout | Freerouting + Gerber + JLCPCB CPL/BOM | 1.0+, not started |

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
  ghcr.io/moellere/wirestudio:v0.11.0
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
python -m pytest                          # ~440 cases, ~20s
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
