"""MCP server wrapping the agent's tool surface.

Each tool here is a thin shim over a function in `wirestudio/agent/tools.py`.
Mutating tools take a `design_id` argument, load the design from the store,
call the underlying handler (which mutates the dict in place), and persist
the result back. Read-only library tools skip the store entirely.

Resources expose read-only views over the library and stored designs:
- `library://components` + `library://components/{id}` for the library catalog
- `library://boards` + `library://boards/{id}` for boards
- `design://{id}/{format}` for rendered design output (json / yaml / ascii)

The server is an `MCPServer` instance. The caller is responsible for mounting
its `streamable_http_app()` into the parent FastAPI app and arranging
`session_manager.run()` in the parent's lifespan.
"""
from __future__ import annotations

from dataclasses import asdict

from typing import Any, Callable, Optional

from mcp.server.mcpserver import MCPServer

from wirestudio.agent.tools import (
    _run_add_bus,
    _run_add_component,
    _run_fab_bom,
    _run_fab_cpl,
    _run_fab_status,
    _run_kicad_pcb,
    _run_kicad_schematic,
    _run_component_check,
    _run_component_create,
    _run_component_delete,
    _run_library_detail,
    _run_list_boards,
    _run_recommend,
    _run_remove_component,
    _run_render,
    _run_route_pcb,
    _run_search_components,
    _run_set_board,
    _run_set_connection,
    _run_set_param,
    _run_set_part_override,
    _run_set_strict,
    _run_solve_pins,
    _run_validate,
)
from wirestudio.designs.active import ActiveDesignTracker
from wirestudio.designs.store import DesignStore
from wirestudio.inventory import check_inventory, entries_from_csv
from wirestudio.inventory.buy import buy_list, buy_list_to_dict
from wirestudio.inventory.store import (
    FAMILIES,
    InventoryEntry,
    InventoryStore,
    default_inventory_store,
)
from wirestudio.generate.ascii_gen import render_ascii
from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.library import Library
from wirestudio.model import Design


def build_mcp_server(
    library: Library,
    designs: DesignStore,
    *,
    name: str = "wirestudio",
    active: Optional[ActiveDesignTracker] = None,
    hardware: bool = True,
    inventory: Optional[InventoryStore] = None,
    workbench_factory: Optional[Callable[[], Any]] = None,
    fleet_factory: Optional[Callable[[], Any]] = None,
    dashboard_factory: Optional[Callable[[], Any]] = None,
) -> MCPServer:
    """Build an MCPServer with all wirestudio tools + resources registered.

    `active` is the shared active-design tracker (Phase 1.4). When set,
    design-bound tools default their `design_id` argument to the tracker's
    current value, so "add a BME280 to this design" resolves against
    whatever the browser is showing. A fresh tracker is built if the
    caller doesn't supply one (test-only path -- production wires through
    `create_app`).

    `hardware` registers the workbench / ChirpStack / fleet tools. The
    factories let a caller inject clients; production passes the same ones
    `create_app` uses for the REST routes.
    """
    mcp = MCPServer(name=name)
    tracker = active or ActiveDesignTracker()
    _register_library_tools(mcp, library)
    _register_design_tools(mcp, library, designs, tracker)
    _register_active_tools(mcp, tracker, designs)
    _register_inventory_tools(
        mcp, library, designs, tracker, inventory or default_inventory_store())
    _register_resources(mcp, library, designs)
    if hardware:
        from wirestudio.mcp.hardware import register_hardware_tools
        from wirestudio.mcp.jobs import JobRegistry

        register_hardware_tools(
            mcp, library, designs, tracker, JobRegistry(),
            workbench_factory=workbench_factory,
            fleet_factory=fleet_factory,
            dashboard_factory=dashboard_factory,
        )
    return mcp


