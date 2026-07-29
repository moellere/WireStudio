# Workbench integration (planned)

[← docs index](index.md)

Scoping for integrating a
[SensorsIot Universal Embedded Workbench](https://github.com/SensorsIot/Universal-Embedded-Workbench)
— a Raspberry Pi that exposes every USB-attached dev board as a network
resource — as the studio's hardware truth layer. Roadmap placement and
phase status live in [index.md](index.md#roadmap); this page carries the
full capability map and design constraints.

## Why

The studio verifies artifacts against upstream tools (`esphome config`,
KiCad netlists, OpenSCAD renders, firmware compiles), but nothing today
verifies them against silicon:

- Flashing is WebSerial-only — Chrome/Edge, local USB, human present.
- The Meshtastic and CircuitPython tiers ship with "no live-flash gate";
  a release can pass every CI check and still fail at boot on hardware.
- LoRaWAN join verification on the external-component path is a manual,
  one-time claim rather than a repeatable gate.
- Radio-path bugs (e.g. an RF front end whose enable pins are never
  driven) are invisible to serial output: firmware reports transmitting
  while nothing leaves the antenna.

The workbench provides exactly the missing capabilities: RFC2217 network
serial per USB slot (esptool-compatible), a JSON HTTP API, GPIO
boot/reset control, a WiFi AP tester with HTTP relay, an on-demand MQTT
broker, UDP debug logging, per-slot GDB/OpenOCD, and an optional RTL-SDR
receiver plus signal generator.

## Capability map

| Workbench capability | Studio integration | Value |
|---|---|---|
| RFC2217 serial per slot | Remote flash transport: flash dialog gains a Local USB / Workbench-slot target; server-side esptool writes over `rfc2217://<pi>:<port>` | Flash benched boards from any browser (no WebSerial requirement, no physical presence); enables headless/MCP-driven flashing |
| Serial monitor + UDP logging | Post-flash boot verification: stream slot serial into the flash dialog over SSE; assert per-framework boot markers (ESPHome boot log, Meshtastic banner, CIRCUITPY enumeration, LoRaWAN join) | Upgrades "flashed" to "flashed and booted" — the failure class CI cannot see |
| Chip detect over the slot | Remote Connect-device: USB-detect/bootstrap for benched boards (chip family, eFuse MAC → DevEUI) | Design bootstrap + LoRaWAN provisioning without walking to the bench |
| WiFi SoftAP + HTTP relay + MQTT broker | Functional gate: flash generated ESPHome firmware, provision against the Pi's AP, assert the device's API/MQTT entities appear | The strongest possible claim — the generated device actually works, not just that the YAML validates |
| SDR receiver | RF truth check for LoRa/Meshtastic: power-spectrum capture during TX | Catches deaf-radio wiring bugs (undriven FEM pins) that present as "won't join" while serial output looks healthy |
| Test sessions + operator prompts | Guided bring-up: "plug the GNSS module into the SH1.25-8", "hold BOOT" | Turns board-specific gotchas into interactive checklists |
| Slots as inventory | Board-farm status: boards list shows "on workbench, slot N" | Small UX win, nearly free once status polling exists |

## Phases

Each phase is independently shippable; later phases build on earlier
ones but none blocks the others' value.

1. **Remote flash transport.** `WORKBENCH_URL` env gate (the usual
   integration seam) enabling `/workbench/status` and
   `/workbench/flash`: the server fetches the framework's image exactly
   as the existing proxies do, writes it with esptool over RFC2217, and
   streams progress over SSE. The flash dialog gains the target toggle.
2. **Boot-marker verification.** A `/workbench/verify` step and serial
   SSE relay in the dialog, with per-framework success/failure
   signatures over the slot's serial.
3. **Nightly hardware gate.** A scheduled job flashes a representative
   example per framework to a dedicated slot and asserts boot/join —
   the "Works (lighter checks)" tiers hold hardware-validated status
   continuously instead of as a one-time claim. Runs from
   infrastructure that can reach the workbench's network (hosted CI
   runners generally cannot).
4. **Functional loop + RF truth.** AP provision + MQTT/API entity
   assertions for generated ESPHome devices; SDR TX power check for
   radio boards.

## Design constraints

- **Thin client only.** The studio talks to the workbench HTTP API; it
  never re-implements slots, serial handling, or RF. The workbench owns
  the bench.
- **Env-gated like every integration.** No `WORKBENCH_URL`, no feature —
  the UI surfaces why, same as fleet/ChirpStack/Thingiverse.
- **No bench state in `design.json`.** Slot assignments and workbench
  hosts are deployment configuration, not design content.
