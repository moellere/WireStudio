"""Bearer-token auth for the REST surface.

Off unless `WIRESTUDIO_API_TOKEN` is set, which keeps the dev loop and
the docker quickstart open as before. Set, every request to the studio
app must carry the token: `Authorization: Bearer <token>` from a client
that can set headers, or the `wirestudio_api_token` cookie for the ones
that cannot (the browser's EventSource on the SSE routes; the web UI
sets the cookie itself once it holds the token). Two paths stay open:
`/health` so a probe needs no secret, and `/mcp`, which carries its own
token. Preflight requests are answered by CORS before they get here.
"""
from __future__ import annotations

import os
import re
import secrets
from http.cookies import SimpleCookie

from starlette.types import ASGIApp, Receive, Scope, Send

API_TOKEN_ENV = "WIRESTUDIO_API_TOKEN"
COOKIE_NAME = "wirestudio_api_token"

_OPEN = re.compile(r"(^|/)(health|mcp)/?$")


def api_token_from_env() -> str:
    return os.environ.get(API_TOKEN_ENV, "").strip()


class ApiTokenMiddleware:
    def __init__(self, app: ASGIApp, *, token: str) -> None:
        if not token:
            raise ValueError("an API token must not be empty")
        self.app = app
        self._token = token

    def _presented(self, scope: Scope) -> str:
        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1", errors="ignore")
        if auth.startswith("Bearer "):
            return auth[len("Bearer "):]
        raw = headers.get(b"cookie", b"").decode("latin-1", errors="ignore")
        if raw:
            jar: SimpleCookie = SimpleCookie()
            try:
                jar.load(raw)
            except Exception:
                return ""
            if COOKIE_NAME in jar:
                return jar[COOKIE_NAME].value
        return ""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") == "OPTIONS" or _OPEN.search(scope.get("path", "")):
            await self.app(scope, receive, send)
            return
        if not secrets.compare_digest(self._presented(scope), self._token):
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"www-authenticate", b'Bearer realm="wirestudio-api"'),
                ],
            })
            await send({"type": "http.response.body", "body": b'{"detail":"missing or invalid API token"}'})
            return
        await self.app(scope, receive, send)
