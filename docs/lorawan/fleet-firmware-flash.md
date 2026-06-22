# Fleet firmware delivery → WebSerial flash (scoping)

How a LoRaWAN device built by fleet-for-esphome gets onto blank hardware
without a network OTA. Companion to
[`workflow-integration.md`](workflow-integration.md); this is the last
gap in the external-component happy path.

## Problem

The external-component LoRaWAN path builds firmware **on the fleet**
(ESPHome inside fleet-for-esphome), not in the studio. But:

- A field LoRaWAN node is headless — no `wifi:` / `api:` / network
  `ota:` (see the headless-render fix). So the fleet's compile→**OTA**
  delivery model can't reach it.
- fleet-for-esphome has no WebSerial flasher.
- The studio's WebSerial flasher (`web/src/lib/flash.ts`) is wired only
  to the **standalone Arduino** path, which fetches its `.bin` from the
  studio's own `/lorawan/firmware/{cache_key}` (studio-compiled). The
  external-component path's artifact lives on the fleet, which the studio
  can't currently fetch.

Net: today the operator hand-runs `esphome run` locally to flash an
external-component LoRaWAN device. That defeats the Chromebook-friendly
compile-server / browser-flasher split the rest of the studio relies on.

## Shape

Studio already owns the browser half. The only missing link is **getting
the compiled artifact from the fleet to the browser**. The browser never
talks to the fleet directly (the `FLEET_TOKEN` is server-side), so the
artifact rides through the studio as a passthrough:

```
fleet (build) ──artifact──▶ studio /fleet/jobs/{run_id}/firmware ──bytes──▶ browser WebSerial ──▶ device
```

Three pieces, two repos.

### 1. Fleet endpoint (UPSTREAM — `weirded/fleet-for-esphome`, out of studio scope)

A new read-only endpoint on the addon's `/ui/api/*` surface that streams
the artifact a finished compile produced:

```
GET /ui/api/jobs/{run_id}/firmware           -> app image (firmware.bin)
GET /ui/api/jobs/{run_id}/firmware/factory   -> merged factory image (firmware-factory.bin)
```

- Auth: same Bearer `FLEET_TOKEN` as the rest of `/ui/api/*`.
- Source path (ESPHome build tree, per device `<name>`):
  - app: `.esphome/build/<name>/.pioenvs/<name>/firmware.bin`
  - factory: `.esphome/build/<name>/.pioenvs/<name>/firmware-factory.bin`
- Content-Type: `application/octet-stream`,
  `Content-Disposition: attachment; filename="<name>.bin"`.