def _register_library_tools(mcp: MCPServer, library: Library) -> None:
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

    @mcp.tool(
        name="library_detail",
        description=(
            "Fetch the full library card for one component or board by id: "
            "electrical metadata, params_schema, ESPHome template, KiCad "
            "block, pin definitions. Use after picking an id from the index, "
            "search_components, or recommend. `kind` is 'component' (default) "
            "or 'board'. Read-only."
        ),
    )
    def library_detail(library_id: str, kind: str = "component") -> dict:
        return _run_library_detail({}, library, library_id=library_id, kind=kind)

    @mcp.tool(
        name="component_check",
        description=(
            "Check a draft library component (full YAML text, same shape "
            "as wirestudio/library/components/*.yaml) before saving it: "
            "the file validates, subcircuit nets hang together, the "
            "ESPHome template renders, and -- when KiCad libraries are "
            "installed -- every symbol, pin name and footprint exists. "
            "Returns errors, warnings, what could not be verified here, "
            "and what is never checked (nothing is simulated). Read-only."
        ),
    )
    def component_check(yaml: str) -> dict:
        return _run_component_check({}, library, yaml=yaml)

    @mcp.tool(
        name="component_create",
        description=(
            "Run component_check and, if it passes, save the YAML into "
            "the user library so the component can be added to designs. "
            "Refuses a bundled id; refuses an existing user id unless "
            "overwrite is true. Relay the warnings and not_checked list: "
            "this proves the file is well-formed and its parts exist, "
            "not that the circuit works."
        ),
    )
    def component_create(yaml: str, overwrite: bool = False) -> dict:
        return _run_component_create({}, library, yaml=yaml, overwrite=overwrite)

    @mcp.tool(
        name="component_delete",
        description=(
            "Remove a component from the user library. Refuses a bundled "
            "id. Designs that reference the id stop rendering until it is "
            "recreated."
        ),
    )
    def component_delete(library_id: str) -> dict:
        return _run_component_delete({}, library, library_id=library_id)


_DESIGN_ID_HINT = (
    " Pass `design_id` explicitly to target a specific design; omit it "
    "to default to the active design set via `set_active_design` (or by "
    "the browser when the user selects a design)."
)

_NO_DESIGN_ERROR = {
    "ok": False,
    "error": (
        "design_id was not provided and no active design is set. "
        "Either pass design_id explicitly or call set_active_design first."
    ),
}


