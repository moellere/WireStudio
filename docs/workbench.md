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
  When the boards live at a different site from the developer, that is
  not an inconvenience but a hard stop: there is no path to the silicon
  at all.
- The Meshtastic and CircuitPython tiers ship with "no live-flash gate";
  a release can pass every CI check and still fail at boot on hardware.
- LoRaWAN join verification on the external-component path is a manual,
  one-time claim rather than a repeatable gate — and it can only be made
  where a gateway is in range, which is wherever the bench is, not
  wherever the developer is.
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
| Slot flash API (Pi-local esptool) | Remote flash transport: flash dialog gains a Local USB / Workbench-slot target; the studio uploads the image and the Pi flashes its own USB | Reaches boards at a remote site, where WebSerial has no path at all; enables headless/MCP-driven flashing |
| RFC2217 serial per slot | Serial relay for boot verification (phase 2) and remote monitoring | Slot output without being at the bench |
| Serial monitor + UDP logging | Post-flash boot verification: stream slot serial into the flash dialog over SSE; assert per-framework boot markers (ESPHome boot log, Meshtastic banner, CIRCUITPY enumeration, LoRaWAN join) | Upgrades "flashed" to "flashed and booted" — the failure class CI cannot see |
| Chip detect over the slot | Remote Connect-device: USB-detect/bootstrap for benched boards (chip family, eFuse MAC → DevEUI) | Design bootstrap + LoRaWAN provisioning without walking to the bench |
| WiFi SoftAP + HTTP relay + MQTT broker | Functional gate: flash generated ESPHome firmware, provision against the Pi's AP, assert the device's API/MQTT entities appear | The strongest possible claim — the generated device actually works, not just that the YAML validates |
| SDR receiver | RF truth check for LoRa/Meshtastic: power-spectrum capture during TX | Catches deaf-radio wiring bugs (undriven FEM pins) that present as "won't join" while serial output looks healthy |
| Test sessions + operator prompts | Guided bring-up: "plug the GNSS module into the SH1.25-8", "hold BOOT" | Turns board-specific gotchas into interactive checklists |
| Slots as inventory | Board-farm status: boards list shows "on workbench, slot N" | Small UX win, nearly free once status polling exists |

## Phases

Each phase is independently shippable; later phases build on earlier
ones but none blocks the others' value.

1. **Remote flash transport.** A `WORKBENCH_URL` env
   gate (the usual integration seam) enabling `/workbench/status`,
   `/workbench/slots` and `/workbench/flash`: the server fetches the
   framework's image exactly as the existing proxies do, uploads it to
   the bench, and streams progress over SSE while the Pi runs esptool
   against its own USB. The flash dialog gains the target toggle.

   Flashing is delegated rather than driven over RFC2217 from the
   studio. esptool's block protocol is a long series of round trips, so
   driving it across the link that separates developer from bench is
   exactly the latency-bound case; one bulk upload followed by a local
   flash is both more robust and thinner, leaving the bench owning the
   bench. RFC2217 is still what phase 2 relays for serial.

   On the reference bench this is not merely the faster option but the
   only one that works: esptool driven over RFC2217 cannot pull the
   board into download mode (it resets into normal boot and reports
   `Wrong boot mode 0x33`), and the portal's GPIO boot control is
   broken by a libgpiod v1/v2 API mismatch. The Pi's local esptool
   drives DTR/RTS on the real devnode and enters download mode fine.

   Two behaviours the bench actually exhibits, worth encoding rather
   than assuming: upload parts are keyed `bin@<offset>`, and the portal
   buffers esptool and answers once with `{ok, output, returncode}`.
   A non-zero `returncode` arrives under HTTP 200, so success must be
   read from that field, and log lines only reach the operator when the
   flash finishes.

   This is the phase that makes a remote bench usable, and the LoRaWAN
   case is why it comes first. A radio board can only be join-tested
   where it can reach a gateway, so when the bench and the ChirpStack
   instance sit at one site and the developer at another, the whole
   provision → flash → join cycle is unreachable over WebSerial. Remote
   flash runs that cycle against the real network from anywhere, and
   every later phase — and every headless or MCP-driven use of the
   bench — depends on it.
2. **Boot-marker verification.** A `/workbench/verify` step and serial
   SSE relay in the dialog, with per-framework success/failure
   signatures over the slot's serial.
3. **Nightly hardware gate.** A scheduled job flashes a representative
   example per framework to a dedicated slot and asserts boot/join —
   the "Works (lighter checks)" tiers hold hardware-validated status
   continuously instead of as a one-time claim. This phase's real
   prerequisite is a self-hosted runner on the bench network: hosted CI
   runners cannot reach it, so the runner is setup and maintenance cost
   the phase has to carry, not an implementation detail.
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
- **`WORKBENCH_URL` is the gate, and it is a real one.** The server
  pushes firmware at a device on an operator-supplied host, so pointing
  it anywhere but a bench you control is the whole risk. `WORKBENCH_TOKEN`
  is optional and sent only when set — for a bench fronted by something
  that authenticates; the stock portal ignores it.

  Phase 1 originally *required* the token, reasoning that every
  comparable gate pairs a host with a credential (`FLEET_URL` +
  `FLEET_TOKEN`). That was wrong: those tokens authenticate to services
  that check them, and this one is checked by nothing. Requiring it gated
  nothing — anyone able to set the URL can set a token too — while
  implying a credential that does not exist and pushing operators to seal
  a dummy value into a secret store. An honest unauthenticated integration
  beats a decorative credential.

  A real outbound guard would be a host allowlist, and there is no
  existing one to reuse: `WIRESTUDIO_ALLOWED_ORIGINS` is CORS and
  `WIRESTUDIO_MCP_ALLOWED_HOSTS` is the MCP SDK's *inbound* DNS-rebinding
  mitigation. Only the comma-split env parsing idiom carries over.
- **Bench resources are exclusive; model the contention.** A slot's
  serial port admits one reader, and the SDR is a single dongle behind
  a global lock — a capture in flight rejects the next caller outright.
  Phase 2 streams a slot, phase 3 flashes on a schedule, and an
  operator may be driving the bench UI through any of it. Every
  workbench call therefore has to expect and surface a busy state, and
  anything long-running has to hold an explicit lease it releases on
  failure rather than assuming the bench is idle.
- **Distinguish a broken build from a broken bench.** Bench hardware
  wedges under sustained use: the RTL-SDR still enumerates but streams
  nothing until a USB reset, sometimes until the Pi reboots. A nightly
  gate that reports those as firmware failures gets muted within a
  month. Every hardware assertion runs behind a pre-flight self-test
  (slot enumerates, chip detects) and reports infrastructure faults as
  a distinct outcome from test failures.
- **RF checks are comparisons, not presence tests.** With AGC a
  near-field transmitter rails the receiver, so a healthy radio can
  read as garbage and an OOK burst can misdetect entirely. The phase-4
  TX check pins a fixed gain and asserts against a known-good baseline
  captured under the same geometry — a bare "is there energy at the
  carrier" test proves nothing.
