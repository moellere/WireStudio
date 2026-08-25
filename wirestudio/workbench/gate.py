"""Nightly hardware gate: is the bench, and everything on it, still alive?

Workbench phase 3. Runs from a cluster CronJob rather than a GitHub
self-hosted runner: WireStudio is a public repo, and a self-hosted
runner would let any fork's pull request execute code on the network
this job can reach. Scheduled from inside the perimeter, nothing
repo-controlled ever runs here.

What this asserts today
-----------------------
Non-destructive checks only:

  bench      the portal answers
  slots      each configured slot is present with its proxy running
  serial     the slot's recorder has captured output recently
  uplinks    the device's DevEUI was seen by ChirpStack recently

That is a real regression detector for the bench itself. A wedged USB
bridge went unnoticed for days because nothing was watching -- `slots`
catches exactly that, and `uplinks` catches a board that is powered but
off the air.

What it does NOT assert yet
---------------------------
It does not flash. The roadmap's phase 3 wants a representative example
per framework flashed to a *dedicated* slot, which is what would retire
the "no live-flash gate" caveat on the Meshtastic / CircuitPython /
LoRaWAN tiers. Every board currently on the bench is carrying real
traffic -- reflashing one nightly costs a rejoin, a DevNonce and about
ten minutes of downtime each time. Add a spare board, set `flash:` on
its entry, and the stage below turns on.

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
    return raw


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


async def run(config: dict, report: Report, client=None, chirp=None) -> None:
    """`client` / `chirp` are injectable so the stages can be tested
    without a bench; production passes neither."""
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

    # --- flash (not enabled; needs a dedicated slot) ---------------------
    for dev in devices:
        if dev.get("flash"):
            report.add("flash", dev["slot"], False,
                       "flash stage requested but not implemented -- see module docstring")


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
