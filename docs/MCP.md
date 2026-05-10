# MCP server (Phase 1.1 skeleton)

Wirestudio exposes its design-editing tool surface over the
[Model Context Protocol](https://modelcontextprotocol.io). Point a host
LLM client (Claude Desktop, Claude Code) at the daemon and the model
drives the studio without burning your Anthropic credits.

This page covers the day-1 skeleton. Phase 1.2-1.5 (live design-changed
SSE channel, MCP resources, set_active_design tool, polished walkthrough)
land in follow-on PRs.

## Endpoint

`POST /mcp` on the wirestudio HTTP API. Streamable HTTP transport, mounted
into the same FastAPI app as `/library/*`, `/design/*`, etc.

## Auth

Bearer token, always required. Resolution order:

1. `WIRESTUDIO_MCP_TOKEN` env var.
2. Persisted file at `~/.config/wirestudio/mcp-token` (override path with
   `WIRESTUDIO_MCP_TOKEN_PATH`).
3. Auto-generated on first start, persisted with mode 0600. Logged at
   INFO so an operator can copy the value: `Generated MCP token; copy
   it from /home/<user>/.config/wirestudio/mcp-token`.

## Claude Desktop config

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "wirestudio": {
      "url": "http://localhost:8765/mcp",
      "headers": { "Authorization": "Bearer <paste-token-here>" }
    }
  }
}
```

For a remote homelab deployment, swap the URL for
`https://wirestudio.your.domain/mcp`.

## DNS-rebinding allowlist

The `mcp` SDK ships with a DNS-rebinding mitigation that defaults to
loopback hostnames. To run wirestudio behind a real hostname, set:

```
WIRESTUDIO_MCP_ALLOWED_HOSTS=wirestudio.example.com:443,wirestudio.example.com
```

## Tools (Phase 1.1)

Same 12 tools the embedded `/agent/turn` flow uses. Mutating tools take
a `design_id` argument and operate on the persisted design at
`designs/<id>.json`:

| Tool | Mutates | Notes |
|------|---------|-------|
| `search_components` | no | library lookup |
| `list_boards` | no | library lookup |
| `recommend` | no | ranked capability search |
| `render` | no | YAML + ASCII for a stored design |
| `validate` | no | schema + library check |
| `set_board` | yes | replace `design.board` |
| `add_component` | yes | append a component |
| `remove_component` | yes | drop component + originating connections |
| `set_param` | yes | per-instance param set/delete |
| `set_connection` | yes | retarget a single connection |
| `add_bus` | yes | append a bus |
| `solve_pins` | yes | auto-assign unbound connections |

`design_id` defaults will land in Phase 1.4 (`set_active_design` tool +
browser cookie); until then, every design-bound tool needs an explicit
`design_id` and the design must already exist on disk (create one via
the web UI's save flow first).

## Disable

`WIRESTUDIO_MCP_ENABLED=false` skips MCP wiring entirely (e.g. for the
`esphome-config` CI run, where the server's lifespan would add startup
latency for nothing).

## Upgrade path

OAuth 2.1 (the MCP spec's multi-user auth flow) is deferred. Right shape
for SaaS-grade hosted MCPs; wrong shape for a single-operator homelab.
Revisit if/when wirestudio grows multi-user.
