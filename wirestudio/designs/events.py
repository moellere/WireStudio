"""In-process pub/sub for design-store mutations.

Wirestudio writes a design from three places now: the HTTP `POST /designs`
endpoint, the MCP tool surface, and the future CLI. A browser tab showing
the same design needs to see those writes without polling. The cheapest
shape that works is a per-design `asyncio.Queue` fan-out: the design store
publishes an event after each write, and a Server-Sent-Events endpoint
subscribes per request.

The bus lives inside the FastAPI app's process. There is no cross-process
broadcast -- if you ever run multiple wirestudio replicas behind a load
balancer you'll need to swap this for a redis pubsub or similar, but a
single-operator homelab deployment doesn't.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

from wirestudio.designs.store import DesignStore, SavedDesignSummary


EventKind = Literal["saved", "deleted"]


@dataclass
class DesignEvent:
    kind: EventKind
    design_id: str
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {"kind": self.kind, "design_id": self.design_id, "at": self.at}


class DesignEventBus:
    """Per-design subscriber set with non-blocking publish.

    Subscribers register via `subscribe(design_id)` and get back an
    `asyncio.Queue` they can `await queue.get()` on. Publishers call
    `publish(event)` from sync code; the bus iterates the queue set for
    that id and puts the event with `put_nowait`. An unbounded queue
    means a slow consumer can grow memory until they disconnect, which
    is acceptable for a single-operator UI; a public deployment would
    want a maxsize + drop policy.
    """

    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[DesignEvent]]] = {}

    def subscribe(self, design_id: str) -> asyncio.Queue[DesignEvent]:
        q: asyncio.Queue[DesignEvent] = asyncio.Queue()
        self._subs.setdefault(design_id, set()).add(q)
        return q

    def unsubscribe(self, design_id: str, queue: asyncio.Queue[DesignEvent]) -> None:
        subs = self._subs.get(design_id)
        if subs is None:
            return
        subs.discard(queue)
        if not subs:
            self._subs.pop(design_id, None)

    def publish(self, event: DesignEvent) -> None:
        for q in list(self._subs.get(event.design_id, ())):
            q.put_nowait(event)

    def subscriber_count(self, design_id: str) -> int:
        return len(self._subs.get(design_id, ()))


class EventEmittingDesignStore:
    """DesignStore wrapper that publishes a DesignEvent after each write.

    Reads delegate transparently. A failed write doesn't publish -- the
    event only fires after the inner store reports success. Designed to
    wrap any DesignStore impl (FileDesignStore today, SQLite tomorrow).
    """

    def __init__(self, inner: DesignStore, events: DesignEventBus) -> None:
        self._inner = inner
        self._events = events

    # Read-through delegation.

    def exists(self, design_id: str) -> bool:
        return self._inner.exists(design_id)

    def list(self) -> list[SavedDesignSummary]:
        return self._inner.list()

    def load(self, design_id: str) -> dict:
        return self._inner.load(design_id)

    # Writes publish on success.

    def save(self, design: dict, design_id: Optional[str] = None) -> tuple[str, str]:
        result_id, saved_at = self._inner.save(design, design_id=design_id)
        self._events.publish(DesignEvent(kind="saved", design_id=result_id, at=saved_at))
        return result_id, saved_at

    def delete(self, design_id: str) -> bool:
        removed = self._inner.delete(design_id)
        if removed:
            self._events.publish(DesignEvent(kind="deleted", design_id=design_id))
        return removed
