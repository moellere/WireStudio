# wirestudio — Working State

Living planning doc. Captures vision, decisions, schemas, and phase plan.
For day-to-day work tracking we'll spin off GitHub issues once a phase is
in flight; this doc stays as the strategic reference and decision log.

## Resuming a session

The repo on `main` is the source of truth — every shipped phase is
committed and pushed. To pick up where we left off:

1. Read this `Status` block + `Phasing` below to confirm what's done.
2. Check the **Next up** subsection for the agreed-upon next iteration.
3. Glance at recent commits (`git log --oneline -20`) for the texture of
   what shipped most recently. Each phase has a multi-line commit message
   that's effectively a per-phase changelog.
4. `pip install -e .[dev] && cd web && npm install` to get a working
   tree; `python -m pytest -q` and `cd web && npm test` should be green.

**Last shipped (2026-05-09 session).** Architectural pass off the
back of a Jules-authored review.

- **PR #18 — `Gemini refinements.md`.** External review doc (Jules)
  flagging async IO, separation-of-concerns, state-management
  abstraction, agent-streaming readability, CORS/rate-limit gaps,
  and a five-step bite-size PR plan. Doc only; no code.
- **PR #19 — Gemini plan, items 1–3 + 5 implemented.**
  - `_validate_design` helper in `wirestudio/api/app.py` (chosen over
    a global `@app.exception_handler` deliberately — Gemini's
    proposal #1's "global handler" variant was rejected as too
    broad: a top-level `ValueError` handler swallows internal bugs
    along with route-input failures).
  - `wirestudio/api/app.py` endpoints migrated to `async def`;
    `wirestudio/fleet/client.py` rewritten on `httpx.AsyncClient`.
  - `slowapi` rate limiting on `/agent/turn` + `/agent/stream`;
    CORS origins now read from `WIRESTUDIO_ALLOWED_ORIGINS`
    (comma-separated) with the localhost defaults preserved when
    unset.
  - `typing.Protocol` interfaces extracted: `DesignStore` in
    `wirestudio/designs/store.py`, `SessionStore` in
    `wirestudio/agent/session.py`. **No SQLite implementation
    yet** — Protocol shipped, alternative backend deferred.
  - `stream_turn_events` in `wirestudio/agent/agent.py` decomposed
    into smaller helpers; `run_turn` is now a thin collapsing
    wrapper over the streaming generator.

**Confirmed already-shipped (corrects an earlier stale "Next up"
block).** Both 0.5 follow-ons that were queued in the
2026-05-06 doc are in fact in `main`:

- `POST /agent/stream` SSE endpoint (`wirestudio/api/app.py:709`)
  yields `tool_use_start` / `tool_result` / `text_delta` /
  `turn_complete` events from `stream_turn_events`.
- `recommend` agent tool (`wirestudio/agent/tools.py:193`) plus
  the deterministic ranker at `wirestudio/recommend/recommender.py`
  and the `POST /library/recommend` HTTP surface
  (`app.py:511`).

**`esphome compile` smoke gate is in fact green.** The earlier
session log called it "never observed." Untrue: the nightly ran
successfully on 2026-05-07 and 2026-05-08, and a manual
`workflow_dispatch` on 2026-05-09 (run 25589055836) compiled
`garage-motion` in 4m17s on warm cache. PlatformIO + ESPHome
2025.12.7 toolchain + our codegen all hold up. Workflow itself
emits a Node 20 deprecation warning — not urgent (deadline
2026-09-16) but worth bumping `actions/checkout@v4` /
`actions/setup-python@v5` / `actions/cache@v4` next time someone
touches a workflow file.

**Last shipped (2026-05-06 session).** Wide cluster of work; the
through-line is "make the studio honest about what's verified" + a
focused first library expansion. Recent merges to `main`:

- **PR #11 — P1 YAML correctness gate.** `python scripts/check_examples.py`
  + `.github/workflows/esphome-config.yml` run every bundled example
  through upstream `esphome config` against pinned ESPHome
  `==2025.12.7`. CONTRIBUTING.md establishes this as the merge bar.
- **PR #12 — Library batch 1.** BH1750, SHT3xD, AHT10/AHT20,
  VL53L0X, PCF8574 (+ regression test for the ESP32-C3 chip-block
  emission bug the gate caught — `chip_variant` started with
  `esp32` so we used to emit `esp32c3:` as the top-level key
  instead of the unified `esp32: { variant: ESP32C3 }`).
- **PR #13 — Dev-loop hooks.** `.pre-commit-config.yaml` runs the
  gate at pre-push time; `.github/workflows/esphome-compile.yml`
  runs `esphome compile garage-motion` nightly + on manual
  dispatch (catches PlatformIO toolchain regressions and codegen
  drift even when no code changed).
- **PR #14 — Rebrand.** Project name `esphome-studio` → `wirestudio`
  per a request from the ESPHome maintainers. Package directory
  `studio/` → `wirestudio/`; env var `STUDIO_STATIC_DIR` →
  `WIRESTUDIO_STATIC_DIR`; Docker image
  `ghcr.io/moellere/esphome-studio` → `ghcr.io/moellere/wirestudio`;
  K8s manifest + docker-compose + nginx upstream all updated. Repo
  also renamed on GitHub side to `moellere/wirestudio` (GitHub
  preserves redirects from the old path).
- **PR #16 — Package-data move + 0.9.0 + release workflow.** A
  pre-flight `python -m build` revealed the wheel only shipped the
  Python code, not `library/*.yaml` / `schema/*.json` / `examples/*.json`
  — `pip install wirestudio` would crash at runtime. Fixed by
  moving the data dirs *inside* the package
  (`wirestudio/library/components/`, `wirestudio/library/boards/`,
  `wirestudio/schema/`, `wirestudio/examples/`) so setuptools
  auto-bundles them via `[tool.setuptools.package-data]`. Bumped
  version 0.1.0 → 0.9.0 to match the Docker tag. Added
  `.github/workflows/release.yml` — tag-triggered PyPI publish via
  OIDC Trusted Publisher with a wheel-data assertion that fails
  loudly if the package-data config drifts.
- **PR #17 — Library batch 2.** Survey-driven additions from
  `jesserockz/esphome-configs`. cse7766 (UART power meter, modern
  Athom/Sonoff plugs), hlw8012 (older 3-pin pulse meter),
  esp32_rmt_led_strip (ESP32 RMT-driven WS2812 — preferred over
  bit-banged `ws2812b` on ESP32 family), esp8285-1m board (the
  actual SoC inside cheap smart plugs). New `Bus.parity` model
  field (cse7766 enforces `EVEN`).

**State of `main` after this session:**

- 49 components × 14 boards × 20 examples
- 299/299 pytest pass; ruff clean
- 20/20 examples pass `esphome config` against ESPHome 2025.12.7
  (the canonical "is the studio's output real" gate)
- Docker image: `ghcr.io/moellere/wirestudio:main` (or `:v0.9.0`
  once that tag pushes from a developer machine)
- Package builds cleanly: `python -m build` produces a 116-file
  wheel that round-trips `pip install dist/*.whl` →
  `from wirestudio.library import default_library; default_library()`
  → render works.

**PyPI side trip — honest retrospective.** Mid-session, after the
rename, we got pulled into "let's claim the wirestudio name on PyPI."
That spawned: package-data move (real bug, justified), bump to
0.9.0 (cheap), release workflow with OIDC Trusted Publisher (real
work, deferred value), then a long battle with the sandbox git
proxy 503-ing every push that forced a batched-MCP-push workaround
+ a per-file commit pattern. Net assessment: the package-data fix
was load-bearing for ANY future `pip install` story; the release
workflow + name-claim are deferred work that didn't ship a
user-visible feature this week. **Not blocking.** Documented in the
"Deferred follow-ups" section below; pick up when there's an actual
reason to publish to PyPI.

**Deferred follow-ups (not blocking; pick up when relevant):**

- *PyPI name claim.* `python -m build && twine upload dist/*` from
  any clean checkout claims `wirestudio` on PyPI. After that,
  configure Trusted Publisher at
  https://pypi.org/manage/project/wirestudio/settings/publishing/
  pointing at `release.yml` + a `pypi` GitHub environment. Future
  releases are then `git tag vX.Y.Z && git push --tags`. The
  workflow's wheel-data assertion catches package-data drift before
  publish.
- *Library batch 3 candidates from the jesserockz survey.* Each
  needs more setup than a one-shot example: tuya MCU bridge (whole
  vendor class — switches/sensors/numbers/selects/climate/fan all
  hang off it), modbus_controller + sdm_meter (RS485 + a MAX485
  transceiver), bl0906 (6-channel energy meter), nextion HMI
  display.
- *Real `esphome compile` smoke.* The workflow exists
  (`esphome-compile.yml`) and runs nightly, but its first run
  hasn't been observed yet. Worth a manual `workflow_dispatch` to
  confirm.
- *Component-coverage matrix.* Make explicit which components have
  a passing example (today implicit in goldens / the gate). One-off
  script that walks the goldens + emits a checkbox table.
- *WebUI streamline.* "Basic vs. advanced" mode toggle proposed
  earlier in the session — show only the verified-tier surface
  (board + components + buses + YAML preview) by default; advanced
  reveals Schematic / Enclosure / Push-to-fleet / Agent. Reduces
  "AI slop" front-door optics. Not started.

**Next up candidates (current ordering, 2026-05-09):**

(Items 1–3 from the previous list shipped: library batch 3 in PR
#20, WebUI basic/advanced toggle in PR #22, coverage matrix in PR
#23. Ruff cleanup shipped in PR #21. PR #24 fixed a real
multi-turn agent regression — `_serialize_assistant_block`
sanitizes SDK parser metadata before history append. Live UI
testing surfaced two strategic items below.)

