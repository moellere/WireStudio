# MCP server

Wirestudio exposes its design-editing tool surface over the
[Model Context Protocol](https://modelcontextprotocol.io). Point a host
LLM client (Claude Code, Claude Desktop) at the daemon and the model
drives the studio using *your* Claude subscription — wirestudio spends
no Anthropic credits of its own.

The LLM never sits in a compile or fetch path. MCP is a thin chat
surface over the **design-editing** tools only; the generators stay
pure functions of `design.json` + library. Same design in, same YAML /
ASCII / KiCad out, every time.

## Quick start

End-to-end: start the daemon, copy the token, wire up a client, edit a
design by chatting.

### 1. Start the daemon

```bash
pip install -e .          # from a repo checkout
python -m wirestudio.api  # serves http://127.0.0.1:8765
```

On first start with no token configured, the server generates one and
logs where it landed:

```
INFO  Generated MCP token; copy it from /home/<user>/.config/wirestudio/mcp-token
```

### 2. Copy the token

```bash
cat ~/.config/wirestudio/mcp-token
```

To pin a known value instead of the generated one, set
`WIRESTUDIO_MCP_TOKEN` before starting the daemon — the env var wins
over the file and nothing is written to disk.

### 3. Wire up a client

**Claude Code** — one command:

```bash
claude mcp add wirestudio \
  --transport http \
  http://localhost:8765/mcp \
  --header "Authorization: Bearer <paste-token-here>"
```

Confirm it connected with `claude mcp list`. Inside a Claude Code
session, `/mcp` shows the wirestudio tools and resources.

**Claude Desktop** — add to `claude_desktop_config.json`:

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

Restart Claude Desktop. The wirestudio tools appear in the tool menu.

### 4. Create a design to edit

The design-editing tools operate on a design that already exists in the
store (`designs/<id>.json`). Two ways to get one:

- **Web UI** — open <http://localhost:8765>, build a design, click
  Save. Whichever design you select in the sidebar becomes the
  *active* design (see below).
- **Tools** — ask the client to start one from scratch; it will save a
  design and then edit it.

### 5. Chat

Tell the client what you want:

> Add a BME280 to this design, put it on the I2C bus, then solve pins
> and show me the YAML.

The model calls `add_component`, `add_bus`, `solve_pins`, `render` in
sequence and reports back. Because the design is *active*, you didn't
have to name a `design_id` — see the next section.

## Active design

Every design-editing tool takes an optional `design_id`. When omitted,
it resolves to the **active design** — a single-slot pointer on the
server (single-user homelab; one pointer per process).

Two ways the pointer gets set:

- The web UI mirrors the sidebar selection into it. Click a design in
  the browser and the client can act on it immediately — "add a relay
  to this design" just works.
- The `set_active_design` tool sets it from the chat side. Useful when
  you're driving entirely from the client with no browser open.

`get_active_design` reads the current value. Deleting the active design
clears the pointer, so a later default-resolved call returns a clean
`ok: false` rather than a 500. If neither a `design_id` argument nor an
active design is set, design-bound tools return:

```json
{"ok": false, "error": "design_id was not provided and no active design is set. ..."}
```

## Endpoint and transport

`POST /mcp` on the wirestudio HTTP API — Streamable HTTP transport (the
modern single-endpoint MCP HTTP transport), mounted into the same
FastAPI app as `/library/*`, `/design/*`, etc. No subprocess, no second
process racing the daemon over the JSON files.

In the production Docker image the API is mounted under `/api`, so the
MCP endpoint is **`/api/mcp`** there. The dev server
(`python -m wirestudio.api` with no `--static-dir`) serves it at
`/mcp`.

## Auth

Bearer token, always required on the MCP endpoint. Resolution order:

1. `WIRESTUDIO_MCP_TOKEN` env var.
2. Persisted file `~/.config/wirestudio/mcp-token` (override the path
   with `WIRESTUDIO_MCP_TOKEN_PATH`).
3. Auto-generated on first start, persisted with mode 0600, path logged
   at INFO.

The token gates `/mcp` only. The rest of the API (`/design/*`,
`/agent/*`, `/library/*`) keeps its existing unauthenticated,
CORS-gated, rate-limited model — hardening those is a separate effort.
The header comparison uses `secrets.compare_digest`, so a bad token
can't be brute-forced by timing.

## Remote deployment

For a homelab deployment behind a real hostname, swap the URL for
`https://wirestudio.your.domain/api/mcp` and clear two hurdles:

**DNS-rebinding allowlist.** The `mcp` SDK ships a DNS-rebinding
mitigation that defaults to loopback hostnames. Allow your hostname:

```
WIRESTUDIO_MCP_ALLOWED_HOSTS=wirestudio.example.com:443,wirestudio.example.com
```

**Token distribution.** Operators on k8s set `WIRESTUDIO_MCP_TOKEN`
from a Secret; the token-file path is then ignored. The daemon binds to
whatever uvicorn is configured for (`--host`); there's no separate MCP
bind flag.

## Tools

The same 12 tools the embedded `/agent/turn` flow uses, plus the two
active-design tools. Mutating tools load the design, apply the change,
and persist back to `designs/<id>.json`.

| Tool | Mutates | Notes |
|------|---------|-------|
| `search_components` | no | fuzzy library lookup by name/category/use_case/alias |
| `list_boards` | no | every board with mcu / framework / platformio_board |
| `recommend` | no | ranked capability search with rationale + constraints |
| `render` | no | YAML + ASCII for a stored design |
| `validate` | no | schema + library check |
| `set_board` | yes | replace `design.board` (does not retarget pins) |
| `add_component` | yes | append a component instance |
| `remove_component` | yes | drop component + its originating connections |
| `set_param` | yes | per-instance param set (`value: null` deletes) |
| `set_connection` | yes | retarget a single connection |
| `add_bus` | yes | append an i2c / spi / uart / 1wire / i2s bus |
| `solve_pins` | yes | auto-assign unbound connections |
| `set_active_design` | — | set the active-design pointer (validates the id exists) |
| `get_active_design` | — | read the active-design pointer |

Every design-bound tool accepts an optional `design_id`; omit it to use
the active design.

## Resources

Seven read-only resources. Compact indexes for discovery, `{id}`
templates for full detail — so the model pulls the heavy library entry
only for the part it actually needs.

| Resource | Content |
|----------|---------|
| `library://components` | compact index: id, name, category, use_cases, aliases |
| `library://components/{id}` | full entry: pins, ESPHome template, params, KiCad symbol |
| `library://boards` | compact index: id, mcu, chip_variant, framework, platformio_board |
| `library://boards/{id}` | full entry: rails, per-pin GPIO caps, default buses |
| `design://{id}/json` | the raw `design.json` |
| `design://{id}/yaml` | rendered ESPHome YAML (re-rendered on every read) |
| `design://{id}/ascii` | ASCII pinout diagram |

In Claude Desktop / Claude Code these surface as attachable references
(e.g. `@library://components/bme280`).

## Disable

`WIRESTUDIO_MCP_ENABLED=false` skips MCP wiring entirely — used by the
`esphome-config` CI run, where the server's lifespan would add startup
latency for nothing.

## Upgrade path

OAuth 2.1 (the MCP spec's multi-user auth flow) is deferred — the right
shape for a SaaS-grade hosted MCP, the wrong shape for a single-operator
homelab tool. Revisit if/when wirestudio grows multi-user.
