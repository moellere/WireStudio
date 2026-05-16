"""HTTP client for a JLCPCB parts search API.

Defaults to the community-hosted `jlcsearch.tscircuit.com` service, which
indexes JLCPCB's SMT assembly catalog (LCSC part id, stock, price,
basic/preferred tier). Point `WIRESTUDIO_JLCPCB_API` at a self-hosted
mirror to override.

No part data is vendored -- the studio queries at BOM-check time only,
and the feature degrades cleanly (`JlcpcbUnavailable`) when the API
can't be reached. BOM checking is never in a generate/compile path.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

DEFAULT_API = "https://jlcsearch.tscircuit.com"
_TIMEOUT = 12.0


class JlcpcbUnavailable(RuntimeError):
    """The JLCPCB search API could not be reached or returned bad data."""


@dataclass
class JlcpcbPart:
    lcsc: str  # LCSC part id, e.g. "C92489"
    mfr: str
    package: str
    description: str
    stock: int
    price: float | None
    basic: bool
    preferred: bool

    @classmethod
    def from_api(cls, d: dict) -> "JlcpcbPart":
        lcsc = d.get("lcsc")
        return cls(
            lcsc=f"C{lcsc}" if lcsc is not None else "",
            mfr=str(d.get("mfr") or ""),
            package=str(d.get("package") or ""),
            description=str(d.get("description") or ""),
            stock=int(d.get("stock") or 0),
            price=float(d["price"]) if d.get("price") is not None else None,
            basic=bool(d.get("is_basic")),
            preferred=bool(d.get("is_preferred")),
        )


class JlcpcbClient:
    """Thin sync wrapper over the JLCPCB parts search API.

    Tests inject an `httpx.MockTransport` so CI never hits the network.
    """

    def __init__(self, base_url: str | None = None, *, transport=None) -> None:
        self.base_url = (
            base_url or os.environ.get("WIRESTUDIO_JLCPCB_API") or DEFAULT_API
        ).rstrip("/")
        self._transport = transport

    def search(self, keyword: str, *, limit: int = 8) -> list[JlcpcbPart]:
        """Return up to `limit` parts matching `keyword`, best-ranked first.

        Raises `JlcpcbUnavailable` on any network / HTTP / decode failure.
        """
        try:
            with httpx.Client(timeout=_TIMEOUT, transport=self._transport) as client:
                resp = client.get(
                    f"{self.base_url}/api/search", params={"q": keyword}
                )
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise JlcpcbUnavailable(f"JLCPCB search failed: {exc}") from exc
        components = data.get("components") if isinstance(data, dict) else None
        parts = [JlcpcbPart.from_api(c) for c in (components or [])]
        return parts[:limit]


def jlcpcb_status(client: JlcpcbClient | None = None) -> dict:
    """Probe the JLCPCB search API. Shape mirrors the other feature-gate
    status endpoints: `available` is the headline the UI keys off."""
    client = client or JlcpcbClient()
    try:
        client.search("BME280", limit=1)
        return {"available": True, "api_url": client.base_url, "reason": None}
    except JlcpcbUnavailable as exc:
        return {"available": False, "api_url": client.base_url, "reason": str(exc)}
