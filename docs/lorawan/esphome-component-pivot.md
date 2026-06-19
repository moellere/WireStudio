# LoRaWAN target pivot: `lorawan-for-esphome` external component

Status: **scoping / decided in principle, spike not started.** This doc
captures the decision to re-found the LoRaWAN firmware path on an ESPHome
external component instead of a standalone RadioLib firmware generator, the
research that justifies it, the shape of the new component repo, the
risk-first spike that gates the rest, and how WireStudio collapses back to a
single ESPHome path afterward.

It does **not** retire [`LORAWAN_TARGET_PLAN.md`](LORAWAN_TARGET_PLAN.md).
That plan stays the reference for the parts this pivot reuses unchanged —
its §2 *key findings* (DevNonce replay, device-authoritative DevEUI, MSB
key order, US915 sub-band 2) and its ChirpStack / provisioning / HA-confirm
work. What this pivot replaces is the firmware *generation* half: the
standalone PlatformIO + Arduino project (`firmware_gen.py`, `templates/`,
the per-component arduino read snippets) gives way to ESPHome YAML that
pulls in the new component.

## Decision

Build a separate ESPHome external component, **`lorawan-for-esphome`** (name
follows ESPHome's branding request — `<thing>-for-esphome`, not
`esphome-<thing>`), that implements the LoRaWAN MAC on top of a RadioLib
radio and uplinks ESPHome sensor states. WireStudio then generates ESPHome
YAML referencing it via `external_components:`, and the LoRaWAN target stops
being a parallel firmware pipeline — it becomes one more ESPHome config,
compiled by the same build backend as every other device.

Reuse-first, per the stated default: the MAC is RadioLib's `LoRaWANNode`
(the same stack the current hardware-validated target already trusts via
`ropg/LoRaWAN_ESP32`), and the radio/sensor/build machinery is ESPHome's.
The new code is only the glue nobody has written: a LoRaWAN component in
ESPHome's lifecycle that joins, persists nonces, and packs subscribed sensor
values into uplinks.

## Why a new repo at all — the research finding

The gap is real and confirmed (web + a 66-repo GitHub search, 2026-06):

- ESPHome core `sx126x`/`sx127x` are **raw packet radios** — SPI config,
  transmit/receive, `on_packet`. No OTAA, no MAC.
- `PaulSchulz/esphome-lora-sx126x` is raw point-to-point LoRa, not LoRaWAN.
- `christianhubmann/esphome-RadioLib` and `smartoctopus/RadioLib-esphome`
  are RadioLib *repackaged to compile under ESPHome* — a build dependency,
  not a MAC component. RadioLib itself carries the LoRaWAN MAC (v7.x).
- `Andrik45719/esphome-meshtastic` is a different protocol.

