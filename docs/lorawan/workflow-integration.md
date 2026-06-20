# LoRaWAN target — workflow integration with `lorawan-for-esphome`

Status: **scoping / decided in principle, not started.** Builds on
[`esphome-component-pivot.md`](esphome-component-pivot.md), which decided the
architecture (`lorawan-for-esphome` is the *device half*; WireStudio emits
ESPHome YAML referencing it and orchestrates the server side). This doc covers
the **workflow** changes inside WireStudio needed to deliver the hardware-join
test: data model, YAML emission, secrets routing, ChirpStack orchestration,
and the web flasher.

The standalone Arduino path (`docs/lorawan/LORAWAN_TARGET_PLAN.md`) keeps
shipping behind the `[lorawan]` install extra until the new path joins on real
hardware. No flag day.

## Goal

A user picks a LoRaWAN-capable design in the studio, clicks "Flash LoRaWAN
device", and the system:

1. Provisions the device in ChirpStack (DevEUI / AppKey / FlushDevNonces).
2. Emits ESPHome YAML referencing `lorawan-for-esphome` with the keys in
   `secrets.yaml`.
3. Compiles via the existing ESPHome `BuildBackend` (no LoRaWAN-specific
   build worker).
4. Flashes from the browser via the existing WebSerial flasher.
5. Surfaces the join + first uplink (MQTT) in the UI; HA sees the entity.

Hardware target for the spike: TTGO LoRa32 v1 (SX1276), already a
hardware-validated board for the current standalone target, against the live
ChirpStack 4.17 (US915 sub-band 2) documented in
[`chirpstack-lorawan-setup.md`](chirpstack-lorawan-setup.md).

## Concrete change set

Six pieces, in the order they need to land. Each item names the rough surface
area and the question it has to answer.

### 1. `Design.lorawan` block (model + schema)

A first-class optional `lorawan:` block on `Design`, mirrored in
`schema/design.schema.json` per the "model and schema change together" rule:

```python
class LoRaWAN(_Strict):
    region: Literal["US915", "EU868", "AU915", "AS923"] = "US915"
    sub_band: int = 2
    radio: RadioConfig                    # sourced from board library `radio:`
    uplink_interval_ms: int = 300_000
    payload: list[PayloadField]           # ordered; the codec contract
    # Filled by the provision flow; never authored by the user.
    dev_eui: Optional[str] = None
    join_eui: Optional[str] = None
    chirpstack_application_id: Optional[str] = None
    device_profile_id: Optional[str] = None

class PayloadField(_Strict):
    sensor: str                           # design-level component_id
```

The radio block is read from the board library's existing `radio:` metadata
(Heltec V2/V3, TTGO LoRa32 v1/v2, T-Beam all carry it from the standalone
target's phase 1). No template changes there.

`PayloadField` is the codec contract: ChirpStack's `decodeUplink` JS and the
device's wire bytes are generated from the same ordered list, exactly as
today. Phase-4 single-output sensor `id`s map cleanly; multi-channel sensors
need per-channel `id:` template surgery (already scoped separately in the
intent thread, lands when the LoRaWAN target needs it).

### 2. Generator branch — emit `external_components:` + `lorawan:`

`targets/esphome/yaml_gen.py` checks `design.lorawan`. When present:

```yaml
external_components:
  - source: github://moellere/lorawan-for-esphome
    ref: <pinned commit SHA>
    components: [lorawan]

lorawan:
  id: lw
  region: US915
  sub_band: 2
  dev_eui:  !secret dev_eui
  join_eui: !secret join_eui
  app_key:  !secret app_key
  uplink_interval: 5min
  radio:
    chip: sx1276
    cs_pin:   GPIO18
    rst_pin:  GPIO23
    dio0_pin: GPIO26

sensor:
  - platform: lorawan
    lorawan_id: lw
    sensor: <each payload field's component id>
```

Component-side sensors continue to render through their existing Jinja
templates. The LoRaWAN target *adds* payload bindings; it doesn't touch
sensor blocks. The new emission is additive over the phase-5 generator.

### 3. Secrets routing — extend recognised keys

`Design.fleet.secrets_ref` already routes `wifi_ssid`/`wifi_password`/`api_key`
into `!secret` references via the existing `Secret` class. Add `dev_eui`,
`join_eui`, `app_key` to the recognised keys; the values themselves never
enter `design.json` (CLAUDE.md rule, preserved). They live in the per-design
`secrets.yaml` that the build consumes, written by the provision step.

### 4. ChirpStack provision flow — extend the consumer side

`targets/lorawan/chirpstack.py` already mints DevEUI/AppKey, creates the
device, calls `FlushDevNonces`, and confirms the join. It's reused
**unchanged**. What changes is what it's wired into:

- A new endpoint `POST /lorawan/provision/{design_id}` that:
  1. Reads the chip's base MAC over WebSerial (esptool-js; already done in
     `usb-detect.ts`) and derives the DevEUI per `LORAWAN_TARGET_PLAN.md`
     §2.2. *Manual override field* is also accepted, so the first hardware
     test isn't coupled to the WebSerial-side derivation.
  2. Calls `chirpstack.py` to ensure the profile + application, create the
     device with the minted AppKey, and flush nonces.
  3. Writes `secrets.yaml` next to the rendered ESPHome config with the
     `dev_eui`/`join_eui`/`app_key` values.
