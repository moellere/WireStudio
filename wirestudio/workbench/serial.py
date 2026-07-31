"""Drive a slot's serial console over the workbench's RFC2217 port.

This is the half of LoRaWAN provisioning that only the browser could do:
reading the device's prompts and writing the answers back. The keys come
from ChirpStack (`provision_device`); this module just gets them into the
device's NVS without a human at the bench.
"""
from __future__ import annotations

import re
import time
from typing import Iterator, Optional, Pattern, Sequence

DEFAULT_BAUD = 115200


class SerialUnavailable(RuntimeError):
    """Raised when the slot's serial port is unusable or the dialogue stalls."""


def _redact(text: str, secrets: Sequence[str]) -> str:
    """Devices echo what they were sent, so a key comes back on the wire.

    Matched case-insensitively: firmware commonly echoes hex uppercase even
    when it was sent lowercase.
    """
    for s in secrets:
        if not s:
            continue
        text = re.sub(re.escape(s), "<redacted>", text, flags=re.IGNORECASE)
    return text


def answer_prompts(
    url: str,
    rules: Sequence[tuple[Pattern[str], str]],
    *,
    done: Pattern[str],
    secrets: Sequence[str] = (),
    baud: int = DEFAULT_BAUD,
    timeout: float = 180.0,
    prompt_marker: str = "Enter",
    nudge: bytes = b"\r\n",
    min_interval: float = 1.0,
) -> Iterator[dict]:
    """Answer a device's serial prompts, yielding redacted log events.

    `rules` is [(pattern, answer)] checked in order against the tail of the
    output; first match wins. Yields ``{"type": "log", "data": ...}`` and a
    final ``{"type": "result", "matched": <text or None>}``.

    Raises SerialUnavailable if the port cannot be opened or the dialogue
    stalls without reaching `done`.
    """
    try:
        import serial  # noqa: PLC0415 -- optional dep, only needed on this path
    except ImportError as exc:  # pragma: no cover - exercised by the extra
        raise SerialUnavailable(
            "pyserial is required for workbench serial provisioning "
            "(pip install 'wirestudio[lorawan]')"
        ) from exc

    try:
        port = serial.serial_for_url(url, baudrate=baud, timeout=1)
    except Exception as exc:
        raise SerialUnavailable(f"cannot open {url}: {exc}") from exc

    buf = ""
    last_sent = 0.0
    deadline = time.monotonic() + timeout
    try:
        # The firmware prints its prompt once, before we attach. A bare newline
        # is rejected and re-prints it, which is what gives us something to
        # match -- without this the dialogue silently never starts.
        if nudge:
            time.sleep(0.5)
            port.write(nudge)
            port.flush()

        while time.monotonic() < deadline:
            chunk = port.read(512).decode("utf-8", "replace")
            if chunk:
                buf += chunk
                yield {"type": "log", "data": _redact(chunk, secrets)}

            hit = done.search(buf)
            if hit:
                yield {"type": "result", "matched": hit.group(0)}
                return

            tail = buf[-400:]
            # Rate-limit so one prompt re-printed twice doesn't consume two
            # answers and desynchronise the rest of the dialogue.
            if prompt_marker in tail and time.monotonic() - last_sent > min_interval:
                for pattern, answer in rules:
                    if pattern.search(tail):
                        port.write((answer + "\r\n").encode())
                        port.flush()
                        yield {
                            "type": "log",
                            "data": f"[sent {_redact(answer, secrets)}]\n",
                        }
                        buf = ""
                        last_sent = time.monotonic()
                        break
    finally:
        try:
            port.close()
        except Exception:  # pragma: no cover - best effort
            pass

    raise SerialUnavailable(
        f"serial dialogue did not reach {done.pattern!r} within {timeout:.0f}s"
    )
