"""Boot-marker verification: did the firmware we flashed actually run?

Drives the real WorkbenchClient against a wire-level fake that speaks the
bench's /api/serial/monitor shape, rather than a fake client -- a fake
client would only prove verify_boot calls the method I think exists.
"""
from __future__ import annotations

import httpx
import pytest

from wirestudio.workbench import WorkbenchClient
from wirestudio.workbench.boot import (
    BOOT_CHECKS,
    JOIN_CHECKS,
    UNSUPPORTED,
    supported_frameworks,
    verify_boot,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _bench(script):
    """script: pattern -> (matched, line, output). Speaks /api/serial/monitor."""
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path != "/api/serial/monitor":
            return httpx.Response(404, json={"error": "unexpected path"})
        body = __import__("json").loads(req.content)
        pattern = body.get("pattern")
        calls.append(body)
        matched, line, output = script.get(pattern, (False, None, []))
        return httpx.Response(200, json={
            "ok": True, "matched": matched, "line": line, "output": output,
        })

    client = WorkbenchClient(base_url="http://bench:8080", token="",
                             transport=httpx.MockTransport(handler))
    return client, calls


async def test_booted_when_the_marker_appears():
    marker = BOOT_CHECKS["esphome"].pattern
    client, calls = _bench({marker: (True, f"[I][app:117]: {marker}", [])})

    out = await verify_boot(client, "SLOT1", "esphome")

    assert out["ok"] is True
    assert out["booted"] is True
    assert out["checks"][0]["stage"] == "boot"
    assert out["checks"][0]["matched"] is True
    assert calls[0]["pattern"] == marker


async def test_not_booted_returns_a_result_not_an_error():
    """A board that flashed but did not boot is the finding, not a failure."""
    client, _ = _bench({BOOT_CHECKS["esphome"].pattern:
                        (False, None, ["rst:0x10 (RTCWDT_RTC_RESET)"] * 20)})

    out = await verify_boot(client, "SLOT1", "esphome")

    assert out["ok"] is True          # the call worked
    assert out["booted"] is False     # the board did not
    assert out["recent_output"], "should surface what it printed instead"
    assert len(out["recent_output"]) <= 15


async def test_join_is_not_checked_unless_asked():
    """The first join after a flash reliably fails, so asserting it by
    default would fail on a healthy board."""
    marker = BOOT_CHECKS["lorawan"].pattern
    client, calls = _bench({marker: (True, marker, [])})

    out = await verify_boot(client, "SLOT1", "lorawan")

    assert out["booted"] is True
    assert "joined" not in out
    assert len(calls) == 1, "should not have monitored for a join"


async def test_join_checked_on_request():
    boot = BOOT_CHECKS["lorawan"].pattern
    join = JOIN_CHECKS["lorawan"].pattern
    client, calls = _bench({boot: (True, boot, []), join: (True, join, [])})

    out = await verify_boot(client, "SLOT1", "lorawan", check_join=True)

    assert out["booted"] is True and out["joined"] is True
    assert [c["stage"] for c in out["checks"]] == ["boot", "join"]
    assert len(calls) == 2


async def test_join_is_not_attempted_when_the_board_never_booted():
    boot = BOOT_CHECKS["lorawan"].pattern
    client, calls = _bench({boot: (False, None, [])})

    out = await verify_boot(client, "SLOT1", "lorawan", check_join=True)

    assert out["booted"] is False
    assert len(calls) == 1, "no point waiting 7 minutes for a join that cannot come"


async def test_join_timeout_allows_for_the_post_flash_retry():
    """The first join after a flash fails; the retry is one uplink interval
    later. A timeout under ~5 minutes would fail on a healthy board."""
    for framework, check in JOIN_CHECKS.items():
        assert check.timeout_s >= 360, f"{framework} join timeout too tight"


@pytest.mark.parametrize("framework", sorted(UNSUPPORTED))
async def test_unsupported_frameworks_say_why(framework):
    client, calls = _bench({})

    out = await verify_boot(client, "SLOT1", framework)

    assert out["ok"] is False
    assert out["error"] == UNSUPPORTED[framework]
    assert not calls, "should not have touched the bench"


async def test_unknown_framework_lists_the_known_ones():
    client, _ = _bench({})
    out = await verify_boot(client, "SLOT1", "nonesuch")
    assert out["ok"] is False
    for known in supported_frameworks():
        assert known in out["error"]
