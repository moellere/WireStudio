"""Tests for the enclosure search relay (0.8 v2).

Uses httpx.MockTransport to stand in for Thingiverse's HTTP API, the
same pattern test_fleet.py uses for the addon. Three concerns:

  1. The status surface (configured vs missing key vs deferred source).
  2. The Thingiverse client maps the upstream `hits` into our
     EnclosureHit shape, with creator + thumbnail + likes preserved.
  3. The aggregator absorbs per-source failures and still returns the
     statuses so the UI can show partial degradation.
"""
from __future__ import annotations

import json

import httpx
import pytest

from studio.enclosure.search import (
    PrintablesSource,
    SearchResponse,
    ThingiverseSource,
    _thingiverse_to_hit,
    query_for_board,
    search_enclosures,
)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def test_thingiverse_status_unconfigured(monkeypatch):
    monkeypatch.delenv("THINGIVERSE_API_KEY", raising=False)
    s = ThingiverseSource().status()
    assert s.available is False
    assert "THINGIVERSE_API_KEY" in (s.reason or "")
    assert "thingiverse.com/developers" in (s.configure_hint or "")


def test_thingiverse_status_configured():
    s = ThingiverseSource(token="tk-1").status()
    assert s.available is True
    assert s.reason is None


def test_printables_is_always_deferred():
    s = PrintablesSource().status()
    assert s.available is False
    assert "deferred" in (s.reason or "").lower()


# ---------------------------------------------------------------------------
# Thingiverse client
# ---------------------------------------------------------------------------

def _thingiverse_transport(*, status: int = 200, body: dict | list | None = None,
                            expected_query: str | None = None) -> httpx.MockTransport:
    """Build a MockTransport that asserts the request shape and returns
    `body` (defaults to a single-hit response)."""
    payload = body if body is not None else {
        "hits": [{
            "id": 12345,
            "name": "ESP32 DevKitC enclosure",
            "creator": {"name": "joedirt", "first_name": "Joe"},
            "thumbnail": "https://example.com/thumb.jpg",
            "public_url": "https://www.thingiverse.com/thing:12345",
            "like_count": 42,
            "description": "A snug enclosure for the DevKitC.",
        }],
    }

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/search", req.url.path
        assert req.headers.get("authorization") == "Bearer tk-1"
        if expected_query is not None:
            assert req.url.params.get("q") == expected_query, req.url.params
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def test_thingiverse_search_returns_empty_when_unconfigured(monkeypatch):
    monkeypatch.delenv("THINGIVERSE_API_KEY", raising=False)
    s = ThingiverseSource()
    assert s.search("anything", limit=5) == []


def test_thingiverse_search_maps_hits_to_enclosure_hits():
    s = ThingiverseSource(token="tk-1", transport=_thingiverse_transport())
    hits = s.search("ESP32 DevKitC enclosure", limit=5)
    assert len(hits) == 1
    h = hits[0]
    assert h.source == "thingiverse"
    assert h.id == "12345"
    assert h.title == "ESP32 DevKitC enclosure"
    assert h.creator == "joedirt"
    assert h.thumbnail_url == "https://example.com/thumb.jpg"
    assert h.model_url == "https://www.thingiverse.com/thing:12345"
    assert h.likes == 42


def test_thingiverse_search_passes_the_query_through():
    s = ThingiverseSource(
        token="tk-1",
        transport=_thingiverse_transport(expected_query="WeMos D1 Mini enclosure case"),
    )
    s.search("WeMos D1 Mini enclosure case", limit=5)


def test_thingiverse_search_handles_legacy_list_response():
    """Older Thingiverse API revisions return the array directly
    rather than wrapping in `{hits: [...]}`. The client should accept
    both."""
    body = [{
        "id": 7,
        "name": "Legacy",
        "public_url": "https://www.thingiverse.com/thing:7",
    }]
    s = ThingiverseSource(token="tk-1", transport=_thingiverse_transport(body=body))
    hits = s.search("anything", limit=5)
    assert len(hits) == 1
    assert hits[0].id == "7"
    assert hits[0].title == "Legacy"


def test_thingiverse_search_returns_empty_on_http_error():
    """Auth failures, server errors, etc. degrade to no hits rather
    than crashing the dialog."""
    s = ThingiverseSource(
        token="tk-1",
        transport=_thingiverse_transport(status=401, body={"error": "bad token"}),
    )
    assert s.search("anything", limit=5) == []


def test_thingiverse_to_hit_handles_string_creator():
    """If the upstream returns a bare string for creator (some endpoints
    do), we fall through gracefully without raising."""
    h = _thingiverse_to_hit({"id": 1, "name": "x", "creator": "joedirt", "public_url": "u"})
    # Bare-string creator falls into the not-a-dict branch; we end up
    # with creator=None rather than crashing on .get().
    assert h.creator is None


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

class _StubSource:
    def __init__(self, name, hits=None, status_kwargs=None, raises=None):
        self.name = name
        self._hits = hits or []
        self._status_kwargs = status_kwargs or {"available": True}
        self._raises = raises

    def status(self):
        from studio.enclosure.search import SourceStatus
        return SourceStatus(source=self.name, **self._status_kwargs)

    def search(self, query, *, limit):
        if self._raises:
            raise self._raises
        return self._hits[:limit]


def test_aggregator_merges_hits_from_multiple_sources():
    from studio.enclosure.search import EnclosureHit
    a = _StubSource("a", hits=[EnclosureHit("a", "1", "A1", None, None, "u1")])
    b = _StubSource("b", hits=[EnclosureHit("b", "2", "B1", None, None, "u2")])
    out = search_enclosures("q", sources=[a, b], limit=10)
    assert isinstance(out, SearchResponse)
    assert out.query == "q"
    assert {s.source for s in out.sources} == {"a", "b"}
    assert {h.id for h in out.results} == {"1", "2"}


def test_aggregator_caps_at_limit():
    from studio.enclosure.search import EnclosureHit
    a = _StubSource("a", hits=[EnclosureHit("a", str(i), f"A{i}", None, None, "u") for i in range(5)])
    out = search_enclosures("q", sources=[a], limit=3)
    assert len(out.results) == 3


def test_aggregator_swallows_per_source_failures():
    from studio.enclosure.search import EnclosureHit
    bad = _StubSource("bad", raises=httpx.ConnectError("boom"))
    good = _StubSource("good", hits=[EnclosureHit("good", "1", "G1", None, None, "u")])
    out = search_enclosures("q", sources=[bad, good], limit=10)
    # The bad source still appears in statuses; the good one's hit is preserved.
    assert {s.source for s in out.sources} == {"bad", "good"}
    assert [h.id for h in out.results] == ["1"]


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,refinement,expected", [
    ("WeMos D1 Mini", None, "WeMos D1 Mini enclosure"),
    ("ESP32-DevKitC-V4", "battery", "ESP32-DevKitC-V4 enclosure battery"),
    ("Foo", "   ", "Foo enclosure"),  # whitespace-only refinement is stripped
    ("  Foo  ", None, "Foo enclosure"),
])
def test_query_for_board(name, refinement, expected):
    assert query_for_board(name, refinement) == expected


# Unused import guard so test failures point at the right place.
def test_smoke_imports():
    assert json is not None  # quiet the linter