- `targets/lorawan/compile.py` retires. The build is the same
  `BuildBackend.run()` call as any ESPHome device — the LoRaWAN target stops
  carrying its own PlatformIO worker.

### 5. Web flasher — small additions on the existing path

The WebSerial flasher already does chip-detect + flash + serial-monitor. Add:

- A **"LoRaWAN device"** flow in the flash dialog that calls the new
  `/lorawan/provision/{design_id}` endpoint before the build, then runs the
  standard ESPHome build via the build backend.
- The serial monitor recognises `lorawan-for-esphome`'s join log line (the
  component owns that string — coordinate the exact format with the device
  repo when the spike fixes a join log).
- A status surface for `targets/lorawan/confirm.py`'s MQTT
  `event/join` + first `event/up` watch — the existing module already does
  this, the UI just needs to subscribe.

### 6. Retirement (parallel to the new path, not before)

The standalone `firmware_gen.py` / `templates/` / `compile.py` and the
per-component arduino read snippets in `library/components/*.yaml` stay
shipping behind the `[lorawan]` extra. They retire only once the
external-component path joins on real hardware and the chirp HA integration
sees the entity. No flag day.

## Locked decisions

Two, recorded so they land in the W1 / W2 diffs and don't get relitigated:

1. **External-component pin form: pinned commit SHA.** The
   `external_components:` block uses `ref: <sha>` against
   `github://moellere/lorawan-for-esphome`. Tags require the component repo
   to start tagging, which the spike isn't ready for. **Future:** switch to
   pinned tag once `lorawan-for-esphome` cuts its first stable release
   (post hardware-join validation). Until then, bumps are reviewed changes
   like any other dependency pin.
