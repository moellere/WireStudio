"""Tests for the design-changed pub/sub: bus + store wrapper.

The HTTP-level SSE endpoint is exercised by manual smoke tests against
uvicorn rather than httpx.ASGITransport -- in-process streaming through
ASGITransport has historically had buffering / lifespan-handshake quirks
that make a long-running SSE handler unreliable to assert against, and
the SSE endpoint itself is thin glue over the bus.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from wirestudio.designs.events import (
    DesignEvent,
    DesignEventBus,
    EventEmittingDesignStore,
)
from wirestudio.designs.store import FileDesignStore


pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# DesignEventBus
# ---------------------------------------------------------------------------


async def test_bus_publish_to_one_subscriber():
    bus = DesignEventBus()
    q = bus.subscribe("garage")
    bus.publish(DesignEvent(kind="saved", design_id="garage"))
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event.kind == "saved"
    assert event.design_id == "garage"


async def test_bus_filters_by_design_id():
    bus = DesignEventBus()
    qa = bus.subscribe("a")
    qb = bus.subscribe("b")
    bus.publish(DesignEvent(kind="saved", design_id="a"))
    bus.publish(DesignEvent(kind="deleted", design_id="b"))

    ea = await asyncio.wait_for(qa.get(), timeout=1.0)
    eb = await asyncio.wait_for(qb.get(), timeout=1.0)
    assert ea.kind == "saved" and ea.design_id == "a"
    assert eb.kind == "deleted" and eb.design_id == "b"
    assert qa.empty() and qb.empty()


async def test_bus_fans_out_to_multiple_subscribers():
    bus = DesignEventBus()
    q1 = bus.subscribe("d")
    q2 = bus.subscribe("d")
    bus.publish(DesignEvent(kind="saved", design_id="d"))

    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert e1.design_id == "d"
    assert e2.design_id == "d"


async def test_bus_unsubscribe_stops_delivery():
    bus = DesignEventBus()
    q = bus.subscribe("d")
    bus.unsubscribe("d", q)
    assert bus.subscriber_count("d") == 0
    bus.publish(DesignEvent(kind="saved", design_id="d"))
    # Nothing in the queue -- the unsubscribe took effect.
    assert q.empty()


async def test_bus_unsubscribe_unknown_id_is_noop():
    bus = DesignEventBus()
    bus.unsubscribe("never-subscribed", asyncio.Queue())  # must not raise


# ---------------------------------------------------------------------------
# EventEmittingDesignStore
# ---------------------------------------------------------------------------


def _seed_design(design_id: str = "test-bench") -> dict:
    return {
        "schema_version": "0.1",
        "id": design_id,
        "name": "Test Bench",
        "board": {"library_id": "esp32-devkitc-v4", "mcu": "esp32", "framework": "arduino"},
        "power": {"supply": "usb-5v", "rail_voltage_v": 5.0, "budget_ma": 500},
        "components": [],
        "buses": [],
        "connections": [],
    }


async def test_store_save_publishes_event(tmp_path: Path):
    bus = DesignEventBus()
    store = EventEmittingDesignStore(FileDesignStore(root=tmp_path), bus)
    q = bus.subscribe("test-bench")

    store.save(_seed_design())

    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event.kind == "saved"
    assert event.design_id == "test-bench"


async def test_store_delete_publishes_event_only_when_removed(tmp_path: Path):
    bus = DesignEventBus()
    store = EventEmittingDesignStore(FileDesignStore(root=tmp_path), bus)
    store.save(_seed_design("real-design"))

    q = bus.subscribe("real-design")
    assert store.delete("real-design") is True
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event.kind == "deleted"

    # Deleting an unknown id returns False and must not publish.
    q2 = bus.subscribe("ghost")
    assert store.delete("ghost") is False
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(q2.get(), timeout=0.1)


def test_store_reads_delegate(tmp_path: Path):
    bus = DesignEventBus()
    inner = FileDesignStore(root=tmp_path)
    inner.save(_seed_design("d1"))
    store = EventEmittingDesignStore(inner, bus)
    assert store.exists("d1") is True
    assert store.exists("missing") is False
    assert store.load("d1")["id"] == "d1"
    assert [s.id for s in store.list()] == ["d1"]