def _register_design_tools(
    mcp: MCPServer, library: Library, designs: DesignStore,
    active: ActiveDesignTracker,
) -> None:
    def _resolve(design_id: Optional[str]) -> Optional[str]:
        return design_id or active.get()

    def _load(design_id: Optional[str]) -> tuple[Optional[str], Optional[dict]]:
        rid = _resolve(design_id)
        if not rid:
            return None, None
        return rid, designs.load(rid)

    def _save(design_id: str, design: dict) -> None:
        designs.save(design, design_id=design_id)

    @mcp.tool(
        name="render",
        description=(
            "Render the named design to ESPHome YAML + ASCII diagram. "
            "Returns both as strings. Read-only." + _DESIGN_ID_HINT
        ),
    )
    def render(design_id: Optional[str] = None) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        return _run_render(design, library)

    @mcp.tool(
        name="validate",
        description=(
            "Validate the named design against the JSON schema and library. "
            "Returns ok=true plus a summary, or ok=false with the failing "
            "field path + message. Read-only." + _DESIGN_ID_HINT
        ),
    )
    def validate(design_id: Optional[str] = None) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        return _run_validate(design, library)

    @mcp.tool(
        name="set_board",
        description=(
            "Replace the design's board. Looks up the library board by id "
            "and updates `design.board.{library_id, mcu, framework}`. Does "
            "NOT translate existing pin references." + _DESIGN_ID_HINT
        ),
    )
    def set_board(library_id: str, design_id: Optional[str] = None) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        result = _run_set_board(design, library, library_id=library_id)
        _save(rid, design)
        return result

    @mcp.tool(
        name="add_component",
        description=(
            "Add a component instance to the design. Auto-generates a "
            "unique instance_id (or use `instance_id_hint`), sets `label` "
            "(default = library component name), copies any provided "
            "`params`. Returns the new instance_id." + _DESIGN_ID_HINT
        ),
    )
    def add_component(
        library_id: str,
        label: Optional[str] = None,
        instance_id_hint: Optional[str] = None,
        params: Optional[dict] = None,
        design_id: Optional[str] = None,
    ) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        result = _run_add_component(
            design,
            library,
            library_id=library_id,
            label=label,
            instance_id_hint=instance_id_hint,
            params=params,
        )
        _save(rid, design)
        return result

    @mcp.tool(
        name="remove_component",
        description=(
            "Remove a component instance and all connections originating "
            "from it. Connections that target it via expander_id are left "
            "as orphans." + _DESIGN_ID_HINT
        ),
    )
    def remove_component(instance_id: str, design_id: Optional[str] = None) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        result = _run_remove_component(design, library, instance_id=instance_id)
        _save(rid, design)
        return result

    @mcp.tool(
        name="set_param",
        description=(
            "Set a single param on a component instance. Pass `value: null` "
            "to delete the param entirely." + _DESIGN_ID_HINT
        ),
    )
    def set_param(
        instance_id: str,
        key: str,
        value: Any = None,
        design_id: Optional[str] = None,
    ) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        result = _run_set_param(
            design, library, instance_id=instance_id, key=key, value=value
        )
        _save(rid, design)
        return result

    @mcp.tool(
        name="set_part_override",
        description=(
            "Accept a drawer substitution for one subcircuit part: set "
            "part_overrides['<component id>.<part id>'] to an MPN so the "
            "BOM, CPL and schematic print that part instead of the "
            "library's. Only the value changes; symbol and footprint "
            "stay, so the substitute must be the same package. Use the "
            "`keys` and `substitutes` an inventory_check line reports; "
            "validate then records the substitution with its caveats. "
            "Pass an empty mpn to remove." + _DESIGN_ID_HINT
        ),
    )
    def set_part_override(
        key: str, mpn: str = "", design_id: Optional[str] = None,
    ) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        result = _run_set_part_override(design, library, key=key, mpn=mpn)
        if result.get("ok"):
            _save(rid, design)
        return result

    @mcp.tool(
        name="set_connection",
        description=(
            "Set the target of a single connection identified by "
            "component_id + pin_role. The `target` shape mirrors the "
            "design.json schema: rail, gpio, bus, or expander_pin."
            + _DESIGN_ID_HINT
        ),
    )
    def set_connection(
        component_id: str,
        pin_role: str,
        target: dict,
        design_id: Optional[str] = None,
    ) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        result = _run_set_connection(
            design,
            library,
            component_id=component_id,
            pin_role=pin_role,
            target=target,
        )
        _save(rid, design)
        return result

    @mcp.tool(
        name="set_strict",
        description=(
            "Toggle the design's strict mode. When enabled, render and "
            "validate refuse a design with warn/error compatibility entries "
            "or design warnings; permissive (default) always generates. "
            "Persists on the design." + _DESIGN_ID_HINT
        ),
    )
    def set_strict(enabled: bool, design_id: Optional[str] = None) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        result = _run_set_strict(design, library, enabled=enabled)
        _save(rid, design)
        return result

    @mcp.tool(
        name="add_bus",
        description=(
            "Add a bus to the design. `type` must be one of i2c / spi / "
            "uart / 1wire / i2s. Other fields depend on type: i2c needs "
            "sda + scl, spi needs clk + miso? + mosi?, uart needs rx + tx "
            "+ baud_rate, i2s needs lrclk + bclk." + _DESIGN_ID_HINT
        ),
    )
    def add_bus(
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
        design_id: Optional[str] = None,
    ) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
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
        _save(rid, design)
        return result

    @mcp.tool(
        name="solve_pins",
        description=(
            "Auto-assign every unbound connection. Doesn't reassign "
            "already-bound pins. Returns the count of assignments made, "
            "any unresolved connections, and any conflict / current-budget "
            "warnings the solver detected. Mutates the design."
            + _DESIGN_ID_HINT
        ),
    )
    def solve_pins(design_id: Optional[str] = None) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        result = _run_solve_pins(design, library)
        _save(rid, design)
        return result

    @mcp.tool(
        name="kicad_schematic",
        description=(
            "Emit the named design's KiCad schematic as a SKiDL Python script. "
            "Read-only." + _DESIGN_ID_HINT
        ),
    )
    def kicad_schematic(design_id: Optional[str] = None) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        return _run_kicad_schematic(design, library)

    @mcp.tool(
        name="kicad_pcb",
        description=(
            "Emit the named design's KiCad .kicad_pcb and return a summary "
            "(size, footprints, nets, routed). The actual board file is "
            "downloaded via POST /design/kicad/pcb. Needs the KiCad libraries "
            "on the server. Read-only." + _DESIGN_ID_HINT
        ),
    )
    def kicad_pcb(design_id: Optional[str] = None) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        return _run_kicad_pcb(design, library)

    @mcp.tool(
        name="route_pcb",
        description=(
            "Autoroute the named design's .kicad_pcb with Freerouting and "
            "return a summary (routed, segments, vias, cache_key). The routed "
            "board file is downloaded via GET /design/kicad/route/{cache_key}. "
            "Cached, so re-routing an unchanged design is instant; a fresh "
            "route can take a minute or two. Needs the route toolchain on the "
            "server. Read-only." + _DESIGN_ID_HINT
        ),
    )
    def route_pcb(design_id: Optional[str] = None) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        return _run_route_pcb(design, library)

    @mcp.tool(
        name="fab_status",
        description=(
            "What fab outputs the server can produce: BOM always; CPL needs "
            "the footprint libraries; Gerbers need kicad-cli; routed Gerbers "
            "also need the Freerouting toolchain. Read-only."
        ),
    )
    def fab_status_tool() -> dict:
        return _run_fab_status({}, library)

    @mcp.tool(
        name="fab_bom",
        description=(
            "Emit the named design's JLCPCB BOM (CSV, grouped by part). "
            "Read-only." + _DESIGN_ID_HINT
        ),
    )
    def fab_bom(design_id: Optional[str] = None) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        return _run_fab_bom(design, library)

    @mcp.tool(
        name="fab_cpl",
        description=(
            "Emit the named design's JLCPCB CPL (pick-and-place, CSV). "
            "Positions match the .kicad_pcb. Needs the footprint libraries. "
            "Read-only." + _DESIGN_ID_HINT
        ),
    )
    def fab_cpl(design_id: Optional[str] = None) -> dict:
        rid, design = _load(design_id)
        if design is None:
            return _NO_DESIGN_ERROR
        return _run_fab_cpl(design, library)


