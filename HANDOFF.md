# WireStudio / bench — handoff

Written 2026-08-26. Everything below is verified live unless marked otherwise.

## Current state

- **wirestudio 0.32.0** — tagged, on PyPI + ghcr, prod running `0.32.0-full`.
  Nothing unreleased; `[Unreleased]` in CHANGELOG is empty.
- **Bench** (`10.254.0.44`, address by IP) on upstream **Embedded-AI-Harness v1.0.1**.
  Hostname pinned to `wyola-workbench` by a local patch (below).
- **Nightly hardware gate** runs 03:30 America/Denver, currently 11/11 green.
  Run on demand:
  `kubectl create job -n wirestudio gate-x --from=cronjob/wirestudio-hardware-gate`
- **Alerts**: 9 firing cluster-wide, down from 25. All remaining are actionable.

### Devices

| DevEUI | Board | Slot | State |
|---|---|---|---|
| `10521cfffe66b6e0` | TTGO T-Beam | SLOT12 | 0.32.0 fw, joined, 24-byte payload |
| `64b708fffeab8974` | Heltec V2 | SLOT19 | fine |
| `8cfd49fffeb55758` | Heltec V4 GNSS | SLOT28 | fine; **no GNSS module seated** |
| `500291fffe9df404` | TTGO LoRa32 v2 | — | **cable out**, on the air only |
| `c44f33fffe76e03d` | Heltec GPS | — | offline by choice since June |

Identify boards by USB bridge, never by slot label (labels are positional):
`10c4:ea60`=T-Beam, `1a86:55d4`=Heltec V2, `303a:1001`=V4/esp32s3.

---

## 1. Workbench phase 2 — the UI half  ← start here

Server side shipped in 0.29.0 and needs no changes: `verify_boot()` in
`wirestudio/workbench/boot.py` holds the per-framework markers, exposed as the
`workbench_verify_boot` MCP tool (`wirestudio/mcp/hardware.py:254`).

Not done: **streaming a slot's serial into the flash dialog over SSE** so a
human watches the boot rather than reading a verdict after the fact.

Touchpoints:

- `wirestudio/api/workbench.py:97` — `/workbench/flash` already returns a
  `StreamingResponse` of SSE. The relay wants the same shape.
- `wirestudio/workbench/client.py` — has `monitor()` and `output()`; note
  `/api/serial/output` returns **oldest-first**, which reads as "nothing
  happened" if you take the tail (filed upstream as SensorsIot#30).
- `web/src/components/FlashDialog.tsx` — the dialog, with an existing test file
  alongside it.

Worth knowing before wiring it: the bench's serial port admits **one reader**,
and the always-on recorder is already one. Anything long-running has to expect
a busy state and release its lease on failure rather than assuming the bench is
idle (`docs/workbench.md`, design constraints).

## 2. Workbench phase 3 — enable the flash stage

The gate is non-destructive today. `flash: true` on a roster entry deliberately
reports an explicit failure rather than doing nothing.

**Blocked on hardware, not code.** It needs a *dedicated* board nothing depends
on — all three on the bench carry live traffic, and a nightly reflash costs a
rejoin, a DevNonce and ~10 min off air each. Adding one spare board turns this
on, and that is what retires the "no live-flash gate" caveat on the Meshtastic
/ CircuitPython / LoRaWAN tiers.

## 3. Workbench phase 4 — not started

AP provision + MQTT/API entity assertions for generated ESPHome devices; SDR
TX power check for radio boards.

---

## Open issues / PRs

- **wirestudio #219** — board `flash_size` unverified; `esp32-s3-devkitc-1`
  ships 8 MB and 32 MB under one name. The undecidable half is now handled:
  the board file keeps the floor and `design.json` carries a
  `board.flash_size_mb` override for a unit whose size has been measured.
  What remains is measurement, and it is still blocked — none of the four
  boards named in the issue is on the bench (SLOT28 is a V4, already
  verified at 16 MB). Each is seconds of `esptool flash-id` once present.
