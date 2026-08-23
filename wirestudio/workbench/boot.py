"""Boot-marker verification: did the firmware we just flashed actually run?

A successful flash proves bytes reached the chip. It says nothing about
whether they boot -- a wrong flash size, an undriven front end, a
half-configured peripheral all flash perfectly and then fail at start-up,
which is the failure class CI cannot see. This asserts a line the running
firmware emits, read through the bench's read-only serial fan-out so
watching cannot disturb what is being watched.

Every marker here comes from a line observed on hardware or emitted by a
template in this repo; none are guessed. Frameworks whose success
signature has not been established are absent rather than approximated --
see UNSUPPORTED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

# ESPHome colours its log lines; the escapes survive into the buffer and
# make a returned line unreadable in JSON.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class BootCheck:
    """One assertion about a line the firmware emits."""

    pattern: str
    proves: str
    timeout_s: float


# Booted: the firmware started and got through init. Fast and reliable --
# this is the assertion worth gating on.
BOOT_CHECKS: dict[str, BootCheck] = {
    # ESPHome logs this once every component's setup() returned.
    # Observed on a Heltec V4: "[I][app:117]: setup() finished successfully!"
    "esphome": BootCheck(
        pattern="setup() finished successfully!",
        proves="every ESPHome component initialised",
        timeout_s=60.0,
    ),
    # The standalone LoRaWAN target prints its own banner from
    # templates/main.cpp.j2 before touching the radio.
    # Observed on a T-Beam and a Heltec V2.
    "lorawan": BootCheck(
        pattern="wirestudio lorawan:",
        proves="standalone LoRaWAN firmware started",
        timeout_s=45.0,
    ),
}

# The ESPHome external-component path boots like any ESPHome device.
BOOT_CHECKS["lorawan-esphome"] = BOOT_CHECKS["esphome"]


# Joined: the device reached the network. Deliberately separate from
# booting, because the first join after a flash reliably fails and only
# the retry -- one uplink interval later -- succeeds. Asserting this
# straight after flashing would fail on a healthy board, so the timeouts
# below allow for that retry and the check is opt-in.
JOIN_CHECKS: dict[str, BootCheck] = {
    # templates/main.cpp.j2 prints this on a successful activation.
    "lorawan": BootCheck(
        pattern="JOINED: OTAA session active",
        proves="joined the LoRaWAN network",
        timeout_s=420.0,
    ),
    # lorawan-for-esphome logs "OTAA join OK (new session)".
    "lorawan-esphome": BootCheck(
        pattern="OTAA join OK",
        proves="joined the LoRaWAN network",
        timeout_s=420.0,
    ),
}

# Frameworks this cannot verify yet, and why. Listed so the gap is a
# recorded fact rather than an apparent oversight.
UNSUPPORTED: dict[str, str] = {
    "meshtastic": (
        "no boot signature established -- needs a Meshtastic board on the "
        "bench to observe one"
    ),
    "circuitpython": (
        "success is CIRCUITPY enumerating as USB mass storage, not a serial "
        "line, so a serial marker is the wrong mechanism"
    ),
}


def boot_check(framework: str) -> Optional[BootCheck]:
    return BOOT_CHECKS.get(framework)


def join_check(framework: str) -> Optional[BootCheck]:
    return JOIN_CHECKS.get(framework)


def supported_frameworks() -> list[str]:
    return sorted(BOOT_CHECKS)


async def _match(client, slot: str, check: BootCheck, since: Optional[float]) -> dict:
    """Look for `check.pattern`, first in what was already captured.

    A boot marker is printed once, in the second or two after reset. By
    the time a caller finishes flashing and asks, it has usually already
    gone past -- and `monitor` only sees the *next* line. So the
    recorder's buffer is consulted first, and live monitoring is the
    fallback for a marker still to come.
    """
    if since is not None:
        for entry in await client.output(slot, lines=1000, since=since):
            text = entry.get("text", "")
            if check.pattern in text:
                return {"matched": True, "line": _ANSI.sub("", text), "via": "buffer"}
    res = await client.monitor(slot, pattern=check.pattern, timeout=check.timeout_s)
    line = res.get("line")
    return {
        "matched": bool(res.get("matched")),
        "line": _ANSI.sub("", line) if line else line,
        "output": res.get("output") or [],
        "via": "monitor",
    }


async def verify_boot(
    client,
    slot: str,
    framework: str,
    *,
    since: Optional[float] = None,
    check_join: bool = False,
) -> dict:
    """Assert the firmware on `slot` started, and optionally that it joined.

    `since` is an epoch bracketing the reset -- pass the time just before
    flashing and the already-captured buffer is searched before waiting
    on new output, which removes the race between a device booting and
    the caller getting around to watching.

    Returns {"ok", "booted", "framework", "checks": [...]} -- never raises
    for a failed assertion, only for an unreachable bench. A board that
    flashed but did not boot is a result, not an error.
    """
    check = boot_check(framework)
    if check is None:
        return {
            "ok": False,
            "framework": framework,
            "error": UNSUPPORTED.get(
                framework,
                f"no boot marker for '{framework}'; known: "
                f"{', '.join(supported_frameworks())}",
            ),
        }

    checks: list[dict] = []
    res = await _match(client, slot, check, since)
    booted = res["matched"]
    checks.append({
        "stage": "boot",
        "pattern": check.pattern,
        "proves": check.proves,
        "matched": booted,
        "line": res.get("line"),
        "via": res.get("via"),
        "timeout_s": check.timeout_s,
    })

    joined = None
    if booted and check_join:
        jc = join_check(framework)
        if jc is None:
            checks.append({
                "stage": "join",
                "matched": None,
                "skipped": f"no join marker for '{framework}'",
            })
        else:
            jres = await _match(client, slot, jc, since)
            joined = jres["matched"]
            checks.append({
                "stage": "join",
                "pattern": jc.pattern,
                "proves": jc.proves,
                "matched": joined,
                "line": jres.get("line"),
                "via": jres.get("via"),
                "timeout_s": jc.timeout_s,
            })

    out = {
        "ok": True,
        "framework": framework,
        "slot": slot,
        "booted": booted,
        "checks": checks,
    }
    if joined is not None:
        out["joined"] = joined
    if not booted:
        # The tail is the useful part: whatever it did print instead.
        out["recent_output"] = (res.get("output") or [])[-15:]
    return out
