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

**Next up candidates:**

- Library batch 3 from the survey list above (probably the most
  obvious continuation — same format as #12 / #17).
- WebUI basic/advanced mode toggle.
- A real `esphome compile` smoke run + fix anything that surfaces.
- Component-coverage matrix script.
- 1.0 — KiCad PCB layout (reuse the schematic's netlist;
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

(Note: the rest of START.md — the per-phase historical changelog
going back through 0.5 / 0.6 / 0.7 / 0.8 / 0.9 v1, the `## Status
(as of 2026-05-04)` block, `## Vision`, `## Decisions locked`,
`## Phasing`, `## Studio web UI (0.3)`, `## USB device bootstrap
(0.4)`, `## design.json (schema_version 0.1)`, `## Component library
file`, `## ASCII diagram format`, `## First PR scaffolding`,
`## Agent tool surface (for 0.2)`, `## Library sourcing strategy`,
`## Open considerations / revisit later`, `## Pending logistics`,
and `## Reference` — is preserved verbatim from the prior version on
`main` and isn't reproduced inline here. The diff against the prior
file is the only delta this commit introduces; see the
`wirestudio-START-md-2026-05-06.patch` artefact in Drive for the
unified diff if you want to verify.)
