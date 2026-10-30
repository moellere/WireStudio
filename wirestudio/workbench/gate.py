"""Nightly hardware gate: is the bench, and everything on it, still alive?

Workbench phase 3. Runs from a cluster CronJob rather than a GitHub
self-hosted runner: WireStudio is a public repo, and a self-hosted
runner would let any fork's pull request execute code on the network
this job can reach. Scheduled from inside the perimeter, nothing
repo-controlled ever runs here.

What this asserts
-----------------
  bench      the portal answers
  slots      each configured slot is present with its proxy running
  serial     the slot's recorder has captured output recently
  uplinks    the device's DevEUI was seen by ChirpStack recently
  flash      each framework listed under a device's `flash:` is written
             to its slot with a full erase
  boot       the written firmware printed its boot marker (boot.py)
  functional for an ESPHome flash on a `functional: true` device: it
             joined WiFi, its native API answers under the design's name,
             and the gate switch round-trips on and off (functional.py)

The first four are non-destructive and are a real regression detector
for the bench itself. A wedged USB bridge went unnoticed for days
because nothing was watching -- `slots` catches exactly that, and
`uplinks` catches a board that is powered but off the air.

`flash` and `boot` retire the "no live-flash gate" caveat on the
framework tiers. They reflash the board every night, so they belong only
on a dedicated board nothing depends on: reflashing a board that carries
real traffic costs a rejoin, a DevNonce and about ten minutes of
downtime each time. A flash device skips `serial`, since what it prints
at rest depends on which framework the previous run left on it; `boot`
asserts its output instead, from a reset issued through the bench once
the flash is done -- the reset esptool issues happens before the bench's
recorder is back, so that first boot is never captured.

Exit code is 0 when every enabled check passes, 1 when one fails,
and 2 when the roster itself is unusable -- a bad config must not read
as a clean bench.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path


class ConfigError(Exception):
    pass


def _load_config(path: Path) -> dict:
    import yaml

    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError:
        raise ConfigError(f"no such roster: {path}") from None
    except (OSError, yaml.YAMLError) as e:
        raise ConfigError(f"cannot read roster {path}: {e}") from None
    if raw is None:
        raise ConfigError(f"roster {path} is empty")
    if not isinstance(raw, dict) or not raw.get("devices"):
        raise ConfigError(f"roster {path} lists no devices")
    for i, dev in enumerate(raw["devices"]):
        if dev.get("on_bench", True) and not dev.get("slot"):
            raise ConfigError(
                f"roster {path}: device {i} ({dev.get('name', '?')}) has no slot. "
                "Set `on_bench: false` if it is off the bench on purpose.")
        if not dev.get("on_bench", True) and not dev.get("dev_eui"):
            raise ConfigError(
                f"roster {path}: device {i} ({dev.get('name', '?')}) is off the "
                "bench with no dev_eui, so nothing about it can be checked.")
        if "flash" in dev:
            _check_flash_entry(path, i, dev)
    return raw


def _check_flash_entry(path: Path, i: int, dev: dict) -> None:
    from wirestudio.library import default_library
    from wirestudio.workbench.images import FRAMEWORKS

    where = f"roster {path}: device {i} ({dev.get('name', '?')})"
    flash = dev["flash"]
    if not isinstance(flash, list) or not flash:
        raise ConfigError(f"{where}: `flash` must list frameworks, e.g. [esphome, micropython]")
    unknown = [f for f in flash if f not in FRAMEWORKS]
    if unknown:
        raise ConfigError(f"{where}: cannot flash {', '.join(map(str, unknown))}; "
                          f"known: {', '.join(FRAMEWORKS)}")
    if not dev.get("on_bench", True):
        raise ConfigError(f"{where}: is off the bench, so it cannot be flashed")
    if not dev.get("board"):
        raise ConfigError(f"{where}: `flash` needs `board`, the library board id")
    try:
        default_library().board(dev["board"])
    except FileNotFoundError:
        raise ConfigError(f"{where}: unknown board '{dev['board']}'") from None
    if dev.get("functional") and "esphome" not in flash:
        raise ConfigError(f"{where}: `functional` checks an ESPHome flash; add esphome to `flash`")
    pin = dev.get("functional_pin")
    if pin is not None and pin not in default_library().board(dev["board"]).gpio_capabilities:
        raise ConfigError(f"{where}: `functional_pin` {pin} is not a GPIO on {dev['board']}")


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool, str]] = []

    def add(self, stage: str, subject: str, ok: bool, detail: str = "") -> None:
        self.rows.append((stage, subject, ok, detail))
        mark = "ok  " if ok else "FAIL"
        print(f"  {mark} {stage:9} {subject:22} {detail}", flush=True)

    @property
    def failed(self) -> list[tuple[str, str, bool, str]]:
        return [r for r in self.rows if not r[2]]


async def run(config: dict, report: Report, client=None, chirp=None, dashboard=None,
              api_factory=None) -> None:
    """`client` / `chirp` / `dashboard` / `api_factory` are injectable so the
    stages can be tested without a bench; production passes none of them."""
    from wirestudio.workbench import WorkbenchClient, WorkbenchUnavailable

    devices = config.get("devices") or []
    max_silence = float(config.get("max_serial_silence_s", 1800))
    max_offline = float(config.get("max_uplink_silence_s", 3600))

    client = client or WorkbenchClient()

    # --- bench ----------------------------------------------------------
    try:
        info = await client.info()
        report.add("bench", "portal", True, info.get("hostname", "?"))
    except Exception as e:
        from wirestudio.errors import describe

        report.add("bench", "portal", False, describe(e))
        return  # nothing downstream can pass

    # --- slots ----------------------------------------------------------
    try:
        slots = {s.label: s for s in await client.slots()}
    except WorkbenchUnavailable as e:
        report.add("slots", "listing", False, str(e))
        return

    # A device declared `on_bench: false` is known to be off the bench -- its
    # USB cable is out, but it is still powered and on the air. Failing on that
    # every night would train the reader to ignore the gate, so it is asserted
    # over the radio only (uplinks, below) and claims no slot.
    on_bench = [d for d in devices if d.get("on_bench", True)]

    for dev in on_bench:
        label = dev["slot"]
        s = slots.get(label)
        if s is None:
            report.add("slots", label, False, "slot not configured on the bench")
            continue
        if not s.present:
            report.add("slots", label, False,
                       "absent -- board unplugged, or its USB bridge is off the bus")
            continue
        # `flashable` is the bench's own composite health answer: present,
        # not flapping, not mid-operation. Reusing it means the gate and a
        # real flash agree on what "healthy" means.
        ok, reason = s.flashable
        if not ok:
            report.add("slots", label, False, reason or "unusable")
            continue
        report.add("slots", label, True, f"present, chip={s.chip or 'undetected'}")

    # A board present on a slot no entry claims is a divergence from the
    # declared bench, the same class as a declared slot being absent, and it
    # is how an off-bench device announces it is back: slot labels are
    # positional, so a reconnected board cannot be predicted onto a label and
    # has to be caught by "something is here that should not be".
    claimed = {d["slot"] for d in on_bench}
    for label, s in sorted(slots.items()):
        if s.present and label not in claimed:
            report.add("slots", label, False,
                       "unexpected board present -- a device declared "
                       "`on_bench: false` may be reconnected and flashable again")

    # --- serial liveness ------------------------------------------------
    cutoff = time.time() - max_silence
    for dev in on_bench:
        if dev.get("flash"):
            continue
        label = dev["slot"]
        s = slots.get(label)
        if s is None or not s.present:
            continue
        try:
            lines = await client.output(label, lines=1000, since=cutoff)
        except Exception as e:
            from wirestudio.errors import describe

            report.add("serial", label, False, describe(e))
            continue
        if lines:
            age = int(time.time() - lines[-1]["ts"])
            report.add("serial", label, True, f"{len(lines)} lines, newest {age}s ago")
        else:
            report.add("serial", label, False,
                       f"nothing captured in {int(max_silence)}s -- board may be hung")

    # --- uplinks --------------------------------------------------------
    # An off-bench device has no slot to name it by, so fall back to its
    # roster name -- this stage is the only assertion it gets.
    euis = [(d.get("slot") or d.get("name") or d["dev_eui"], d["dev_eui"])
            for d in devices if d.get("dev_eui")]
    if euis:
        from wirestudio.targets.lorawan import chirpstack as cs

        chirp = chirp or cs.ChirpStackClient()
        if not chirp.is_configured():
            report.add("uplinks", "chirpstack", False, "not configured")
        else:
            from chirpstack_api import api

            stubs, auth = chirp._get_stubs(), chirp._auth
            for label, eui in euis:
                try:
                    act = chirp.get_activation(eui)
                    # last_seen_at is on the response, not on .device
                    dev = stubs.device.Get(
                        api.GetDeviceRequest(dev_eui=eui), metadata=auth)
                except Exception as e:
                    from wirestudio.errors import describe

                    report.add("uplinks", label, False, describe(e))
                    continue
                if act is None:
                    report.add("uplinks", label, False, f"{eui} has no activation")
                    continue
                # An activation only proves the device joined once. A board
                # can hold a valid session and be off the air for months --
                # which is exactly how a dead device hid on this bench.
                seen = dev.last_seen_at.seconds
                if not seen:
                    report.add("uplinks", label, False, f"{eui} has never been seen")
                    continue
                age = int(time.time() - seen)
                detail = f"dev_addr={act.get('dev_addr')} fCnt={act.get('f_cnt_up')} seen {age}s ago"
                report.add("uplinks", label, age <= max_offline, detail
                           if age <= max_offline
                           else f"{detail} -- silent for over {int(max_offline)}s")

    # --- flash + boot ---------------------------------------------------
    flashers = [d for d in on_bench
                if d.get("flash") and d["slot"] in slots and slots[d["slot"]].flashable[0]]
    if flashers:
        from wirestudio.esphome_dashboard import DashboardClient
        from wirestudio.library import default_library

        dashboard = dashboard or DashboardClient()
        library = default_library()
        for dev in flashers:
            for framework in dev["flash"]:
                await _flash_one(dev, framework, client, report, library, dashboard, api_factory)


async def _flash_one(dev: dict, framework: str, client, report: Report, library,
                     dashboard, api_factory=None) -> None:
    from wirestudio.errors import describe
    from wirestudio.workbench import images
    from wirestudio.workbench.boot import verify_boot

    label = dev["slot"]
    subject = f"{label}/{framework}"
    board = library.board(dev["board"])
    functional_pin = None
    if framework == "esphome" and dev.get("functional"):
        from wirestudio.workbench.functional import FunctionalError, free_pin

        try:
            functional_pin = dev.get("functional_pin") or free_pin(board.gpio_capabilities)
        except FunctionalError as e:
            report.add("functional", subject, False, str(e))
    try:
        image = await images.image_for(framework, board, library, dashboard=dashboard,
                                       functional_pin=functional_pin)
    except images.ImageUnavailable as e:
        report.add("flash", subject, False, str(e))
        return

    try:
        async for _ in client.flash(label, images=[(image.offset, image.data)],
                                    chip=board.chip_variant, erase=True):
            pass
    except Exception as e:
        report.add("flash", subject, False, describe(e))
        return
    report.add("flash", subject, True, f"{image.version}, {len(image.data)} bytes at {image.offset:#x}")

    booted_at = time.time()
    try:
        res = await verify_boot(client, label, framework, reset=True)
    except Exception as e:
        report.add("boot", subject, False, describe(e))
        return
    if res.get("booted"):
        report.add("boot", subject, True, res["checks"][0].get("line") or "")
        if functional_pin:
            await _functional(dev, subject, board, client, report, booted_at, api_factory)
    else:
        tail = " | ".join(str(e.get("text", e) if isinstance(e, dict) else e).strip()
                          for e in res.get("recent_output", [])[-5:])
        report.add("boot", subject, False,
                   f"no '{res['checks'][0]['pattern']}' within "
                   f"{int(res['checks'][0]['timeout_s'])}s; last output: {tail or 'nothing'}")

async def _functional(dev: dict, subject: str, board, client, report: Report, since: float,
                      api_factory) -> None:
    from wirestudio.errors import describe
    from wirestudio.workbench import functional

    host = dev.get("functional_host")
    if not host:
        try:
            host = await functional.wait_for_ip(client, dev["slot"], since)
        except Exception as e:
            report.add("functional", subject, False, describe(e))
            return
    if not host:
        report.add("functional", subject, False,
                   "no 'IP Address' in the boot log within 60s -- the firmware did not join WiFi")
        return
    try:
        res = await functional.verify(host, functional.device_name(board.id, True), api_factory=api_factory)
    except Exception as e:
        report.add("functional", subject, False, describe(e))
        return
    detail = res.detail
    if not res.ok:
        # A device at the edge of the access point's range joins, drops and
        # rejoins; its API then times out like broken firmware would. The
        # signal it logged tells the two apart.
        try:
            rssi = await functional.last_rssi(client, dev["slot"], since)
        except Exception:
            rssi = None
        if rssi is not None:
            detail += f" (the device logged WiFi at {rssi} dBm{'; too weak to hold a link' if rssi <= -85 else ''})"
    report.add("functional", subject, res.ok, detail)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--config", type=Path,
        default=(Path(os.environ["HARDWARE_GATE_CONFIG"])
                 if os.environ.get("HARDWARE_GATE_CONFIG") else None),
        help="bench roster YAML; or set HARDWARE_GATE_CONFIG",
    )
    ap.add_argument("--json", action="store_true", help="emit machine-readable results")
    args = ap.parse_args()

    if args.config is None:
        print("no config: pass --config or set HARDWARE_GATE_CONFIG. The roster\n"
              "is deployment state (slot labels, DevEUIs), so it is not shipped --\n"
              "see docs/workbench.md for the schema.", file=sys.stderr)
        return 2
    try:
        config = _load_config(args.config)
    except ConfigError as e:
        print(f"hardware gate: {e}", file=sys.stderr)
        return 2
    print(f"hardware gate: {args.config}")
    print(f"bench: {os.environ.get('WORKBENCH_URL', '(WORKBENCH_URL unset)')}\n")

    report = Report()
    asyncio.run(run(config, report))

    failed = report.failed
    print()
    if args.json:
        print(json.dumps([
            {"stage": s, "subject": subj, "ok": ok, "detail": d}
            for s, subj, ok, d in report.rows
        ]))
    if failed:
        print(f"FAILED: {len(failed)} of {len(report.rows)} checks", file=sys.stderr)
        for stage, subject, _, detail in failed:
            print(f"  {stage}/{subject}: {detail}", file=sys.stderr)
        return 1
    print(f"OK: {len(report.rows)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
