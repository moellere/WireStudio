"""Exception rendering never produces a bare message."""
from __future__ import annotations

import httpx
import pytest

from wirestudio.errors import describe


# Every one of these is raised by httpx with no message in real failures,
# so `f"{e}"` renders as "" and the caller emits a message ending in a
# colon and nothing else.
MESSAGELESS = [
    httpx.ConnectTimeout(""),
    httpx.ReadTimeout(""),
    httpx.PoolTimeout(""),
    httpx.ConnectError(""),
    httpx.ReadError(""),
    httpx.RemoteProtocolError(""),
]


@pytest.mark.parametrize("exc", MESSAGELESS, ids=lambda e: type(e).__name__)
def test_messageless_exceptions_render_as_their_class(exc):
    assert str(exc) == "", "premise: httpx renders these empty"
    assert describe(exc) == type(exc).__name__


def test_a_real_message_is_preserved():
    assert describe(ValueError("bad offset 0x10000")) == "bad offset 0x10000"


def test_whitespace_only_counts_as_empty():
    assert describe(ValueError("   \n ")) == "ValueError"


def test_never_returns_empty():
    for exc in MESSAGELESS + [ValueError(""), RuntimeError(), Exception()]:
        assert describe(exc), f"{type(exc).__name__} rendered empty"
