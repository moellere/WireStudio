"""Rendering exceptions into something a reader can act on."""
from __future__ import annotations


def describe(exc: BaseException) -> str:
    """Human-readable text for an exception. Never empty.

    httpx raises its timeout and connection errors with no message, so
    `f"{exc}"` renders as `""` -- every one of ConnectTimeout,
    ReadTimeout, PoolTimeout, ConnectError, ReadError and
    RemoteProtocolError does it. The caller then emits "unreachable: "
    or "firmware not available for run <id>: " and the reader is told
    that something failed but not what.

    Worse, it only happens for *some* failure modes, so the same tool
    reports a useful message one minute and a bare colon the next --
    which reads as an intermittent bug in the tool rather than a class
    of error that carries no text.

    Falls back to the exception's class name, which for this family is
    the informative part anyway.
    """
    text = str(exc).strip()
    return text or type(exc).__name__
