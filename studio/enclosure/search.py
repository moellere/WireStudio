"""Search clients for community-uploaded 3D enclosure models.

0.8 v2 ships a single source -- Thingiverse (documented API, reachable
with a free key). Printables doesn't expose a public API yet; we leave
a stub source whose `is_configured()` always returns False with a
"deferred" reason, surfaced by the status endpoint so users see the
gap rather than being silently down a hit.

Each source returns a list of `EnclosureHit` records the API can
serialise verbatim. The query is built from the board's display name
plus an optional user-supplied refinement -- e.g., "ESP32 DevKitC
enclosure" -> ranked Thingiverse results.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional, Protocol

import httpx


@dataclass
class EnclosureHit:
    """One row in a search result list."""
    source: str            # thingiverse | printables | ...
    id: str                # source-native id (string for portability)
    title: str
    creator: Optional[str]
    thumbnail_url: Optional[str]
    model_url: str
    likes: Optional[int] = None
    summary: Optional[str] = None


@dataclass
class SourceStatus:
    """Per-source configuration / availability surface."""
    source: str
    available: bool
    reason: Optional[str] = None
    # Free-text note carrying the configuration handle (env var name,
    # etc.) so the UI can guide the user to enable a missing source.
    configure_hint: Optional[str] = None


@dataclass
class SearchResponse:
    query: str
    sources: list[SourceStatus] = field(default_factory=list)
    results: list[EnclosureHit] = field(default_factory=list)


class _Source(Protocol):
    """Each search source implements this minimal surface so the
    aggregator can fan out without caring about per-vendor specifics."""

    name: str

    def status(self) -> SourceStatus: ...
    def search(self, query: str, *, limit: int) -> list[EnclosureHit]: ...


# ---------------------------------------------------------------------------
# Thingiverse
# ---------------------------------------------------------------------------

class ThingiverseSource:
    """Talks to api.thingiverse.com using a Bearer app token.

    Auth: register an app at https://www.thingiverse.com/developers and
    set the resulting token as `THINGIVERSE_API_KEY`. Rate limit is
    ~300 requests/hour for the public tier; we don't cache today,
    on the assumption that searches are infrequent and bursty.
    """

    name = "thingiverse"
    base_url = "https://api.thingiverse.com"

    def __init__(
        self,
        token: Optional[str] = None,
        *,
        timeout: float = 15.0,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        self.token = token if token is not None else os.environ.get("THINGIVERSE_API_KEY", "")
        self.timeout = timeout
        self._transport = transport

    def status(self) -> SourceStatus:
        if not self.token:
            return SourceStatus(
                source=self.name,
                available=False,
                reason="THINGIVERSE_API_KEY not set",
                configure_hint="Register an app at https://www.thingiverse.com/developers and export THINGIVERSE_API_KEY=<token>",
            )
        return SourceStatus(source=self.name, available=True)

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            },
            transport=self._transport,
        )

    def search(self, query: str, *, limit: int = 20) -> list[EnclosureHit]:
        if not self.token:
            return []
        with self._client() as c:
            resp = c.get(
                "/search",
                params={"q": query, "type": "things", "per_page": str(limit)},
            )
        if resp.status_code != 200:
            return []
        body = resp.json()
        # Thingiverse wraps results in `hits` (newer API) or returns the
        # raw list (older API); accept both shapes.
        items = body.get("hits") if isinstance(body, dict) else body
        if not isinstance(items, list):
            return []
        return [_thingiverse_to_hit(it) for it in items[:limit] if isinstance(it, dict)]


def _thingiverse_to_hit(it: dict) -> EnclosureHit:
    creator = it.get("creator") or {}
    if isinstance(creator, dict):
        creator_name = creator.get("name") or creator.get("first_name")
    else:
        creator_name = None
    return EnclosureHit(
        source="thingiverse",
        id=str(it.get("id") or it.get("public_url") or ""),
        title=str(it.get("name") or "untitled"),
        creator=creator_name,
        thumbnail_url=it.get("thumbnail") or it.get("preview_image"),
        model_url=str(it.get("public_url") or it.get("url") or ""),
        likes=it.get("like_count"),
        summary=it.get("description_html") or it.get("description"),
    )


# ---------------------------------------------------------------------------
# Printables (deferred)
# ---------------------------------------------------------------------------

class PrintablesSource:
    """Stub source: Printables doesn't expose a public REST/GraphQL API
    today, and scraping their internals is fragile. Status is always
    `available=False` with a 'deferred' reason; search returns empty.
    Kept in the source list so the UI surfaces the gap honestly."""

    name = "printables"

    def status(self) -> SourceStatus:
        return SourceStatus(
            source=self.name,
            available=False,
            reason="Printables search deferred -- no public API yet",
            configure_hint=None,
        )

    def search(self, query: str, *, limit: int = 20) -> list[EnclosureHit]:
        return []


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def default_sources() -> list[_Source]:
    return [ThingiverseSource(), PrintablesSource()]


def search_enclosures(
    query: str,
    *,
    sources: Optional[list[_Source]] = None,
    limit: int = 20,
) -> SearchResponse:
    """Run `query` against every configured source and merge the hits.

    Returns the per-source status alongside the merged result list so
    the UI can surface "thingiverse: 12 hits / printables: deferred"
    without a separate round-trip. Per-source failures are absorbed
    silently; the source's status entry already explains why it's not
    contributing hits.
    """
    sources = sources if sources is not None else default_sources()
    statuses: list[SourceStatus] = []
    hits: list[EnclosureHit] = []
    for s in sources:
        statuses.append(s.status())
        try:
            hits.extend(s.search(query, limit=limit))
        except (httpx.HTTPError, ValueError):
            # Failures degrade to "no hits from this source" -- the
            # status entry already carries the user-visible reason
            # for any auth/configuration gap.
            pass
    return SearchResponse(query=query, sources=statuses, results=hits[:limit])


def query_for_board(board_name: str, refinement: Optional[str] = None) -> str:
    """Construct the search string we send to each source. Just `<board>
    enclosure` plus the user's optional extra terms, with whitespace
    collapsed so empty refinements don't tear the query."""
    parts = [board_name.strip(), "enclosure"]
    if refinement and refinement.strip():
        parts.append(refinement.strip())
    return " ".join(p for p in parts if p)