2. **DevEUI source: MAC-derived from eFuse, with a manual override field.**
   Default behaviour is the pivot-doc plan — read the chip's base MAC over
   WebSerial during flashing and derive an EUI-64 per
   `LORAWAN_TARGET_PLAN.md` §2.2. The `LoRaWAN.dev_eui` field on `Design` is
   optional and, when set, overrides the derivation. The override defuses the
   `getEfuseMac()` byte-order risk (`§2.2` caveat / arduino-esp32 #6458) for
   the first hardware test by removing one variable from the failure surface,
   and remains available for fleet deployments that want device identity
   under operator control.

## Suggested phasing

Three commits, smallest-first, each independently shippable. Each step is
gated by the `esphome config` CI check the studio already runs.

| Step | What | Why this size |
|---|---|---|
| **W1** | `Design.lorawan` IR + schema. Pure data; no rendering yet. Tests over model round-trip + schema validation. | Catches the IR shape before any generator/orchestration depends on it. ~80 lines. |
| **W2** | Generator emits `external_components:` + `lorawan:` + payload `sensor:` bindings when `design.lorawan` is present. **Worked example**: TTGO LoRa32 v1 with one battery uplink, gated by `esphome config`. | After this step the studio renders a flashable YAML by hand: manually mint keys, drop them in `secrets.yaml`, build, flash. Enough to attempt the **hardware join test** before the orchestration UI lands. ~150 lines + a golden. |
| **W3** | `/lorawan/provision/{design_id}` endpoint (DevEUI from MAC or manual, ChirpStack provision + nonce flush, `secrets.yaml` write); web flasher "LoRaWAN device" path; serial-monitor join-line recognition; MQTT status surface. | Turns W2's by-hand flow into one-click. ~200 lines, mostly glue over `chirpstack.py` / `confirm.py` / the existing flasher. |

W2 is the **smallest unit that unblocks the hardware test**, which is the
real point of this whole thread. W3 is what makes it a product feature for
non-developers.

## Hardware-join test acceptance

The spike's payoff. Confirms `lorawan-for-esphome` works against a real
gateway and the WireStudio integration is correct end-to-end.

1. Studio renders ESPHome YAML for a TTGO LoRa32 v1 design with a single
   sensor payload (e.g. ADC battery).
2. Provision: DevEUI minted (manual or MAC-derived), device registered in
   ChirpStack, `FlushDevNonces` called, `secrets.yaml` written.
3. Build: ESPHome `BuildBackend` produces `firmware.bin` referencing
   `github://moellere/lorawan-for-esphome@<sha>`.
4. Flash: WebSerial flash succeeds; device boots.
5. Join: serial monitor shows the component's join log; ChirpStack `event/join`
   fires (on the HA MQTT broker, app topic).
6. Uplink: first `event/up` decodes through the codec, fields appear under
   `object`; HA chirp integration creates the entity.
7. **Power-cycle re-joins without nonce flush** — proves nonce persistence
   via `ESPPreferences` (the spike's main risk).

The test is hand-driven after W2 lands and one-click after W3.

## Risks / unknowns

- **ESPHome external-components fetch.** ESPHome's build needs outbound
  network at build time to clone `lorawan-for-esphome` from GitHub. The
  `BuildBackend` container has the existing build's network policy — confirm
  it covers `github://` fetches, or pre-clone the component into a build-time
  cache. This is the most likely "first build fails" cause.
- **eFuse-MAC byte order.** The pivot doc §2.2 caveat still applies —
  `getEfuseMac()` byte order varies across arduino-esp32 2.x. W2's manual
  override field defuses this for the first hardware test; W3 has to get the
  derivation right.
- **Join log format.** WireStudio's serial monitor parses for "joined". The
  exact string is owned by `lorawan-for-esphome`. Lock the format with the
  device repo before W3 — one line of coordination, but easy to miss.
- **Component compile-time keys.** ESPHome's `secrets.yaml` is read at compile
  time, not flash time. A re-key requires a rebuild. Acceptable for the spike
  (and matches the pivot doc's "build-time injection" decision), but worth
  surfacing because users may expect serial-rekey behaviour from the
  standalone path.

## What stays where (clean boundary)

- **`lorawan-for-esphome`:** radio init, OTAA join, FCnt, nonce persistence,
  payload packing. **Never** talks to ChirpStack's management API.
- **WireStudio:** ChirpStack provisioning, `FlushDevNonces`, `secrets.yaml`
  authoring, build orchestration, WebSerial flash, MQTT join/uplink confirm,
  HA entity check.

This line is exactly what
[`lorawan-for-esphome`'s HANDOFF.md][handoff] enforces on the device side;
this doc enforces it on the orchestrator side.

## Sources

- [`esphome-component-pivot.md`](esphome-component-pivot.md) — the architecture decision
- [`LORAWAN_TARGET_PLAN.md`](LORAWAN_TARGET_PLAN.md) — key findings carry forward; §2 is canonical for DevNonce / DevEUI / MSB key behaviour
- [`chirpstack-lorawan-setup.md`](chirpstack-lorawan-setup.md) — gateway + broker reference (IPs, topics, creds)
- `lorawan-for-esphome` — the device half, scaffolded and building; hardware join unverified at time of writing

[handoff]: https://github.com/moellere/lorawan-for-esphome/blob/main/HANDOFF.md
