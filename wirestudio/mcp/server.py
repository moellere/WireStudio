"""MCP server wrapping the agent's tool surface.

Each tool here is a thin shim over a function in `wirestudio/agent/tools.py`.
Mutating tools take a `design_id` argument, load the design from the store,
call the underlying handler (which mutates the dict in place), and persist
the result back. Read-only library tools skip the store entirely.

Resources expose read-only views over the library and stored designs:
- `library://components` + `library://components/{id}` for the library catalog
- `library://boards` + `library://boards/{id}` for boards
- `design://{id}/{format}` for rendered design output (json / yaml / ascii)

The server is a `FastMCP` instance. The caller is responsible for mounting
its `streamable_http_app()` into the parent FastAPI app and arranging
`session_manager.run()` in the parent's lifespan.
"""
from __future__ import annotations

from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from wirestudio.agent.tools import (
    _run_add_bus,
    _run_add_component,
    _run_list_boards,
    _run_recommend,
    _run_remove_component,
    _run_render,
    _run_search_components,
    _run_set_board,
    _run_set_connection,
    _run_set_param,
    _run_solve_pins,
    _run_validate,
)
from wirestudio.designs.store import DesignStore
from wirestudio.generate.ascii_gen import render_ascii
from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.library import Library
from wirestudio.model import Design


def build_mcp_server(
    library: Library,
    designs: DesignStore,
    *,
    name: str = "wirestudio",
) -> FastMCP:
    """Build a FastMCP server with all wirestudio tools + resources registered."""
    mcp = FastMCP(name=name)
    _register_library_tools(mcp, library)
    _register_design_tools(mcp, library, designs)
    _register_resources(mcp, library, designs)
    return mcp


def _register_library_tools(mcp: FastMCP, library: Library) -> None:
    @mcp.tool(
        name="search_components",
        description=(
            "Fuzzy-search the component library by name, category, use_case, "
            "or alias. Returns up to 10 matches with library_id, name, "
            "category, and required ESPHome integrations. Use this before "
            "calling add_component so you never invent a library_id."
        ),
    )
    def search_components(query: str) -> dict:
        return _run_search_components({}, library, query=query)

    @mcp.tool(
        name="list_boards",
        description=(
            "List every board in the library with its mcu, chip_variant, "
            "framework, and platformio_board."
        ),
    )
    def list_boards() -> dict:
        return _run_list_boards({}, library)

    @mcp.tool(
        name="recommend",
        description=(
            "Rank library components against a free-text capability query "
            "(e.g. 'motion detection', 'temperature humidity'). Returns up "
            "to `limit` candidates with their electrical metadata, an "
            "in-examples count, and a one-line rationale per pick. "
            "Read-only -- doesn't add anything to a design. Optionally "
            "pass constraints (voltage, max_current_ma_peak, required_bus, "
            "excluded_categories) to filter before ranking."
        ),
    )
    def recommend(
        query: str,
        limit: int = 10,
        constraints: Optional[dict] = None,
    ) -> dict:
        return _run_recommend(
            {}, library, query=query, limit=limit, constraints=constraints
        )


