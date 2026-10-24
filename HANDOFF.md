# WireStudio — handoff

Written 2026-10-24 by the cloud development session, for a session on a VM
with direct tool access. Part A is verified as of writing. Part B is the
bench and homelab state the homelab session last recorded (2026-09-26); it
was not re-checked for this handoff.

# Part A — development

## Where things stand

- **wirestudio 0.46.0** is tagged (`v0.46.0`, annotated, on `283a99a`). The
  homelab session pushed the tag with the user's OK; the release and
  docker workflows were running at handoff, and that session was to
  confirm prod and both gate CronJobs on `0.46.0-full`. Confirm that first.
- **main** is at `2c898dc`. `[Unreleased]` holds one entry, the promotion
  script.
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

After 0.46.0: the promotion script (#400), release notes from 0.46.0 (#401).

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
flash stage's evidence. What remains:

- **The flash stage's first green week on covbench**, the dedicated bench
  (earliest around 2026-10-30). That fills the **at release** cells in
  `docs/release-notes-1.0.md`: Remote workbench, Meshtastic, CircuitPython
  and MicroPython either go to Verified on the nightly flash job or are
  demoted to Experimental; the Agent row records its nightly score.
- Then the 1.0 release itself: the notes' text opens the `[1.0.0]` section of
  CHANGELOG, the README status table is the contract, and the upgrade
  workflow's result against 0.46.0 (or whatever is newest on PyPI) goes in
  the notes.
- Not required for 1.0: workbench phase 4, the JLCPCB order, the printed
  enclosure.

## Open threads

- **esphome repo:** `common/secrets.yaml` is still tracked in git, although
  that repo's CLAUDE.md calls it gitignored. Whether to untrack it (and
  rotate what it holds) is the user's decision, still pending. Never print
  its contents.
- **LoRaWAN coverage:** 64 parts still lack a `lorawan:` block; each is
  explained in `scripts/framework_baseline.yaml`. The remaining `deferred:`
  ones are candidates for the next block PRs.

## Gotchas from this round

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

# Part B — bench and homelab (as of 2026-09-26)

The homelab session's last recorded state, not re-checked for this handoff.
Its version line was 0.32.0 then; prod has since followed every release.

- **Bench** (`10.254.0.44`, address by IP) on upstream **Embedded-AI-Harness v1.0.1**.
  Merged onto the ChirpStack host `wyolora` 2026-09-26: `10.254.0.44` and
  `10.254.0.11` are aliases of one machine. ChirpStack holds `:8080`, so the
  workbench portal is on **`:8081`** (`WORKBENCH_URL=http://10.254.0.44:8081`).
- **Nightly hardware gate** runs 03:30 America/Denver, currently 11/11 green.
  Run on demand:
  `kubectl create job -n wirestudio gate-x --from=cronjob/wirestudio-hardware-gate`
- **Alerts**: 9 firing cluster-wide, down from 25. All remaining are actionable.

### Devices

| DevEUI | Board | Slot | State |
|---|---|---|---|
| `10521cfffe66b6e0` | TTGO T-Beam | SLOT12 | 0.32.0 fw, joined, 24-byte payload |
| `8cfd49fffeb55758` | Heltec V4 GNSS | SLOT14 | ESPHome build, 12-byte payload (lat, lon, sats); no fix at all on 09-26 (NaN coords, 0 sats) -- L76K reports ANTENNA OPEN |
| `64b708fffeab8974` | TTGO T3 v1.6.1 spare (battery) | SLOT19 | ESPHome, 8-byte payload; took over the old Heltec V2 identity |
| `70b3baec29813d83` | Heltec V2 | SLOT31 | on loan to roboat P4 HIL since 2026-08-29, joins as monet-node in the `roboat` app, 20-byte payload on fport 10 |
| `500291fffe9df404` | TTGO LoRa32 v2 | off bench | on the air (4-byte payload, 5 min) but USB cable out; `on_bench: false` in the gate; still needs the ADC-pin/divider reflash |
| `c44f33fffe76e03d` | Heltec GPS | — | not on USB; ChirpStack last saw it 2026-09-26 21:49 UTC |

Identify boards by USB bridge and payload, never by slot label (labels are
positional; the bench was re-enumerated 2026-09-26 and the gate roster in the
argocd repo and the ChirpStack `slot` tags match the labels above):
`10c4:ea60` CP2104=T-Beam, `10c4:ea60` CP2102=Heltec V2, `1a86:55d4`=TTGO T3,
`303a:1001`=V4/esp32s3. When two boards share a bridge, match the slot's serial
log timestamps against each DevEUI's uplink times in ChirpStack.

---

## 1. Workbench phase 2 — the UI half

Server side shipped in 0.29.0 and needs no changes: `verify_boot()` in
`wirestudio/workbench/boot.py` holds the per-framework markers, exposed as the
`workbench_verify_boot` MCP tool (`wirestudio/mcp/hardware.py:254`).

Since #290 the flash dialog shows a slot's boot output and verdict after a
slot flash (`/workbench/slots/{slot}/output`), and #375 verifies a boot from a
bench reset. Still not done: **streaming the serial into the dialog live over
SSE**, so a human watches the boot as it happens.

Touchpoints:

- `wirestudio/api/workbench.py:97` — `/workbench/flash` already returns a
  `StreamingResponse` of SSE. The relay wants the same shape.
- `wirestudio/workbench/client.py` — has `monitor()` and `output()`; note
  `/api/serial/output` returns **oldest-first**, which reads as "nothing
  happened" if you take the tail (filed upstream as SensorsIot#30).
