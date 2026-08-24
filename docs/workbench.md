# Workbench integration

[← docs index](index.md)

Integrating a
[SensorsIot Embedded AI Harness](https://github.com/SensorsIot/Embedded-AI-Harness)
(formerly Universal Embedded Workbench) — a Raspberry Pi that exposes
every USB-attached dev board as a network resource — as the studio's
hardware truth layer. Roadmap placement and phase status live in
[index.md](index.md#roadmap); this page carries the full capability map
and design constraints.

**Phase 1 has shipped** (0.25.0): remote flash transport, slot listing
with pre-flight, and — from 0.26.0 — the whole LoRaWAN bring-up
(flash → register in ChirpStack → push keys over the slot's serial
prompt → verify the join) against a bench slot, with no human at the
bench. 0.27.0 put the same reach behind MCP tools. Later phases
(continuous serial relay, scheduled flashing, a live-device CI gate)
are still scoping; the phase table below marks which is which.

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
3. **Nightly hardware gate.** A scheduled job asserts the bench and
   everything on it is still alive — see [The gate](#the-gate) below.

   The scheduler is a cluster CronJob, **not** a self-hosted runner as
   originally planned. WireStudio is a public repository, so a runner
   on the bench network would let any fork's pull request execute code
   with reach into that network; the `pull_request` trigger runs
   fork-authored workflows by design. Scheduling from inside the
   perimeter keeps the same reach with nothing repo-controlled running
   on it, and the cluster already holds the bench and ChirpStack
   credentials. The cost is that the gate cannot annotate a PR.

   The flashing half — a representative example per framework flashed
   to a dedicated slot, which is what would let the "Works (lighter
   checks)" tiers hold hardware-validated status continuously — is
   **not** yet enabled. It needs a board nothing else depends on;
   see the caveat under [The gate](#the-gate).
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

## The gate

`wirestudio-hardware-gate --config <roster.yaml>` runs the phase-3
checks and exits non-zero if any fail. It needs `WORKBENCH_URL` (plus
`WORKBENCH_TOKEN` if the bench is authenticated) and, for the uplink
stage, the usual ChirpStack environment.

| stage | asserts |
|---|---|
| `bench` | the portal answers; nothing downstream runs if it doesn't |
| `slots` | each configured slot is present and `flashable` |
| `serial` | the slot's recorder captured output within `max_serial_silence_s` |
| `uplinks` | ChirpStack saw the DevEUI within `max_uplink_silence_s` |

The roster is deployment state — slot labels and DevEUIs describe one
physical bench — so it is not shipped in the package.
`scripts/hardware_gate.example.yaml` documents the schema:

```yaml
max_serial_silence_s: 1800
max_uplink_silence_s: 3600
devices:
  - slot: SLOT12          # positional label, from sorted hub-port order
    name: TTGO T-Beam
    framework: lorawan
    dev_eui: 10521cfffe66b6e0   # optional; enables the uplinks stage
```

Two decisions worth keeping:

**A missing slot is a failure, not a lookup.** Slot labels are
positional, assigned in sorted hub-port order, so a board that moves
ports gets a new label. Resolving that silently would hide the event —
"the hardware moved or died" is precisely what a nightly check exists
to report.

**Serial and uplinks are independent, and both are needed.** A board
can be present and printing to serial while completely off the air, and
— as the reference bench demonstrates — it can be transmitting happily
while absent from the USB bus, alive but unflashable. An activation
record only proves the device joined *once*; the gate asserts
`last_seen_at` recency because a stale session is indistinguishable
from a live one otherwise. A device silent since June still had a
valid activation.

**The flash stage is not enabled.** Setting `flash: true` on a device
reports as an explicit failure rather than doing nothing. Turning it on
needs a *dedicated* board: every device on the reference bench carries
real traffic, and reflashing one nightly costs a rejoin, a DevNonce and
about ten minutes off the air each time. Until then the gate is a
bench-health detector, and the "no live-flash gate" caveat on the
framework tiers still stands.

### How a failure reaches you

There is no PR to annotate, so a failed Job is the report. Two Prometheus
alerts turn that into a push notification via the cluster's
alertmanager → ntfy bridge:

- `WireStudioHardwareGateFailed` — the newest run failed and nothing has
  succeeded since. It compares against the CronJob's `lastSuccessfulTime`
  rather than alerting on `kube_job_status_failed` directly, because
  failed Jobs are deliberately kept for a week as evidence and a bare
  `> 0` would keep firing long after a fix. Re-running the gate by hand
  clears it: `kubectl create job --from=cronjob/...` inherits the
  CronJob's ownerReference, so `lastSuccessfulTime` advances.
- `WireStudioHardwareGateStale` — no successful run in 26 hours. This
  covers the mode the gate itself is built around: absence reading as
  health. If the CronJob stops firing there is no failed Job to find, so
  the first alert stays silent; staleness cannot be fooled that way, and
  it also catches a sustained failure whose Jobs have aged out.

Both live in the argocd repo, not here, since they describe the
deployment. The pod log is the full report:
`kubectl logs -n wirestudio -l job-name=<job> --tail=30`.
