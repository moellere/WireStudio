"""MCP (Model Context Protocol) server for wirestudio.

Exposes the agent's design-editing tool surface (`wirestudio/agent/tools.py`)
as MCP tools so a host LLM client (Claude Desktop, Claude Code) can drive
the studio without burning the user's Anthropic credits. The server mounts
into the existing FastAPI app at `/mcp` over the Streamable HTTP transport.
"""
from wirestudio.mcp.auth import (
    DEFAULT_TOKEN_PATH,
    BearerTokenMiddleware,
    TokenManagedError,
    TokenStore,
    load_token_store,
    resolve_token,
)
from wirestudio.mcp.server import build_mcp_server

__all__ = [
    "BearerTokenMiddleware",
    "DEFAULT_TOKEN_PATH",
    "TokenManagedError",
    "TokenStore",
    "build_mcp_server",
    "load_token_store",
    "resolve_token",
]
