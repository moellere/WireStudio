# Roadmap to 1.0

Written against 0.39.0 (2026-10-18). Per-release deltas stay in
[`CHANGELOG.md`](../CHANGELOG.md); the status table in the
[README](../README.md#status) is the live record of what is verified.
This page says what 1.0 means, what has to land to get there, and what
is deliberately left out.

## What 1.0 means

The studio already has the surface area of a 1.0. What it does not yet
have is the set of promises a 1.0 makes. Four of them:

1. **`design.json` is stable.** `schema_version` moves from `0.1` to
   `1.0` once, with a migrator, and after that no breaking change ships
   without one. A design saved under 1.0 loads under every later 1.x.
2. **Nothing is advertised without a gate.** Every row in the README
   status table is either *Verified* (a CI or nightly gate fails the PR
   or the night) or *Experimental* (hidden behind the advanced toggle,
   with the caveat on the row). The middle tier, *Works (lighter
   checks)*, is gone: each entry is promoted or demoted.
3. **Install and upgrade are boring.** `pip install wirestudio` and the
   image upgrade in place: stores migrate, the user library survives,
   the pinned ESPHome has a published support table, and third-party
   data in the tree has its licence recorded.
4. **The agent and MCP surfaces are measured, not just present.** A
   fixed task list scores the agent; an MCP client exercises the server
   in CI.

Everything below is ordered by which promise it serves. Version numbers
are nominal: one theme can span two minors, two themes can share one.

## 1. Model completion and schema freeze

The last planned changes to the document shape, then the freeze.

- **0.40 — Connectors** ([#300](https://github.com/moellere/WireStudio/issues/300)).
  Pin kind `passthrough` and connection target `net`, so a harness
  connector can put pads on a subcircuit's internal nets and on lines
  another component already owns. Connector family `connector_1x02` …
  `connector_1x08` plus a 2x05 IDC, footprint from a `family` param.
  A desk-bike-shaped example pins the netlist. Closes the last "finish
  it by hand in KiCad" gap on the schematic.
- **0.41 — Retire the standalone LoRaWAN sugar.** `design.lorawan.gps`
  / `dht22` / `oled` lower to library components internally (phase A of
  the framework plan in `START.md`), so the Arduino path reads the same
  `components` / `buses` / `connections` the ESPHome generator does.
  The fields stay accepted until 1.0 and are rewritten by the migrator.
- **0.42 — Migration mechanism.** `wirestudio.migrate`: a chain of
  per-version functions over the raw document, run on load by the
  design stores, the CLI (`wirestudio migrate design.json`), the REST
  `POST /designs` path and `create_design` on MCP. A test loads every
  bundled example and every golden through it. The first real step is
  the sugar rewrite above; `0.1 → 1.0` is the second, cut at release.
- **Schema audit before the freeze.** One pass over
  `design.schema.json` for fields that exist for one example, names
  that differ between the schema and the API, and anything the
  generators ignore. Each is removed, renamed, or documented as
  deliberate. This is the only window to do it without a migrator step.

## 2. Promote or demote every "Works" row

The middle tier today, and what moves each row.

| Row | What promotes it | If that cannot happen |
|---|---|---|
| LoRaWAN standalone and external-component paths | the flash stage of the nightly hardware gate (below) | stays *hardware-validated*, labelled as such, no CI claim |
| Remote workbench | same gate, plus the transport tests already there | same |
| Meshtastic flash + config | nightly flash of a radio board, boot verdict by banner once one is established upstream, config read back | demote to *Experimental* |
| CircuitPython flash + code.py | nightly flash, boot verdict by the CIRCUITPY drive enumerating on the bench, `code.py` runs without a traceback on the serial console | demote |
| MicroPython flash + main.py | nightly flash, REPL banner, `main.py` runs without a traceback | demote |
| Component authoring | a user component compiled through `esphome config` in CI, not only the static gate; the check gate run on a corpus of bad components it must reject | stays *Works* only if the compile step is impossible, which it is not |
| ESPHome dashboard compile | a dashboard container in CI, a real compile of one example, the four wire assumptions asserted against it | demote to *Experimental* with the 2026.6.5 validation noted |
| MCP server | an MCP client in CI that connects, lists tools, drives one design from `create_design` to `render` and reads a resource | this is a test, not hardware; it lands |
| Thingiverse relay | nothing; third-party ranking | stays *Experimental* |
| Agent | the eval harness (section 5) | stays *Experimental* |

### The nightly flash stage (workbench phase 3)

Blocked on one spare board. Every board on the reference bench carries
live traffic, so the gate is non-destructive today. One dedicated
ESP32-S3 (or two: one plain, one radio) turns on `flash: true` for a
representative example per framework, and that single change retires
every "no live-flash gate" caveat at once. It is the highest-leverage
item on this page and the only one a human has to buy hardware for.

Once it runs: the gate flashes one example per framework per night,
reads the boot verdict through `workbench_verify_boot`, and the README
row cites the job. The CronJob stays inside the cluster (a public
repository cannot run fork PRs against a bench), so a failed Job is the
report, as with the existing gate.

### Functional loop (workbench phase 4)

Not started. For the ESPHome tier it is the difference between "boots"
and "works": provision against the bench's AP, assert the device's
native API answers and the expected entities appear (a sensor reading,
a switch that toggles), assert an MQTT publish for the `base_mqtt`
shape. For radio boards an SDR power-spectrum capture during TX catches
the deaf-radio wiring bug (an undriven FEM pin) that serial cannot.
Phase 4 is a 1.0 stretch goal: it raises the ESPHome tier from
*compiles and boots* to *behaves*, but 1.0 can ship without it if the
flash stage is in.

## 3. Framework parity and library coverage

Component blocks per framework today, out of 94:

| Framework | Blocks |
|---|---|
| esphome | 94 |
| circuitpython | 38 |
| tasmota | 24 |
| micropython | 16 |
| lorawan | 5 |

100% is the wrong bar: a Tuya MCU bridge has no CircuitPython meaning.
The bar is the one `library-coverage.md` already holds ESPHome to:
**zero unexplained gaps.** Extend `scripts/coverage_matrix.py` with a
per-framework column, a per-framework baseline file listing each
missing block with its reason (`no driver upstream`, `no meaning on
this framework`, `deferred: needs X`), and `--strict` failing the PR
on a gap with no entry. Then work the baselines down:

- **CircuitPython and MicroPython** share the same fragment shape;
  bring MicroPython to the CircuitPython set (sensors with a `mip`
  driver, displays, expanders) and both to every actuator and sensor
  that has an upstream driver.
- **Tasmota** covers what Tasmota's template format can express; the
  baseline will be long and honest.
- **LoRaWAN** gains a block for every sensor the payload codec can
  carry (the phase A refactor makes this a library-file edit).

Boards: all 26 have an ESPHome example. The enclosure block is on 7.
Section 4 covers the rest.

## 4. Physical outputs

- **PCB.** Routed DRC feedback in the UI (today it is a CI verdict),
  via-cost and keepout tuning exposed as route params, copper pours for
  the power nets. One bundled example **ordered from JLCPCB and brought
  up** on the bench, with the order's BOM / CPL / Gerber committed as a
  fixture. That is the only test of the fab bundle that is not a
  structural check; it costs real money and is a 1.0 gate only if the
  owner decides it is.
- **Enclosure.** `enclosure:` metadata for every board whose outline
  and mount holes are published (most of the 19 without one are M5Stack
  units and supermini boards with known dimensions). A lid with
  snap-fit or screw bosses, since a shell with no top is not an
  enclosure. The YAPP_Box question gets decided, not deferred: either
  the generator adopts it as the engine behind the same `.scad`
  endpoint, or the in-house one stays and the decision is recorded.
  One enclosure printed and fitted to its board, photographed in the
  docs.
- **Schematic.** 0.40 draws the sheet itself (board, peripherals,
  subcircuits as blocks, PWR_FLAGs, no-connects) and
  `scripts/check_sch.py` has kicad-cli read every example's netlist back
  from the geometry. What remains is coverage, not mechanism: a
  `schematic:` layout for the six subcircuits still drawn as stacks
  ([#311](https://github.com/moellere/WireStudio/issues/311)) and a
  `kicad.pin_map` for the twenty boards drawn as generic headers
  ([#312](https://github.com/moellere/WireStudio/issues/312)), which
  retires `global_label_dangling` from the ERC baseline. After that the
  baseline holds only what KiCad's pin types cannot express (the
  passive-header `pin_not_driven` cases and SPI's shared MISO) and the
  library-table warning a `sym-lib-table` in the image would remove.

## 5. Agent and MCP

- **Agent eval harness.** A fixed task list (twenty to thirty
  natural-language asks across the bundled examples: add a sensor, move
  it to a bus, resolve a pin conflict, build a driver from blocks)
  scored on three things: the final design validates, the intended
  change is present, and tool calls stayed under a budget. Runs on
  demand and nightly against the default model, with the score in the
  job summary. A regression gate holds the pass count. This is what
  promotes the agent from *Experimental*, and what makes a model swap
  evidence-driven.
- **MCP conformance in CI.** The `mcp` client library against the
  mounted server: connect with the token, list tools and resources,
  `create_design` → `add_component` → `solve_pins` → `render`, read
  `design://{id}/yaml`, confirm the `design-changed` event fired. Closes
  the "not run against a live MCP client" caveat.
- **Cost line.** The remaining items from the cost-tuning list in
  `START.md` (compact `search_components` results, `max_iterations`
  at 8) ship behind the eval so a cheaper turn is shown not to cost
  passes.

## 6. Operations and hygiene

- **`LICENSES.md`.** Promised since day one; third-party data is in
  the tree now (KiCad symbol and footprint references, Tasmota template
  ids sourced from `tasmota_template.h`, Meshtastic variant map,
  CircuitPython board ids). One file naming each source and its
  licence.
- **ESPHome support table.** Attribute `esphome-matrix` failures to
  components so the README can say "supports ESPHome 2026.6 through
  2026.10; `max98357a` needs 2026.6+". The matrix exists; the
  attribution and the table do not.
- **Store migrations.** The SQLite stores get a schema version and a
  migrator of their own; the JSON file stores need none beyond the
  design migrator. Documented backup and restore for both.
- **Upgrade test.** A CI job installs the previous release, seeds a
  design and a user component, upgrades to the candidate, and asserts
  both load and render identically.
- **Workflow actions.** The Node 20 runner deprecation deadline has
  passed; bump `actions/checkout`, `setup-python`, `cache` and
  `upload-artifact` to their current majors in one PR.
- **Flash size measurement** ([#219](https://github.com/moellere/WireStudio/issues/219)).
  Code is done; the four named boards need `esptool flash-id` once each
  when they reach the bench. Not a 1.0 blocker.

## 7. Documentation for 1.0

- The README status table becomes the 1.0 contract: two tiers,
  *Verified* and *Experimental*, every row citing its gate.
- `START.md` is a 100 KB working log. At 1.0 the decisions it holds
  (locked decisions, the framework axis, the MCP architectural
  principle, the schema) move into `docs/` as short reference pages,
  and `START.md` is reduced to the session-resume block and a pointer.
  The CLAUDE.md convention that cites it moves with it.
- `docs/user_guide.md` gains the paths that landed since it was
  written: inventory, component authoring, the six-framework flash
  dialog, the workbench, both build paths.
- Release notes for 1.0 list the migrations and the tier changes, not
  the features.

## Out of scope for 1.0

Stated so nobody waits on them.

- **LoRaWAN multi-region and TTN.** Safety-sensitive and untestable
  without a non-US915 gateway. The region table design is in
  `START.md`; it ships when a gateway exists to test it. 1.0 is US915
  and ChirpStack, documented as such.
- **Multi-user and HA replicas.** The studio is a single-user tool with
  one active design per process. A multi-writer backend is 1.x if a
  second user ever appears.
- **Reverse import** (ESPHome YAML to `design.json`). Would make the
  artifact a source, which the architecture rules out.
- **Multi-device projects.** One design, one device.
- **New targets.** Arduino/PlatformIO scaffolds, Zephyr, Zigbee/Thread
  on the C6, Printables search.
- **Component variants (`extends:`).** `aliases` covers the lookup
  case; inheritance waits for a second concrete need.

## Sequencing

The dependency order, not a calendar:

1. 0.40 connectors and 0.41 sugar retirement, since they change the
   model and must precede the freeze.
2. 0.42 migrator, then the schema audit.
3. Per-framework coverage baselines and the MCP conformance test, both
   pure CI, in parallel with 1 and 2.
4. Agent eval harness.
5. The flash stage of the hardware gate, as soon as the spare board is
   on the bench; the promote/demote pass follows its first green week.
6. Physical outputs and the hygiene list, in any order.
7. Docs consolidation and the `1.0` schema cut, last.

The release that carries the schema cut, the two-tier status table and
the upgrade test is 1.0. Phase 4 of the workbench, the JLCPCB order and
the printed enclosure are each welcome before it and not required by it.