def _register_inventory_tools(
    mcp: MCPServer,
    library: Library,
    designs: DesignStore,
    tracker: ActiveDesignTracker,
    inventory: InventoryStore,
) -> None:
    """The parts drawer over MCP.

    The REST inventory routes sit behind SSO in production, so these are
    the only way a headless client gets a drawer into the studio.
    """

    def _wire(e: InventoryEntry) -> dict:
        return {k: v for k, v in {
            "key": e.key, "label": e.label, "kind": e.kind,
            "library_id": e.library_id, "mpn": e.mpn,
            "quantity": e.quantity, "min_quantity": e.min_quantity,
            "low_stock": e.low_stock, "location": e.location, "note": e.note,
            "family": e.family, "polarity": e.polarity, "package": e.package,
            "pinout": e.pinout, "value": e.value,
            "v_max": e.v_max, "i_max": e.i_max,
        }.items() if v not in ("", None)}

    @mcp.tool(
        name="inventory_list",
        description=(
            "List what is physically on hand. Entries are library "
            "components/modules (keyed by library_id) or discrete parts "
            "with no library file -- transistors, passives, regulators -- "
            "keyed 'part:<mpn>'. Filter with kind='part' to see only the "
            "drawer. Check here before designing a circuit from discretes."
        ),
    )
    def inventory_list(kind: str = "") -> dict:
        entries = inventory.list()
        if kind:
            entries = [e for e in entries if e.kind == kind]
        return {"count": len(entries), "entries": [_wire(e) for e in entries]}

    @mcp.tool(
        name="inventory_set",
        description=(
            "Add or update one inventory entry. Pass mpn for a discrete "
            "part (kind defaults to 'part'), or library_id for a library "
            f"component/module. Families: {', '.join(FAMILIES)}. v_max / "
            "i_max are magnitudes in volts / amps; polarity carries the "
            "sign ('pnp', 'p')."
        ),
    )
    def inventory_set(
        mpn: str = "",
        library_id: str = "",
        kind: str = "",
        quantity: int = 0,
        min_quantity: int = 0,
        location: str = "",
        note: str = "",
        family: str = "",
        polarity: str = "",
        package: str = "",
        pinout: str = "",
        value: str = "",
        v_max: Optional[float] = None,
        i_max: Optional[float] = None,
    ) -> dict:
        resolved = kind or ("part" if mpn else "component")
        if resolved != "part":
            try:
                (library.module if resolved == "module" else library.component)(
                    library_id)
            except FileNotFoundError:
                return {"error": f"no {resolved} with library id {library_id!r}"}
        try:
            entry = InventoryEntry(
                library_id=library_id if resolved != "part" else "",
                mpn=mpn if resolved == "part" else "",
                kind=resolved, quantity=quantity, min_quantity=min_quantity,
                location=location, note=note, family=family, polarity=polarity,
                package=package, pinout=pinout, value=value,
                v_max=v_max, i_max=i_max,
            )
        except ValueError as e:
            return {"error": str(e)}
        return {"entry": _wire(inventory.set(entry))}

    @mcp.tool(
        name="inventory_import",
        description=(
            "Bulk-load inventory from spreadsheet CSV text. Finds the "
            "header wherever it starts and maps common column names "
            "(Part, Family, Polarity, Qty, Package, Pinout, Kit "
            "Locations, Notes). Rows it cannot use come back in "
            "'rejected' with a reason -- nothing is dropped silently."
        ),
    )
    def inventory_import(csv: str) -> dict:
        result = entries_from_csv(csv)
        rejected = [
            {"row": r.row, "reason": r.reason, "raw": r.raw}
            for r in result.rejected
        ]
        imported = updated = 0
        for entry in result.entries:
            if entry.kind != "part":
                try:
                    (library.module if entry.kind == "module"
                     else library.component)(entry.library_id)
                except FileNotFoundError:
                    rejected.append({
                        "row": 0,
                        "reason": f"no {entry.kind} with library id "
                                  f"{entry.library_id!r}",
                        "raw": {"library_id": entry.library_id},
                    })
                    continue
            if inventory.get(entry.key) is not None:
                updated += 1
            else:
                imported += 1
            inventory.set(entry)
        return {"imported": imported, "updated": updated,
                "rejected": rejected, "header_row": result.header_row}

    @mcp.tool(
        name="inventory_check",
        description=(
            "Cross-check a design's BOM against what is on hand. "
            "'lines' covers library components and modules; 'parts' "
            "covers the discrete parts a subcircuit component expands "
            "into plus the design's passives, matched by MPN for "
            "semiconductors and by magnitude for passives. A part lands "
            "as 'have', 'partial', 'need', 'assumed' (a common passive "
            "value nobody inventories) or 'untracked'. A 'need' or "
            "'partial' semiconductor carries 'substitutes': drawer parts "
            "of the same family, polarity and package whose ratings "
            "clear what the circuit asks. These are proposals with "
            "explicit caveats, not verdicts; relay the caveats. "
            "'pick_list' groups everything to pull by drawer location, "
            "then unlocated stock, assumed common values, and what is "
            "missing. Defaults to the active design."
        ),
    )
    def inventory_check(design_id: str = "") -> dict:
        resolved = design_id or tracker.get()
        if not resolved:
            return {"error": "no design_id given and no active design"}
        try:
            raw = designs.load(resolved)
        except FileNotFoundError as e:
            return {"error": str(e)}
        report = check_inventory(
            Design.model_validate(raw), library, inventory.list())
        return {
            "design_id": report.design_id,
            "summary": report.summary,
            "lines": [
                {"library_id": ln.library_id, "kind": ln.kind, "name": ln.name,
                 "needed": ln.needed, "on_hand": ln.on_hand,
                 "status": ln.status, "location": ln.location}
                for ln in report.lines
            ],
            "parts_summary": report.parts_summary,
            "parts": [
                {"value": ln.value, "family": ln.family, "refs": ln.refs,
                 "needed": ln.needed, "on_hand": ln.on_hand,
                 "status": ln.status, "matched": ln.matched,
                 "location": ln.location, "keys": ln.keys,
                 "substituted_for": ln.substituted_for,
                 "substitutes": [asdict(sub) for sub in ln.substitutes]}
                for ln in report.parts
            ],
            "pick_list": [asdict(g) for g in report.pick_list],
        }


    @mcp.tool(
        name="buy_list",
        description=(
            "What the drawer is short for a design, priced on JLCPCB: "
            "the inventory check's need/partial lines (components by "
            "library id, semiconductors by MPN, passives by value and "
            "family) each with the best JLCPCB match, LCSC id, stock and "
            "price, or 'not_found'. Common passives the check assumes on "
            "hand are not listed. With the parts API down the shortfalls "
            "still come back, marked available=false. Defaults to the "
            "active design."
        ),
    )
    def buy_list_tool(design_id: str = "") -> dict:
        resolved = design_id or tracker.get()
        if not resolved:
            return {"error": "no design_id given and no active design"}
        try:
            raw = designs.load(resolved)
        except FileNotFoundError as e:
            return {"error": str(e)}
        return buy_list_to_dict(
            buy_list(Design.model_validate(raw), library, inventory.list()))


def _register_active_tools(
    mcp: MCPServer, active: ActiveDesignTracker, designs: DesignStore
) -> None:
    @mcp.tool(
        name="set_active_design",
        description=(
            "Set the active design id. Subsequent design-editing tools "
            "(render, validate, add_component, etc.) default their "
            "`design_id` to this value when not supplied, so a user "
            "prompt like 'add a BME280 to this design' resolves without "
            "an explicit id. Pass an empty string to clear. Validates "
            "the id exists in the store; returns ok=false otherwise so "
            "the model knows to create or save a design first."
        ),
    )
    def set_active_design(design_id: str) -> dict:
        if not design_id:
            active.clear()
            return {"ok": True, "active_design_id": None}
        if not designs.exists(design_id):
            return {
                "ok": False,
                "error": f"no design with id {design_id!r}; save it first",
            }
        active.set(design_id)
        return {"ok": True, "active_design_id": design_id}

    @mcp.tool(
        name="get_active_design",
        description=(
            "Read the current active design id. Returns "
            "{active_design_id: string | null}."
        ),
    )
    def get_active_design() -> dict:
        return {"active_design_id": active.get()}


def _register_resources(mcp: MCPServer, library: Library, designs: DesignStore) -> None:
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
