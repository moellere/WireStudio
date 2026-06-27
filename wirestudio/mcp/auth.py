"""Bearer-token auth for the MCP HTTP endpoint.

Resolution precedence: env var `WIRESTUDIO_MCP_TOKEN` > persisted file
(`~/.config/wirestudio/mcp-token`, mode 0600) > newly generated token
(persisted to the same file). Tokens are 32 raw bytes encoded with
`secrets.token_urlsafe`.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from pathlib import Path

from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_PATH = Path(os.path.expanduser("~/.config/wirestudio/mcp-token"))
ENV_VAR = "WIRESTUDIO_MCP_TOKEN"


class TokenManagedError(RuntimeError):
    """Raised when rotation is attempted on an externally-managed token.

    When the token comes from `WIRESTUDIO_MCP_TOKEN` we can't rewrite it -- the
    operator owns it (k8s Secret / sops). Rotating would only diverge the live
    value from the secret, so we refuse.
    """


def _generate_and_persist(path: Path) -> str:
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    path.chmod(0o600)
    return token


class TokenStore:
    """Holds the live MCP bearer token so rotation takes effect without a restart.

    `BearerTokenMiddleware` reads `.token` on every request rather than
    capturing the value at construction time. `env_managed` is True when the
    token came from the env var, in which case `rotate()` raises.
    """

    def __init__(self, *, token: str, path: Path, env_managed: bool) -> None:
        self._token = token
        self._path = path
        self.env_managed = env_managed

    @property
    def token(self) -> str:
        return self._token

    def rotate(self) -> str:
        if self.env_managed:
            raise TokenManagedError(
                f"token is set via {ENV_VAR}; rotate it by updating that secret, not here"
            )
        self._token = _generate_and_persist(self._path)
        logger.info("Rotated MCP token; persisted to %s", self._path)
        return self._token


def load_token_store(
    *,
    env_var: str = ENV_VAR,
    token_path: Path | None = None,
) -> TokenStore:
    """Resolve the MCP bearer token into a mutable store.

    The env var wins if set (operators using k8s Secrets / sops set this and
    the token-file path is ignored). Otherwise the persisted file is read.
    Otherwise a fresh token is generated, persisted with mode 0600, and the
    path is logged at INFO so the operator knows where to copy it from.
    """
    path = token_path or DEFAULT_TOKEN_PATH

    env_token = os.environ.get(env_var)
    if env_token:
        return TokenStore(token=env_token.strip(), path=path, env_managed=True)

    if path.exists():
        return TokenStore(token=path.read_text().strip(), path=path, env_managed=False)

    token = _generate_and_persist(path)
    logger.info("Generated MCP token; copy it from %s", path)
    return TokenStore(token=token, path=path, env_managed=False)


def resolve_token(
    *,
    env_var: str = ENV_VAR,
    token_path: Path | None = None,
) -> str:
    """Return the current MCP bearer token. See `load_token_store`."""
    return load_token_store(env_var=env_var, token_path=token_path).token


class BearerTokenMiddleware:
    """ASGI middleware that 401s requests under `path_prefix` lacking a matching bearer token.

    Compares the `Authorization: Bearer <token>` header against the configured
    token using `secrets.compare_digest` so a malicious client can't use timing
    to brute-force the token. Requests outside `path_prefix` (e.g. the SPA's
    `/`, `/favicon.ico`, `/library/...`) pass through untouched -- the token
    only gates the MCP endpoint, not the rest of the API.
    """

    def __init__(self, app: ASGIApp, *, store: TokenStore, path_prefix: str = "/mcp") -> None:
        self.app = app
        self._store = store
        # Regex match: prefix as a path component (preceded by "/" or start,
        # followed by "/" or end). We can't compare scope[path] literally
        # because Starlette's nested Mount('/') doesn't strip path
        # consistently -- in the prod-mode wrapper studio_app's mount of
        # mcp_app at "/" leaves path as "/api/mcp" rather than "/mcp" by
        # the time the inner middleware runs. Suffix-as-component match
        # works for both bare ("/mcp") and wrapped ("/api/mcp") deployments.
        slug = path_prefix.strip("/")
        if not slug:
            raise ValueError(f"path_prefix must contain at least one path segment: {path_prefix!r}")
        self._path_re = re.compile(rf"(^|/){re.escape(slug)}(/|$)")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not self._path_re.search(path):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        auth = headers.get(b"authorization", b"").decode("latin-1", errors="ignore")
        prefix = "Bearer "
        if not auth.startswith(prefix) or not secrets.compare_digest(
            auth[len(prefix):], self._store.token
        ):
            await _send_401(send)
            return
        await self.app(scope, receive, send)


async def _send_401(send: Send) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b'Bearer realm="wirestudio-mcp"'),
            ],
        }
    )
    await send(
        {
            "type": "http.response.body",
            "body": b'{"error":"missing or invalid bearer token"}',
        }
    )