- `404` when the run hasn't finished, the run failed, or the file is
  absent (e.g. an older ESPHome that didn't emit a factory image).
- `200` streams the bytes.

This is the only out-of-scope work. Until it ships, the studio side
below is built but the button stays disabled with an explanatory hint.

### 2. Studio server passthrough (IN SCOPE — `wirestudio/fleet/client.py` + `wirestudio/fleet/api`)

- `FleetClient.get_firmware(run_id, *, factory=False) -> bytes` — fetches
  the fleet endpoint with the server-side token. `FleetUnavailable` on
  404 / non-200, mirroring `get_job_log`.
- FastAPI route `GET /fleet/jobs/{run_id}/firmware[?factory=true]` that
  streams the bytes to the browser as `application/octet-stream`. Mirrors
  the studio's existing standalone-path artifact route
  (`/lorawan/firmware/{cache_key}` + `/factory`), so the browser side is
  symmetric across both LoRaWAN paths.

### 3. Studio web (IN SCOPE — `LorawanProvisionEsphomeDialog.tsx` + `api/client.ts`)

- `api.fleetFirmware(runId, { factory })` — returns `Uint8Array`, exactly
  like the existing `api.lorawanFirmware(cacheKey)` / `lorawanFactory`.
- A **"Flash via WebSerial →"** step in the provision dialog, appearing
  after **Push to fleet →** reports a successful compile:
  1. Poll the existing run-status surface (`api.fleetRunStatus(runId)` /
     `fleetJobLog`) until the verdict is success — the artifact doesn't
     exist before then.
  2. On click: `fleetFirmware(runId, { factory: true })` →
     `flashFirmware({ images: [{ data, address: 0x0 }], eraseAll: true })`
     for a blank board (factory image at 0x0, full erase). A blank board
     has no NVS to preserve, and `/lorawan/provision-esphome` re-flushes
     DevNonces, so the wipe is safe (the §2.1 reasoning, already encoded
     in `flash.ts`).
  3. Stream the boot log via the existing `onSerial` callback so the join
     line is visible in the dialog — the dialog already polls
     `/lorawan/activation/{dev_eui}` in parallel, so "flashed → joined"
     lands in one view.

`flash.ts` needs **no changes** — it's already image-agnostic; the caller
picks the image and address. The new code is a client method, a passthrough
route, and dialog wiring.

## Decisions

- **Factory image, full erase, for the dialog's button.** The provision
  flow is "blank board → join". App-region re-flash (preserve NVS) is the
  re-key/update case; defer a separate "update firmware" button to a
  follow-up. One button, one well-understood path first.
- **Passthrough, not a redirect.** The browser must not hold `FLEET_TOKEN`.
  The studio proxies the bytes; the fleet stays reachable only from the
  studio's network, same as every other `/fleet/*` call.
- **Gate on compile success, not just `run_id`.** The artifact is absent
  until the build finishes; the button polls the run to terminal-success
  before enabling, reusing the existing status infra (no new polling).
- **No studio-side build for the external-component path.** This keeps
  the lean studio image lean (the `-lorawan` PlatformIO variant remains
  the standalone path's concern). The fleet stays the single ESPHome
  builder; the studio only ferries the result.

## Risks / open questions

- **ESPHome factory-image availability.** Older ESPHome may not emit
  `firmware-factory.bin`. The fleet endpoint `404`s the factory route in
  that case; the studio falls back to app-image-at-0x10000 only if the
  board is known-provisioned, else surfaces "factory image unavailable —
  flash locally". Confirm the fleet's pinned ESPHome emits factory images.
- **Artifact retention.** How long does the fleet keep build artifacts
  after a run? If they're GC'd quickly, the flash button needs to fetch
  promptly or trigger a rebuild. Define retention with the fleet endpoint.
- **Run-id → device mapping.** `push_device(compile=True)` returns one
  `run_id` for the enqueue; confirm the firmware endpoint keys off
  `run_id` (not device name) so a stale artifact from a prior build can't
  be flashed by mistake.

## Reuse / build map

| Piece | Status |
|---|---|
| `web/src/lib/flash.ts` (`flashFirmware`, image-agnostic) | reuse as-is |
| `api.lorawanFirmware` / `lorawanFactory` (Uint8Array fetch shape) | mirror for `fleetFirmware` |
| `/lorawan/firmware/{cache_key}` route (studio artifact passthrough) | mirror for `/fleet/jobs/{run_id}/firmware` |
| `FleetClient.get_job_log` (token'd fleet GET + `FleetUnavailable`) | mirror for `get_firmware` |
| `fleetRunStatus` / `fleetJobLog` (run polling) | reuse to gate the button |
| `LorawanProvisionEsphomeDialog` push/poll state machine | extend with a flash step |
| fleet `GET /ui/api/jobs/{run_id}/firmware[/factory]` | **upstream, does not exist yet** |

## Phasing

1. **Upstream** — fleet artifact endpoint. Blocks the end-to-end, nothing
   else.
2. **Studio server** — `get_firmware` + passthrough route + tests.
   Buildable now against the contract above; route returns 502 until the
   fleet endpoint exists.
3. **Studio web** — `fleetFirmware` + dialog flash step. Button disabled
   with a hint until (1) lands; wired and tested against a mocked client.

Steps 2 and 3 can land behind the disabled button before step 1 exists,
so the studio is ready the moment the fleet endpoint ships.
