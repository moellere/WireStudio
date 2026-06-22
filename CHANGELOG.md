# Changelog

All notable changes to wirestudio.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **LoRaWAN: flash fleet-built firmware via WebSerial from the provision
  dialog.** Closes the workflow gap where the external-component LoRaWAN
  path built firmware on the fleet but had no way to land it on a headless
  device (no network OTA, no fleet flasher). New
  `FleetClient.get_firmware(run_id, *, factory=)` + `GET
  /fleet/jobs/{run_id}/firmware[?factory=true]` route ferry the addon's
  build artifact through the studio (browser never holds `FLEET_TOKEN`),
  mirroring the standalone path's `/lorawan/firmware/{cache_key}` so the
  existing `lib/flash.ts` consumes both paths identically. The provision
  dialog gains a **Flash via WebSerial →** step after a successful Push to
  fleet: polls the run-status endpoint until the verdict is `passed`,
  pulls the factory image, then writes it to a blank board at 0x0 with
  `eraseAll: true` (NVS is empty, `/lorawan/provision-esphome` re-flushed
  DevNonces, so the wipe is safe per §2.1). Scoped in
  `docs/lorawan/fleet-firmware-flash.md`. The upstream addon endpoint is
  still being implemented; until it ships, the button stays available but
  the call resolves to 404 with a clear "firmware artifact not available"
  message rather than a silent hang.

## [0.17.2] — 2026-06-20

### Fixed

- **LoRaWAN external-component path now renders headless.** The renderer
  emitted `wifi:` / `api:` / network `ota:` / `captive_portal:` whenever
  the design carried a `fleet.secrets_ref`, including on
  `lorawan-for-esphome` designs. Per the upstream README, all four
  blocks reboot-loop the device when the network is unreachable
  (`wifi:` and `api:` default to `reboot_timeout: 15min`), and every
  reboot burns a DevNonce in the OTAA flow -- the device eventually
  stops joining. The fleet/HA addon path's headless field nodes need
  *no* network stack. The renderer now drops the four blocks (including
  any set via `esphome_extras`) whenever `design.lorawan.payload` is
  non-empty. The `lorawan-battery-uplink` golden was regenerated to
  match. User-reported during a Push-to-fleet flow that produced YAML
  the fleet wouldn't compile cleanly.
