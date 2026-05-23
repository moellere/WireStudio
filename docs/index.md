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
with a `--strict` no-regression gate; a pinned ESPHome version called
out in the README + workflow; CONTRIBUTING.md establishes the gate as
the merge bar. Next: an ESPHome version matrix in CI so component
support can be called out per release.

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

**Priority 4 — PCB layout.** *Deferred to 1.0+.* No work in flight;
not adding surface here until P1 is rock solid.

**Plumbing — already shipped.** API (`0.2`), web UI (`0.3` +
`0.6+`), USB bootstrap (`0.4`), agent (`0.5` + streaming), CSP
solver (`0.6`), fleet handoff (`0.7`), enclosure (`0.8`), KiCad
schematic (`0.9`), MCP server + KiCad symbol importer (`0.10`),
Docker single-image deploy + K8s manifest.

**Future** — multi-writer state backend so the studio can run as a
HA replica; agent eval harness against a task list; ESPHome version
matrix in CI (last 2 stables) so we can call out which components
work where.