def _register_design_tools(
    mcp: FastMCP, library: Library, designs: DesignStore
) -> None:
    def _load(design_id: str) -> dict:
        return designs.load(design_id)

    def _save(design_id: str, design: dict) -> None:
        designs.save(design, design_id=design_id)

    @mcp.tool(
        name="render",
        description=(
            "Render the named design to ESPHome YAML + ASCII diagram. "
            "Returns both as strings. Read-only."
        ),
    )
    def render(design_id: str) -> dict:
        return _run_render(_load(design_id), library)

    @mcp.tool(
        name="validate",
        description=(
            "Validate the named design against the JSON schema and library. "
            "Returns ok=true plus a summary, or ok=false with the failing "
            "field path + message. Read-only."
        ),
    )
    def validate(design_id: str) -> dict:
        return _run_validate(_load(design_id), library)

    @mcp.tool(
        name="set_board",
        description=(
            "Replace the design's board. Looks up the library board by id "
            "and updates `design.board.{library_id, mcu, framework}`. Does "
            "NOT translate existing pin references."
        ),
    )
    def set_board(design_id: str, library_id: str) -> dict:
        design = _load(design_id)
        result = _run_set_board(design, library, library_id=library_id)
        _save(design_id, design)
        return result

    @mcp.tool(
        name="add_component",
        description=(
            "Add a component instance to the design. Auto-generates a "
            "unique instance_id (or use `instance_id_hint`), sets `label` "
            "(default = library component name), copies any provided "
            "`params`. Returns the new instance_id."
        ),
    )
    def add_component(
        design_id: str,
        library_id: str,
        label: Optional[str] = None,
        instance_id_hint: Optional[str] = None,
        params: Optional[dict] = None,
    ) -> dict:
        design = _load(design_id)
        result = _run_add_component(
            design,
            library,
            library_id=library_id,
            label=label,
            instance_id_hint=instance_id_hint,
            params=params,
        )
        _save(design_id, design)
        return result

    @mcp.tool(
        name="remove_component",
        description=(
            "Remove a component instance and all connections originating "
            "from it. Connections that target it via expander_id are left "
            "as orphans."
        ),
    )
    def remove_component(design_id: str, instance_id: str) -> dict:
        design = _load(design_id)
        result = _run_remove_component(design, library, instance_id=instance_id)
        _save(design_id, design)
        return result

    @mcp.tool(
        name="set_param",
        description=(
            "Set a single param on a component instance. Pass `value: null` "
            "to delete the param entirely."
        ),
    )
    def set_param(
        design_id: str,
        instance_id: str,
        key: str,
        value: Any = None,
    ) -> dict:
        design = _load(design_id)
        result = _run_set_param(
            design, library, instance_id=instance_id, key=key, value=value
        )
        _save(design_id, design)
        return result

    @mcp.tool(
        name="set_connection",
        description=(
            "Set the target of a single connection identified by "
            "component_id + pin_role. The `target` shape mirrors the "
            "design.json schema: rail, gpio, bus, or expander_pin."
        ),
    )
    def set_connection(
        design_id: str,
        component_id: str,
        pin_role: str,
        target: dict,
    ) -> dict:
        design = _load(design_id)
        result = _run_set_connection(
            design,
            library,
            component_id=component_id,
            pin_role=pin_role,
            target=target,
        )
        _save(design_id, design)
        return result

    @mcp.tool(
        name="add_bus",
        description=(
            "Add a bus to the design. `type` must be one of i2c / spi / "
            "uart / 1wire / i2s. Other fields depend on type: i2c needs "
            "sda + scl, spi needs clk + miso? + mosi?, uart needs rx + tx "
            "+ baud_rate, i2s needs lrclk + bclk."
        ),
    )
    def add_bus(
        design_id: str,
        id: str,
        type: str,
        sda: Optional[str] = None,
        scl: Optional[str] = None,
        frequency_hz: Optional[int] = None,
        miso: Optional[str] = None,
        mosi: Optional[str] = None,
        clk: Optional[str] = None,
        cs: Optional[str] = None,
        rx: Optional[str] = None,
        tx: Optional[str] = None,
        baud_rate: Optional[int] = None,
        lrclk: Optional[str] = None,
        bclk: Optional[str] = None,
    ) -> dict:
        design = _load(design_id)
        fields = {
            "id": id,
            "type": type,
            "sda": sda,
            "scl": scl,
            "frequency_hz": frequency_hz,
            "miso": miso,
            "mosi": mosi,
            "clk": clk,
            "cs": cs,
            "rx": rx,
            "tx": tx,
            "baud_rate": baud_rate,
            "lrclk": lrclk,
            "bclk": bclk,
        }
        result = _run_add_bus(
            design, library, **{k: v for k, v in fields.items() if v is not None}
        )
        _save(design_id, design)
        return result

    @mcp.tool(
        name="solve_pins",
        description=(
            "Auto-assign every unbound connection. Doesn't reassign "
            "already-bound pins. Returns the count of assignments made, "
            "any unresolved connections, and any conflict / current-budget "
            "warnings the solver detected. Mutates the design."
        ),
    )
    def solve_pins(design_id: str) -> dict:
        design = _load(design_id)
        result = _run_solve_pins(design, library)
        _save(design_id, design)
        return result


