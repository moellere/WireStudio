# WireStudio — LoRaWAN flash/provision target: build plan & handoff

> **Pivot in progress (2026-06):** the firmware-*generation* half of this plan
> (standalone PlatformIO/Arduino project — `firmware_gen.py`, `templates/`, the
> per-component arduino snippets) is being re-founded on an ESPHome external
> component. See [`esphome-component-pivot.md`](esphome-component-pivot.md). The
> §2 key findings and the ChirpStack / provisioning / HA-confirm work below are
> carried forward unchanged; the standalone path keeps shipping until the
> component path is hardware-validated.

> **This doc was written in a different working directory and is meant to be dropped into the
> WireStudio repo.** Suggested location: `docs/lorawan/`. It is a self-contained handoff:
> a fresh Claude session opened in `~/wirestudio` should be able to start from this file alone.

---

## 0. First actions for a fresh session in `~/wirestudio`

1. Read the repo's own conventions and architecture first:
   - `CLAUDE.md` (voice, "design.json is the single source of truth", no premature abstraction,
     validate at boundaries, `# TODO(0.x):`, "no new top-level docs", "no splitting `wirestudio/`
     into more packages until 0.2 needs them").
   - `wirestudio/model.py`, `wirestudio/schema/design.schema.json` (the `Design` model + JSON schema —
     they must change together; `schema_version` is `"0.1"`).
   - `wirestudio/library/boards/*.yaml`, `wirestudio/library/components/*.yaml`.
   - `wirestudio/csp/pin_solver.py`, `wirestudio/csp/compatibility.py`.
   - `wirestudio/api/serve.py`, `wirestudio/api/app.py`, `wirestudio/api/schemas.py`.
   - `wirestudio/generate/yaml_gen.py`, `wirestudio/generate/ascii_gen.py` (the existing generators —
     these become the `esphome` target).
   - `wirestudio/fleet/client.py` (the "push to remote builder, poll build log" pattern to mirror).
   - `web/src/lib/usb-detect.ts`, `web/src/lib/bootstrap.ts` (`DetectedChip`), `web/src/components/UsbDetectDialog.tsx`,
     `CapabilityPickerDialog.tsx`, `ParamForm.tsx`, `PinoutView.tsx`.
   - `docs/deployment.md`, `deploy/k8s.yaml`.
2. Read `chirpstack-lorawan-setup.md` (bundled next to this file) — the live ChirpStack/LoRaWAN
   infra this target talks to. §10 essentials are also embedded in §10 below.
3. **Commit the key findings (§2) to WireStudio's project memory** — they were established through
   research in a previous session and should not be relitigated.
4. Confirm the locked decisions (§3) still hold, then start at Phase 0 (§11).

---

## 1. Objective

Add a second **target** to WireStudio: a web-based **compile → flash → provision → verify** service for
**LoRaWAN** devices, alongside the existing ESPHome-YAML target. The user often works on a Chromebook/Chromebox
and cannot run a local toolchain. The service must:

- Detect/select a **LoRaWAN-capable board** over USB (WebSerial), pick peripheral sensors/actuators and params.
- Compile firmware **server-side** (in the pod/container).
- **Flash from the browser** (esptool-js / WebSerial) to the device plugged into the *client* machine.
- **Programmatically provision the device in ChirpStack** (create device + keys), retrieve DevEUI/AppKey.
- Confirm OTAA **join**, confirm sensor **uplinks are received and decoded** (the goal is *data is
  flowing and HA is receiving it* — **not** value-sanity validation, e.g. a DHT22 reporting 450 °C is
  out of v1 scope), and confirm the device appears in the **Home Assistant chirp integration**.

Board selection is **constrained to boards that carry a LoRa/LoRaWAN radio** (SX1276/78 or SX1262).

---

## 2. Key findings that shape the design (do not relitigate)

### 2.1 The dominant OTAA failure mode is **DevNonce replay rejection**, not byte order
LoRaWAN 1.0.4/1.1 requires every JoinRequest to carry a **monotonically increasing DevNonce**. ChirpStack
enforces replay protection: a DevNonce it has already seen (or a lower one) → the join is **silently dropped**,
which presents identically to an "authentication" failure. **Re-flashing or power-cycling** a naive firmware
resets the counter to 0 → ChirpStack rejects. The user confirmed they already handle MSB byte order correctly;
this is the real cause of their join history. Evidence (their exact board, TTGO LoRa32):
- RadioLib #1480 — "Join failed: -1116 (DevNonce has already been used)… on TTGO LoRa32 after power cycle".
- ChirpStack forum — "Device on OTAA (TTGO LoRa32 V1) not connecting unless 'Flush OTAA device nonces'".

**The flasher fixes this in two places, both automated:**
1. **Firmware:** RadioLib + [`ropg/LoRaWAN_ESP32`](https://github.com/ropg/LoRaWAN_ESP32) persistence — stores
   DevNonces in **NVS flash**, session in RTC RAM → nonces survive reboots.
2. **Server:** on every (re)provision, call ChirpStack to **flush the device's OTAA DevNonces** (same as the
   UI's "Flush OTAA device nonces") so a freshly-flashed device joins cleanly.

**Sharp edge:** a full-chip erase (`esptool --erase-all`) wipes NVS and resets nonces. Rule: re-flash the
**app region only** (preserve NVS) on a known device, OR pair a full erase with an automatic ChirpStack
nonce-flush. Getting this wrong silently reintroduces the failure.

### 2.2 DevEUI is reliably readable over USB — with one caveat
The ESP32 base MAC is **factory-burned in eFuse** and readable by esptool from the **ROM bootloader**, so it
works on a **blank, unflashed board** — no firmware needed. esptool-js exposes it (`loader.chip.readMac()`),
and WireStudio's `usb-detect.ts` already reads it in the same step it detects the chip. Standard derivation:
MAC-48 → EUI-64 by inserting `0xFF,0xFE`.
**Caveat:** `ESP.getEfuseMac()` byte order changed/broke across arduino-esp32 2.x (arduino-esp32 #6458). If
firmware derives the DevEUI at runtime with a different byte order than what was registered, the join's DevEUI
matches no device → reject. **Fix: one component is authoritative for the DevEUI; never derive it twice.**

### 2.3 Runtime serial provisioning is the right model — and mostly off-the-shelf
`ropg/LoRaWAN_ESP32` already manages **DevEUI/AppKey/NwkKey/band+subband in NVS**, and **if NVS has no
provisioning data it prompts for the values over the serial port and stores them.** So "flash credential-free
firmware → device emits DevEUI → register → push keys back → join" is an adaptation of an existing serial flow,
not new research. This makes the **device authoritative for its DevEUI** (kills the §2.2 mismatch class) and
lets us **compile one generic binary per board+peripheral profile and cache it** (no per-device compile).

### 2.4 Other load-bearing facts
- **RadioLib** takes DevEUI/JoinEUI/AppKey in **MSB** order (matches the ChirpStack UI). Preferred over LMIC
  (LMIC wants byte-reversed EUIs but MSB key — a separate footgun).
- **Region/sub-band must match the gateway: US915, sub-band 2.** A wrong channel mask = device transmits joins
  on channels the gateway never hears = "won't join" that is not auth. The generator must hard-pin this.
- **WebSerial + esptool-js run client-side in Chrome (incl. ChromeOS).** The server never touches USB → the
  Chromebook constraint is satisfied by the compile-server / browser-flasher split. WireStudio already proves
  the WebSerial half works.

---

## 3. Locked architecture decisions

| Decision | Choice | Why |
|---|---|---|
| Relationship to WireStudio | **Monorepo + pluggable targets** (not a fork) | One shared core; LoRaWAN is an additive target. The rename from esphome-studio enables this. |
| LoRaWAN firmware stack | **RadioLib + `ropg/LoRaWAN_ESP32`** | MSB creds match ChirpStack; persistence library fixes DevNonce + does serial provisioning. |
| Provisioning model | **Generic cached firmware + serial runtime provisioning** (primary); compile-time credential injection (secondary/field option) | Device-authoritative DevEUI, no per-device compile, no re-flash to re-key. |
| Config channel | **Serial over the already-open WebSerial port** (primary); **WebBluetooth** optional for field re-provisioning; **skip SoftAP** (bad on Chromebook) | Port is already open from flashing — no pairing, no network switch. |
| Compilation | **In-pod PlatformIO worker**, toolchain/framework cached in the image/volume | Self-contained; both reference repos use PlatformIO. |
| Deployment | **One multi-arch OCI image → k8s pod *and* Proxmox LXC** (the target homelab is Proxmox LXC + k8s); `docker run`/`podman` inside an LXC or a direct install both work; external users get `docker run` | Reuses WireStudio's existing image + `deploy/k8s.yaml` + ArgoCD overlays. The PlatformIO compile worker runs **in-pod** on k8s and **natively** in an LXC. |
| Anti-bloat contract | Core knows nothing about ESPHome or LoRaWAN; target-specific heavy deps are **optional extras** + feature-gated | Same pattern WireStudio already uses for agent/fleet/MCP. |

---

## 4. WireStudio reuse map

| Capability | Source |
|---|---|
| WebSerial chip detect + MAC read | **Reuse** `web/src/lib/usb-detect.ts`, `UsbDetectDialog.tsx` (esptool-js already a dep) |
| Board + component + pin model, JSON schema | **Reuse/extend** `model.py`, `schema/design.schema.json` |
| Board/component library + CSP pin solver + compat checker | **Reuse** `library/`, `csp/` (boards gain a `radio:` block) |
| Web shell: board pick, capability picker, param forms, pinout | **Reuse** React components |
| FastAPI serve + single-image Docker + k8s/ArgoCD | **Reuse** `api/`, `docs/deployment.md`, `deploy/` |
| "Push to remote builder, poll build log" pattern | **Reuse as template** `fleet/client.py` |
| WebSerial **flash** (writeFlash) + **serial monitor** | **New** `web/src/lib/flash.ts` |
| **ChirpStack gRPC client** (provision, keys, nonce-flush, activation) | **New** `targets/lorawan/chirpstack.py` |
| **LoRaWAN firmware generator** (PlatformIO + RadioLib + LoRaWAN_ESP32) | **New** `targets/lorawan/firmware_gen.py` — core IP |
| **In-pod PlatformIO compile worker** | **New** `targets/lorawan/compile.py` |
| **Join + HA-entity confirmation** | **New** (ChirpStack MQTT + HA REST) |

> ESPHome has **no LoRaWAN MAC stack** — its `sx127x` component is raw packet radio, not OTAA. So the LoRaWAN
> firmware generator is genuinely new; everything around it is liftable.

---

## 5. Target-plugin architecture & repo structure

This is the 0.2-style restructure that WireStudio's CLAUDE.md anticipates ("no splitting `wirestudio/` into more
packages **until 0.2 needs them**") — adding a second target **is** that trigger. Treat the split as a
deliberate, reviewed change, kept minimal and non-breaking for the ESPHome path.

```
wirestudio/
  core/                       # shared; knows nothing about any target
    model.py                  # + Design.target, + Design.lorawan; keep Design strict (extra=forbid)
    library/                  # boards/components; LoRaWAN boards gain a radio: block
    csp/                      # pin_solver, compatibility (unchanged)
    designs/                  # design store (unchanged)
  targets/
    base.py                   # TargetPlugin interface + registry
    esphome/                  # the current product, moved behind the interface
      __init__.py             # registers TargetPlugin(id="esphome", ...)
      yaml_gen.py, ascii_gen.py, fleet/    # today's generate/ + fleet/
    lorawan/                  # NEW (optional extra: pip install wirestudio[lorawan])
      __init__.py             # registers TargetPlugin(id="lorawan", board_filter=has_radio, ...)
      firmware_gen.py         # design -> PlatformIO project (templates/)
      templates/              # platformio.ini.j2, main.cpp.j2, partitions, per-component snippets
      compile.py              # in-pod PlatformIO build worker + artifact cache
      chirpstack.py           # gRPC client: profile/app/device/keys/flush-nonces/activation
      provision.py            # serial provisioning protocol (host side)
      confirm.py              # MQTT join/uplink watch + HA entity check
  api/
    app.py / serve.py         # mounts each enabled target's router
web/src/
  lib/usb-detect.ts           # shared (exists)
  lib/flash.ts                # NEW shared: esptool-js writeFlash + serial monitor
  targets/esphome/            # existing design panes (re-homed)
  targets/lorawan/            # flash / provision / monitor / status panes
```

`TargetPlugin` (sketch — keep it small, validate at boundaries, no speculative hooks):

```python
# wirestudio/targets/base.py
class TargetPlugin(Protocol):
    id: str                                   # "esphome" | "lorawan"
    def board_ids(self, library) -> list[str]: ...        # filtered selectable boards
    def validate(self, design: Design) -> list[DesignWarning]: ...
    def router(self) -> APIRouter | None: ...             # target-specific endpoints, mounted under /api/<id>
    # esphome implements generate()->yaml; lorawan implements firmware/provision/flash endpoints
```

Heavy LoRaWAN deps (`grpcio` + `chirpstack-api`, `paho-mqtt`, and the PlatformIO invocation) live under an
optional extra and a feature gate, so an ESPHome-only install never pulls them. Mirror the env-var gating in
`docs/deployment.md`.

---

## 6. Data model & library schema extensions

### 6.1 `Design` (in `core/model.py`) — keep `extra="forbid"`
```python
class LoRaWAN(_Strict):
    region: Literal["US915"] = "US915"
    sub_band: int = 2
    join_eui: Optional[str] = None                  # MSB hex; default to a fixed JoinEUI if unset
    chirpstack_application_id: Optional[str] = None # UUID
    device_profile_id: Optional[str] = None         # UUID (US915 sub-2 profile)
    provisioning: Literal["runtime_serial", "compile_time"] = "runtime_serial"
    dev_eui: Optional[str] = None                   # filled after provisioning (device-authoritative)

class Design(_Strict):
    ...
    target: Literal["esphome", "lorawan"] = "esphome"   # default keeps existing behavior
    lorawan: Optional[LoRaWAN] = None
```
Update `schema/design.schema.json` in the same change; regenerate any affected goldens in `tests/golden/`.

### 6.2 Board library — add a `radio:` block (the critical generator input)
Only boards with `radio:` are offered by the lorawan target's `board_filter`.
```yaml
# library/boards/ttgo-lora32-v1.yaml  (extend; pins already present as onboard_peripherals.lora_sx1276)
radio:
  chip: sx1276            # sx1276 | sx1278 | sx1262
  radiolib_class: SX1276  # RadioLib module class name used in the template
  pins: {cs: GPIO18, rst: GPIO23, dio0: GPIO26, dio1: null, busy: null}
  tcxo_voltage: 0.0       # SX1262 boards usually need a TCXO ref (e.g. 1.8); 0 = none
  dio2_as_rf_switch: false
```
SX1262 boards (T-Beam v1.1+, Heltec V3, RAK WisBlock) use `dio1` + `busy` (+ usually `tcxo_voltage`,
`dio2_as_rf_switch: true`); SX1276/78 use `dio0` (+ optional `dio1`). The template branches on `radiolib_class`.

Initial LoRaWAN board set: `ttgo-lora32-v1` (SX1276, already in lib), `ttgo-t-beam` (SX1276 v1.0 / SX1262 v1.1+),
plus add Heltec WiFi LoRa 32 V3 (SX1262) and a RAK WisBlock core as the library grows.

---

## 7. Provisioning pipeline (primary: runtime serial)

```
1. WebSerial detect      esptool-js → MCU family + base MAC (works on blank board). Confirms the picked
                         model's MCU; MAC is a fallback DevEUI seed.
2. Serve generic .bin    cache key = hash(board, peripheral set, region, sub_band, fw template version).
                         Compile only on cache miss (§9).
3. Flash app region      esptool-js writeFlash; preserve NVS on a known device (§2.1 sharp edge).
4. Device emits DevEUI   firmware prints it over the still-open serial port; host reads it.
5. Server provisions     ChirpStack: ensure profile+app → create device + AppKey → FLUSH DevNonces (§8).
6. Push keys back        host writes JoinEUI + AppKey to device over serial → device stores in NVS.
7. Join + confirm        device joins; serial shows progress; server confirms via MQTT event/join + first
                         event/up, then checks the HA chirp entity exists.
```

Serial protocol (adapt LoRaWAN_ESP32's prompt into a deterministic, newline-delimited exchange the web
flasher drives — AT-ish, host-initiated):
```
<- DEVEUI 70b3d5xxxxxxxxxx          # device announces on boot when unprovisioned
-> SET JOINEUI <16-hex MSB>
-> SET APPKEY  <32-hex MSB>
-> SET BAND US915
-> SET SUBBAND 2
-> PROVISION                        # device writes NVS
<- OK
-> JOIN
<- JOIN OK | JOIN FAIL <code>       # streamed; also visible in the serial monitor
```
Device state machine: `unprovisioned → provisioned(NVS) → joined`. Nonces persist across reboots so a later
power-cycle does not re-trigger the §2.1 failure.

Secondary (compile-time) path: server injects literal DevEUI (server-derived from the §1 MAC) + AppKey into
`main.cpp.j2` and compiles a one-off binary. Use for field flashing without the serial handshake.

---

## 8. ChirpStack integration

**Endpoints (see §10 / bundled `chirpstack-lorawan-setup.md`):** gRPC/REST/UI multiplexed at
`http://<chirpstack-host>:8080`. Auth = a **Bearer API token generated in the UI** (NOT the JWT signing secret).
App-layer MQTT is bridged to the HA broker at `<ha-mqtt-host>:1883` (user `chirpstack`).

**gRPC sequence (`chirpstack-api` Python):**
1. `DeviceProfileService` — ensure a **US915, sub-band 2** profile exists (MAC version, OTAA, ADR). Cache its UUID.
2. `ApplicationService` — ensure the target application exists. Cache its UUID.
3. `DeviceService.Create` — DevEUI (device-reported), name, profile, app.
4. `DeviceService.CreateKeys` — set the key. **LoRaWAN 1.0.x footgun:** the AppKey
   goes in the `DeviceKeys.nwk_key` field, *not* `app_key` (`app_key` is 1.1-only).
   We pin MAC version 1.0.4, so the root key is written to `nwk_key`. Getting this
   wrong is another silent "won't join" class. (`UpdateKeys` on re-key.)
5. **Flush DevNonces** — the API behind the UI's "Flush OTAA device nonces" (verify exact RPC name against the
   pinned `chirpstack-api` version; it lives on `DeviceService`). Call on every (re)provision. **This is the §2.1 fix.**
6. Confirm join: subscribe to MQTT `application/{app}/device/{devEui}/event/join` on the HA broker, OR poll
   `DeviceService.GetActivation`. Then watch `.../event/up` for the first decoded uplink (the `object` codec field).

**HA confirmation:** the chirp custom component creates entities from ChirpStack. Confirm via HA REST
(`GET /api/states`, long-lived token) filtered to the device, or delegate to the Home Assistant MCP per the
global `~/CLAUDE.md` subagent pattern.

**Secrets:** follow WireStudio's "secrets never in `design.json`" rule — ChirpStack token, MQTT creds, and HA
token come from env/secret refs, not the design or this doc.

---

## 9. Firmware generation & compile worker

**`firmware_gen.py`:** pure function `Design → PlatformIO project dir` via Jinja2 templates. "Generic" = generic
over **credentials**, not peripherals (sensor code differs), so the cache key includes the peripheral set.

`templates/platformio.ini.j2` (board key from `board.platformio_board`):
```ini
[env:{{ board.platformio_board }}]
platform = espressif32
board = {{ board.platformio_board }}
framework = arduino
monitor_speed = 115200
lib_deps =
    jgromes/RadioLib
    ropg/LoRaWAN_ESP32
{% for dep in component_lib_deps %}    {{ dep }}
{% endfor %}
build_flags =
    -D LW_REGION_US915
    -D LW_SUBBAND={{ lorawan.sub_band }}
```

`templates/main.cpp.j2` (branch on `radio.radiolib_class`; US915 + sub-band 2 channel mask; LoRaWAN_ESP32
persistence for nonces; serial provisioning when NVS empty; per-component read loop assembled from snippets):
```cpp
// radio instance per board metadata
{{ radio.radiolib_class }} radio = new Module({{ radio.pins.cs }}, {{ radio.pins.dio1 or radio.pins.dio0 }},
                                              {{ radio.pins.rst }}, {{ radio.pins.busy or 'RADIOLIB_NC' }});
LoRaWANNode node(&radio, &US915, {{ lorawan.sub_band - 1 }});   // sub-band index
// setup(): persist.begin(); if (!provisioned) serialProvision();  node.beginOTAA(joinEUI, devEUI, nwkKey, appKey);
//          restore nonces from NVS; node.activateOTAA();
// loop(): {% for c in components %}{{ c.read_snippet }}{% endfor %}  build payload; node.sendReceive(...)
```
Each `library/components/<id>.yaml` gains a small **arduino read snippet** (parallel to its existing ESPHome
`yaml_template`) so the loop is assembled from selected peripherals. The uplink payload byte layout should be
emitted alongside a matching **ChirpStack codec** (the `decodeUplink` JS), so HA sees named fields — keep the
two in lockstep (one generator owns both).

**`compile.py`:** `pio run` in the pod → merged `.bin`. Cache the PlatformIO core + ESP32 framework + toolchain
in the image layer / a mounted volume so warm builds are ~1–2 min and the pod is offline-capable. Add a build
queue + timeout; if exposed to other users, sandbox it (it executes a build). Mirror `fleet/client.py`'s
job/log-polling shape for the build-status API so the web UI can stream logs.

---

## 10. ChirpStack infra essentials (full detail in bundled `chirpstack-lorawan-setup.md`)

- Gateway `<gw-host>` @ `<gw-ip>` (typical setup: remote, behind VPN). RAK2287 / SX1302, **US915 sub-band 2**
  (`us915_1`): 903.9–905.3 MHz multi-SF + 904.6 MHz 500 kHz. Gateway ID is the chip-silicon EUI-64
  (read off your hardware).
- ChirpStack 4.17 @ `http://<chirpstack-host>:8080` (gRPC + REST + UI on one port). Token via UI → API Keys.
- App MQTT bridged to HA broker `<ha-mqtt-host>:1883`, user `chirpstack`. Topics:
  `application/{app_id}/device/{dev_eui}/event/{up,join,ack,txack,status,...}` (consume), `.../command/down`
  (downlink). Decoded sensor fields arrive under the payload `object` key (from the device profile codec).
- Bridge health: `gateway/<gw-host>/bridge/state` (`1`/`0`, retained). The flasher backend should reach the
  ChirpStack gRPC API and the HA MQTT broker; both need to be reachable from the network the studio runs on.

---

## 11. Phased build plan

Each phase is independently testable and (mostly) shippable. Use `# TODO(0.x):` tags per WireStudio convention.

> **Status (2026-05-24):** Phase 0 (additive seam, not the §5 full relocation), Phase 1
> (radio boards + `has_radio` filter), Phase 2 (firmware generator), and **Phase 3**
> (in-pod PlatformIO compile worker + cache, `/lorawan/compile` SSE endpoints, CI gate,
> `WITH_LORAWAN` Docker layer) are **done and green**: all three radio boards
> (`ttgo-lora32-v1`, `ttgo-t-beam` SX1276; `heltec-wifi-lora32-v3` SX1262) compile to a
> `firmware.bin` via `pio run` (RadioLib 7.6.0 + LoRaWAN_ESP32 1.3.0). Phase 5
> (ChirpStack client incl. `FlushDevNonces`) is built and **validated against the live
> 4.17 server**. The firmware uses LoRaWAN_ESP32's `persist.manage()` (serial
> provisioning when NVS is empty) — there is no `node->setBand()`/`beginOTAA()` in user
> code; `manage()` does that internally. (Docker `WITH_LORAWAN=true` layer is written but
> not yet built in CI.) **Phase 4** (web flash + serial monitor) is built —
> `web/src/lib/flash.ts` (esptool-js app-region writeFlash @ 0x10000 + `rawRead` serial
> monitor), `/lorawan/compile` SSE client, and a `LorawanFlashDialog` wired into the
> toolbar; type-check + 139 web tests + production build are green, but a real
> device-flash is unverified (no hardware here) and only the app-region path exists
> (blank-board full flash is a follow-up). **Phase 6** device side is free
> (LoRaWAN_ESP32 `persist.manage()` already prompts over serial), and its backend half is
> built + tested: `POST /lorawan/provision` issues an AppKey, registers the device in
> ChirpStack, and flushes nonces. Remaining Phase 6: the browser serial-prompt driver
> (derive DevEUI from the chip MAC, answer the prompts) — pairs with hardware flash testing.
> Next: finish Phase 6 host side / Phase 7 (MQTT join+uplink confirm).

| Phase | Goal | Key deliverables | Acceptance |
|---|---|---|---|
| **0** | Target-plugin seam (no LoRaWAN behavior yet) | `core/` + `targets/` split; `TargetPlugin` + registry; move ESPHome generators behind `esphome` target; add `Design.target` default `"esphome"`; `[lorawan]` optional-extra + feature gate; register a `lorawan` stub | Existing suite + `esphome config` gate + goldens **all still pass**; both targets registered; ESPHome behavior byte-identical |
| **1** | LoRaWAN board library | `radio:` block on LoRaWAN boards; `board_filter=has_radio`; add Heltec V3 (SX1262) + a RAK board; schema + goldens updated | lorawan target lists only radio boards; pin solver validates radio pins; compat flags conflicts |
| **2** | Firmware generator (compile-time path first) | `firmware_gen.py` + `templates/`; RadioLib + LoRaWAN_ESP32; US915 sub-2; per-component arduino snippets + matching codec | `pio run` builds a `.bin` for each board profile in CI; manual: device boots + joins |
| **3** | In-pod compile worker + cache | `compile.py`; build endpoint; profile-hash cache; toolchain cached in image; queue/timeout; log-polling API (fleet-style) | API returns a `.bin`; identical request = cache hit; logs stream to client |
| **4** | Web flash + serial monitor | `web/src/lib/flash.ts` (writeFlash, app-region option, progress); lorawan panes (reuse detect + capability picker); Flash button; live serial log | Flash a cached `.bin` from the browser (incl. ChromeOS); see boot/join logs |
| **5** | ChirpStack provisioning + nonce flush | `chirpstack.py`: ensure profile/app, create device + keys, **flush DevNonces**, GetActivation | Provisioning a DevEUI creates the device idempotently and flushes nonces (verified against the live server) |
| **6** | Runtime serial provisioning (primary flow) | `provision.py` + firmware serial protocol (§7); switch to generic cached firmware; app-region re-flash preserves NVS; full-erase auto-flushes nonces | End-to-end: flash generic bin → read DevEUI → provision → push keys → **join**; power-cycle does **not** break re-join |
| **7** | Join + HA confirmation + status UI | `confirm.py`: MQTT join/uplink watch + HA REST entity check; SSE/websocket to UI | UI shows "joined ✓", first uplink **received & decoded**, "HA entity present ✓". Scope = *data flowing + HA receiving it*; **value-sanity checks are explicitly out of v1 scope** (lower priority) |
| **8** | Packaging / deploy / (multi-user) hardening | Image with PlatformIO layer; runs as a **k8s pod and a Proxmox LXC** (`docker run`/`podman` or direct install) — both are homelab targets; if public: auth, per-tenant ChirpStack creds, sandbox the compile worker | `kubectl apply` (k8s) **and** `docker run` inside an LXC both serve the lorawan target; build worker is resource-bounded |

---

## 12. Open questions / risks

- ~~Exact ChirpStack flush-nonces RPC name~~ **RESOLVED**: `DeviceService.FlushDevNonces`
  (request `FlushDevNoncesRequest(dev_eui=...)`), confirmed in `chirpstack-api` 4.18.0.
  Implemented in `targets/lorawan/chirpstack.py`. Note: client is 4.18 vs the live
  server 4.17 — same v4 protobufs, but re-verify against the server in live testing.
- **SX1262 board specifics** (TCXO voltage, `dio2_as_rf_switch`, RF switch pins) vary per board — capture
  precisely in each board's `radio:` block; wrong TCXO config = radio init fails, looks like "no join".
- **App-region-only flashing vs NVS layout** — confirm the partition table so writeFlash preserves the NVS
  partition; otherwise fall back to full-erase + auto nonce-flush.
- **WebBluetooth field path** is out of scope for v1 but keep the provisioning protocol transport-agnostic so
  the same `SET/PROVISION/JOIN` exchange can later run over a BLE GATT service.
- **Multi-user exposure** turns three things from optional to required: auth/multi-tenancy (the design store is
  single-writer file-on-disk — `Recreate` strategy per `deployment.md`), per-tenant ChirpStack credentials, and
  sandboxing the compile worker.
- **Codec ↔ payload lockstep** — the firmware's payload byte layout and the ChirpStack `decodeUplink` codec
  must be generated together or HA sees raw bytes instead of named fields.

---

## 13. Sources

- RadioLib DevNonce-on-power-cycle (TTGO LoRa32): https://github.com/jgromes/RadioLib/issues/1480
- ChirpStack "Flush OTAA device nonces" (TTGO LoRa32 V1): https://forum.chirpstack.io/t/device-on-otaa-ttgo-lora32-v1-not-connecting-unless-flush-otaa-device-nonces-invalid-devnonce/24273
- ChirpStack "DevNonce has already been used": https://forum.chirpstack.io/t/otaa-error-devnonce-has-already-been-used/18233
- RadioLib persistence + provisioning lib: https://github.com/ropg/LoRaWAN_ESP32
- radiolib-persistence examples: https://github.com/radiolib-org/radiolib-persistence
- ESP32 eFuse base MAC: https://github.com/espressif/esp-idf/blob/master/components/esp_hw_support/include/esp_mac.h
- MAC→DevEUI derivation example (Paxcounter): https://github.com/cyberman54/ESP32-Paxcounter/blob/master/src/lorawan.cpp
- arduino-esp32 getEfuseMac byte-order issue: https://github.com/espressif/arduino-esp32/issues/6458
- Reference firmware (RadioLib, MSB creds): https://github.com/designer2k2/tbeam-lorawan-mapper
- Reference firmware (LMIC OTAA): https://github.com/Xinyuan-LilyGO/LilyGo-LoRa-Series/tree/master/examples/LoRaWAN/LMIC_Library_OTTA