- **LoRaWAN: render passes SCK / MISO / MOSI to lorawan-for-esphome.**
  v0 of the upstream component constructed RadioLib's `Module` without
  calling `SPI.begin(sck, miso, mosi, cs)`, so it used arduino-esp32's
  VSPI defaults (18/19/23/5). TTGO LoRa32 v1 (and most LoRa boards)
  wire the radio to non-VSPI pins (5/19/27/18) -- the SX1276
  chip-version readback returned garbage and the join failed with
  `ERR_CHIP_NOT_FOUND (-2)`. Renderer now emits `sck_pin` / `miso_pin`
  / `mosi_pin` in the radio block, sourced from the board library's
  `default_buses.spi`. Pinned to `lorawan-for-esphome` @
  `1f7ee9a` (lorawan-for-esphome#2) which adds the matching schema
  fields and calls `SPI.begin()` before constructing the RadioLib
  Module. Also moves `_LORAWAN_FOR_ESPHOME_REF` off `main` to that
  pinned SHA, closing the `# TODO: pin to a commit SHA` left from the
  W2 spike. User-reported during the first hardware join attempt on a
  freshly flashed TTGO LoRa32 v1.
- **LoRaWAN: `create_device` is actually idempotent now.** ChirpStack v4
  scopes `dev_eui` uniquely per tenant (not per application) and leaks
  the SQLite UNIQUE constraint as `INTERNAL` rather than `ALREADY_EXISTS`
  on a duplicate. `create_device` now resolves the conflict via a
  follow-up `Device.Get`: same application -> the documented idempotent
  no-op (the rest of `provision_device` re-keys and flushes nonces);
  different application -> raise with the conflicting `application_id`
  so the operator removes the device there instead of silently re-homing
  across paths (standalone vs esphome). `set_device_keys` gets the
  same INTERNAL/UNIQUE handling for the `device_keys.dev_eui` row, so a
  re-provision falls through to `UpdateKeys` the same way ALREADY_EXISTS
  did.
- **LoRaWAN: gRPC errors no longer hide behind a bare 500.** Every
  `ChirpStackClient` helper now wraps `grpc.RpcError` ->
  `ChirpStackUnavailable(_rpc_msg(exc))`, the same convention `ping()`
  already used. `/lorawan/provision-esphome`, `/lorawan/provision`,
  `/lorawan/activation`, and the codec endpoints already caught
  `ChirpStackUnavailable` -> 502; now they actually receive it, so a bad
  Bearer token surfaces as `502 "UNAUTHENTICATED:"` with the gRPC
  details visible in the response body instead of an unhandled 500 the
  UI couldn't explain. Triggered by a user-side debugging session: the
  pod had a stale token, the provisioning click 500'd silently, and
  reproducing it took digging through container logs to find the
  `_InactiveRpcError` the stack swallowed.

### Added

- **k8s manifest: ChirpStack provisioning envs.** `deploy/k8s.yaml` now
  wires `CHIRPSTACK_API_URL` (plain env, defaults to the in-cluster
  Service name `chirpstack:8080`) and `CHIRPSTACK_API_TOKEN` (optional
  secretKeyRef on `wirestudio-secrets`). A commented `CHIRPSTACK_API_TLS`
  entry covers the TLS-channel case. Closes the gap where `/lorawan/provision*`
  needed the operator to hand-add envs after every `kubectl apply`.
- **Provision dialog gates on `/lorawan/chirpstack/status`.** The
  external-component path's `LorawanProvisionEsphomeDialog` now probes
  ChirpStack reachability + auth on mount. When the probe returns
  `available: false`, the dialog renders an inline banner with the gRPC
  reason (plus a nudge that the Bearer token comes from the ChirpStack
  UI's **API Keys**, not the JWT signing secret -- the §11 footgun the
  setup doc warns about) and the Provision button stays disabled. Pairs
  with the wrap above: the banner shows the same `UNAUTHENTICATED:`
  string the click would otherwise have produced, but at dialog-open
  time, so the operator catches the misconfiguration before clicking.

### Changed

- **`deploy/k8s.yaml` image pin bumped `v0.12.0` → `v0.17.1`.** The
  standalone manifest's hardcoded image tag was five releases stale (the
  kustomize overlays roll forward, but the plain manifest doesn't).
- **`CHIRPSTACK_API_URL` default is now `chirpstack:8080`.** Was a
  specific LAN IP that meant something only on the original author's
  network; the new default is the typical in-cluster Service name and
  works out of the box for the k8s manifest. Non-k8s deploys still set
  the env explicitly.
- **Scrubbed local-environment specifics from `docs/lorawan/`.** Replaced
  real gateway hostname, private IP addresses, gateway silicon ID, and
  personal DNS names with documentation placeholders (`mygw`, `10.0.x.x`,
  `*.example.com`, `0000000000000000`). The setup snapshot keeps its
  structure but no longer leaks a single operator's network into a public
  repo.

## [0.17.1] — 2026-06-20

### Fixed

- **Inspector: editable JSON for object/array params.** The Inspector's
  `ParamForm` rendered scalar params (string/int/number/bool/enum)
  inline, but for `object` and `array` schemas it just stringified the
  value as read-only and showed "structured editing not yet supported."
  That left whole classes of params un-editable through the UI --
  `uart_gps.sensors` (the visible LoRaWAN-external-component blocker --
  sub-sensor IDs need to live here so `lorawan.payload` bindings can
  reference them), `pulse_counter.filters` / `count_mode`,
  `gpio_input.on_press` and the other `on_*` action lists. Now a JSON
  textarea per object/array param: parses on every keystroke and
  commits to the design only when the buffer is valid; kind-mismatched
  input (`[1,2]` on an `object` schema, `{"a":1}` on `array`) shows an
  inline parse error and doesn't commit; textarea auto-sizes 3-12 rows.
- **DesignPane: visible "stale" signal when render fails.** When the
  auto-debounced `/design/render` fails, the YAML/ASCII pane kept
  showing the prior successful render -- intentional context, but
  nothing visually flagged that the content was no longer current.
  Three coordinated signals: a rose dot on the ASCII / YAML tab labels
  (JSON stays clean since it reads design state directly), a sub-line
  on the "Render failed" banner naming the stale tab and pointing at
  the JSON tab for live state, and an `opacity-50` transition on the
  stale content itself. Surfaced during the LoRaWAN walkthrough: user
  edits weren't visibly ignored, but a series of small renderer
  rejections made it look that way.
- **`uart_gps` template: optional `params.sensors` guard.** The template
  referenced `(params.sensors or {}).items()` to default-empty when the
  user hadn't set the optional sensors map -- but that defense doesn't
  work under our `StrictUndefined` Jinja env: accessing
  `params.sensors` on a params dict without that key raises
  `UndefinedError` BEFORE the `or {}` evaluates, so the fallback never
  gets a chance. Symptom: adding `uart_gps` via the Inspector (which
  leaves `params: {}`) failed `/design/render` with 422
  `'dict object' has no attribute 'sensors'`. Switches to the standard
  `{%- if params.sensors is defined and params.sensors %}` guard used
  by `bme280` / `dht` / `sht3xd` / the phase-3 multi-channel sensors.
- **Pin solver: respect bus pin assignments.** `_used_gpio_pins` walked
  only `design.connections` for `kind: gpio` targets, but UART tx/rx,
  I2C sda/scl, SPI clk/miso/mosi/cs, I2S lrclk/bclk, and 1-wire pin
  live on the bus object itself (a component's bus connection target
  is `{kind: "bus", bus_id: "uart0"}` and doesn't carry the GPIO). So
  the solver treated bus pins as free. Symptom: design has UART on
  `tx=GPIO13`, user adds an HC-SR501 PIR with `OUT` unbound, solver
  picks `GPIO13` for `OUT` -- the same pin as UART tx. Now harvests
  bus pin slots into the used set.
- **Generator error hint: don't suggest "missing bus" for params
  errors.** The `UndefinedError` -> 422 converter blindly appended
  "Likely a missing bus connection" to every error message. That was
  a false friend when the actual error was a missing optional param
  (the `uart_gps.sensors` case above). Now differentiates: a
  `'dict object' has no attribute ...` error suggests the optional
  param / is-defined-guard fix; everything else still suggests the
  bus connection check.

## [0.17.0] — 2026-06-20

### Added

- **LoRaWAN: fleet push inlines per-device secrets.** `POST /fleet/push`
  gains an optional `lorawan_secrets: {dev_eui, join_eui, app_key}` body
  field; when present, the renderer substitutes literal values for the
  matching `!secret <name>` references in the `lorawan:` block, so the
  YAML the fleet stores carries the keys minted by
  `/lorawan/provision-esphome` without a separate write to the fleet's
  `secrets.yaml`. Any key not provided keeps its `!secret` reference; a
  request with `lorawan_secrets` against a non-LoRaWAN design is a no-op.
  The provision dialog gains a **"Push to fleet"** button next to the
  secrets block: provision → push → compile flows through one click, with
  the resulting filename + compile run id surfaced inline.
- **LoRaWAN: WebSerial DevEUI auto-derive (restored).** The provision
  dialog gains a "Detect from chip" button that reads the chip's eFuse
  MAC over WebSerial via the existing `detectChip()` + `macToEui64()`
  helpers and fills the DevEUI field. Disabled with a hint when WebSerial
  isn't available (e.g. Firefox / mobile). Manual entry remains the
  fallback; editing the field clears the detection hint.

### Changed

- **ADC component: `attenuation` value renamed `11db` -> `12db`.** ESPHome
  2024.5 renamed the value to match the actual ESP-IDF gain; `11db` still
  parses but emits a deprecation warning that surfaced as noise during the
  W2 `esphome config` gate. Behaviour is identical -- the same ESP-IDF setting
  is selected. Updates the `adc.yaml` template (params_schema enum + default
  + description), the two examples that pin a value explicitly
  (`analog-node`, `lorawan-battery-uplink`), the matching goldens, and the
  starter-design generator (`seed.py:_seed_battery_adc`). Verified by
  diffing goldens: the only golden change is the literal `11db -> 12db`
  swap on the two affected configs.

### Added

- **LoRaWAN workflow integration (W3 — orchestration endpoint).** New
  `POST /lorawan/provision-esphome` mints an AppKey, registers the device in
  ChirpStack against a path-specific device profile
  (`wirestudio-esphome-<region>-sub<n>`, distinct from the standalone path's
  per-component-set profiles), flushes its DevNonces, and returns the three
  keys in a `secrets:` block ready to drop into the `secrets.yaml` that
  rides next to the rendered ESPHome config. The AppKey is ephemeral --
  returned once, never persisted to `design.json` (CLAUDE.md rule). The
  endpoint gates on `design.lorawan.payload` being non-empty so a
  misrouted call against a standalone-path design fails with a clear 422.
  Codec setting (the JS decoder) is deferred to a follow-up endpoint so the
  device joins first; the new path's decoder is generated from
  `design.lorawan.payload`, not the standalone `codec.py`. DevEUI is the
  manual override field per the locked decision; the eFuse-MAC derivation
  over WebSerial is a separate iteration.

- **LoRaWAN workflow integration (W2 — generator emits the external-component
  block).** When `design.lorawan.payload` is non-empty, the YAML generator now
  emits an `external_components: - source: github://moellere/lorawan-for-esphome
  ref: <pinned>` block, the `lorawan:` config (region / sub_band / keys via
  `!secret` / radio config sourced from the board library's existing
  metadata), and one `sensor: - platform: lorawan, sensor: <id>` binding per
  payload field. Keys never enter `design.json` -- `dev_eui` / `join_eui` /
  `app_key` route through `Design.fleet.secrets_ref`. The radio block adapts
  to the chip family: SX127x boards emit dio0; SX126x boards emit dio1, busy,
  optional `tcxo_voltage`, and `dio2_as_rf_switch`. Worked example
  `lorawan-battery-uplink.json` (TTGO LoRa32 v1 + ADC battery, US915 sub-band
  2) -- the smallest design that exercises the full new path and can be
  hand-flashed against the live ChirpStack for the hardware-join test ahead
  of W3's orchestration UI. The standalone Arduino path is unaffected:
  emission is gated on `payload` non-empty, so existing non-LoRaWAN designs
  render byte-identical.

- **LoRaWAN workflow integration (W1 — `Design.lorawan` IR extension).** Adds
  the IR shape the external-component path needs: a `PayloadField` class
  (`{sensor: <component_id>}`) and an ordered `LoRaWAN.payload: list[...]`
  list -- the codec contract shared between the device's wire bytes and the
  ChirpStack `decodeUplink` decoder. Broadens `LoRaWAN.region` to accept
  US915 / EU868 / AU915 / AS923 (default still US915). The existing
  standalone-Arduino fields (`gps` / `dht22` / `oled` / `provisioning`) are
  untouched -- both paths share the block during the transition documented in
  `docs/lorawan/workflow-integration.md`. Schema mirrors. Pure IR addition,
  no generator branch yet (W2 wires that up).
- **Intent-to-device synthesis (phase 5 — condition gating).** An automation
  gains an optional `conditions: [...]` list; the trigger must fire AND every
  condition must hold for the actions to run. The generator wraps the action
  list in ESPHome's `if: { condition: ..., then: [...] }` form -- a single
  condition emits as an inline mapping, multiple conditions emit as a list
  (ESPHome's implicit AND). `CapabilityChecks` adds a `predicate -> esphome`
  mapping; 5 components gain `is_on` / `is_off` predicates that lower to
  `binary_sensor.is_on`, `switch.is_on`, or `light.is_on`: `gpio_input`,
  `gpio_output`, `ws2812b`, `hc-sr501`, `rcwl-0516`. The two motion sensors
  also gain an `id:` line in their binary_sensor template so condition
  predicates can reference them. New validator warnings:
  `automation_unknown_predicate` (predicate not in the component's checks),
  plus the existing `automation_unknown_component` /
  `automation_component_no_capability` codes now cover condition references.
  Worked example `guarded-button-light.json`: a button press toggles a light
  only when an enable switch is on. `design.json` schema gains
  `automations[].conditions`. The `sensor.in_range` predicate (single-output
  and multi-channel) is scoped separately because the multi-channel
  sub-sensor needs per-channel `id:` template surgery.

- **Intent-to-device synthesis (phase 4 — on_value_range threshold bounds).**
  An automation trigger gains optional `above` / `below` numeric bounds for the
  `on_value_range` event; the lowering wraps the action list in a
  `{above, below, then}` range entry, producing ESPHome's
  `on_value_range: - above: 28.0\n  then: [...]` shape. Two new permissive
  validator warnings (`automation_bounds_require_value_range`,
  `automation_value_range_needs_bounds`) catch the two cooperative mistakes
  -- bounds on the wrong event, or `on_value_range` with no bounds (which
  would fire on every reading). All 7 phase-3 multi-channel sensors (dht,
  bme280, bmp180, bmp280, aht10, htu21d, sht3xd) gain channel-tagged
  `on_value_range` provides and matching `params.<channel>_on_value_range`
  passthroughs in each sub-block, so a threshold trigger composes with the
  multi-channel selector. New worked example
  `temp-above-turns-on-fan.json` (bme280 temperature >= 28°C -> fan on).
  `design.json` schema gains `automations[].trigger.above` / `.below`.

- **Intent-to-device synthesis (phase 3 — multi-channel sensor triggers).**
  An automation trigger gains an optional `channel:` selecting which sub-block
  on a multi-output sensor it hangs off (e.g. `temperature` vs `humidity` on a
  bme280). Capability `provides` entries gain a matching `channel:` so the
  validator can check the trigger references a real (channel, event) pair, and
  the lowering combines them into a `<channel>_<event>` params key so the
  template's per-channel passthrough fires inside the right sub-block. Seven
  environmental sensors gain channel-tagged capability blocks and the matching
  `params.<channel>_on_value` passthroughs: `dht`, `bme280`, `bmp180`, `bmp280`,
  `aht10`, `htu21d`, `sht3xd`. New worked example `temp-turns-on-fan.json`
  exercises the path end-to-end (bme280 temperature -> switch). The validator's
  unknown-event warning now lists provides as `<channel>.<event>` pairs so the
  fix is obvious. `mpu6050` (7-channel IMU) replaces dht as the unannotated-
  component test fixture; the remaining unannotated multi-output components
  (power meters, the other IMU) carry too many channels to enumerate without
  a further design call. `design.json` schema gains
  `automations[].trigger.channel`.

- **Intent-to-device synthesis (phase 2 — value→transform→action).** An
  automation action gains an optional `transform` (action-arg name → a C++
  expression in terms of `x`, the value the trigger emits) that the generator
  lowers to an ESPHome `!lambda "return <expr>;"`. `rotary_encoder` gains
  `on_value` (kind=value) and the `uln2003` stepper gains `set_target`
  (→ `stepper.set_target`), wiring the canonical encoder→stepper case. New
  worked example `encoder-drives-stepper.json`: a knob's cumulative count
  drives the motor via `target: !lambda return (long) (x * 10);`, so each
  detent commands ten steps. The lambda rides the existing `params.on_*`
  `tojson` passthrough as a sentinel string and is restored to a tagged
  `!lambda` scalar after parse; the tag-quoting fixup keeps the body quoted
  when it isn't a plain-scalar-safe expression (a ternary, say). `design.json`
  gains `automations[].actions[].transform` in model + schema.

- **Intent-to-device synthesis (phase 1.5b — single-output sensor triggers).**
  Nine single-value sensors gain a `params.on_value` / `on_value_range`
  template passthrough plus a `role: sensor` `capability:` block, so a sensor
  reading can drive an automation: `ds18b20` (1-wire temperature), `bh1750` +
  `tsl2561` (lux), `vl53l0x` (ToF distance), `hx711` (load cell), `max31855`
  (thermocouple), `pulse_counter` (rate), `ads1115_channel` (ADC channel), and
  `tuya_sensor` (Tuya datapoint). `on_value` (kind=value) lowers a direct
  action list through the existing phase-1 path; `on_value_range` (kind=event)
  is declared for the threshold case that phase 2's richer trigger IR will
  carry the bounds for. Multi-channel sensors (`dht`, `bme280`, IMUs, power
  meters) stay unannotated: which sub-channel a trigger hangs off is a separate
  design call. Same evidence gate as 1.5a — every declared `provides.event` is
  tested against a real `params.<event>` passthrough — plus a lowering test
  proving a `ds18b20` `on_value` automation renders `switch.turn_on` into the
  sensor block.

- **Intent-to-device synthesis (phase 1.5a — wider library annotations).**
  Ten more library components gain `capability:` blocks so they can
  participate in `automations`: `hc-sr501` + `rcwl-0516` (motion sensors,
  on_press/on_release), `rc522` + `rdm6300` (RFID readers, on_tag /
  on_tag_removed), `rotary_encoder` (on_clockwise / on_anticlockwise; on_value
  with a transform lands in phase 2), `adc` + `hc-sr04` (analog input + ultrasonic
  distance, on_value / on_value_range), `rf_bridge` (on_code_received),
  `ws2812b` (light, both events + the standard `light.turn_on`/`turn_off`/
  `toggle` accepts), and `tuya_switch` (accepts side only — its template
  doesn't pass through the on_turn_on/off events yet). The annotation is
  evidence-grounded: each declared `provides.event` is gated by a test that
  the component's existing ESPHome template actually has a matching
  `params.<event>` passthrough (so an automation lowers into a key the
  renderer emits), and each `accepts.esphome` verb is gated against the
  known ESPHome platform prefixes (`switch.` / `light.` / `stepper.`).
  Adds a second worked example, `motion-turns-on-light.json` (PIR -> WS2812B
  via two automations on the on_press / on_release edges), proving the
  lowering generalises across capability pairs. Components without an `on_*`
  template passthrough (most of the bare-temperature/humidity sensors,
  displays, buses, hubs, cameras, PMICs, generic radios) stay unannotated --
  template-passthrough additions are phase 1.5b, scoped separately because
  template surgery has a different risk profile than additive metadata.



- **Intent-to-device synthesis (phase 1 — declarative event→action).** Adds a
  *functional* layer on top of the existing structural surface: library
  components gain an optional `capability:` block declaring their `role`
  (input / sensor / output / controller), the events they `provides`, and the
  actions they `accepts` with explicit ESPHome verbs. `design.json` gains an
  `automations: [{trigger, actions}]` graph parallel to the physical
  `connections` graph. The YAML generator lowers each automation onto the
  trigger component's `params.<event_key>` (extending any user-authored list,
  not replacing it), so the existing library templates render it as the right
  ESPHome trigger block — for the worked example
  (`button-toggles-light.json`), a press lowers to
  `on_press: [{switch.toggle: porch_light}]`. The `/design/validate` endpoint
  surfaces dangling refs as permissive warnings (`automation_unknown_component`,
  `automation_component_no_capability`, `automation_unknown_event`,
  `automation_unknown_action`) — half-authored automations don't block
  rendering, they just don't fire. Annotated `gpio_input` + `gpio_output` (the
  two components the worked example needs); the remaining ~58 library entries
  pick up annotations in phase 1.5. Value→transform→action (the encoder /
  stepper case) and a live `esphome config` authoring loop arrive in later
  phases per `docs/intent-to-device.md`.

- **Build-backend seam (framework axis, phase C — structural).** A
  `BuildBackend` protocol (`status` / `enqueue` / `stream` / `artifact`) now
  sits behind the LoRaWAN compile + firmware-download routes, with the in-pod
  PlatformIO worker wrapped as `LocalCompileBackend` and exposed via
  `LorawanTarget.build_backend()`. The endpoints no longer import the compile
  worker directly, so a *remote* LoRaWAN build worker (a build-agent pool, the
  way fleet-for-esphome pools esphome builds) drops in later as a second
  backend without touching the API — proven by a fake poll-style backend in the
  tests. No wire-API, frontend, or behavior change: one-at-a-time WebSerial
  flashing still streams the in-pod build exactly as before. (The job-id route
  guard is now backend-agnostic instead of hex-only, so a remote worker's
  handle addresses its artifact through the same `/lorawan/firmware/{id}`
  route.)

### Changed

- **LoRaWAN target: framework axis + library codegen blocks (phases A & B).**
  The four LoRaWAN sensors (GPS / AXP192 battery / DHT22 / OLED) were hardcoded
  into `codec.py` (`*_FIELDS` lists) and `main.cpp.j2`; they now live as
  per-component `lorawan:` codegen blocks in `library/components/*.yaml`
  (`lib_deps` / `requires` / `globals` / `setup` / `loop` / `fields` with HA
  hints). A single `codec.resolve_components()` assembles the design's
  components plus the board's onboard peripherals, and both the firmware
  generator and the codec build from that one inventory -- so expanding the
  LoRaWAN sensor set is now a library-file edit, at parity with ESPHome, and
  the payload/decoder stay in lockstep. `TargetPlugin` gains formal
  `generate()` + `component_ids()` and `/design/render` routes through the
  target. The uplink payload layout, ChirpStack `decodeUplink` + Home Assistant
  entities, and device-profile names are **unchanged** (byte-identical to
  0.16.0), so existing provisioned devices and HA entities are unaffected.

### Fixed

- **Power budget ignored the board's own draw.** Every Wi-Fi MCU's ~70-300 mA
  active current was invisible to the budget check; `LibraryBoard` had no
  current fields, and both budget callsites (`csp/pin_solver.py`,
  `generate/ascii_gen.py`) only summed `design.components`. Result: a bare D1
  Mini design reported `~0mA peak`. `LibraryBoard` now carries
  `current_ma_typical` + `current_ma_peak` (Wi-Fi associated active / TX burst,
  datasheet-sourced per MCU family with per-board overhead for USB-UART, LDO,
  status LEDs, onboard radios / displays / PMIC). All 23 bundled boards are
  annotated; both budget paths include the board's draw. Bumped
  `power.budget_ma` on the 24 examples whose budgets were silently low because
  the board was uncounted, and refreshed the ASCII goldens.

## [0.16.0] — 2026-06-14

### Fixed

- **LoRaWAN firmware boot-loop on TTGO LoRa32 (issue #80).** The TTGO
  `ttgo-lora32-v1`/`-v2` profiles declared the onboard SSD1306 reset on
  GPIO16. On these boards driving GPIO16 in the reset pulse wedges the chip
  at boot — *before* `Wire.begin()` — so the interrupt watchdog reboots it in
  a loop (`TG1WDT`), confirmed on hardware by serial bisection. The reset pin
  is dropped from both profiles (the template already skips the pulse when no
  reset pin is set; the SSD1306 self-resets on power-up). Heltec profiles keep
  their GPIO reset, which is correct there. The generated `main.cpp` also
  bounds the I2C bring-up (`Wire.setTimeOut` + ACK probe before
  `display.begin()`, `loop()` gated on `oledReady`) so an absent or
  differently-wired panel degrades gracefully rather than hanging.

### Added

- **`ttgo-lora32-v2` board profile** (LilyGO LoRa32 V2.1 / "T3 v1.6.1"),
  mapping to PlatformIO board `ttgo-lora32-v21`. Electrically identical to
  `ttgo-lora32-v1`; the distinct profile lets the most common "TTGO LoRa32"
  hardware select its matching board key.
- **Home Assistant entities from the LoRaWAN codec.** The generated ChirpStack
  codec now includes a `getHaDeviceInfo()` block alongside `decodeUplink`, so
  the [chirp2mqtt](https://github.com/modrisb/chirp) HA integration publishes
  MQTT-discovery entities for every payload field — temperature, humidity,
  battery (mV→V), GPS, link quality (RSSI/SNR) — with proper `device_class`/
  unit/`state_class`. GPS payloads (lat+lon) additionally emit a
  `device_tracker` whose latitude/longitude attributes drive the HA map. Each
  payload `Field` carries optional `ha_*` hints driving this. ChirpStack device
  profiles are also created with `auto_detect_measurements` enabled for
  ChirpStack's own metrics dashboards.

## [0.15.0] — 2026-06-11

### Added

- **Agent system payload slimmed (~10K tokens/turn) + `library_detail` tool.**
  The agent's system block now carries a **compact library index**
  (id / name / category / use_cases / aliases for components; id / name / mcu
  for boards) instead of dumping every full pydantic model. The full card
  (electrical metadata, `params_schema`, ESPHome template, KiCad block, pin
  definitions) loads on demand via a new `library_detail` tool — exposed on
  both the agent and the MCP server. Concrete win on 60 components: the
  library block drops from ~178 KB / ~44,500 tokens to ~23 KB / ~5,900 tokens
  per turn (**~87% reduction, ~38,600 tokens saved/turn**); the rest is
  fetched only when the agent actually needs it. The prompt cache still
  holds the slim block stable across turns.
- **Agent + MCP tool coverage for PCB and fab outputs.** The agent's tool
  surface and the MCP server gain `kicad_schematic`, `kicad_pcb` (returns a
  summary, not the megabyte board text), `fab_status`, `fab_bom`, and
  `fab_cpl` — so an agent (Claude Desktop / Claude Code over MCP, or the
  Anthropic API agent) can now drive design → board → BOM/CPL/Gerber-status
  end to end. Library-gated tools report `available: false` cleanly when the
  server doesn't have the KiCad libraries.
- **Fab outputs (Gerber / drill / CPL / BOM).** New `/design/fab/*` endpoints
  turn a design into a JLCPCB upload bundle: a **BOM** CSV (pure, grouped by
  part), a **CPL** pick-and-place CSV whose positions match the `.kicad_pcb`
  placement, and **Gerber + drill** via `kicad-cli` (gated like the schematic
  render). `POST /design/fab/package` zips all four. `GET /design/fab/status`
  reports what's available. Boards are unrouted until the Freerouting step, so
  the Gerbers carry pads but no traces — `is_routed`/status flag that. The
  KiCad export dialog gains a **Fab outputs** section (BOM / CPL / fab-package
  buttons, each gated on what the server supports). The `pcb-drc` CI tier also
  smoke-tests the Gerber export path.

## [0.14.0] — 2026-05-26

### Added

- **KiCad PCB export (`.kicad_pcb`).** A new `POST /design/kicad/pcb` emits a
  KiCad 8 board: every component + board footprint embedded from the pinned
  KiCad libraries and grid-placed, each pad bound to the net it shares in the
  design, plus an `Edge.Cuts` outline — no routing, so it opens in KiCad's PCB
  editor with a complete ratsnest ready to route (PCB layout, step 2; the
  footprint gate in 0.13.0 was step 1). Pad numbers resolve through the
  component's `kicad.pin_map` and symbol; generic connectors bind positionally.
  Reference designators and net names are shared with the schematic
  (`wirestudio/kicad/netlist.py`). Feature-gated like the schematic render —
  needs the footprint + symbol libraries on the server (`GET
  /design/kicad/pcb/status`); a `pcb-layout` CI gate proves every bundled
  example emits a structurally sound board, and a `pcb-drc` tier opens each
  board in real KiCad and runs DRC (unrouted airwires expected/ignored). The
  KiCad export dialog gains a **Download .kicad_pcb** button (gated on the
  server having the libraries). Freerouting autoroute and Gerber/CPL/BOM
  export remain on the path to 1.0.
- **Blank-board LoRaWAN flash.** The compile worker now also emits a merged
  factory image (bootloader + partitions + app via esptool `merge_bin` at the
  per-chip bootloader offset), served at `GET /lorawan/firmware/{key}/factory`.
  The flash dialog's **"Blank board — full flash"** toggle writes it at 0x0 with
  a full erase, for a board that's never been flashed; the default stays an
  app-region re-flash that preserves the bootloader + NVS DevNonces.
- **Local component inventory.** Track parts on hand in a single
  `inventory.json` (`GET`/`PUT`/`DELETE /inventory`), cross-check a design's
  BOM against it (`POST /design/inventory/check` → have / partial / need),
  and let the recommender prefer parts already in the drawer (`use_inventory`,
  a flat +5 boost). `INVENTORY_PATH` env override for the Docker `/data` volume.
  A web **Inventory** panel lists/adds/edits/removes entries and runs the BOM
  check against the open design (have / partial / need). Per-part low-stock
  thresholds (a `low` badge when on hand ≤ the reorder point) and CSV
  import/export (`GET /inventory/export.csv`, `POST /inventory/import`).
- **ULN2003 stepper driver** library component (28BYJ-48): ESPHome `stepper`
  platform on four control pins, with a KiCad footprint and a `blind-stepper`
  example (motorized blind) that round-trips through `esphome config`.
- **`-lorawan` Docker image.** CI builds and publishes a
  `wirestudio:<tag>-lorawan` variant (amd64) with PlatformIO + the `[lorawan]`
  extra baked in, so `/lorawan/compile` works in a deployment — the lean
  default image has no toolchain. Documented in [deployment](docs/deployment.md).

### Fixed

- **Dev deploy couldn't build LoRaWAN firmware.** The `bump-dev` job pinned
  the dev overlay to the lean `sha-<short>` image (no PlatformIO), so
  `/lorawan/compile` failed on the staging instance. The dev app now tracks
  the `-lorawan` variant (`bump-dev` waits on the `lorawan-image` job and
  writes the `-lorawan` tag), and the dev pod's memory limit is raised to 2Gi
  so the espressif32 link step doesn't OOMKill mid-build. Prod stays lean.
- **LoRaWAN GPS-on-console-UART footgun.** The flash dialog's external-GPS
  default was GPIO3/GPIO1 — U0RXD/U0TXD (the USB-serial console) on the classic
  ESP32, so a GPS there flooded the provisioning prompt with garbage and the
  device never joined. Default is now GPIO23/GPIO17, and the lorawan target's
  `validate()` warns (`lorawan_gps_on_console_uart`) when a GPS lands on the
  console UART.

## [0.13.0] — 2026-05-25

### Added

- **LoRaWAN device target.** A new `lorawan` generation target builds
  RadioLib + LoRaWAN_ESP32 firmware for US915 radio boards, flashes it over
  WebSerial, and provisions devices against ChirpStack — the uplink payload
  and the ChirpStack `decodeUplink` codec come from one field spec, so they
  stay in lockstep. Adds a `wirestudio/targets/` plugin seam (`esphome` wraps
  the existing generators in place), `Design.target` + a `LoRaWAN` config
  block (GPS / DHT22 / OLED), Heltec WiFi LoRa 32 V2 (SX1276) and V3 (SX1262)
  boards, a `/lorawan/*` API, and a web flash dialog. Behind a `[lorawan]`
  extra. Validated end-to-end on a TTGO T-Beam against live ChirpStack 4.17.
- **`make check`** — one local command that runs the same fast gates CI
  runs (ruff, pytest, a clean web build, vitest). Heavy external-CLI
  gates live under `make gates`.
- **Pre-push clean web build.** The pre-push hook now wipes the `tsc -b`
  cache and rebuilds the SPA, so a stale local cache can't pass while a
  fresh-container CI build fails on a real type error.
- **CHANGELOG nudge.** A `changelog` workflow fails a PR that changes
  `wirestudio/` code without touching `CHANGELOG.md`; escape with
  `[skip changelog]` in the PR title or the `skip-changelog` label.
- **`dev` integration branch.** The PR gates and image build now run on
  `dev` as well as `main`; `dev` merges publish a rolling `:dev` image.
- **Side-by-side ArgoCD deploys.** `deploy/overlays/{prod,dev}` +
  `deploy/argocd/` run a pinned-release prod app and a rolling dev app
  from one tree; CI commits the new image sha to the dev overlay on each
  `dev` merge. See `docs/deployment.md`.
- **Footprint coverage + gate (PCB layout, step 1).** Every library
  component (59) and board (23) now declares a real KiCad `footprint`.
  A new `kicad-footprint` workflow clones `kicad-footprints@8.0.0` and
  fails the PR if any referenced footprint doesn't resolve — the
  footprint counterpart to the symbol gate, and the foundation the
  upcoming `.kicad_pcb` emit builds on.

### Changed

- **Version is single-sourced** from `wirestudio/__init__.py`;
  `pyproject.toml` reads it dynamically. Bump it in one place.

## [0.12.0] — 2026-05-23

Headline: three of the four priority tiers (YAML, wiring schema,
enclosure) are now gated in CI; onboard peripherals auto-populate when
you adopt a board; and every library component and board is exercised
by a bundled example (100% coverage, enforced).

### Added

- **Onboard-peripheral auto-populate.** Adopting a dev board — via USB
  detection or **New design** — now seeds its built-in parts (LCD,
  buttons, IMU, RGB/IR, LoRa, GPS, ...) already wired. Covers all 13
  boards that carry `onboard_peripherals` metadata; peripherals with no
  library component (e.g. the AXP192 PMIC) are skipped with a warning.
  New `POST /design/seed_onboard` endpoint.
- **New library components:** `mpu6886` (Atom-family IMU),
  `remote_transmitter` (IR blaster), `i2s_microphone` (I2S/PDM mic).
- **Schematic gate (KiCad) — Verified.** `kicad-schematic` workflow
  runs every example's SKiDL script against the pinned upstream KiCad
  symbol libraries and fails on any unresolved symbol or pin.
- **Enclosure gate (OpenSCAD) — Verified.** `enclosure-render` workflow
  renders every enclosure-capable board's `.scad` and asserts a
  non-empty manifold solid.
- **Coverage `--strict` gate** wired into CI, plus an **`esphome-matrix`**
  workflow that runs the example gate across the pin + latest stables so
  pin bumps are evidence-driven.
- **100% library coverage:** every component (59) and board (21) is now
  exercised by a bundled example that passes both the ESPHome-config and
  KiCad-netlist gates; the `--strict` baseline is empty.
- Agent streaming failure-mode tests; API schema field descriptions.

### Fixed

- USB-connect board detection now matches esptool's detailed chip names
  (e.g. `ESP32-PICO-D4`) to the right board family; the board-picker
  modal scrolls and the confirm button stays reachable.
- ~16 library `kicad:` blocks corrected to real upstream symbols (the
  schematic gate surfaced hallucinated/wrong references).
- `BusList` web build break (missing `useEffect` import).

## [0.11.0] — 2026-05-17

Headline: composite modules, a KiCad schematic renderer, a JLCPCB
feasibility check, a redesigned web UI, and a much wider board library.

### Added

- **Composite modules.** A `library/modules/<id>.yaml` bundles several
  components under one part. Selecting it inserts every component at
  once, each stamped with module provenance, and the BOM collapses the
  bundle to a single line. The web picker gains a "Modules" tab; new
  endpoints `GET /library/modules{,/id}` and `POST /design/insert_module`.
  First module: the 1.3" OLED + EC11 encoder combo.
- **KiCad schematic render.** `POST /design/kicad/schematic` and an
  inline web preview render a design to a KiCad sheet via `kicad-cli`.
  (Phase 2.)
- **JLCPCB feasibility check.** `wirestudio.jlcpcb` cross-checks the BOM
  against JLCPCB part stock and price. (Phase 2.)
- **Compile-status feedback.** Push-to-fleet runs report a compile
  verdict (running / passed / failed) polled from fleet-for-esphome.
- **Board library expansion.** M5Stack Atom-family boards (Atom, Atom
  Matrix, Atom Echo, AtomU, AtomS3, AtomS3 Lite) with bundled examples,
  and the ESP32 C3 / S3 / C6 SuperMini boards. Boards now carry an
  optional product image, surfaced in the board picker.
- **OLED + encoder library.** SH1106 support via a `model` param on the
  ssd1306 component, plus an OLED-knob example.

### Changed

- **Web UI redesign.** Reworked header, left sidebar, and inspector,
  followed by a polish pass on error states, loading/empty
  placeholders, and copy. The board picker is grouped by chip family.
- **Performance.** Library summaries are pre-computed at load; the
  PinoutView memoizes its derived state to cut re-renders.
- **Docs.** Project documentation moved into `docs/`.

### Security

- Fixed a path-traversal vulnerability in the `/examples` endpoint.
- Restricted the previously over-permissive CORS policy to known
  origins.

### Fixed

- The Library Component inspector read the wrong field for notes.

## [0.10.0] — 2026-05-16

Headline: an MCP server that lets a host LLM client drive the studio,
plus a wide cluster of library, agent, and API work.

### Added

- **MCP server.** The design-editing tool surface is exposed over the
  Model Context Protocol at `/mcp` — Streamable HTTP transport mounted
  into the FastAPI app, bearer-token auth (`WIRESTUDIO_MCP_TOKEN` or an
  auto-generated file token). Drive the studio from Claude Code or
  Claude Desktop on a Claude subscription instead of an Anthropic key.
  Phase 1.1 through 1.5:
  - `design-changed` SSE channel (`GET /designs/{id}/events`) so
    browser tabs re-fetch after an MCP write.
  - Seven read-only resources — `library://components{,/id}`,
    `library://boards{,/id}`, `design://{id}/{json,yaml,ascii}`.
  - `set_active_design` pointer so design-bound tools resolve a
    default `design_id` from the browser selection or chat.
  - End-to-end setup walkthrough in `docs/mcp.md` — start the
    daemon, wire up Claude Code / Desktop, chat.
- **KiCad symbol importer.** `python -m wirestudio.kicad.import
  --symbol Lib:Symbol` reads a `.kicad_sym` library and drafts a
  `kicad:` block — or, with `--into <id>`, splices it into an existing
  component with an auto-derived `pin_map`. First of the Phase 2
  knowledge importers.
- **Library batches 2 & 3.** cse7766 + hlw8012 power meters,
  `esp32_rmt_led_strip`, the esp8285-1m board; modbus_controller +
  sdm_meter, bl0906, nextion HMI, and the tuya MCU bridge.
- **Component coverage matrix** (`docs/library-coverage.md`) — which
  library entries have a passing bundled example.
- KiCad `kicad:` symbol mapping completed across the whole library so
  every component and board exports to the SKiDL schematic generator.
- Two environmental-sensor examples (attic-logger, weather-station);
  `Field(description=...)` across the API schemas so `/docs` is
  self-documenting.

### Changed

- **Async API.** `wirestudio/api` endpoints migrated to `async def`;
  the fleet client rewritten on `httpx.AsyncClient`. `slowapi` rate
  limiting on the agent endpoints; CORS origins read from
  `WIRESTUDIO_ALLOWED_ORIGINS`. `DesignStore` and `SessionStore`
  extracted as `typing.Protocol` interfaces.
- **Agent cost tuning.** Configurable model tier via
  `WIRESTUDIO_AGENT_MODEL`, prompt-cache breakpoints, and a slimmer
  system payload — markedly cheaper per turn.
- Web UI gains a basic / advanced mode toggle that hides the
  lighter-checked surfaces by default.
- References to the OTA-deploy companion project updated
  `distributed-esphome` → `fleet-for-esphome` (upstream rename).

### Fixed

- Multi-turn agent regression — assistant blocks are stripped of SDK
  parser metadata before they are appended to history.
- `add_bus` fills missing pin fields from `board.default_buses`; the
  YAML renderer is guarded against `StrictUndefined`.
- `esp32:` chip-block emission corrected for every ESP32-family
  variant.

## [0.9.0] — 2026-05-05

First tagged release. Covers the full arc from the initial generator
pipeline (0.1) through the KiCad schematic exporter (0.9). Future
entries record only what changed since the prior tag.

### Pipeline (0.1 → 0.6)

- **0.1 — Generator pipeline.** `design.json` (JSON-Schema-validated)
  → ESPHome YAML + ASCII wiring diagram + BOM via pure functions over
  the static library. CLI: `python -m wirestudio.generate <design.json>`.
- **0.2 — HTTP API.** FastAPI server at `python -m wirestudio.api` exposing
  the same generators over `/library/*`, `/design/*`, `/examples/*`.
  Auto-generated OpenAPI docs at `/docs`.
- **0.3 — Web UI v1.** React 19 + Vite + Tailwind v4 three-pane shell.
  Editable: board picker, fleet metadata, requirements, warnings,
  per-component params, per-connection targets. Add/remove component
  instances with auto-wiring (rails by voltage match, bus pins to a
  matching bus, missing buses auto-prepended from `default_buses`).
  Debounced render (250 ms) into local state. Reset / Download JSON
  buttons.
- **0.4 — USB device bootstrap.** "Connect device" header button runs
  `esptool-js` over WebSerial. Reads chip family + MAC, normalises
  the chip name, filters board library to candidates with the matching
  `chip_variant`, seeds a fresh `design.json` on adopt.
- **0.5 — Agent layer.** Claude tool-using agent (`wirestudio/agent/`)
  with a constrained tool surface: `search_components`, `add_component`,
  `set_param`, `set_connection`, `solve_pins`, `recommend`, etc. Session
  history at `sessions/<id>.jsonl`. SSE streaming variant via
  `client.messages.stream()`. Recommendation mode.
- **0.6 — CSP pin solver.** Auto-assigns every unbound connection.
  GPIO with empty pin → board GPIO matching the library role; bus
  pins → matching design bus; expander pins → next free slot on the
  first `io_expander`. Conflicts + current-budget overruns surface as
  warnings. Boot-strap-aware preference (avoids `boot_high`/`boot_low`
  pins for outputs unless forced).
- **Compat checker.** `wirestudio/csp/compatibility.py` validates pin
  capabilities across the design: input-only-as-output, boot-strap
  conflicts, serial-console reuse, voltage limits, ADC2/WiFi conflict
  on classic ESP32, locked-pin-vs-bound divergence, locked-pin-cap
  mismatch.

### Fleet handoff (0.7)

- **`POST /fleet/push`** ships the rendered YAML to a configured
  fleet-for-esphome ha-addon (`FLEET_URL` + `FLEET_TOKEN`). Optional
  `compile: true` enqueues an OTA build. Header **Push to fleet**
  modal with status banner, device-name input, compile checkbox.
- **Build-log polling** at `GET /fleet/jobs/{run_id}/log?offset=N`;
  the dialog tails it at 1.5 s into a scrolling viewer once a compile
  is enqueued.
- **SSE log relay** at `GET /fleet/jobs/{run_id}/log/stream` —
  server-side polls the addon at ~300 ms and streams Server-Sent
  Events. Client uses `EventSource` first, falls back to polling at
  the last accepted offset on transport error.
- **Strict-only push** — `strict: true` on `POST /fleet/push` refuses
  the upload when warn/error compatibility entries remain, mirroring
  the `POST /design/render?strict=true` envelope. Header gains a
  global **strict** toggle (amber when on); the dialog renders a
  matching notice.

### UX accumulated through 0.7+

- **Capability-driven "Add by function" picker.** New `GET
  /library/use_cases` aggregates the canonical capability vocabulary;
  two-pane dialog ranks library components for the picked use case
  (or free text), with an alternatives disclosure showing score deltas
  and a one-click add per result.
- **Pin locks.** `locked_pins[role] -> pin` per component. Solver
  applies locks (force-fills empty bindings, flags mismatches).
  Inspector gains a 🔓/🔒 toggle next to each gpio pin selector.
- **Bus editor.** Inspector design view gains a Buses section. Rename
  bus id (atomic — rewrites every `connection.target.bus_id`),
  edit per-type pin slots, add / remove buses, inline compatibility
  warnings filtered to each bus card.
- **Drag-and-drop pinout.** Per-instance Pinout view with two-column
  layout: board GPIOs (with capability badges) on the left,
  draggable connection chips on the right. Drop fires a connection
  rewrite. Conflict detection paints rose; current binding glows
  emerald.
- **Server-side design persistence.** `designs/<id>.json` store
  with `GET / POST / DELETE /designs[/<id>]`. UI gains a **Saved**
  tab and a **New design** dialog seeded from a board pick.

### Library expansion

41 components, 13 boards. Every entry carries a `kicad:` mapping
(see "KiCad schematic export" below) and most carry `enclosure:`
metadata for the OpenSCAD generator.

- **Sensors:** BME280, BMP180, BMP280, HTU21D, DS18B20, MPU6050,
  HC-SR501 (PIR), HC-SR04 (ultrasonic), RCWL-0516 (microwave radar),
  TSL2561 (lux), MAX31855 (K-type thermocouple, SPI), HX711 (24-bit
  load-cell ADC), DHT11/22, LD2420 (mmWave radar), CC1101 (sub-GHz
  radio), pulse_counter, rotary_encoder.
- **ADCs / IO:** ADS1115 hub + per-channel components, MCP23008,
  MCP23017, gpio_input / gpio_output, adc.
- **Displays:** SSD1306 (I2C OLED), ST7789 (SPI TFT), ILI9xxx (SPI),
  LCD-PCF8574 (I2C character LCD), MAX7219 (LED matrix), TM1638,
  XPT2046 (touch).
- **RF / RFID:** RC522, RDM6300, SX127x (LoRa), uart_gps,
  rf_bridge.
- **Audio:** MAX98357A (I2S DAC + amp), RTTTL piezo.
- **Light:** WS2812B, APA102.
- **Hub / camera:** esp32_camera, ads1115_channel.
- **Boards:** wemos-d1-mini, esp32-devkitc-v4, nodemcu-32s,
  nodemcu-v2, ttgo-lora32-v1, esp01_1m, esp32-c3-devkitm-1,
  esp32-s3-devkitc-1, esp32-wrover-cam, esp32cam-ai-thinker,
  m5stack-atom, m5stack-atoms3, ttgo-t-beam.

### 1-wire bus type (0.7+)

`Bus.pin` field added; `1wire` rendered as a top-level `one_wire:`
block. Multiple DS18B20s on the same physical wire share a single
bus block plus N `dallas_temp` sensors. New `examples/multi-temp.json`
+ golden artefacts.

### Schema extension: `kind: "component"` connection target (0.9)

Lets one component instance reference another by id (`ads1115_channel`
→ `ads1115` hub). `parent_library_id` on the library `Pin` constrains
the reference; the solver auto-binds. Channels become first-class
inspector citizens with their own params row instead of being buried
inside an `array` param. ConnectionForm gains a `component` kind in
the dropdown with a sibling-instance picker.

### 0.8 — Enclosure suggestions

- **v1 — Parametric OpenSCAD generator.** Each dev-board YAML carries
  an `enclosure:` block (PCB outline, mount holes, port cutouts).
  `wirestudio/enclosure/openscad.py` emits a self-contained `.scad` shell
  with tunables (wall, floor, clearance, standoff geometry) at the
  top so the user dials in fit without re-rendering.
- **v2 — Thingiverse search relay.** Pluggable per-source search at
  `wirestudio/enclosure/search.py`. Thingiverse implementation gated on
  `THINGIVERSE_API_KEY`. Printables deferred (no public API yet);
  source stays in the catalogue with `available: false, reason:
  "Printables search deferred -- no public API yet"`. `GET /enclosure/
  search` + `GET /enclosure/search/status`.
- Header **Enclosure** button opens a tabbed dialog (Generate /
  Search community models).

### 0.9 — KiCad schematic export

- **`KicadSymbolRef`** on `LibraryComponent` + `LibraryBoard`:
  `symbol_lib`, `symbol`, `footprint`, `pin_map` (role → KiCad pin
  name), optional `value` override. 100 % library coverage (41
  components + 13 boards).
- **`wirestudio/kicad/generator.py`** walks `design.json` and emits a
  SKiDL Python script. The studio doesn't import or run SKiDL itself
  — this keeps the artefact transparent (the user can `cat`/edit it)
  and avoids adding numpy + EDA-toolchain weight to the server.
- **`POST /design/kicad/schematic`** returns the script with
  `Content-Disposition: attachment`. Header **Schematic** button
  opens a download dialog with usage instructions and a SKiDL doc
  link. PCB layout deferred to 1.0+.

### Deployment (Docker + GHCR)

- **Multi-stage `Dockerfile`** — `node:20-alpine` builds the SPA,
  `python:3.11-slim` ships the bundle. tini for signal handling.
  ~180 MB; `linux/amd64` + `linux/arm64`. `EXPOSE 8765`,
  `VOLUME /data`.
- **`wirestudio/api/serve.py`** mounts the studio app at `/api` and the
  built bundle at `/`. Bare-API mode preserved (Vite dev keeps
  working).
- **`SESSIONS_DIR` + `DESIGNS_DIR`** env vars route the stores at
  `/data/sessions` + `/data/designs`.
- **GitHub Actions** (`.github/workflows/docker.yml`) publishes to
  `ghcr.io/moellere/wirestudio` on push-to-main and `v*` tag
  push. Multi-arch via `docker/build-push-action` + GHA cache.
- **Two-service compose recipe** in `deploy/` for users who want
  nginx in front (HTTP/2, brotli, scaling api workers
  independently). Documented as opt-in, not the default.

### Test surface

297 pytest, 125 vitest. Goldens for every bundled example pin both
YAML + ASCII output. RTL/jsdom component tests cover BusList,
ConnectionForm, EnclosureDialog, Inspector, CapabilityPickerDialog,
PinoutView, PushToFleetDialog, SchematicDialog. ruff + tsc + vite
build clean across the whole arc.

[Unreleased]: https://github.com/moellere/wirestudio/compare/v0.11.0...HEAD
[0.11.0]: https://github.com/moellere/wirestudio/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/moellere/wirestudio/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/moellere/wirestudio/releases/tag/v0.9.0
