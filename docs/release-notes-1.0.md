# wirestudio 1.0 release notes (draft)

Draft. At release this text opens the `[1.0.0]` section of
`CHANGELOG.md`, which the release workflow publishes as the GitHub
release body; the feature entries accumulated under `[Unreleased]` stay
below it. Items marked **at release** are filled in when the flash
stage of the hardware gate has run and the schema is cut.

These notes cover what changes for someone upgrading from 0.45.0 and
what each part of the studio now promises. Coming from an earlier
release, read the last section too: the migrations run automatically
from any release, but 0.41.0 through 0.45.0 changed some outputs on the
way.

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

## Upgrading from 0.45.0

Back up the data directory first (`docs/deployment.md`, "Backup and
restore"). For the SQLite layout, copy the databases with
`python -m wirestudio.sqlite_store backup <db> <dest>`, which is safe
while the studio runs; a plain copy of a WAL database is not.

Nothing else is manual. The `upgrade` workflow seeds a data directory
with the newest release on PyPI (0.45.0) through its own REST API, in
both store layouts, and 1.0 must load every design at the current
schema, render it as the original renders, and read back the user
library, inventory, sessions and store versions. **At release:** the
result against 0.45.0.

### design.json

0.43.0 through 0.45.0 already write `schema_version` 1.0, so their
designs load unchanged. Every path that reads a design (the file and
SQLite stores, every REST endpoint that takes one, MCP `create_design`,
the generate CLI) runs the migration chain first, so a file from an
older release loads unchanged on disk and is rewritten the next time it
is saved. To rewrite files in place, or to check them in CI:

```
wirestudio-migrate design.json --write
wirestudio-migrate design.json --check
```

| Step | Since | Change |
|---|---|---|
| 0.1 → 0.2 | 0.41.0 | `lorawan.gps`, `lorawan.dht22` and `lorawan.oled` become the `uart_gps`, `dht` and `ssd1306` components with their bus and connections. |
| 0.2 → 0.3 | 0.41.0 | Drops fields nothing read: `created_at`, `updated_at`, `agent`, and `lorawan.chirpstack_application_id`, `device_profile_id`, `provisioning` and `dev_eui`. |
| 0.3 → 1.0 | 0.43.0 | The `lorawan` sugar blocks leave the model; any still in a document are rewritten as in `0.1 → 0.2`, and the version becomes 1.0. A document at 1.0 that carries one is refused. |
| any version | 0.45.0 | A bus named after an ESPHome-reserved id (`spi0`, `uart0`, ...) is renamed the way the studio names one (`spi_bus0`), with its connection targets and `*_id` references. |

A document with no `schema_version`, or one written by a newer release,
is refused with a message saying so.

### Stores

No store schema change since 0.41.0. A store that 1.0 has opened is
refused by an older release if a later step adds a version, so keep the
backup if you may roll back.

### KiCad outputs

- **IO-expander pins reach the expander.** A part wired to an expander
  pin now lands on the expander's own GPx pad in the schematic, the
  netlist and the PCB. Before, each such net had one pad. Regenerate any
  board laid out under 0.45.0 for a design with an MCP230xx, PCF8574 or
  74HC595.

## Tier changes

| Row | 0.40.0 | 0.45.0 | 1.0 | Gate |
|---|---|---|---|---|
| MCP server | Works | Verified | Verified | the `mcp` client drives the mounted server over Streamable HTTP with the token, every PR |
| Component authoring | Works | Verified | Verified | a user component and its synthetic design through `esphome config`, and a corpus of bad components, every PR |
| ESPHome dashboard compile | Works | Verified | Verified | push, compile and fetch against a live ESPHome dashboard, nightly |
| Agent | Experimental | Verified | Verified | the 28-task eval through Claude Code over MCP, nightly, held to `gate.claude_code_min_pass` (**at release:** the score) |
| WLED target | (new) | Verified | Verified | goldens every PR; the usermod build against WLED v0.15.2 on PRs that touch it and nightly |
| LoRaWAN target | Works (hardware-validated) | Verified | Verified | firmware builds on PRs that touch the target and daily; the nightly hardware gate hears the bench's T-Beam |
| LoRaWAN external-component path | Works (hardware-validated) | Verified | Verified | `esphome config` every PR; the nightly hardware gate hears three bench boards on it |
| Remote workbench | Works (hardware-validated) | Works (hardware-validated) | **at release** | same, plus the transport tests |
| Meshtastic flashing + config | Works | Works | **at release** | a nightly flash of a radio board, or Experimental |
| CircuitPython flashing | Works | Works | **at release** | a nightly flash with a boot verdict, or Experimental |
| MicroPython flashing + main.py | Works | Works | **at release** | a nightly flash with a boot verdict, or Experimental |

Every other row keeps its tier. ESPHome output validates on releases
2026.3 through 2026.9 (`docs/esphome-support.md`); the pin is 2026.6.5.

## Coming from an earlier release

The migration chain covers every version, so any data directory
upgrades straight to 1.0. Releases write these schema versions: 0.40.0
and earlier 0.1, 0.41.0 through 0.42.2 0.3, and 0.43.0 on 1.0. What
changed on the way, newest first:

- **Routed boards before 0.45.0 shorted their buses.** The netlist put
  every line of a bus on one net, so a routed I2C board tied SDA to SCL,
  and SPI and UART boards tied every bus line together, in the PCB and
  the schematic. 0.45.0 gives each line its own net (`BUS_<id>_SDA`,
  `BUS_<id>_SCL`, ...; a part's UART TX on the MCU's RX). Do not send a
  board routed before 0.45.0 to fab; regenerate it.
- **Pin directions (0.45.0).** A pin's kind is the line's direction as
  the MCU sees it. Sensor outputs moved to `digital_in` and lines the
  MCU drives (resets, LED data, display DC, shift-register lines) to
  `digital_out`, so validate warns where it was silent before: a strap
  pin driven by a sensor (`boot_strap_driven`) or under an output
  (`boot_strap_output`), and more than two `remote_receiver`s on a
  classic ESP32 (`rmt_memory`).
- **Community import (0.45.0).** `POST /community/designs/{slug}/import`
  replaces 0.44.0's `GET /community/designs/{slug}`, and installs the
  design's own components into the user library.
- **MCP and agent clients (0.42.0).** `search_components` returns each
  match's `library_id`, `name`, `category` and `score`, best match
  first; a client that read `use_cases`, `required_components` or the
  current draw from a match gets them from `library_detail` instead.
  The embedded agent stops after 8 model calls a turn, down from 12.
- **SQLite stores (0.41.0).** A file from 0.40.0 has no schema version; it is
  adopted at version 1 with its rows on first open, and 0.40.0 cannot
  open it afterwards. `python -m wirestudio.sqlite_store version <db>`
  prints a file's version.
- **LoRaWAN codec payload order (0.41.0).** A design that set a `lorawan.dht22`
  (or `gps` / `oled`) block on a board with onboard sensors packs the
  design's sensors before the onboard ones. Re-push the codec to
  ChirpStack when you reflash such a device.
- **KiCad schematic and PCB for 19 boards (0.41.0).** Boards drawn as generic
  headers bind each GPIO and rail to its header pad from the vendor's
  pinout. Six change header size: ESP32-C3-DevKitM-1 (2x15), ESP32-C6
  SuperMini (2x10), ESP32-S3 SuperMini (2x09), TTGO LoRa32 V2 and
  T-Beam (2x13), ESP32-WROVER-CAM (2x20); the M5Stack Atoms become a
  1x13. A board layout started under 0.40.0 for one of these needs its
  footprint updated.
- **Enclosures (0.41.0).** The `.scad` is a YAPP_Box base and lid. The tunables
  at the top keep their names (`lid_t` and `ridge_h` are new); the old
  `shell()` and `standoffs()` modules are gone, so a hand edit of those
  does not carry over.

## Not in 1.0

LoRaWAN regions other than US915 and network servers other than
ChirpStack, more than one user or design per process, importing
existing ESPHome YAML, multi-device projects, and new targets. The
reasons are in [`roadmap.md`](roadmap.md#out-of-scope-for-10).
