# WireStudio — handoff

Written 2026-10-24 by the cloud development session, for a session on a VM
with direct tool access. Part A is verified as of writing and was re-checked
by a VM session the same evening, after the history rewrite (below). Part B
is the bench and homelab state, refreshed and re-checked by the homelab
session on 2026-10-24 (after 0.46.0 rolled out).

# Part A — development

## Where things stand

- **wirestudio 0.46.0** is released (`v0.46.0`, annotated, on `366103e`
  after the rewrite). Prod and both gate CronJobs run `0.46.0-full`, and
  `/api/version` on prod answers 0.46.0 (re-checked 2026-10-24 evening).
- **main** is past 0.46.0 by three `[Unreleased]` entries: the promotion
  script (#400), board revisions with the Heltec V4 PA pin (#407) and the
  live serial relay in the flash dialog (#408), plus docs. That is a 0.47.0
  when the user wants one; the release notes' upgrade baseline then moves
  again (#401 shows the shape).
- **The public history was rewritten on 2026-10-24** (git-filter-repo,
  redacting addresses and host names). Every commit hash changed and a
  clone from before it shares no ancestor with `origin/main`. Re-clone, or
  `git fetch && git reset --hard origin/main` in an old clone before
  branching; a PR from the old history cannot merge.
- **No open pull requests** in `moellere/wirestudio` or
  `moellere/wirestudio-designs`.
- **The catalogue** (`moellere/wirestudio-designs`) pins `wirestudio @
  v0.46.0` and publishes `index.json` with `designs`, `components` and
  `boards` (14 designs, no library entries yet).

## How the work has been run

- One pull request per item, from a branch off main; squash-merge your own
  PR when CI is green. The cloud session was confined to one branch name
  (`claude/vigilant-curie-1abfus`); a VM session need not be.
- **Minor releases need the user's OK.** Releases have been tagged by the
  homelab session (`session_01GYUoMEvDXb4HR3rwcZAb5F`), which also moves
  prod (`deploy/overlays/prod/kustomization.yaml` names the image tag; the
  release PR bumps it). A release PR changes CHANGELOG (heading and compare
  links), `wirestudio/__init__.py` and that tag, nothing else.
- After a release reaches PyPI, the 1.0 release notes
  (`docs/release-notes-1.0.md`) move their "Upgrading from" baseline to it
  (#393, #401 did this for 0.45.0 and 0.46.0).
- When the catalogue needs a new WireStudio feature, bump its
  `requirements.txt` pin in the same PR that uses the feature; its CI
  installs from the git tag, so it needs the tag, not PyPI.

## What landed since 0.44.0

0.45.0 (#383 to #391): routed DRC in the studio, route parameters, a GND pour
filled after routing, one net per bus line, community designs that carry their
components, the pin-direction audit.

0.46.0 (#392 to #399):
- IO-expander pins reach the expander's own pads (#392).
- ERC runs inside a KiCad project; `lib_symbol_issues` is retired from the ERC
  baseline (#394).
- Enclosures for the ESP32-C3-DevKitM-1 and ESP32-S3-DevKitC-1, from
  Espressif's DXFs (#395).
- LoRaWAN blocks for the UART, SPI and Modbus parts; coverage 38 of 102 (#396).
- **Community library, steps 1 to 3** (#397, #398, wirestudio-designs#5).

After 0.46.0: the promotion script (#400), release notes from 0.46.0 (#401),
this handoff (#402 to #405), the two-bench section of `docs/workbench.md` and
the README header (#406), board revisions (#407, Part B's Heltec finding
turned into `design.board.revision`), live serial over SSE after a workbench
flash (#408, closing workbench phase 2).

## The community library

Users can now add boards and components and share them, and the maintainer
can promote shared ones into the bundled library.

- **User boards** (`wirestudio/library/__init__.py`): `LIBRARY_USER_DIR/boards/`
  beside `components/`; bundled ids always win. `wirestudio/library/board_check.py`
  is the board gate (pins against `gpio_capabilities`, KiCad symbol pins,
  enclosure geometry, `platformio_board` against ESPHome's board table, an
  ESPHome render of the seeded onboard parts). REST, MCP and agent tools
  mirror the component ones; the studio's editor is `LibraryEditorDialog`.
- **Studio install and share** (`wirestudio/api/community.py`):
  `/community/library`, `/community/library/{components|boards}/{id}/install`,
  `/community/library/share`. Installs fetch only through index URLs, run the
  gate, and never overwrite a user's entry (409). A design on a user board
  shares and imports with that board.
- **Catalogue** (`wirestudio-designs/scripts/library.py`): entries live at
  `library/components/<id>/component.yaml` and `library/boards/<id>/board.yaml`
  with a `meta.yaml` (author, tags, a required https `source`), MIT. CI runs
  the WireStudio gate and `esphome config`, and refuses an id a design ships
  as a different file. Designs may ship `boards/<id>.yaml`.
- **Promotion** (`scripts/promote_library.py`): dry run by default; `--write`
  adds the file under a credit header, a CHANGELOG line and the coverage
  baseline entries, then lists the catalogue files to delete at the next pin
  bump (the catalogue refuses a bundled id). Each promotion is the user's
  call. None has happened yet; the catalogue's library is empty.

## Road to 1.0

`docs/roadmap.md` has the plan; its "Sequencing" list is done except the
flash stage's evidence. Sections 1, 3, 5, 6 and 8 are complete, section 4
closed its last issues (#344, #345, #346) on 2026-10-24, and the open issues
are #357 (built; close at 1.0), #312 (only the ATOM U left) and #219 (not a
blocker). What remains, in order:

1. **The flash stage's first green week on covbench.** Night 1 of 7 was
   2026-10-24: 11 checks, all four frameworks flashed and booted. The
   CronJob runs 04:30 America/Denver; a red night restarts the count, so
   the earliest promote/demote pass is 2026-10-30. Nothing to build here.
2. **The promote/demote pass** (roadmap sections 2 and 7). The README
   status table holds four *Works* rows: Remote workbench, Meshtastic,
   MicroPython, CircuitPython. Each goes to *Verified* citing the flash
   bench through `docs/workbench.md` ("The reference deployment: two
   benches", added in #406), or to *Experimental* with its caveat. The
   same pass fills the five **at release** cells in
   `docs/release-notes-1.0.md`: those four rows and the Agent row's
   score. Claude Code has scored 26 of 28 on every scored run so far,
   the last on 2026-10-24 (dispatched run 40113780344); the gate is 24.
3. **Both eval gates are set** (done 2026-10-24). The `ANTHROPIC_API_KEY`
   secret is in place; the embedded agent scored 26 of 28 on two runs
   (40118320452, 40118970332), so `gate.min_pass` is 25, and Claude Code's
   gate rose to 25 on 27, 27 and 26. The release notes' Agent cell is
   filled. The embedded agent's `first-i2c-part` miss was a studio bug,
   #410, fixed on main after the scored runs: the next dispatched run
   should show it passing, and the gate can move up on two such runs.
4. **The 1.0 release PR**, with the user's OK: the notes' text opens the
   `[1.0.0]` section of CHANGELOG with the `[Unreleased]` entries beneath
   it, `wirestudio/__init__.py` moves, and the `upgrade` workflow's result
   against 0.46.0 (or whatever is newest on PyPI) goes in the notes. The
   roadmap's "Written against 0.39.0" header and its section 2 table get
   their final wording in the same PR.
5. Not required for 1.0: workbench phase 4, the JLCPCB order, the printed
   enclosure.

## Open threads

- **esphome repo:** `common/secrets.yaml` is still tracked in git, although
  that repo's CLAUDE.md calls it gitignored. Whether to untrack it (and
  rotate what it holds) is the user's decision, still pending. Never print
  its contents.
- **LoRaWAN coverage:** 52 parts still lack a `lorawan:` block; each is
  explained in `scripts/framework_baseline.yaml`. Twelve deferred parts
  gained blocks on 2026-10-25; the three left `deferred:` (pn532, wiegand,
  remote_receiver) report an id at an instant and wait on a last-seen field
  convention in the codec.

## Gotchas from this round

- An old clone looks fine (`git status` clean, tests pass) but is on the
  pre-rewrite history; `git merge-base main origin/main` returning nothing
  is the tell. The `release` tags were re-pointed too, so compare against
  `git ls-remote --tags origin`, not a local tag.
- `npx tsc -p .` skips files that `tsc -b` (the CI `web` job and the docker
  build) checks, such as `web/src/lib/bootstrap.test.ts`. Run `tsc -b`.
- `esphome config` accepts an unknown `board:` with only a warning; the board
  gate's lookup in `esphome.components.*.boards.BOARDS` is what catches a bad
  key.
- The studio caches the catalogue index for five minutes (`INDEX_TTL_S`);
  tests that republish an index inside one test see the old one.
- Two `tests/test_lorawan_api.py` unwritable-directory tests fail when the
  suite runs as root (chmod cannot lock root out). They pass in CI.
- `CHANGELOG.md` headings are checked by `scripts/check_changelog.py`, and a
  new library entry must satisfy `python scripts/coverage_matrix.py --strict`
  (an example or a baseline entry, and a reason per framework gap).
- Branch protection wants a PR up to date with main. `gh pr update-branch`
  does it, but two open PRs that both add to `[Unreleased]` conflict there;
  merge `origin/main` into the branch, keep both entries, push.

## Tooling the cloud container lacked

The VM should have these directly; the cloud session worked around them.

- The PlatformIO registry was blocked: the LoRaWAN firmware was built with
  PlatformIO 6.2.0's penv and RadioLib 7.8.1 / LoRaWAN_ESP32 1.3.0 cloned
  from GitHub into each project's `lib/`. The `lorawan-firmware` workflow is
  the authoritative build.
- KiCad 8 ran in Docker (`kicad8`), and dockerd died often. The KiCad 8.0.0
  symbol and footprint libraries were cloned to `/tmp/kicad-sym-8.0.0` and
  `/tmp/kicad-fp-8.0.0`; the gates read them through `KICAD8_SYMBOL_DIR` and
  `KICAD8_FOOTPRINT_DIR`.
- `dl.espressif.com` was blocked, so the DevKit dimensions came from the
  homelab session.
- `.venv/` carries `esphome==2026.6.5`, the pin the config gate uses.

# Part B — bench and homelab (re-checked 2026-10-24)

Re-checked by the homelab session after 0.46.0 rolled out. Addresses, host
names and site names are deliberately left out of this public file: the
homelab session's notes and the gate ConfigMaps in the (private) argocd repo
hold them. `WORKBENCH_URL` in each gate's config is the source of truth.

## Releases and prod

- **Prod and both gate CronJobs run `0.46.0-full`** (tag pushed 2026-10-24 on
  283a99a; the API reports 0.46.0). Each minor release since 0.43.0 was
  preceded by a snapshot of the `/data` PVC, kept off-cluster by the homelab
  session.
- Release flow that works: tag → `release` + `docker` workflows → Argo CD
  Image Updater writes the new tag → force a refresh
  (`kubectl annotate application -n argocd app-wirestudio argocd.argoproj.io/refresh=normal --overwrite`)
  → check the Deployment **and both CronJob** images. A `cancelled`
  `full-image`/`lorawan-image` check on the main commit is the docker
  workflow's concurrency, not a failure; the tag run builds them.

## Two benches, two gates

| | LoRaWAN bench | Flash bench |
|---|---|---|
| Harness | Embedded-AI-Harness (upstream), portal on `:8081` because ChirpStack shares the host and holds `:8080` | Embedded-AI-Harness (upstream), portal on `:8080` |
| CronJob | `wirestudio-hardware-gate`, 03:30 America/Denver | `wirestudio-hardware-gate-covbench`, 04:30 America/Denver |
| Mode | **non-destructive**: slot presence, serial freshness, uplinks in ChirpStack | **flashes every night**: ESPHome, CircuitPython, MicroPython on the dev board, Meshtastic on the T3, then boot verification |
| Last run (2026-10-24) | OK, 13 checks | OK, 11 checks |

Run either on demand:
`kubectl create job -n wirestudio gate-x --from=cronjob/<cronjob>`.
Delete one-off jobs when done: a failed one keeps `KubeJobFailed` firing.

### LoRaWAN bench devices

| DevEUI | Board | Slot | State 2026-10-24 |
|---|---|---|---|
| `10521cfffe66b6e0` | TTGO T-Beam | SLOT12 | joined, uplinking (standalone RadioLib) |
| `8cfd49fffeb55758` | Heltec V4 GNSS (**V4.3**, see below) | SLOT14 | joined, uplinking; ESPHome build pinned to lorawan-for-esphome 137d06e |
| `64b708fffeab8974` | TTGO T3 v1.6.1 spare (battery) | SLOT19 | joined, uplinking |
| `70b3baec29813d83` | Heltec V2 | SLOT31 | still on loan to the roboat HIL work, joins as monet-node |
| `500291fffe9df404` | TTGO LoRa32 v2 | off bench | ChirpStack last saw it 2026-09-26; not on the air |
| `c44f33fffe76e03d` | Heltec GPS | off bench | ChirpStack last saw it 2026-09-26 |

Identify boards by USB bridge and payload, never by slot label (labels are
positional): CP2104 `10c4:ea60` = T-Beam, CP2102 `10c4:ea60` = Heltec V2,
`1a86:55d4` = TTGO T3, `303a:1001` = V4 (ESP32-S3 native USB).

### Flash bench devices

| Slot | Board | Gate flashes |
|---|---|---|
| AUTO-1 | ESP32 dev board (ESP32-D0WD, CP2102) | ESPHome, CircuitPython, MicroPython (the last stays on at rest) |
| AUTO-2 | TTGO T3 V1.6.1 (ESP32-PICO-D4, CH9102), **433 MHz** radio | Meshtastic `.factory.bin` (the app-only `.bin` boot-loops) |

The flash bench answers the old "phase 3: enable the flash stage" item: it has
boards nothing else depends on, so it flashes nightly. The LoRaWAN bench stays
non-destructive, because every board there carries live traffic and a reflash
costs a rejoin and a DevNonce.

## Workbench phase 2 is closed

#408 streams a slot's serial live into the flash dialog:
`GET /workbench/slots/{slot}/stream` relays the recorder's buffer as SSE in
the `/workbench/flash` event shape, bounded by `seconds` and `idle`, and
stops polling the bench when the client disconnects. It reads the buffer,
never the port, so the harness's one serial reader (the recorder) is
untouched. The boot verdict (#290, #375) is unchanged beside it. Phase 4 is
the only workbench phase left, and it is not a 1.0 item.

## Heltec V4 on SLOT14 is a V4.3: PA control is GPIO5

Measured 2026-10-24 by gateway-side RSSI, same board and gateway, three
builds of lorawan-for-esphome main:

| PA pin config | Gateway RSSI |
|---|---|
| `txen_pin: GPIO46` (the "proven" V4 config) | -110 to -114 dBm |
| `txen_pin: GPIO5` | **-58 to -67 dBm** |
| GPIO46 held high | -110 to -118 dBm, still receives fine |

So on this board GPIO5 (V4.3 CTX) turns the PA on and GPIO46 does nothing.
The "proven" config transmits with the PA bypassed. The bench's own build
holds GPIO5 and GPIO46 high statically, which works at bench range but leaves
the TX path selected during RX. Details are on
moellere/lorawan-for-esphome#16.

WireStudio picks the pin by revision since #407: the board file lists
`revisions: "4.2"` (txen GPIO46, the default) and `"4.3"` (GPIO5), a design
chooses with `board.revision`, `validate` warns when a V4 design names none,
and the `heltec-v4-gnss-tracker` example is marked `"4.3"`. The bench's own
build (137d06e) predates this and still holds both pins high.

The same session validated lorawan-for-esphome main @ ca52396 (RadioLib
7.7.1) on this board: radio init, OTAA join, uplink, fport-10 downlink, no
Task-WDT panic across six failed joins, and nonce persistence across a reset.
The bench went back to its gate firmware afterwards.

**Reflashing a LoRaWAN bench board:** flush its DevNonces server-side first
(`ChirpStackClient.flush_dev_nonces`), flash the factory image, reset through
the harness (`/api/serial/reset`) so the recorder sees the boot, and restore
the gate firmware when done. The gate's silence windows (30 min serial, 60 min
uplink) give room for a short swap.

## Upstream harness issues (all still open, 2026-10-24)

- SensorsIot/Embedded-AI-Harness#29: MCP could reset a slot but never answer it.
- SensorsIot/Embedded-AI-Harness#30: `/api/serial/output?lines=N` returns the
  **oldest** lines. Read with `since=` or take the whole buffer.
- SensorsIot/Embedded-AI-Harness#31: keep-hostname opt-out; the LoRaWAN
  bench still carries a local patch for it.
- SensorsIot/Embedded-AI-Harness#57: the first boot after `/api/flash` is never
  recorded, because esptool's final reset fires before the recorder
  reattaches. WireStudio 0.43.0 works around it by resetting through the
  harness after a flash.
- moellere/WireStudio#219: board `flash_size` measurement. Still blocked on
  boards; SLOT14 is a V4 already verified at 16 MB.

## Verification gaps (unchanged since 2026-09-26)

- `fix_age_min` non-zero path never observed on hardware; it reads 0 with a
  live fix. Treat it as unproven until it moves.
- T-Beam GPS is poor but genuine indoors. Lat/lon go out unconditionally on
  purpose, so a position in the payload is not evidence of a current fix.

## Alerts (2026-10-24)

Apart from the Watchdog, the only unsilenced alerts are `WoLNodeStuckOff`
for two cluster nodes that are powered off. They are unrelated to WireStudio.
The September list (redis CPU throttling, prometheus DaemonSet rollouts, an
external node_exporter) is no longer firing.

## Hardware, needs a human at the LoRaWAN bench

- **Heltec V4 GNSS antenna** still reports ANTENNA OPEN every cycle. Reseat it
  or fit an external antenna; until then its uplinks carry no fix.
- **TTGO LoRa32 v2** (`500291…`) is off the air. It needs plugging back in and
  the ADC-pin/divider reflash.
- **Heltec GPS** (`c44f33…`) needs a rebuild, reflash and profile update when
  it returns: `fix_age_min` moved its payload from 17 to 19 bytes.
- Optional: read the V4's silkscreen to confirm V4.3.

## Gotchas worth knowing before you start

- **The argocd repo is often not on its main branch locally.** Check the
  branch before committing.
- **Argo CD often will not pick up a push on its own.** Annotate to force a
  refresh (command above).
- **`severity: info` alerts route to the null receiver** and can never notify.
- **One invalid rule voids an entire PrometheusRule object.**
- **Prometheus retention is 10 d.** A `[14d]` range silently evaluates over
  less.
- **Harness installs re-enumerate USB**, which reboots every attached board
  and costs each LoRaWAN board a rejoin.
- **"The TTGO" is ambiguous**: T-Beam, T3 v1.6.1 and LoRa32 v2 are different
  boards with different radio pin maps. The T3 on the flash bench is a 433 MHz
  unit and cannot do US915. Confirm which board before flashing.