1. **Agent cost tuning.** Multi-turn agent sessions burn through
   API credits faster than expected on `claude-opus-4-7`. Tackle
   in priority of impact:
   1. **Configurable model tier.** Default to `claude-sonnet-4-6`
      (5× cheaper input/output than Opus) via env var
      `WIRESTUDIO_AGENT_MODEL`. Opus stays as an opt-in. Agent
      work here is tool-routing + dict editing, not frontier
      reasoning — Sonnet is sufficient.
   2. **Verify prompt caching is hitting.** The library JSON has
      `cache_control: ephemeral` at `agent.py:172` but
      `cache_read_input_tokens` hasn't been confirmed in usage.
      Also add a cache breakpoint on `SYSTEM_INSTRUCTIONS` (it's
      stable across turns, currently uncached).
   3. **Slim the system payload.** Today every system prompt
      carries the full library YAML for 56 components + 14
      boards (~30–50 KB). Emit a compact index by default
      (id + category + use_cases + aliases); add a
      `library_detail(id)` tool the agent calls when it needs
      the full sheet for a specific component.
   4. **Lower `max_iterations`.** Currently 12. Most design
      edits take 3–5 tool calls; cap at 8.
   5. **Compact `tool_result` payloads.** `search_components`
      returns full library cards; trim to id + category +
      score. Saves repeat-trip tokens.

   Combined estimate: 5–10× cheaper per turn with no real
   capability loss. Items 1.1 + 1.2 are this session's PR.