- `web/src/components/FlashDialog.tsx` — the dialog, with an existing test file
  alongside it.

Worth knowing before wiring it: the bench's serial port admits **one reader**,
and the always-on recorder is already one. Anything long-running has to expect
a busy state and release its lease on failure rather than assuming the bench is
idle (`docs/workbench.md`, design constraints).

## 2. Workbench phase 3 — enable the flash stage

The gate is non-destructive today. `flash: true` on a roster entry deliberately
reports an explicit failure rather than doing nothing.

**Blocked on hardware, not code.** It needs a *dedicated* board nothing depends
on — all three on the bench carry live traffic, and a nightly reflash costs a
rejoin, a DevNonce and ~10 min off air each. Adding one spare board turns this
on, and that is what retires the "no live-flash gate" caveat on the Meshtastic
/ CircuitPython / LoRaWAN tiers.

## 3. Workbench phase 4 — not started

AP provision + MQTT/API entity assertions for generated ESPHome devices; SDR
TX power check for radio boards.

---

## Open issues / PRs

- **wirestudio #219** — board `flash_size` unverified; `esp32-s3-devkitc-1`
  ships 8 MB and 32 MB under one name. The undecidable half is now handled:
  the board file keeps the floor and `design.json` carries a
  `board.flash_size_mb` override for a unit whose size has been measured.
  What remains is measurement, and it is still blocked — none of the four
  boards named in the issue is on the bench (SLOT14 is a V4, already
  verified at 16 MB). Each is seconds of `esptool flash-id` once present.
- **SensorsIot/Embedded-AI-Harness #29** — "MCP could reset a slot but never
  answer it". Open **18 days, no review**. Nudge or ping.
- **SensorsIot/Embedded-AI-Harness #31** — keep-hostname opt-out (opened
  2026-08-26). If merged, the bench's local patch can be dropped.

---

## Verification gaps (things believed true but not proven)

- **`fix_age_min` non-zero path never observed on hardware.** New in 0.32.0.
  Reads 0 correctly with a live fix, across 13 uplinks. The stale (`>0`) and
  never-fixed (`65535`) paths are covered by unit tests and construction only.
  A field that always reads 0 is indistinguishable from a broken one — treat as
  unproven until it moves. Should show itself the first time the T-Beam is
  parked with its GNSS off.
- **T-Beam GPS quality** is poor but genuine: sats 0–8, ~25–70 m scatter,
  altitude still climbing an hour into uptime. That is the metal workshop, not
  a fault. Expect it to improve outdoors on the vehicle.
  Note lat/lon are published **unconditionally on purpose** (last-known position
  is the feature for a vehicle tracker) — a position in the payload is *not*
  evidence of a current fix.

---

## Remaining alerts (all real — do not silence)

- `TargetDown job=dorkwall` — node_exporter on `dorkwall.dorktool.com:9100`
  unreachable (external host).
- `CPUThrottlingHigh ns=redis` ×2 — CPU limit too tight; tuning.
- `KubeDaemonSetNotScheduled` / `RolloutStuck` ×2 in ns `prometheus`. The
  `node-feature-discovery` pair is already null-routed at the alertmanager
  route; the `prometheus` pair is not covered.

The `nomtom-app` 404 that used to sit in this list is fixed — its
ServiceMonitor was disabled in nomtom-deploy#4. Giving that app real metrics
is tracked in `HANDOFF-METRICS.md` in the nomtom repo, not here.

## Hardware, needs a human at Wyola

- **Reflash the TTGO LoRa32 v2** with the ADC-pin/divider fix; its USB cable
  is out again, so plug it in first (it will appear as an unclaimed slot).
- **Fix the Heltec V4's GNSS antenna.** The L76K on SLOT14 reports ANTENNA
  OPEN every cycle and sees ~9 satellites with only two at a usable SNR, so it
  fixes only intermittently -- on 2026-09-26 not at all. Reseat the antenna
  connector or fit an external antenna. Unfixed uplinks carry NaN coordinates
  with `satellites=0`.
- **Heltec GPS** (`c44f33…`): when it returns it needs a rebuild, reflash and
  profile update before it decodes — `fix_age_min` moved its payload 17 → 19
  bytes, and a refreshed profile would reject the old firmware's 17-byte uplink.

---

## Gotchas worth knowing before you start

- **The argocd repo is not on `master` by default.** It was sitting on
  `fix/uptime-kuma-heap-oom`. Check the branch before committing.
- **ArgoCD often will not pick up a push on its own** — annotate to force:
  `kubectl annotate app -n argocd <app> argocd.argoproj.io/refresh=normal --overwrite`
- **`severity: info` alerts route to the null receiver** and can never notify.
- **One invalid rule voids an entire PrometheusRule object** — that is how 12
  homelab alerts stayed dead for 114 days.
- **Prometheus retention is 10 d** — a `[14d]` range silently evaluates over
  less.
- **Bench installs reboot every attached board** (USB re-enumeration), costing
  a rejoin each. Budget for it.
- **The bench hostname patch** lives at `~/bench-patches/keep-hostname.patch`
  with marker `/etc/rfc2217/keep-hostname`; re-apply if an update clobbers
  `install.sh`.
- **"Wyola" is a street address in NW Arkansas** (~35.8833, -94.0737), not
  Wyola, Montana. Do not infer the site's location from the name.
- **"The TTGO" is ambiguous** — the T-Beam (SLOT12) and the TTGO LoRa32 v2 are
  different boards with different radio pin maps and different battery sensing.
  Confirm which before flashing.
