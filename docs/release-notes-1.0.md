# wirestudio 1.0 release notes (draft)

Draft. At release this text opens the `[1.0.0]` section of
`CHANGELOG.md`, which the release workflow publishes as the GitHub
release body; the feature entries accumulated under `[Unreleased]` stay
below it. Items marked **at release** are filled in when the flash
stage of the hardware gate has run and the schema is cut.

These notes cover what changes for someone upgrading from 0.40.0 and
what each part of the studio now promises. The features since 0.40.0
are in the changelog entries that follow.

## What 1.0 promises

- **Designs keep loading.** A design saved under 1.0 loads under every
  1.x. A change to the document shape ships only with a migration step
  that rewrites older documents on load.
- **Stores keep opening.** The SQLite design and session stores carry a
  schema version and migrate themselves on open. An upgrade never needs
  a manual step to keep its data.
- **Every advertised surface cites its gate.** The README status table
  has two tiers. *Verified* rows name the CI or nightly job that fails
  when the surface breaks; everything else is *Experimental* and says
  what it lacks.

## Upgrading from 0.40.0

Back up the data directory first (`docs/deployment.md`, "Backup and
restore"). For the SQLite layout, copy the databases with
`python -m wirestudio.sqlite_store backup <db> <dest>`, which is safe
while the studio runs; a plain copy of a WAL database is not.

Nothing else is manual. The `upgrade` workflow seeds a data directory
with 0.40.0 through its own REST API, in both store layouts, and the
release must load every design at the current schema and render it as
the original renders, and read back the user library, inventory,
sessions and store versions. Against 0.40.0, all 75 bundled designs
pass in both layouts.

### design.json

0.40.0 wrote `schema_version` 0.1. 1.0 writes **at release: 1.0**.
Every path that reads a design (the file and SQLite stores, every REST
endpoint that takes one, MCP `create_design`, the generate CLI) runs the
migration chain first, so old files load unchanged on disk and are
rewritten in the new shape the next time they are saved. To rewrite
files in place, or to check them in CI:

```
wirestudio-migrate design.json --write
wirestudio-migrate design.json --check
```

What the steps change, and only this:

| Step | Change |
|---|---|
| 0.1 → 0.2 | `lorawan.gps`, `lorawan.dht22` and `lorawan.oled` become the `uart_gps`, `dht` and `ssd1306` components with their bus and connections. |
| 0.2 → 0.3 | Fields nothing read are dropped: `created_at`, `updated_at`, `agent`, and `lorawan.chirpstack_application_id`, `device_profile_id`, `provisioning` and `dev_eui`. |
| 0.3 → 1.0 | **At release.** The three LoRaWAN blocks leave the model; the version becomes 1.0. |

A document with no `schema_version`, or one written by a newer release,
is refused with a message saying so.

### Stores

- **SQLite (`DESIGNS_DB`, `SESSIONS_DB`).** A file from 0.40.0 has no
  schema version; it is adopted at version 1 with its rows on first
  open. A file opened by 1.0 cannot go back to 0.40.0: a store from a
  newer release is refused, so keep the backup if you may roll back.
  `python -m wirestudio.sqlite_store version <db>` prints a file's
  version.
- **JSON files (`DESIGNS_DIR`, `SESSIONS_DIR`, `INVENTORY_PATH`, the
  user library).** No change beyond the design migration above.

### Outputs that change on regeneration

The generators are pure functions of the design, so these show up the
next time an artifact is rendered, not in stored data.

- **LoRaWAN codec payload order.** A design that set a `lorawan.dht22`
  (or `gps` / `oled`) block on a board with onboard sensors now packs
  the design's sensors before the onboard ones, as every other design
  already did. Re-push the codec to ChirpStack when you reflash such a
  device.
- **KiCad schematic and PCB for 19 boards.** Boards drawn as generic
  headers now bind each GPIO and rail to its header pad from the
  vendor's pinout, so nets reach the board. Six change header size:
  ESP32-C3-DevKitM-1 (2x15), ESP32-C6 SuperMini (2x10), ESP32-S3
  SuperMini (2x09), TTGO LoRa32 V2 and T-Beam (2x13), ESP32-WROVER-CAM
  (2x20); the M5Stack Atoms become a 1x13. A board layout started under
  0.40.0 for one of these needs its footprint updated.
- **Enclosures.** The `.scad` is now a YAPP_Box base and lid. The
  tunables at the top keep their names (`lid_t` and `ridge_h` are new);
  the old `shell()` and `standoffs()` modules are gone, so a hand edit
  of those does not carry over.

## Tier changes since 0.40.0

| Row | 0.40.0 | 1.0 | Gate |
|---|---|---|---|
| MCP server | Works | Verified | the `mcp` client drives the mounted server over Streamable HTTP with the token, every PR |
| Component authoring | Works | Verified | a user component and its synthetic design through `esphome config`, and a corpus of bad components, every PR |
| ESPHome dashboard compile | Works | Verified | push, compile and fetch against a live ESPHome dashboard, nightly |
| Agent | Experimental | Verified | the 28-task eval through Claude Code over MCP, nightly, held to `gate.claude_code_min_pass` (**at release:** the score) |
| WLED target | (new) | Verified | goldens every PR; the usermod build against WLED v0.15.2 on PRs that touch it and nightly |
| LoRaWAN target | Works (hardware-validated) | **at release** | the flash stage of the hardware gate |
| LoRaWAN external-component path | Works (hardware-validated) | **at release** | same |
| Remote workbench | Works (hardware-validated) | **at release** | same, plus the transport tests |
| Meshtastic flashing + config | Works | **at release** | a nightly flash of a radio board, or Experimental |
| CircuitPython flashing | Works | **at release** | a nightly flash with a boot verdict, or Experimental |
| MicroPython flashing + main.py | Works | **at release** | a nightly flash with a boot verdict, or Experimental |

Every other row keeps its tier. ESPHome output validates on releases
2026.3 through 2026.9 (`docs/esphome-support.md`); the pin is 2026.6.5.

## Not in 1.0

LoRaWAN regions other than US915 and network servers other than
ChirpStack, more than one user or design per process, importing
existing ESPHome YAML, multi-device projects, and new targets. The
reasons are in [`roadmap.md`](roadmap.md#out-of-scope-for-10).