2. **MCP pivot (architectural decision, not yet scoped to code).**
   Expose the existing agent tool surface (`wirestudio/agent/tools.py`
   — 11 tools) as an MCP server. Users with a Claude Code or
   Claude Desktop subscription drive the studio from their host
   client; wirestudio pays nothing for LLM tokens. Subscription
   economics for the user, decoupling for us.

   The architectural principle (load-bearing for every MCP-era
   PR after this):

   > Wirestudio is the **compile engine** for ESPHome / KiCAD /
   > OpenSCAD / BOM outputs. It owns design.json and the
   > deterministic generators. **No LLM ever sits in a compile
   > or fetch path** — they're pure functions of design + library.
   > MCP is a thin chat surface over the **design-editing** tools
   > only. LLMs are useful for interpreting natural language into
   > design edits, proposing library entries from upstream
   > lookups, and explaining things; never for emitting an
   > artifact.

   Why this matters: contrast with KiCAD-MCP-Server
   (https://github.com/mixelpixx/KiCAD-MCP-Server), which makes
   the LLM the schematic engine — every component placement,
   every wire, every route is a tool call. Reproducibility
   suffers (same prompt → different schematic across runs);
   cost compounds (every edit burns tokens); audit trail
   evaporates (the bug is in a non-deterministic chat, not in
   a function). Wirestudio's design keeps the LLM out of the
   compile loop entirely. Same `design.json` → same
   `.kicad_sch` every time; diffable in git; cheap.

   ### Phase 1: wirestudio MCP server (the actual scope)

   1. **MCP server skeleton — shipped (PR #27, 2026-05-10).**
      `wirestudio/mcp/server.py` wraps all 12 tools from
      `wirestudio/agent/tools.py` as FastMCP tools; mounted into
      the existing FastAPI app at `/mcp` over Streamable HTTP.
      Bearer-token auth (`WIRESTUDIO_MCP_TOKEN` env var or
      auto-generated to `~/.config/wirestudio/mcp-token` mode
      0600). Mutating tools take `design_id` and persist back to
      the design store; read-only library tools skip storage.
      `WIRESTUDIO_MCP_ENABLED=false` short-circuits the wiring
      for envs that don't need it. `docs/MCP.md` covers config +
      env-var precedence; a polished walkthrough lands with the
      Phase 1.5 docs sweep.
   2. **`design-changed` SSE channel** on the HTTP API. Browser
      tabs subscribe per design id; any write to that design
      (from MCP, HTTP, or CLI) triggers the same channel and the
      browser re-fetches + re-renders. Closes the
      "drive-from-chat, see-it-in-the-browser" loop.
   3. **MCP resources** — `library://components`,
      `library://boards`, `design://{id}/yaml`,
      `design://{id}/ascii`. Read-only views the LLM can pull
      without burning tokens reconstructing them.
   4. **`set_active_design(id)` tool + UI plumbing.** Browser
      cookies the active id; MCP tools default to it. So the
      user's "add a BME280 to this design" prompt resolves
      against whatever the browser tab is showing. Until this
      lands, every design-bound MCP tool needs an explicit
      `design_id` and the design must already exist in the
      store (created via the web UI's save flow).
   5. **MCP docs.** Polished walkthrough on top of the
      Phase 1.1 `docs/MCP.md` skeleton — end-to-end "click here,
      paste this, ask Claude to do that" flow.

   Remaining 1.2-1.5 are the next 2-3 PRs.

   ### Phase 2: knowledge importers (bigger payoff than KiCAD-MCP)

   We do **not** integrate KiCAD-MCP-Server. Every capability
   it wraps (KiCAD symbol/footprint libs, JLCPCB part lookup,
   custom symbol generation, kicad-cli operations) is directly
   programmable from Python without an MCP middleman:

   - `.kicad_sym` and `.pretty` files ship with KiCAD; parse
     them with `kiutils` or by hand.
   - JLCPCB has a public part API; community tools
     (`easyeda2kicad`, JLCPCB BOM matchers) hit it directly.
   - `kicad-cli` (KiCAD 7+) is a real shell command for DRC,
     SVG export, etc.

   So we build small in-process **knowledge importers**:

   - `wirestudio.kicad.import` — `python -m
     wirestudio.kicad.import --symbol Sensor:BME280` emits a
     draft `library/components/bme280.yaml` snippet (or fills
     the `kicad:` block on an existing one). Closes the
     "no-kicad-mapping" tail without hand-writing each entry.
   - `wirestudio.jlcpcb` — `python -m wirestudio.jlcpcb check
     examples/garage-motion.json` walks the BOM, queries
     JLCPCB, surfaces "C25 (BME280) — 12 in stock @ $4.20" or
     "P/N not found, source manually." Pre-PCB-order
     feasibility gate.
   - `wirestudio.kicad.cli render --png` — shells out to
     `kicad-cli` to produce a PNG of the rendered schematic.
     Inline preview in the web UI; closes the "I can't see
     what the schematic looks like without leaving the studio"
     gap.

   These importers benefit the CLI and web UI too, not just
   the chat-driven flow. Same code reachable from MCP tools so
   Claude can call them on the user's behalf.

   ### Decisions locked before phase 1 (2026-05-10)

   - **Transport: Streamable HTTP** (the modern single-endpoint
     MCP HTTP transport, not the deprecated HTTP+SSE two-endpoint
     variant). Mounted into the existing FastAPI app at `/mcp`
     via the `mcp` SDK's ASGI integration — same process, same
     uvicorn, no subprocess. STDIO is rejected for wirestudio's
     shape: it would spawn a second wirestudio process per chat
     session with its own copies of `default_library()`, the
     design store, and session state, racing the browser-facing
     daemon over the same JSON files. HTTP also makes the
     `design-changed` SSE channel trivial — MCP writes and
     browser fan-out share an in-process pub/sub. A
     `python -m wirestudio.mcp.stdio` wrapper for Claude Desktop
     users who prefer subprocess config can be a ~30-line
     follow-up; ship HTTP first.
   - **Auth: bearer token, always required on `/mcp`.** Read
     from `WIRESTUDIO_MCP_TOKEN`; if unset, auto-generate a
     32-byte token at first start and persist it to
     `~/.config/wirestudio/mcp-token` (mode 0600). Log
     "Generated MCP token; copy from <path>" once. Operators
     using k8s Secrets / sops / etc. set the env var and the
     file path is ignored. Token guards `/mcp` only — existing
     `/design/*`, `/agent/*`, `/library/*` endpoints keep their
     current unauthenticated + CORS-gated + rate-limited model;
     hardening those is a separate effort and bundling it would
     balloon this PR's scope. Bind address inherits today's
     uvicorn config (no new flag) — Docker/K8s deployments
     already face the network correctly. Loopback-only-no-auth
     is rejected: wirestudio's actual shape is "daemon on a
     server, client on a laptop," and loopback would break that
     day-1 UX. OAuth 2.1 (the MCP spec's official multi-user
     flow) is deferred — right for SaaS-grade hosted MCPs,
     wrong for a single-operator homelab tool. Documented as
     upgrade path in `docs/MCP.md`.
   - **Embedded agent retirement: held.** `/agent/turn` and
     `/agent/stream` keep running unchanged through the MCP
     phase. They use the user's Anthropic key and stay useful
     for users without a Claude subscription, plus they're the
     only client today for the embedded session store. Revisit
     after Phase 1 + Phase 2 ship and we have usage signal on
     whether anyone still hits the embedded endpoints.

3. **Gemini plan tail (open items from PR #19's review doc):**
   - SQLite-backed `DesignStore` + `SessionStore` implementations
     (Protocol abstractions are in; alternative backend isn't).
   - `Field(description="…")` on `wirestudio.api.schemas` so
     `/docs` (Swagger UI) is self-documenting without reading
     source.
   - Split `docs/DEVELOPMENT.md` out of `README.md` (dev onboarding
     vs. user-facing pitch).
   - `print` → `logging` cleanup (audit `wirestudio/api`,
     `wirestudio/agent`, `wirestudio/fleet`).
   - Agent failure-mode tests: Anthropic 429 / connection error /
     mid-stream disconnect coverage in `tests/test_agent.py`.
     PR #24's `parsed_output` regression would have been caught
     by a "real-API-rejects-extras" test in this group.
   - (Decided against:) global `@app.exception_handler` — see PR #19
     rationale; helper-function approach is the chosen pattern.

4. **Library coverage gap follow-ups.** PR #23's matrix surfaced
   25 components and 6 boards without a bundled example. Each is
   a small example PR in the #12 / #17 mold. Useful steady-state
   work between substantive items.

5. 1.0 — KiCad PCB layout (reuse the schematic's netlist;
   Freerouting; Gerber + JLCPCB CPL/BOM).


**0.9 v2 -- library mapping expansion shipped.** The remaining 20
components + 7 boards now carry a `kicad:` block, taking coverage
from 21/41 + 6/13 to 41/41 + 13/13. Real-symbol mappings: BMP280,
DHT11/22, Rotary_Encoder_Switch, Buzzer (for RTTTL piezo). Generic-
header fallbacks (with the part name as `value:`) for breakouts
that lack a first-party `kicad-symbols` entry: CC1101, ILI9xxx,
LCD-PCF8574, LD2420, MAX7219, RDM6300, RF-Bridge, TM1638, XPT2046,
APA102, the four ESP32-S3/C3/CAM boards, M5Stack Atom + AtomS3,
TTGO T-Beam. Virtual ESPHome platforms (`adc`, `ads1115_channel`,
`gpio_input`, `gpio_output`, `pulse_counter`, `esp32_camera`) map
to small (1-2 pin) labelled headers so the schematic shows where
the real-world part connects -- the user replaces with the actual
switch / relay / camera-FPC after import.

New regression test (`test_every_library_entry_has_a_kicad_block`)
asserts 100% coverage going forward; the next library addition
without a `kicad:` block fails it loudly with a "add one referencing
the matching kicad-symbols entry, or a generic Connector_Generic
header with the part name as `value:`" hint. Existing fallback
test rewritten to inject a synthetic unmapped entry rather than
depending on a real-but-unmapped library_id (which drifts as
mappings land).

291 pytest (+1 guardrail), 125 vitest, ruff + tsc + vite build clean.
- Printables search source. Currently deferred -- Printables
  doesn't expose a public REST/GraphQL API and scraping their
  internals is fragile (the page-level GraphQL endpoint changes
  without notice + their CDN aggressively rate-limits unauthenticated
  reads). Revisit when they ship a documented API or a community
  proxy stabilises. The studio surfaces the gap honestly via the
  search-status endpoint (`available: false, reason: "Printables
  search deferred -- no public API yet"`) so users see why it's
  empty rather than wondering if something broke.
- 0.9 — KiCad schematic export. Full scope in the Roadmap section
  below; key points: SKiDL-driven, `kicad:` reference block per
  component/board (we stay canonical for ESPHome semantics, KiCad
  for schematic rendering), `wirestudio/kicad/scaffold.py` helper for
  cheap library expansion, PCB deferred to 1.0+.

**0.9 v1 -- KiCad schematic export shipped.** New `kicad:` reference
block on `LibraryComponent` + `LibraryBoard` (KicadSymbolRef:
symbol_lib + symbol + footprint + pin_map + value override).
Mappings landed for the entire library: every one of the 41
library components and 13 boards carries a `kicad:` block (v1
shipped 21+6, v2 closed the rest). Real-symbol mappings cover the
parts with first-party `kicad-symbols` entries (BME280, BMP280,
DS18B20, MPU6050, ADS1115, MCP23008/17, SSD1306, WS2812B,
MAX31855, HX711, TSL2561, SX1276, MAX98357A, DHT11/22,
Rotary_Encoder_Switch, Buzzer for RTTTL piezo). Generic
`Connector_Generic` headers with the part name as `value:` cover
breakouts without a first-party entry (HC-SR501, HC-SR04,
RCWL-0516, RC522, ST7789, UART GPS, CC1101, ILI9xxx, LCD-PCF8574,
LD2420, MAX7219, RDM6300, RF-Bridge, TM1638, XPT2046, APA102,
ESP32-S3/C3 DevKits, ESP32-CAM AI-Thinker, ESP32-WROVER-CAM,
M5Stack Atom + AtomS3, TTGO T-Beam). Virtual ESPHome platforms
(`adc`, `ads1115_channel`, `gpio_input`, `gpio_output`,
`pulse_counter`, `esp32_camera`) map to 1-2 pin labelled headers
so the schematic shows where the real-world part connects.

`wirestudio/kicad/generator.py` walks the design and emits a SKiDL Python
script. The studio doesn't import or run SKiDL itself -- a hard
runtime dep would pull in numpy + EDA-toolchain weight that's wrong
for a server. The user installs SKiDL locally and runs the script
to produce `<design_id>.kicad_sch`. Pin-name remaps from each
component's `kicad.pin_map` bake into the connection lines (the
BME280's VCC role becomes `c_bme1["VDD"]` to match the Bosch
symbol's pin name); rails / buses / GPIO / expander_pin / component
targets each render as the right SKiDL net expression.

`POST /design/kicad/schematic` returns the script text with a
Content-Disposition: attachment header. Header gains a **Schematic**
button (between Solve pins and Push to fleet) opening
`SchematicDialog` with usage instructions and a one-click
`.skidl.py` download.

15 new tests: 13 pytest (each bundled example compiles, mappings
flow through, fallback emits TODO, every net kind renders right,
component-target round-trip with the ADS1115 hub split, identifier
sanitisation parametric); 2 API contract; 5 vitest (download
round-trip, success affirmation, 422 banner, design-id in the
usage snippet, SKiDL doc link).

PCB layout (Freerouting + Gerber export) deferred to 1.0+ as
planned.

**0.8 v2 -- enclosure search relay shipped (Thingiverse).**
`wirestudio/enclosure/search.py` adds a pluggable per-source search client.
v2 ships the Thingiverse implementation (documented API, free
`THINGIVERSE_API_KEY` token from https://www.thingiverse.com/developers,
~300 req/hour rate limit). The Printables source is included in the
catalogue but always reports `available: false, reason: "Printables
search deferred -- no public API yet"`; deferred deliberately because
their public API is undocumented, their internal GraphQL endpoint
changes without notice, and their CDN rate-limits unauthenticated
reads. Revisit when a documented API or stable community proxy
appears.

`GET /enclosure/search?library_id=<board>&query=<refinement>` runs the
constructed query (`<board.name> enclosure [<refinement>]`) against
every configured source and returns the merged ranked results
alongside per-source statuses so the UI can render configuration
hints when a source is unconfigured. `GET /enclosure/search/status`
surfaces the same status list ahead of any actual search.

The header **Generate enclosure** button is replaced by a single
**Enclosure** button that opens a tabbed dialog: Generate (the
original parametric `.scad` download path) and Search (the new
relay). The Search tab fires an initial query on first open with
no refinement, renders per-source status banners (emerald for
available, amber for unavailable + the configure hint), and shows
results as cards with thumbnail + creator + likes that link out to
the source. A free-text refinement field re-fires the search; a
cancellation guard via a ticket ref prevents stale responses from
overwriting newer ones.

20 new pytest cases (17 search-client unit tests + 3 endpoint
contract tests using the existing `httpx.MockTransport` pattern from
the fleet client). 5 new vitest cases for the dialog (Generate
success + 422 banner; Search initial fetch + result rendering;
refinement round-trip; configuration-hint surface when no source
is available).

**0.8 v1 -- parametric OpenSCAD enclosure generator shipped.** Each
of the 5 dev-board YAMLs (`wemos-d1-mini`, `esp32-devkitc-v4`,
`nodemcu-32s`, `nodemcu-v2`, `ttgo-lora32-v1`) gains an `enclosure:`
block carrying PCB outline (length / width / thickness in mm), mount
hole positions + diameters, and port cutouts (USB micro on every
board, plus the SMA jack on the TTGO LoRa32 V1). ESP-01S deliberately
skips the block -- it's a header-mount module without a clear PCB
outline.

`wirestudio/enclosure/openscad.py` walks a design's board metadata and
emits a self-contained `.scad` file: tunables block at the top
(wall, floor, clearance, standoff geometry, port_clearance) so the
user can dial in fit without re-rendering, then a `module shell()`
that subtracts an inner cavity + every defined port cutout from the
outer hull, then a `module standoffs()` that places M2.5-clearance
posts at each mount hole. Boards without enclosure metadata raise
`EnclosureUnavailable` cleanly.

`POST /design/enclosure/openscad` returns the text with a
`Content-Disposition: attachment; filename="<design_id>.scad"`
header. Header gains a **Generate enclosure** button that synthesises
the request from the live design and triggers a browser download.

10 new pytest cases pin the renderer (tunables present, dimensions
appear verbatim, mount holes / ports render on the right walls,
short_a vs short_b cutouts translate correctly, ESP-01S fallback);
3 new API tests cover the endpoint contract.

**Drag-and-drop pinout shipped.** New `PinoutView` component renders
a two-column view in the component-instance inspector: left lists
every board GPIO with capability badges (boot strap, ADC1/ADC2,
input-only, serial console, I2C SDA/SCL); right lists this instance's
gpio-target connections as draggable chips. Dropping a chip onto a
board pin rewrites the connection's target. Conflict detection paints
the rose tone on pins another component already uses; the row that's
currently bound (on this instance) glows emerald with a "← <role>"
breadcrumb.

The Connections section gains a Form/Pinout toggle: Form (default)
covers every target kind including the new component target; Pinout
is the visual shortcut for board-pin-heavy designs. Native HTML5
drag/drop -- no library dependency, ~200 lines of TSX, ~150 lines of
test coverage. 7 new vitest cases (empty states, capability badge
rendering, pin-currently-here annotation, conflict detection, the
drag-start-then-drop round trip, and the empty-payload no-op).

**ADS1115 hub-only split shipped.** New `kind: "component"` connection
target lets one component instance reference another by id. The
generator surfaces the referenced instance as `parent` in the
template's Jinja context (sibling to `bus`); the pin solver fills
unbound `kind: component` targets by picking the first design
component whose library_id matches the role's `parent_library_id`
hint on the library Pin. ConnectionForm gains a `component` option
in the kind dropdown with a sibling-instance picker.

`ads1115` is now hub-only -- it registers the `ads1115:` block but
emits no sensors. Each logical reading is a separate
`ads1115_channel` instance with its own multiplexer/gain/update_interval
params and a HUB connection (kind=component) pointing at the hub.
Channels show up as first-class components in the inspector instead
of being buried inside a `channels` array param. The schema /
model / generator / solver / web type extension is generic; future
hub patterns (RGB controllers, multiplexed mux chips) can reuse it
without further surgery.

**SSE log relay shipped.** New `GET /fleet/jobs/{run_id}/log/stream`
endpoint server-side-polls the addon's `/ui/api/jobs/{id}/log` at
~300ms (vs the browser-driven 1.5s) and emits Server-Sent Events:
`data:` frames carry `{log, offset, finished}` chunks; an
`event: done` frame caps a successful run; an `event: error` frame
surfaces logical failures (unknown run_id) so the client knows not
to retry. `interval_ms` query param tunes the cadence with a 100ms
floor.

PushToFleetDialog tries `EventSource` first; on transport error it
closes and falls back to the existing 1.5s `setTimeout` polling
loop, picking up at the offset of the last accepted chunk so no log
bytes are lost. The status pill shows `(stream)` or `(poll)` so
testers can see which path is in use. EventSource isn't on jsdom by
default, so the existing polling tests stay green; the SSE path got
3 new tests using a FakeEventSource stub (chunk -> done flow,
transport-error fallback to polling, server-emitted error event).

241 pytest (+3), 108 vitest (+3), ruff + tsc + vite build clean.

**Library expansion v3 shipped (5 components).**
- `bmp180` — older Bosch barometric T/P (I2C, fixed 0x77, no humidity).
  Renders the deprecated-but-supported `bmp085` ESPHome platform; covers
  legacy modules people still have on hand.
- `htu21d` — T/H (I2C, fixed 0x40). Drop-in for designs that don't need
  pressure; covers the Si7021 / SHT2x families on the same protocol.
- `max31855` — K-type thermocouple amp (SPI, MISO-only). Range -270 to
  +1372°C. Optional `reference_temperature: true` publishes the cold-
  junction reading. CS is per-component native (`spi_cs`).
- `hx711` — 24-bit load-cell ADC, custom 2-wire serial (DOUT + SCK on
  free GPIOs, no bus). Channel A 128/64x or channel B 32x via the
  `gain` param.
- `tsl2561` — ambient light / lux (I2C). Address selectable across
  0x29/0x39/0x49 via the ADDR pin; gain + integration_time tunables.

10 new tests: 5 yaml-gen smoke (each component renders the expected
ESPHome platform with the right pin / address / param wiring) + 5
recommender pin tests (thermocouple, weight, lux, pressure, humidity
all land on the right top pick).

**Library expansion: ADS1115 + MPU6050 shipped.**
- `library/components/ads1115.yaml`: 4-channel 16-bit ADC over I2C.
  Renders an `ads1115:` hub block + per-channel `sensor:` entries
  driven by a `channels` param (multiplexer, name, gain, update_
  interval). Address selectable via the ADDR pin maps to 0x48-0x4B.
  Solves the ADC2/WiFi conflict on classic ESP32 by giving the
  chip a known-good external ADC.
- `library/components/mpu6050.yaml`: 6-axis IMU (3-axis accel +
  3-axis gyro + die temp). All seven channels emitted in one
  `sensor:` entry; AD0 selects 0x68/0x69. The INT pin isn't modeled
  yet -- a binary_sensor in esphome_extras handles motion-wake until
  someone needs richer support.
- 4 new yaml-gen tests (per-channel rendering, hub-with-no-channels
  smoke, full IMU axis emission, both parts sharing a single I2C
  bus) + 2 new recommender tests (adc query lands on ads1115, IMU
  queries land on mpu6050).

**Inspector composition tests shipped.** New `Inspector.test.tsx`
(9 tests) covers the DesignInspector composition: null-design
fallback, component row rendering with id+label+library_id, section
counts (Components/Buses/Requirements/Warnings) reflecting the design,
selection callback firing with `kind: "component_instance"` when a
row is clicked, the per-row ✕ wiring through to onRemoveComponent,
the Compatibility section's hide/show on warning presence, the Fleet
section's gate on the design's fleet block, and the empty-components
affordance. api.getComponent is mocked at the boundary; no real
network calls.

228 pytest (+6), 105 vitest (+9), ruff + tsc + vite build clean.

**1-wire bus type promotion shipped.** The `Bus` model gains a `pin`
field (single-pin bus, parallel to the multi-pin sets on i2c/spi).
yaml_gen renders a top-level `one_wire:` block per 1-wire bus
(`{platform: gpio, pin, id}`) so multiple sensors on a shared physical
bus emit a single bus block, not one per sensor. The DS18B20 template
no longer carries a `one_wire:` block of its own -- it reads `bus.id`
and emits `dallas_temp` with the matching `one_wire_id`. Pin-solver
and bus-pin compatibility checks gain a `1wire` entry; the BusList
editor surfaces a `pin` field on 1wire cards instead of the previous
"lives on each component" placeholder. design.ts's `neededBusTypes`
and `defaultTargetForPin` recognise the new `onewire_data` pin kind.

New `examples/multi-temp.json` + golden artifacts pin the round-trip:
two DS18B20s with distinct ROM addresses sharing `wire0` on D6 plus
an RCWL-0516 microwave motion sensor on D5. 4 new pytest cases (2
yaml-gen, 1 ascii-gen golden, 1 yaml-gen single-instance smoke).

**Strict-only push gate shipped.** `POST /fleet/push` now accepts
`strict: bool` and refuses the push with the same `strict_mode_blocked`
envelope that `/design/render?strict=true` uses when any warn/error
compat entry remains. The studio app threads its global strict-mode
toggle into `PushToFleetDialog` as a prop; the dialog renders an
amber notice when strict is on and the result-banner formatter
recognises the envelope so the user sees the friendly message
instead of the raw JSON. 2 new pytest cases pin the gate.

**Library expansion: RCWL-0516 + DS18B20 shipped.**
- `library/components/rcwl-0516.yaml`: microwave doppler motion sensor.
  Same VCC/GND/OUT pin set as the HC-SR501 PIR but draws ~3 mA peak
  vs ~50 mA, so it complements the PIR for battery builds. No params
  (sensitivity/on-time live on the SMD resistors). Recommender ranks
  it alongside the PIR for `motion`/`occupancy`/`presence` queries.
- `library/components/ds18b20.yaml`: first 1-wire library citizen.
  VCC/GND/DATA + the canonical 4.7kΩ pull-up between DATA and VCC
  encoded in `passives`. Each instance renders its own
  `one_wire: [{ id: <comp>_bus }]` block plus a `dallas_temp` sensor
  pointing at it; the existing `_deep_merge` of list-typed top-level
  blocks means N independent DS18B20s on N different pins coexist
  cleanly. Sharing a single physical bus among multiple sensors is
  noted in the component's `notes` field but not yet wired -- that's
  a 1-wire-bus promotion candidate above. Params expose `address`
  (ROM), `update_interval`, `resolution` (9-12 bits).

7 new pytest cases (yaml gen for both + recommender ranks both +
strict push). 220 pytest, 96 vitest, ruff + tsc + build clean.

**ConnectionForm + PushToFleetDialog component tests shipped.** New
`ConnectionForm.test.tsx` (7 tests) covers the LockToggle's three
states (unlocked / locked-in-sync / locked-diverged), the disabled
state when no pin is bound, the onLockedPinChange round-trip, the
inline mismatch hint, and the non-render guard for non-gpio targets.
New `PushToFleetDialog.test.tsx` (6 tests) covers the status fetch
gating Push, the device-name round-trip in the fleetPush payload,
no-run_id-no-log-viewer, single-shot finished-on-first-poll, and
`vi.useFakeTimers` driven multi-chunk polling that confirms the
1.5s gap is honoured and the second poll fetches at the offset
returned by the first. Plus an error-path test that surfaces
"log error: addon disconnected" and stops the loop.

**Strict-mode toggle shipped.** `POST /design/render?strict=true`
now refuses to produce YAML/ASCII when any compatibility entry of
severity warn or error remains; the response is a 422 with detail
shape `{error: "strict_mode_blocked", message, warnings[]}`. Header
gains a "strict" checkbox (amber-tinted when on, plain when off);
flipping it re-fires the debounced render with the new flag in the
deps array. The existing renderError banner gets a small upgrade to
recognise the `strict_mode_blocked` envelope and surface the count
instead of dumping the JSON envelope. info-severity entries are
deliberately left as a permissive signal -- they're educational
(voltage_limit on D1 Mini A0, current-budget guidance) and don't
block. 3 new pytest cases pin the gate.

**Capability picker alternatives disclosure shipped.** Each match in
the picker now carries a small "▸ N alternatives" toggle below its
metadata row. Clicking expands an inline list of the OTHER currently-
visible matches (filtered through the same bus filter) with their
score and the delta against the row -- emerald-tinted when an
alternative beats the row's score, muted-zinc when it's worse.
Single-expanded-at-a-time policy: opening one closes the previous so
the result list never grows multiple stacked alternatives panels.

**RTL/jsdom component tests scaffolded.** New `vitest.config.ts`
extends the existing vite config with `environment: "jsdom"` and a
setup file that imports `@testing-library/jest-dom` matchers. First
two suites cover the surfaces with the most state machinery:
- `BusList.test.tsx`: rename draft commits on Enter, reverts on
  Escape (caught and fixed a real bug -- the previous Escape handler
  blurred the input, racing the queued state reset and leaking the
  stale draft through commitRename), rejects collision with another
  bus's id, inline compat warnings filter to the matching card.
- `CapabilityPickerDialog.test.tsx`: alternatives disclosure shows
  "N alternatives" toggle on every multi-match list, expansion is
  single-row-at-a-time with aria-expanded synchronised, score delta
  carries the sign and the right tint, bus filter hides + counter
  surface and the unhide path. Plus an Add round-trip that confirms
  onAdd receives the library_id and the row flips to the affirmation.

15 new vitest cases (53 -> 68 -> 83); the network surface is mocked
at the api/client boundary so the suite stays fast (2.4s for all 83).

**Bus rename propagation + inline bus card warnings shipped.** New
`renameBus(d, oldId, newId)` helper rewrites the bus's id and every
`connection.target.bus_id == oldId` atomically. The bus card's id
input now keeps a local draft and commits on blur or Enter (Esc
reverts) so a mid-typing intermediate like "" or "i" doesn't briefly
orphan connections; the field tints amber while dirty and red on a
collision with another bus's id. `updateBus` silently strips an `id`
key from its patch so nothing else sneaks past renameBus. Each bus
card now also filters whole-design compatibility warnings down to
its own (matched on `component_id`) and renders them inline below
the pin grid in severity-tinted rows -- so a boot-strap warning on
`spi0.CLK` shows up on the spi0 card, not just under the design's
Compatibility section.

**Pin-lock inspector toggle shipped.** Connection rows in the inspector
gain a 🔓/🔒 button next to the gpio pin selector. Click 🔓 lock to
write `locked_pins[role]` for the currently bound pin; click 🔒 to
clear it. The lock badge turns amber when the bound pin diverges from
the lock and an inline "solver will flag a mismatch" hint surfaces
the discrepancy without leaving the row. Reads/writes go through new
`readConnections.locked_pin` and `setLockedPin` helpers in
`web/src/lib/design.ts`.

**Bus editor shipped.** Design Inspector now has a Buses section with
one card per bus. Each card lets the user rename the id, edit the
type's pin slots (`sda`/`scl` for i2c, `clk`/`miso`/`mosi` for spi,
`tx`/`rx` for uart, `lrclk`/`bclk` for i2s) plus the type's tunable
(frequency_hz / baud_rate). Pin selectors are populated from the
board's `gpio_capabilities`; an "+ add bus" picker creates a fresh bus
seeded from `board.default_buses` when present. Removing a bus
intentionally leaves connections that target it dangling so the
render-time error makes the inconsistency loud.

**Pin locks shipped (permissive).** `Component.locked_pins` is no
longer dead code:
- Solver applies locks before solving. Empty gpio targets get filled
  from the lock; bound targets that disagree surface a
  `locked_pin_mismatch` warning (the bound pin stays put — divergence
  might be intentional). Lock keys that aren't real roles on the
  library component surface a `locked_pin_unknown_role` warning.
  Locks against non-gpio targets surface `locked_pin_wrong_kind`.
- compatibility.py validates the lock's target pin against the role's
  required capability; a `locked_pin_invalid` (severity: error) fires
  when, say, an `analog_in` lock lands on a pin without `adc`.
- 6 new tests pin all paths.

**Capability picker bus filter shipped.** Dialog now receives the
design's bus types (i2c/spi/uart/i2s/1wire) and offers a "match my
buses" checkbox (default on). When on, ranked matches whose
`required_components` include a bus the design lacks are dropped
from the visible list with a "N hidden by the bus filter" note.
Uncheck to see everything (e.g., when the user is happy to add a
new bus). The agent's recommend tool is unchanged — this is a
UI-side filter only.

**Capability-driven "Add by function" picker shipped.** New backend
endpoint `GET /library/use_cases` aggregates the library's canonical
capability vocabulary (sorted by component count, with a 3-id sample
per row). Header button **Add by function** opens a two-pane dialog:
left shows the use_case rows + a free-text override; right runs the
existing `/library/recommend` and renders ranked matches with rationale,
current draw, voltage range, and a one-click Add button that reuses the
same `handleAddComponent` path as the inspector. The first result is
badged "top pick" but the user can grab any of the eight returned —
the case where you already have a specific part on hand.

**0.7+ build-log polling shipped.** Studio relays the addon's HTTP
fallback `GET /ui/api/jobs/{id}/log?offset=N` as `GET /fleet/jobs/{run_id}/log`
and the Push-to-fleet dialog tails it (1.5s poll) into a scrolling
viewer below the result banner once a compile is enqueued. 6 new fleet
tests cover unconfigured 503, unknown run_id 502, and the offset-based
chunking contract.

**ADC2/WiFi conflict detection shipped.** All three ESP32 boards
(esp32-devkitc-v4, nodemcu-32s, ttgo-lora32-v1) carry `adc1` / `adc2`
pin tags. compatibility.py emits `adc2_wifi_conflict` warnings when an
analog_in lands on an ADC2 pin on a classic ESP32 (chip_variant ==
"esp32"); the pin solver uses a secondary preference key so unbound
analog_in connections land on ADC1 pins (GPIO32-39) by default. 4
new tests pin both paths.

**0.7 distributed-esphome handoff shipped.** `wirestudio/fleet/client.py`
talks to the ha-addon's `/ui/api/*` surface using a Bearer token.
`GET /fleet/status` + `POST /fleet/push` expose this to the UI;
**Push to fleet** in the header opens a modal with the device-name
input, a status banner, and a "compile after upload" toggle. Config:
`FLEET_URL` + `FLEET_TOKEN` env vars on the API server. Tests use
`httpx.MockTransport` to stand in for the addon -- 18 new tests
covering filename validation, configured-vs-unauthorized status,
pending-rename create flow, in-place overwrite, compile enqueue,
and the HTTP contract end-to-end.

## Status (as of 2026-05-04)

- **0.1 MVP shipped.** `python -m wirestudio.generate examples/<name>.json`
  produces ESPHome YAML + ASCII diagrams pinned by goldens.
- **0.2 HTTP API shipped.** FastAPI server at `python -m wirestudio.api`,
  endpoints under `/library/*`, `/design/*`, `/examples/*`. Auto-generated
  OpenAPI docs at `/docs`. Pure layer over the generators, no server-side
  state. Permissive CORS for the 0.3 web UI.
- **0.3 web UI v1 shipped.** React 19 + Vite + Tailwind v4 under `web/`.
  Three-pane layout (examples/library sidebar / design preview /
  inspector). Editable surfaces:
  - **design view**: board picker (dropdown of all library boards),
    fleet metadata (device_name + tags), requirements list (add /
    edit / remove), warnings list (add / edit / remove);
  - **component-instance view**: params (form generated from the
    library's `params_schema`), connections (per-row editor with
    target-kind selector and rail/gpio/bus/expander_pin sub-controls).
  Add/remove component instances from the components list (with
  auto-wiring: rails picked by voltage match, bus pins linked to a
  matching bus, missing buses auto-prepended from the board's
  `default_buses`). Edits land in local design state and re-render via
  debounced (250ms) `POST /design/render`. Reset reverts to the loaded
  example; Download JSON saves the modified design.json. Vitest covers
  `lib/design.ts` (41 tests). Drag-and-drop pinout and bus editor
  are follow-on iterations.
- **0.4 USB device bootstrap shipped.** "Connect device" header button
  opens a modal that runs `esptool-js` over WebSerial. Reads chip
  family + MAC, normalizes the chip name (ESP32-S3 -> esp32s3),
  filters the board library to candidates with the matching
  `chip_variant`, and on adopt seeds a fresh `design.json` with the
  picked board pre-filled and an `info` warning carrying the
  detected chip + MAC. esptool-js is dynamic-imported so vitest
  (no `navigator.serial`) doesn't choke; Vite code-splits the
  per-chip stub flashers into separate chunks loaded only on demand.
  WebSerial is Chromium-only so a fallback notice steers
  Firefox/Safari users to the manual flow. Vitest +8 tests
  (49 total) cover chip-name normalization, board candidate
  matching, and bootstrap-design shape.
- **0.5 agent layer shipped.** Claude tool-using agent at
  `wirestudio/agent/` (`tools.py`, `session.py`, `agent.py`). 10-tool
  surface: `search_components`, `list_boards`, `set_board`,
  `add_component`, `remove_component`, `set_param`, `set_connection`,
  `add_bus`, `render`, `validate`. Manual agentic loop on
  `claude-opus-4-7` with adaptive thinking; library JSON cached in the
  system prompt for ~90% read discount on subsequent turns; per-turn
  design context goes in the user message so the cache stays valid as
  the design changes. Conversation history persists in
  `sessions/<id>.jsonl` (plain role/text only; the tool ceremony stays
  in memory). API: `POST /agent/turn` returns updated design +
  assistant text + a tool-calls log; `GET /agent/status` reports
  availability; `GET /agent/sessions/{id}` returns the JSONL contents.
  Agent endpoints 503 cleanly when `ANTHROPIC_API_KEY` is unset. Web
  UI: header `Agent` button opens a sidebar drawer; chat replaces the
  working design on each turn so the live YAML/ASCII updates as the
  agent edits. Pytest +24 (114 total) covers every tool implementation,
  session JSONL round-trip, and the API contract (status / 503 / 404).
- **0.6 CSP solver + port compatibility validation shipped.** Pin
  solver at `wirestudio/csp/pin_solver.py`. Port compatibility validator at
  `wirestudio/csp/compatibility.py` walks every gpio + bus pin assignment
  and emits codes (`input_only_as_output`, `boot_strap_output`,
  `serial_console`, `voltage_limit`, `function_unsupported`) based on
  the board YAML's semantic tags (`boot_high`, `boot_low`, `serial_tx`,
  `serial_rx`, `pull_up_external`, `pull_down_external`, `adc_max_1v`,
  `no_pwm`, `no_i2c`, `no_interrupt`, `no_pull_internal`). Auto-runs
  on every `/design/render`, `/design/validate`, and
  `/design/solve_pins`; surfaces in the Inspector's design view as a
  Compatibility section, plus filtered to per-instance in the
  component-instance view. Solver also deprioritizes boot-strap and
  serial pins for output assignments. Pytest +14 (138 total) covers
  every code path including a known-examples snapshot test that
  catches regressions in the board YAML tags.

- **legacy 0.6 entry below kept for context.** `wirestudio/csp/pin_solver.py` -- pure
  Python, no external solver lib (problem size is tiny). Fills every
  unbound connection: `kind: gpio` with empty pin -> a board GPIO
  matching the library pin's capability (digital in/out -> any gpio,
  analog_in -> needs `adc`, with strap/boot/builtin_led pins
  deprioritized for outputs); `kind: bus` with empty bus_id -> first
  matching design bus, with a "no_matching_bus" warning when the type
  is missing; `kind: expander_pin` with empty expander_id -> next free
  slot on the first io_expander. Already-bound pins are left alone
  (the user's call) but conflicts surface as warnings. Current budget
  is checked: peak draw > `power.budget_ma` emits a `current_budget`
  warning. Pure: returns a new design dict alongside the diff and any
  warnings. Wired in three places: a `solve_pins` agent tool (the
  agent uses it after a non-trivial wiring change), a standalone
  `POST /design/solve_pins` HTTP endpoint, and a `Solve pins` header
  button in the web UI that shows a transient banner with the
  assignments + warnings. Pytest +12 (126 total) covers the
  no-mutation invariant, gpio/bus/expander assignment, no-candidate
  paths, conflict + budget warnings, and the "no board"/"unknown
  board" error paths.
- **12 example designs** spanning ESP8266 + ESP32 + ESP-IDF + Sonoff:
  garage-motion, awning-control, wasserpir, oled, bluemotion,
  distance-sensor, securitypanel, rc522, esp32-audio, bluesonoff,
  wemosgps, ttgo-lora32.
- **Library:** 6 boards, 14 components, 5 bus types (i2c/spi/uart/1wire/i2s),
  4 connection target kinds (rail/gpio/bus/expander_pin).
- **Tests:** 89 passing (CLI generators + API), ruff clean.
- **Decided:** option 1 (`kind: expander_pin`) for expander wiring;
  shipped. UI-first phasing: API → Web UI → USB bootstrap → Agent → CSP.

## Vision

Agent-driven ESPHome device design tool. User describes a goal (or picks parts);
tool produces an ESPHome YAML, an ASCII wiring diagram, a BOM, and (later) hands
the device off to `weirded/distributed-esphome` for compile + OTA deploy.

Sister project to `weirded/distributed-esphome`. Knowledge base seeded from
`esphome/esphome` (schemas) plus a hand-curated electrical library.

## Decisions locked

- **Repo:** `moellere/wirestudio` (new, just created).
- **Mode:** **Permissive.** CSP/electrical violations surface as `warnings[]`,
  do not block generation. Revisit for "strict mode" toggle later.
- **Wiring output for 0.1:** **ASCII art only.** KiCad deferred (still the
  longer-term target — design model must not paint into an ASCII corner).
- **Stack:** Python backend (FastAPI or aiohttp — match distributed-esphome),
  React 19 + Vite + Tailwind + shadcn frontend (later), Claude API for the
  agent (with prompt caching for the component KB).
- **Single source of truth:** `design.json` (versioned, JSON-Schema-validated).
  All artifacts (YAML, ASCII, BOM) are derived. No round-trip from artifacts
  back to the document.
- **Conversation/document split:** Agent chat history stored separately
  (`sessions/<id>.jsonl`). `design.json` stays clean and diff-able.
- **Reasoning layers:**
  1. Agent (Claude, tool-using) — elicitation, recommendations, narrative.
  2. CSP solver (`python-constraint` or OR-tools) — pin/bus/budget assignment.
  3. Generators (pure functions) — `design.json` → YAML / ASCII / BOM.
- **Secrets:** Never in `design.json`. Reference `distributed-esphome`'s
  `secrets.yaml` via `!secret name`.
- **Knowledge base sources** (see *Library sourcing strategy* below for the
  hybrid plan): ESPHome integrations for YAML schema, PlatformIO board JSON
  for board metadata, hand-curation + LLM-extracted datasheet data for the
  electrical layer ESPHome doesn't carry.

## Phasing

UI-first ordering: a manual web UI ships before the agent so users have an
immediate way in and the agent (when it arrives) lands in a working surface.

- **0.1 — MVP pipeline.** ✅ Shipped. `design.json` → ESPHome YAML + ASCII.
  Library scaffolding, generators, golden tests.
- **0.2 — HTTP API.** ✅ Shipped. FastAPI server (`python -m wirestudio.api`),
  endpoints under `/library/*`, `/design/*`, `/examples/*`. Auto-generated
  OpenAPI at `/docs`. CORS open for `localhost:5173`/`localhost:3000` so
  0.3's UI can hit it directly. Pure layer over `wirestudio.generate`, no
  server-side state. /design/render currently returns `{yaml, ascii}`;
  structured BOM + power-budget responses will be added when 0.3 needs
  them rather than guessed at now.
- **0.3 — Studio Web UI v1.** React 19 + Vite + Tailwind v4 under `web/`.
  Three-pane layout: left sidebar (examples / boards / components with
  search), center design pane (ASCII / YAML / JSON tabs + design header),
  right inspector (design / board / component / component-instance
  views). Read-only first iteration shipped, then param-edit forms
  layered on: clicking a component instance opens a generated form
  (string / enum / int / bool) populated from `params_schema`; edits
  flow back to local design state and re-render via debounced
  `/design/render`. Connection / bus / board edits, drag-and-drop, and
  the agent sidebar (0.5) are follow-on iterations.
- **0.4 — USB device bootstrap.** ✅ Shipped (initial). "Connect device"
  toolbar button opens a modal that uses
  [`esptool-js`](https://github.com/espressif/esptool-js) over WebSerial
  in the browser to detect chip family + MAC, then offers the matching
  boards from the library. Picking one seeds a fresh `design.json` with
  the board pre-filled. Pure browser, no backend involved. Same approach
  web.esphome.io uses. Future: also detect flash size + PSRAM presence
  for richer board disambiguation, and support specifying a custom
  baud rate / reset strategy for stubborn boards.
- **0.5 — Agent layer.** ✅ Shipped (initial). Claude tool-using agent
  with the constrained tool surface in *Agent tool surface* below.
  Lands as a sidebar in the UI; also exposed via `POST /agent/turn`.
  Conversation history in `sessions/<id>.jsonl`, separate from
  `design.json`. Future: streamed responses (currently waits for
  end_turn before returning), agent-side handoff to 0.6's CSP solver
  via a `solve_pins` tool, recommendation mode ("I want motion
  detection" → ranked options).
- **0.6 — CSP solver.** ✅ Shipped (initial). Pin assignment lives in
  `wirestudio/csp/pin_solver.py`; surfaced as the `solve_pins` agent tool,
  the standalone `POST /design/solve_pins` endpoint, and a "Solve pins"
  header button. Greedy + capability-aware: respects board GPIO
  capabilities, prefers non-strap pins for outputs, picks first
  matching bus by type, fills expander pins on the first io_expander.
  Future: recommendation mode ("I want motion detection" → ranked
  options), strict-mode pin locks, multi-objective optimization
  (minimize used pins, minimize current draw, maximize headroom),
  proper backtracking on hard constraints.
- **0.7 — distributed-esphome handoff.** ✅ Shipped (initial). The studio
  API talks to the ha-addon's `/ui/api/*` surface using `FLEET_URL` +
  `FLEET_TOKEN`. Push uses the addon's staged-create flow (`.pending.<n>.yaml`
  -> `<n>.yaml`) for new devices, in-place writes for existing ones.
  Optional `compile: true` enqueues an OTA build via `POST /ui/api/compile`.
  UI: **Push to fleet** modal with status banner + device-name input.
  Future: live build-log tailing, queue/history surface, fleet-side
  device list to pick a target name from.
- **0.8 — Enclosure suggestions.** Two halves:
  - **v1 ✅ Shipped (parametric OpenSCAD generator).** Each dev-board
    YAML carries an `enclosure:` block with PCB outline + mount holes
   + port cutouts. `wirestudio/enclosure/openscad.py` emits a
    self-contained `.scad` shell (bottom + 4 walls, mounting standoffs
    aligned with the mount holes, edge cutouts for every port) with
    tunables (wall, floor, clearance, standoff geometry) at the top
    so the user dials in fit without re-rendering. Endpoint
    `POST /design/enclosure/openscad`; header **Generate enclosure**
    button triggers a browser download.
  - **v2 ✅ Shipped (Thingiverse search relay).** Pluggable
    per-source search at `wirestudio/enclosure/search.py`. Thingiverse
    implementation gated on `THINGIVERSE_API_KEY`. Printables
    deliberately deferred (no public API yet; their internal GraphQL
    endpoint changes without notice and the CDN rate-limits
    unauthenticated reads -- the source stays in the catalogue but
    always reports `available: false` with a "deferred" reason so
    the UI surfaces the gap honestly). `GET /enclosure/search`
    + `GET /enclosure/search/status` endpoints. The header
    **Generate enclosure** button is now a single **Enclosure**
    button opening a tabbed dialog (Generate / Search).
  - **Stretch — component dimensions on breakouts** (BME280 module,
    OLED module, etc.) so the generator can place display windows
    and stack-mount cutouts, not just the headline USB port.
- **0.9 — KiCad schematic export.** ✅ Shipped (v1). Walks
  `design.json` and emits a SKiDL Python script the user runs
  locally to produce `<design_id>.kicad_sch`. The studio doesn't
  import or run SKiDL itself -- this keeps the artefact transparent
  (the user can `cat` it, edit it, regenerate) and avoids adding
  numpy + EDA-toolchain weight to the server. PCB layout deferred
  to 1.0+ as planned. Concretely:

  - **Library mapping, not duplication.** Our `library/components/<id>.yaml`
    stays the canonical source for ESPHome semantics; it gains a small
    `kicad:` block that *references* the matching `kicad-symbols`
    entry rather than copying its pin geometry. The two libraries
    sit at orthogonal layers -- KiCad's covers schematic rendering
    (pin numbers, electrical types, footprint, datasheet); ours
    covers the rest (Jinja YAML template, use_cases, required buses,
    `params_schema`, electrical bounds, capability tags). Replacing
    one with the other moves the data, doesn't eliminate it.

    Block shape:
    ```yaml
    kicad:
      symbol_lib: Sensor
      symbol: BME280
      footprint: Package_LGA:LGA-8_2.5x2.5mm_P0.65mm_LayoutBorder3x3y
      pin_map:                # studio role -> KiCad pin name
        VCC: VDD
        GND: GND
        SDA: SDA
        SCL: SCL
    ```

    Pin map handles the cases where our role names differ from a
    symbol's (e.g., our `VCC` vs Bosch's `VDD`); most parts are 1:1.

  - **Boards likewise.** `library/boards/<id>.yaml` gains the same
    `kicad:` block (e.g., WeMos D1 Mini -> `MCU_Module:WeMos_D1_mini`),
    so the schematic gets the right module symbol, not just a sea of
    nets.

  - **Generator.** New `wirestudio/kicad/` module: walks `design.json`,
    converts each component instance into a SKiDL `Part(...)`, each
    connection into a Net assignment, and either emits a SKiDL Python
    script (the user runs it themselves) or invokes SKiDL in-process
    to write `<design_id>.kicad_sch` directly. New endpoint
    `POST /design/kicad` returns the artifact; CLI gets a
    `--out-kicad` flag.

  - **Scaffold helper.** Cheap tooling win: `wirestudio/kicad/scaffold.py`
    reads a `.kicad_sym` file and prints a starter
    `library/components/<id>.yaml` skeleton (pin roles + voltage
    hints prefilled from the symbol's pin electrical_types). Cuts
    ~80% of the boilerplate when adding a new library entry. Author
    fills in the ESPHome template + use_cases + params_schema after.

  - **Coverage.** `kicad-symbols` (the libraries shipped with KiCad,
    CC-BY-SA + GPL exception) covers nearly every component we
    already have: BME280, BMP180, HTU21D, DS18B20, MPU6050, ADS1115,
    TSL2561, MAX31855, HX711, SSD1306, MCP23008/17, SX127x, WS2812B,
    plus the board modules. The PIRs (HC-SR501) and microwave radar
    (RCWL-0516) are typically wired as 3-pin `Connector_Generic`
    instances since they're breakouts; same for HC-SR04. SnapEDA /
    Component Search Engine cover the remaining manufacturer parts
    (RC522 etc.) for free.

  - **PCB layout deferred to 1.0+.** SKiDL can also emit netlists
    that feed Freerouting + KiCad's PCB editor, but auto-routed
    boards are a per-design quality concern that wants its own
    iteration. 0.9 ships only the schematic.

- **Future — KiCad PCB layout.** Reuse the schematic's netlist;
  Freerouting for autorouting; Gerber + JLCPCB CPL/BOM export.

The UI-first ordering means 0.5's agent and 0.6's solver each have a
visible place to land. If the agent lands first (alternative ordering),
it ships as a CLI/tool-only surface and we re-skin it later — strictly
worse for the headline feature.

## Studio web UI (0.3)

Three-panel layout, all driven by the API in 0.2.

- **Library panel (left).**
  - Search box, category facets (sensor, display, switch, expander, light,
    io_expander, …), bus-type chips (i2c, spi, uart, 1wire, i2s).
  - Two tabs: *Components* and *Boards*.
  - Drag a component card onto the canvas to add to the current design.
- **Design canvas (center).**
  - Top: board pinout diagram with active connections drawn as wires
    between board pins and component blocks. Reuses the `gpio_capabilities`
    map from board YAMLs to color pins by capability.
  - Middle: ASCII diagram block (the current `ascii_gen` output, rendered
    in a monospace box). Live re-render on every design change.
  - Bottom: BOM table + power summary + warnings tray.
- **Inspector panel (right).**
  - When a component is selected: editable form for `params`, derived from
    the component's `params_schema`. Connection list with per-pin assignment.
  - When a connection is selected: kind selector (rail / gpio / bus /
    expander_pin once 0.4-ish); pin picker filtered by capability.
  - When the design root is selected: board picker, power supply, fleet
    metadata, secrets references, requirements list.
- **Toolbar.**
  - "Connect device" (0.4) → triggers WebSerial detect.
  - "Talk to agent" (0.5) → opens agent sidebar.
  - "Solve pins" (0.6) → runs CSP, applies result, shows diff.
  - "Push to fleet" (0.7) → POST to distributed-esphome.
  - Export YAML / Export ASCII / Export `design.json`.

Recommendation surfaces (ranked component options for a stated capability)
fold into the library panel as a separate "Suggest" mode.

## USB device bootstrap (0.4)

Flow:

1. User clicks "Connect device". Browser prompts for serial port permission
   (Chrome WebSerial; no extension or backend needed).
2. `esptool-js` reads chip variant (`esp32`, `esp32s3`, `esp32c3`, `esp8266`,
   `esp8285`, `esp32c6`, etc.), flash size, MAC.
3. Studio cross-references the chip variant against `library/boards/*.yaml`,
   filtering to boards whose `mcu` / `chip_variant` match.
4. UI shows top 3-5 candidates ("ESP32 chip with 4MB flash and PSRAM
   detected — likely candidates: ESP32-DevKitC-V4, ESP32-WROVER-Kit. Pick
   one, or pick *Generic ESP32-WROOM-32*."). User picks.
5. Studio bootstraps a `design.json` with the `board:` block populated and
   an empty `components: []`. `power.budget_ma` defaults from the board's
   regulator metadata.
6. Normal design flow from there. Detected chip is also retained as a
   `warnings[]` entry if the user later changes the board to something
   incompatible with what's actually plugged in.

This is where the studio earns its "agentic but grounded" framing: the
agent never has to *guess* what hardware you have — the device tells us.

## `design.json` (schema_version 0.1)

​```jsonc
{
  "schema_version": "0.1",
  "id": "garage-motion-v1",
  "name": "Garage motion sensor",
  "description": "Outdoor PIR + temp/humidity, USB powered.",
  "created_at": "2026-05-03T12:00:00Z",
  "updated_at": "2026-05-03T12:34:00Z",

  "board": {
    "library_id": "esp32-devkitc-v4",
    "mcu": "esp32",
    "framework": "arduino",
    "pinned_esphome_version": "2024.10.0"
  },

  "power": {
    "supply": "usb-5v",
    "rail_voltage_v": 5.0,
    "regulator": "onboard-ams1117",
    "budget_ma": 500
  },

  "requirements": [
    { "id": "r1", "kind": "capability",  "text": "detect motion at front door" },
    { "id": "r2", "kind": "environment", "text": "outdoor, covered" },
    { "id": "r3", "kind": "constraint",  "text": "USB powered" }
  ],

  "components": [
    {
      "id": "pir1",
      "library_id": "hc-sr501",
      "label": "Driveway PIR",
      "role": "motion_sensor",
      "params": { "retrigger": "H", "pulse_ms": 2500 },
      "locked_pins": {}
    },
    {
      "id": "bme1",
      "library_id": "bme280",
      "label": "Porch climate",
      "params": { "address": "0x76" }
    }
  ],

  "buses": [
    { "id": "i2c0", "type": "i2c", "frequency_hz": 100000,
      "sda": "GPIO21", "scl": "GPIO22" }
  ],

  "connections": [
    { "component_id": "pir1", "pin_role": "VCC", "target": { "kind": "rail", "rail": "5V" } },
    { "component_id": "pir1", "pin_role": "GND", "target": { "kind": "rail", "rail": "GND" } },
    { "component_id": "pir1", "pin_role": "OUT", "target": { "kind": "gpio", "pin": "GPIO13" } },
    { "component_id": "bme1", "pin_role": "VCC", "target": { "kind": "rail", "rail": "3V3" } },
    { "component_id": "bme1", "pin_role": "GND", "target": { "kind": "rail", "rail": "GND" } },
    { "component_id": "bme1", "pin_role": "SDA", "target": { "kind": "bus", "bus_id": "i2c0" } },
    { "component_id": "bme1", "pin_role": "SCL", "target": { "kind": "bus", "bus_id": "i2c0" } }
  ],

  "passives": [
    { "id": "c1", "kind": "capacitor", "value": "100nF",
      "between": ["bme1.VCC", "GND"], "purpose": "decoupling bme1" },
    { "id": "r1", "kind": "resistor",  "value": "4.7k",
      "between": ["i2c0.SDA", "3V3"],  "purpose": "I2C pull-up" },
    { "id": "r2", "kind": "resistor",  "value": "4.7k",
      "between": ["i2c0.SCL", "3V3"],  "purpose": "I2C pull-up" }
  ],

  "warnings": [
    { "level": "warn", "code": "current_budget",
      "text": "Estimated 320mA peak vs 500mA budget — OK." }
  ],

  "esphome_extras": {
    "captive_portal": {},
    "logger": { "level": "INFO" }
  },

  "fleet": {
    "device_name": "garage-motion",
    "tags": ["outdoor", "porch"],
    "secrets_ref": { "wifi_ssid": "!secret wifi_ssid", "api_key": "!secret api_key" }
  },

  "agent": {
    "session_id": "01J...",
    "history_ref": "sessions/01J....jsonl"
  }
}
​```

## Component library file — `library/components/<id>.yaml`

​```yaml
id: bme280
name: Bosch BME280 (T/H/P)
category: sensor
use_cases: [temperature, humidity, pressure, weather]
aliases: [bmp280, bme680]

electrical:
  vcc_min: 1.8
  vcc_max: 3.6                 # NOT 5V tolerant
  current_ma_typical: 0.6
  current_ma_peak: 4
  pins:
    - role: VCC
      kind: power
    - role: GND
      kind: ground
    - role: SDA
      kind: i2c_sda
      pull_up: { required: true, value: "4.7k", to: VCC }
    - role: SCL
      kind: i2c_scl
      pull_up: { required: true, value: "4.7k", to: VCC }
  passives:
    - kind: capacitor
      value: "100nF"
      between: [VCC, GND]
      purpose: decoupling

esphome:
  required_components: [i2c]
  yaml_template: |
    i2c:
      - id: {{ bus.id }}
        sda: {{ bus.sda }}
        scl: {{ bus.scl }}
    sensor:
      - platform: bme280_i2c
        address: {{ params.address | default("0x76") }}
        i2c_id: {{ bus.id }}
        temperature: { name: "{{ label }} Temperature" }
        humidity:    { name: "{{ label }} Humidity" }
        pressure:    { name: "{{ label }} Pressure" }

params_schema:
  address: { type: string, enum: ["0x76", "0x77"], default: "0x76" }

notes: "3V3 only. On 5V boards, place behind level shifter or use 3V3 rail."
​```

## ASCII diagram format

Pinout block + connection table + passives note. Diff-friendly, README-pasteable.

​```
ESP32-DevKitC-V4 --- garage-motion-v1
+------------------------------------------------------+
|  Rails:  5V (USB), 3V3 (onboard reg), GND            |
|                                                      |
|  GPIO13 ------------------ PIR.OUT     (HC-SR501)    |
|  GPIO21 (SDA) --+--------- BME280.SDA                |
|                 +-[4.7kohm]- 3V3                     |
|  GPIO22 (SCL) --+--------- BME280.SCL                |
|                 +-[4.7kohm]- 3V3                     |
|  3V3   ----------------- BME280.VCC --||-- GND (100nF)|
|  5V    ----------------- PIR.VCC                     |
|  GND   ----------------- BME280.GND, PIR.GND         |
+------------------------------------------------------+

BOM: ESP32-DevKitC-V4, HC-SR501, BME280 breakout, 2x 4.7kohm, 1x 100nF
Power budget: ~12mA idle, ~320mA peak (limit 500mA)  OK
Warnings: none
​```

(Use box-drawing chars in the real renderer; ASCII fallback shown above for portability.)

## First PR scaffolding (proposed)

​```
wirestudio/
├── README.md
├── LICENSE                    # MIT (matches ESPHome python frontend)
├── pyproject.toml
├── schema/
│   └── design.schema.json     # JSON Schema for design.json (0.1)
├── library/
│   ├── boards/
│   │   └── esp32-devkitc-v4.yaml
│   └── components/
│       ├── bme280.yaml
│       ├── hc-sr501.yaml
│       └── ssd1306.yaml
├── wirestudio/
│   ├── __init__.py
│   ├── model.py               # pydantic models mirroring design.schema.json
│   ├── library.py             # load+validate library files
│   ├── generate/
│   │   ├── yaml_gen.py        # design.json -> ESPHome YAML
│   │   └── ascii_gen.py       # design.json -> ASCII diagram
│   └── validate.py            # esphome config dry-run wrapper
├── examples/
│   └── garage-motion.json
└── tests/
    ├── test_yaml_gen.py
    ├── test_ascii_gen.py
    └── golden/                # YAML + ASCII goldens per example
​```

No agent, no CSP, no API server in PR #1. Goal: `python -m wirestudio.generate
examples/garage-motion.json` produces YAML + ASCII; tests pin them to goldens.

## Agent tool surface (for 0.2)

Discrete operations the LLM is allowed to call:
- `search_components(query)` — fuzzy search KB by name/use_case/alias
- `add_component(library_id, label, params?)` → component_id
- `remove_component(component_id)`
- `set_param(component_id, key, value)`
- `lock_pin(component_id, pin_role, gpio)`
- `set_board(library_id)`
- `solve_pins()` — invokes CSP, returns assignments + warnings
- `generate_yaml()` / `render_ascii()` / `bom()`
- `validate()` — `esphome config` dry-run

Constrained surface = predictable agent.

## Library sourcing strategy

Hybrid. Different parts of the library map to different sources; some are
mineable, some have to be hand-curated.

| Studio field | Best source | Mineable |
|---|---|---|
| Board: `mcu`, `chip_variant`, `platformio_board`, `flash_size_mb` | PlatformIO board JSON ([`platform-espressif32/boards/*.json`](https://github.com/platformio/platform-espressif32/tree/develop/boards), `platform-espressif8266/boards/*.json`) | yes — clean JSON |
| Board: GPIO list + per-pin capabilities (PWM, ADC, strap, I2C, SPI, input-only) | espressif/esp-idf hw-reference + per-module datasheets ([`docs.espressif.com/.../hw-reference/`](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/hw-reference/)) | partial — RST tables, needs scraping |
| Board: rails (5V/3V3/GND, regulator), USB chip | datasheet / dev-board schematic | no — hand-curate one entry per *module class*, not per board |
| Component: ESPHome YAML template + config schema | [esphome/esphome `components/<name>/`](https://github.com/esphome/esphome/tree/dev/esphome/components) — START already plans `schema_gen.py` | yes — ESPHome's own `CONFIG_SCHEMA` (voluptuous) |
| Component: pin role names, required buses, framework constraints | also from the integration code (`PROTOCOL_HOOKS` for I2C/SPI; `cv.GPIOSensor`) | partial |
| Component: voltage range, current draw, pull-up requirements, decoupling caps | datasheet | no — hand-curated, but the agent (0.5) is the natural extractor |

Plan:

- **Don't aim for exhaustive.** Cover the ~30 most common components seen
  across `moellere/esphome` (the survey already enumerated them) and the
  boards actually in use. That's >90% real-world fit.
- **Module classes, not boards.** Curate ESP32-WROOM-32, ESP32-S3-WROOM-1,
  ESP-12F (esp8266), etc. Specific boards (DevKitC-V4, NodeMCU-32S,
  WeMos D1 Mini) inherit pin capabilities from their module and only
  override what they expose differently.
- **Datasheet → component pipeline.** When the agent (0.5) lands, build a
  one-shot tool: feed it a datasheet PDF/URL + an ESPHome integration
  name; it emits a candidate `library/components/<id>.yaml` for human
  review. Same prompt-cached component KB the agent uses for design
  conversations.
- **License hygiene.** Schema-derived data from ESPHome (GPLv3 runtime,
  MIT python frontend) is fine; vendoring source is not. See *License
  hygiene* under Open considerations.

## Open considerations / revisit later

- **Strict-mode toggle.** Per-design opt-in for blocking on electrical violations.
- **Reverse import.** Existing ESPHome YAML → `design.json`. Defer past 0.1
  but keep `connections[]` expressible from a parsed YAML.
- **Multi-device projects.** 0.1 is single-device. Multi-device (e.g. a
  mesh of related sensors sharing secrets/tags) is future scope.
- **Component variants.** BME280 vs BME680 vs BMP280 — `aliases` field is a
  start; full variant inheritance (`extends:`) is later.
- **License hygiene.** ESPHome runtime is GPLv3; python frontend is MIT.
  Schema-derived data is fine; vendoring source needs review. `LICENSES.md`
  from day one.
- **Smoke-test corpus.** Canonical designs (motion, T/H, relay+button, OLED
  clock) with golden YAML+ASCII. Add new one every time the agent guesses wrong.
- **Prompt caching.** Component library easily exceeds 30k tokens — inject
  as single cached block on every Claude API call (use the `claude-api` skill).
- **Validation pass.** Run `esphome config` in a sandbox before declaring
  any design "done" — catches schema drift between our library and ESPHome.

## Pending logistics

- **Branching strategy.** Currently committing direct-to-main with linear
  history. When 0.2 work spans multiple PRs we'll switch to feature
  branches; for now the constraint is that this repo has no other humans
  pushing.
- **Issue tracking.** Once 0.2 (HTTP API) starts, spin off a milestone with
  one issue per endpoint + one for the OpenAPI spec. Same pattern for 0.3
  (one issue per UI panel).
- **License hygiene.** ESPHome runtime is GPLv3; python frontend is MIT.
  Studio is MIT (matches ESPHome python frontend). Schema-derived data is
  fine; vendoring source needs review. Land a `LICENSES.md` when a third
  source enters the tree.

## Reference

- distributed-esphome (sister project): https://github.com/weirded/distributed-esphome
- moellere/esphome (curated device fleet, agent reference corpus): https://github.com/moellere/esphome
- ESPHome upstream: https://github.com/esphome/esphome
- ESPHome schema source: `esphome/schema_gen.py` in upstream
- PlatformIO ESP32 board JSON: https://github.com/platformio/platform-espressif32/tree/develop/boards
- esptool-js (browser USB detect): https://github.com/espressif/esptool-js
- Espressif HW reference: https://docs.espressif.com/projects/esp-idf/en/latest/esp32/hw-reference/