- **SensorsIot/Embedded-AI-Harness #29** — "MCP could reset a slot but never
  answer it". Open **18 days, no review**. Nudge or ping.
- **SensorsIot/Embedded-AI-Harness #31** — keep-hostname opt-out (opened
  2026-08-26). If merged, the bench's local patch can be dropped.

---

## Verification gaps (things believed true but not proven)

- **`fix_age_min` non-zero path never observed on hardware.** New in 0.32.0.
  Reads 0 correctly with a live fix, across 13 uplinks. The stale (`>0`) and
  never-fixed (`65535`) paths are covered by unit tests and construction only.
  A field that always reads 0 is indistinguishable from a broken one — treat as
  unproven until it moves. Should show itself the first time the T-Beam is
  parked with its GNSS off.
- **T-Beam GPS quality** is poor but genuine: sats 0–8, ~25–70 m scatter,
  altitude still climbing an hour into uptime. That is the metal workshop, not
  a fault. Expect it to improve outdoors on the vehicle.
  Note lat/lon are published **unconditionally on purpose** (last-known position
  is the feature for a vehicle tracker) — a position in the payload is *not*
  evidence of a current fix.

---

## Remaining alerts (all real — do not silence)

- `TargetDown job=dorkwall` — node_exporter on `dorkwall.dorktool.com:9100`
  unreachable (external host).
- `CPUThrottlingHigh ns=redis` ×2 — CPU limit too tight; tuning.
- `KubeDaemonSetNotScheduled` / `RolloutStuck` ×2 in ns `prometheus`. The
  `node-feature-discovery` pair is already null-routed at the alertmanager
  route; the `prometheus` pair is not covered.

The `nomtom-app` 404 that used to sit in this list is fixed — its
ServiceMonitor was disabled in nomtom-deploy#4. Giving that app real metrics
is tracked in `HANDOFF-METRICS.md` in the nomtom repo, not here.

## Hardware, needs a human at Wyola

- **Reseat the TTGO LoRa32 v2's USB cable.** It is powered and uplinking
  (fCnt ~4700) but absent from the bench, so it cannot be flashed. It still
  needs the ADC-pin/divider reflash. The gate watches for its return — when it
  reappears on any slot, the slots stage reports "unexpected board present" and
  alerts, because positional labels mean the slot cannot be predicted.
- **Seat a GNSS module** on the Heltec V4 (SLOT28) if its GPS is wanted.
- **Heltec GPS** (`c44f33…`): when it returns it needs a rebuild, reflash and
  profile update before it decodes — `fix_age_min` moved its payload 17 → 19
  bytes, and a refreshed profile would reject the old firmware's 17-byte uplink.

---

## Gotchas worth knowing before you start

- **The argocd repo is not on `master` by default.** It was sitting on
  `fix/uptime-kuma-heap-oom`. Check the branch before committing.
- **ArgoCD often will not pick up a push on its own** — annotate to force:
  `kubectl annotate app -n argocd <app> argocd.argoproj.io/refresh=normal --overwrite`
- **`severity: info` alerts route to the null receiver** and can never notify.
- **One invalid rule voids an entire PrometheusRule object** — that is how 12
  homelab alerts stayed dead for 114 days.
- **Prometheus retention is 10 d** — a `[14d]` range silently evaluates over
  less.
- **Bench installs reboot every attached board** (USB re-enumeration), costing
  a rejoin each. Budget for it.
- **The bench hostname patch** lives at `~/bench-patches/keep-hostname.patch`
  with marker `/etc/rfc2217/keep-hostname`; re-apply if an update clobbers
  `install.sh`.
- **"Wyola" is a street address in NW Arkansas** (~35.8833, -94.0737), not
  Wyola, Montana. Do not infer the site's location from the name.
- **"The TTGO" is ambiguous** — the T-Beam (SLOT12) and the TTGO LoRa32 v2 are
  different boards with different radio pin maps and different battery sensing.
  Confirm which before flashing.