def _register_resources(mcp: FastMCP, library: Library, designs: DesignStore) -> None:
    """Read-only views of the library and stored designs.

    The library catalog resources serve a dual purpose: they let an LLM
    client pull a compact index without burning tool-call tokens, and
    they're the natural place for a host (Claude Desktop, Claude Code)
    to surface attachable references like `@library://components/bme280`.
    Design resources expose the rendered output (yaml / ascii) so a
    user can drop the current design into chat without copy-paste.
    """

    @mcp.resource(
        "library://components",
        name="components_index",
        title="Library: components index",
        description=(
            "Compact list of every library component (id, name, category, "
            "use_cases, aliases). Pull this first to discover available "
            "parts, then read library://components/{id} for the full "
            "electrical + ESPHome detail of a specific entry."
        ),
        mime_type="application/json",
    )
    def components_index() -> dict:
        return {
            "components": [
                {
                    "id": c.id,
                    "name": c.name,
                    "category": c.category,
                    "use_cases": list(c.use_cases),
                    "aliases": list(c.aliases),
                }
                for c in library.list_components()
            ],
        }

    @mcp.resource(
        "library://components/{component_id}",
        name="component_detail",
        title="Library: component detail",
        description=(
            "Full library entry for one component: electrical pins, ESPHome "
            "Jinja template, params schema, KiCad symbol mapping, current "
            "draw, vcc band. Use this before add_component to learn the "
            "exact pin roles + param keys the part expects."
        ),
        mime_type="application/json",
    )
    def component_detail(component_id: str) -> dict:
        return library.component(component_id).model_dump()

    @mcp.resource(
        "library://boards",
        name="boards_index",
        title="Library: boards index",
        description=(
            "Compact list of every supported board (id, name, mcu, "
            "chip_variant, framework, platformio_board). Pull this to "
            "pick a board target; read library://boards/{id} for pinout, "
            "rails, default_buses."
        ),
        mime_type="application/json",
    )
    def boards_index() -> dict:
        return {
            "boards": [
                {
                    "id": b.id,
                    "name": b.name,
                    "mcu": b.mcu,
                    "chip_variant": b.chip_variant,
                    "framework": b.framework,
                    "platformio_board": b.platformio_board,
                    "flash_size_mb": b.flash_size_mb,
                }
                for b in library.list_boards()
            ],
        }

    @mcp.resource(
        "library://boards/{board_id}",
        name="board_detail",
        title="Library: board detail",
        description=(
            "Full library entry for one board: rails, GPIO capabilities "
            "per-pin, default buses (sda/scl/clk/miso/mosi), enclosure "
            "metadata, KiCad symbol mapping."
        ),
        mime_type="application/json",
    )
    def board_detail(board_id: str) -> dict:
        return library.board(board_id).model_dump()

    @mcp.resource(
        "design://{design_id}/json",
        name="design_json",
        title="Design: raw design.json",
        description=(
            "The on-disk design.json for the named design. Read-only view; "
            "to mutate, use the design-editing tools."
        ),
        mime_type="application/json",
    )
    def design_json(design_id: str) -> dict:
        return designs.load(design_id)

    @mcp.resource(
        "design://{design_id}/yaml",
        name="design_yaml",
        title="Design: rendered ESPHome YAML",
        description=(
            "Current ESPHome YAML for the named design. Refreshes on every "
            "read against the latest stored state, so an MCP write followed "
            "by a re-read shows the new output."
        ),
        mime_type="text/yaml",
    )
    def design_yaml(design_id: str) -> str:
        d = Design.model_validate(designs.load(design_id))
        return render_yaml(d, library)

    @mcp.resource(
        "design://{design_id}/ascii",
        name="design_ascii",
        title="Design: ASCII diagram",
        description=(
            "ASCII pinout diagram for the named design. A compact view of "
            "rails, components, pin assignments, and BOM that fits in a "
            "single chat message."
        ),
        mime_type="text/plain",
    )
    def design_ascii(design_id: str) -> str:
        d = Design.model_validate(designs.load(design_id))
        return render_ascii(d, library)