Nobody has built the middle layer — a LoRaWAN-MAC ESPHome component that
joins a network and uplinks ESPHome sensor values. ESPHome's own tracking
issue ([feature-requests#2634]) confirms LoRaWAN "is not yet available in
the main component" and is expected to arrive, if at all, as a separate
component. So this is a genuine contribution, not a duplicate, and it earns
its own repo.

Reuse stack the spike leans on, in priority order:

1. **Upstream `jgromes/RadioLib` via `lib_deps`** — try this first. The
   ESPHome-compile forks are likely stale workarounds; RadioLib has moved a
   lot. Only fall back to a fork if upstream won't compile under ESPHome's
   build flags.
2. **ESPHome's own `ESPPreferences`** for DevNonce/session persistence —
   ESPHome already has NVS-backed preference storage. Using it means the
   component may not need `ropg/LoRaWAN_ESP32` at all, narrowing the
   dependency surface to RadioLib alone. (LoRaWAN_ESP32 remains the
   fallback if its persistence semantics prove load-bearing.)
3. **ESPHome's SPI + sensor framework** — radio transport and the entire
   sensor catalog come for free.

## Shape of `lorawan-for-esphome`

Standard ESPHome external-component layout:

```
components/lorawan/
  __init__.py        # config schema: region, sub_band, otaa keys (!secret),
                     # radio pins/chip, uplink interval, payload field list
  lorawan.h / .cpp   # Component: owns RadioLib node + radio; join, FCnt,
                     # RX windows; nonce persistence via ESPPreferences
  sensor.py          # binds a sensor_id -> a payload field (codec in config)
```

Config WireStudio (or a hand author) emits:

```yaml
external_components:
  - source: github://moellere/lorawan-for-esphome

lorawan:
  region: US915
  sub_band: 2
  dev_eui: !secret dev_eui          # or device-authoritative (see below)
  join_eui: !secret join_eui
  app_key: !secret app_key
  radio:
    chip: sx1276                     # sx1276 | sx1278 | sx1262
    cs_pin: GPIO18
    rst_pin: GPIO23
    dio0_pin: GPIO26
  uplink_interval: 5min
  payload:                          # ordered byte layout
    - sensor: living_temp
    - sensor: battery_voltage
```

The `payload:` list **is** the codec contract. WireStudio's existing
ChirpStack `decodeUplink` generation and HA-entity confirmation map onto it
unchanged — the firmware byte layout and the ChirpStack decoder still get
generated in lockstep from one field spec, exactly as today; only the source
of the layout moves from `firmware_gen.py` into the component config.

Marginal cost of supporting a new sensor drops from "write an Arduino read
snippet + codec field + a real-radio test" to "one line in `payload:`" — any
ESPHome sensor platform is a valid source with zero new firmware code. That
is the entire reason for the pivot.

## The spike (gates everything else)

One risk dominates: **loop timing.** LoRaWAN class-A RX windows open at RX1
+1 s and RX2 +2 s and RadioLib blocks around them; ESPHome's main loop is
cooperative and must not stall WiFi/API/other components. Resolution is known
(pin the radio to the second core on ESP32, or accept a bounded block during
the uplink burst), but it must be proven before any of the mechanical work is
worth doing.

Spike scope — smallest thing that proves the integration:

- A minimal `lorawan:` component wrapping RadioLib (upstream first).
- OTAA-joins the live ChirpStack 4.17 on a **TTGO LoRa32 v1** (SX1276,
  already a hardware-validated board for the current target).
- Uplinks **one hardcoded field** on an interval.
- Nonces persist across a power cycle via `ESPPreferences` (proves the §2.1
  failure mode stays fixed under the new persistence path).

Acceptance: device joins cleanly, uplink decodes in ChirpStack, WiFi/API
stay responsive during the uplink burst, and a power-cycle re-joins without a
nonce flush. If that holds, the rest — config schema, sensor binding, the
payload codec, more radios/boards — is mechanical.

## How WireStudio pivots afterward

The current `targets/lorawan/` splits cleanly into "reuse" and "retire":

| Piece | Fate after pivot |
|---|---|
| `chirpstack.py` (provision, keys, **FlushDevNonces**, activation) | **Reuse as-is** — independent of how firmware is built |
| `confirm.py` (MQTT join/uplink + HA entity check) | **Reuse as-is** |
| codec / payload-field spec ↔ ChirpStack `decodeUplink` | **Reuse**, driven by the component `payload:` config instead of `firmware_gen.py` |
| `firmware_gen.py`, `templates/` (platformio.ini, main.cpp, arduino snippets) | **Retire** — replaced by ESPHome YAML + the external component |
| per-component arduino read snippets in `library/components/*.yaml` | **Retire** — ESPHome sensor platforms produce the values |
| `compile.py` (in-pod PlatformIO worker) | **Converge** onto ESPHome's build path via the existing `BuildBackend` seam — LoRaWAN compile becomes `esphome compile` of a config with `external_components:` |
| runtime serial provisioning (`provision.py`, §7 of the plan) | **Reconsider** — device-authoritative DevEUI (§2.2/2.3) can be preserved in the component, or keys injected via ESPHome secrets at build; decide during the spike |

The payoff is structural: the LoRaWAN target stops being a second generation
pipeline and rejoins the ESPHome path. One target, one build backend
(`BuildBackend`), and the intent-to-device capability layer (roles /
provides / accepts / automations) applies to LoRaWAN devices for free instead
of being ESPHome-only. The `targets` plugin seam stays — `lorawan` becomes a
thin target that emits the `external_components:` block and owns ChirpStack
provisioning + HA confirm, not a parallel firmware generator.

This is a deliberate walk-back of a hardware-validated path, so it stays
additive until the spike proves out: the standalone firmware generator keeps
working and shipping behind `[lorawan]` until the component path joins on real
hardware and decodes in HA. No flag day.

## Open questions / risks

- **RX-window timing under ESPHome's cooperative loop** — the spike's whole
  point. Second-core pinning vs bounded blocking; measure WiFi/API
  responsiveness during uplink.
- **Upstream RadioLib vs an ESPHome-compile fork** — prefer upstream via
  `lib_deps`; only fork if it won't build. Avoid inheriting fork maintenance.
- **Nonce persistence path** — `ESPPreferences` (drops the LoRaWAN_ESP32
  dependency) vs keeping `ropg/LoRaWAN_ESP32`. Verify the §2.1 fix holds
  under whichever wins.
- **Provisioning model** — device-authoritative DevEUI (§2.2/2.3) vs
  build-time key injection via ESPHome secrets. The latter is simpler in the
  ESPHome model; the former kills the DevEUI-mismatch class. Decide on
  evidence during the spike.
- **CI gate** — LoRaWAN examples validate via `esphome config`/`compile`
  only if the external component is fetchable in CI (`external_components`
  with a pinned ref). Wire this into the existing esphome gate rather than a
  separate `lorawan-firmware` workflow once the pipelines merge.
- **Repo ownership** — `lorawan-for-esphome` is a new artifact surface
  WireStudio depends on by pinned ref. Pin it; treat a bump as a reviewed
  change like the ESPHome version pin.

## Sources

- ESPHome LoRaWAN tracking: https://github.com/esphome/feature-requests/issues/2634
- RadioLib (LoRaWAN MAC, upstream): https://github.com/jgromes/RadioLib
- RadioLib ESPHome-compile fork: https://github.com/christianhubmann/esphome-RadioLib
- RadioLib ESPHome-compile fork: https://github.com/smartoctopus/RadioLib-esphome
- Raw LoRa ESPHome component (not LoRaWAN): https://github.com/PaulSchulz/esphome-lora-sx126x
- RadioLib on ESP Component Registry: https://components.espressif.com/components/jgromes/radiolib
- Carried-forward LoRaWAN findings + ChirpStack/provisioning detail: [`LORAWAN_TARGET_PLAN.md`](LORAWAN_TARGET_PLAN.md)

[feature-requests#2634]: https://github.com/esphome/feature-requests/issues/2634
