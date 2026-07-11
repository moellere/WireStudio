from __future__ import annotations

import asyncio
import json
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import os
from pydantic import ValidationError

from wirestudio.mcp import (
    BearerTokenMiddleware,
    TokenManagedError,
    build_mcp_server,
    load_token_store,
)

from wirestudio import __version__
from wirestudio.agent.agent import is_available as agent_available, run_turn, stream_turn_events
from wirestudio.agent.session import SessionStore, FileSessionStore
from wirestudio.designs.store import DesignStore, FileDesignStore
from wirestudio.api.schemas import (
    AgentSession,
    AgentSessionMessage,
    AgentToolCall,
    AgentTurnRequest,
    AgentTurnResponse,
    BoardSummary,
    CompatibilityWarning as CompatWire,
    ComponentSummary,
    ExampleSummary,
    InventoryCheckLine,
    InventoryCheckRequest,
    InventoryCheckResponse,
    InventoryEntryModel,
    McpTokenResponse,
    ModuleSummary,
    FleetJobLogResponse,
    FleetJobStatus,
    FleetPushRequest,
    FleetPushResponse,
    FleetRunStatus,
    FleetStatus,
    PinAssignment,
    Recommendation as RecommendationWire,
    RecommendRequest,
    RecommendResponse,
    RenderResponse,
    SaveDesignRequest,
    SaveDesignResponse,
    SavedDesignSummary,
    SetInventoryRequest,
    SolvePinsResponse,
    SolverWarning,
    UseCaseEntry,
    ValidateResponse,
)
from wirestudio.inventory import (
    InventoryEntry,
    check_inventory,
    entries_from_csv,
    entries_to_csv,
)
from wirestudio.inventory.store import InventoryStore, default_inventory_store
from wirestudio.designs.active import ActiveDesignTracker
from wirestudio.designs.events import DesignEventBus, EventEmittingDesignStore
from wirestudio.fleet.client import FleetClient, FleetUnavailable
from wirestudio.csp.compatibility import check_pin_compatibility, strict_blockers
from wirestudio.csp.pin_solver import solve_pins as run_solve_pins
from wirestudio.intent import validate_automations
from wirestudio.enclosure import (
    EnclosureUnavailable,
    default_sources,
    generate_scad,
    query_for_board,
    search_enclosures,
)
from wirestudio.kicad import generate_skidl
from wirestudio.kicad.fab import (
    GerberUnavailable,
    export_fab_package,
    export_gerbers,
    fab_status,
    generate_bom,
    generate_cpl,
)
from wirestudio.kicad.pcb import PcbUnavailable, generate_kicad_pcb, pcb_status
from wirestudio.kicad.render import (
    RenderError,
    RenderUnavailable,
    render_schematic,
    render_status,
)
from wirestudio.jlcpcb import check_bom, jlcpcb_status, report_to_dict
from wirestudio.recommend.recommender import Constraints, recommend_components
from wirestudio.library import (
    Library,
    LibraryBoard,
    LibraryComponent,
    LibraryModule,
    default_library,
)
from wirestudio.designs.seed import insert_module
from wirestudio.model import Design
from wirestudio.seed import seed_onboard_components
from wirestudio.targets import get_target, target_ids


def _wire_compat(warnings) -> list[CompatWire]:
    return [
        CompatWire(
            severity=w.severity, code=w.code, pin=w.pin,
            component_id=w.component_id, pin_role=w.pin_role,
            message=w.message,
        )
        for w in warnings
    ]

# Bundled examples live inside the wirestudio/ package so they
# ship in the wheel; resolves whether the studio runs from
# source or is pip-installed.
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _board_summary(b: LibraryBoard) -> BoardSummary:
    return BoardSummary(
        id=b.id,
        name=b.name,
        mcu=b.mcu,
        chip_variant=b.chip_variant,
        framework=b.framework,
        platformio_board=b.platformio_board,
        flash_size_mb=b.flash_size_mb,
        image=b.image,
        rail_names=[r.name for r in b.rails],
    )


def _component_summary(c: LibraryComponent) -> ComponentSummary:
    return ComponentSummary(
        id=c.id,
        name=c.name,
        category=c.category,
        use_cases=list(c.use_cases),
        aliases=list(c.aliases),
        required_components=list(c.esphome.required_components),
        current_ma_typical=c.electrical.current_ma_typical,
        current_ma_peak=c.electrical.current_ma_peak,
    )


def _module_summary(m: LibraryModule) -> ModuleSummary:
    return ModuleSummary(
        id=m.id,
        name=m.name,
        category=m.category,
        description=m.description,
        use_cases=list(m.use_cases),
        component_count=len(m.components),
    )


def _example_summary(path: Path) -> ExampleSummary:
    data = json.loads(path.read_text())
    return ExampleSummary(
        id=data["id"],
        name=data["name"],
        description=data.get("description", ""),
        board_library_id=data["board"]["library_id"],
        chip_family=data["board"]["mcu"],
    )



def _validate_design(design: dict) -> Design:
    try:
        return Design.model_validate(design)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from e

def create_app(
    library: Optional[Library] = None,
    sessions: Optional[SessionStore] = None,
    designs: Optional[DesignStore] = None,
    fleet_client_factory=None,
    event_bus: Optional[DesignEventBus] = None,
    active_design: Optional[ActiveDesignTracker] = None,
    inventory: Optional[InventoryStore] = None,
) -> FastAPI:
    import os as _os
    lib = library or default_library()

    # Pre-compute component and board summaries to avoid re-parsing YAML
    # and re-allocating models on every request. The library is immutable.
    _precomputed_components = [_component_summary(c) for c in lib.list_components()]
    _precomputed_boards = [_board_summary(b) for b in lib.list_boards()]
    # SESSIONS_DIR / DESIGNS_DIR env vars let the Docker image point
    # the stores at a /data volume without the caller plumbing args
    # through. Falls back to the package-local default in dev.
    sessions_store = sessions or FileSessionStore(root=_os.environ.get("SESSIONS_DIR") or None)
    inner_designs = designs or FileDesignStore(root=_os.environ.get("DESIGNS_DIR") or None)
    bus = event_bus or DesignEventBus()
    # Every write goes through the wrapper so MCP tools, HTTP endpoints,
    # and any future CLI all fan out to subscribed browser tabs without
    # the caller knowing about the bus.
    designs_store = EventEmittingDesignStore(inner_designs, bus)
    active = active_design or ActiveDesignTracker()
    # INVENTORY_PATH env var points the single inventory.json at a /data
    # volume in the Docker image; falls back to the package-local default.
    inventory_store = inventory or default_inventory_store()
    # Tests substitute a factory that returns a FleetClient bound to an
    # httpx.MockTransport so we never hit the network in CI.
    make_fleet: callable = fleet_client_factory or (lambda: FleetClient())

    limiter = Limiter(key_func=get_remote_address)


    mcp_enabled = os.environ.get("WIRESTUDIO_MCP_ENABLED", "true").lower() != "false"
    mcp_server = build_mcp_server(lib, designs_store, active=active) if mcp_enabled else None

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        # FastMCP's session_manager wraps the streamable_http_app; without
        # entering its run() context the /mcp endpoint 500s with "Task group
        # is not initialized." AsyncExitStack lets us no-op when MCP is
        # disabled without a duplicate yield branch.
        async with AsyncExitStack() as stack:
            if mcp_server is not None:
                await stack.enter_async_context(mcp_server.session_manager.run())
            yield

    # `docs_url=None` disables FastAPI's built-in /docs so we can serve our
    # own that points Swagger UI at /api/openapi.json -- which works whether
    # the page is reached directly (browser at :8765/docs) or via the
    # Vite dev proxy (browser at :5173/api/docs, proxied to /docs on the
    # API and stripped of the /api prefix). The default /docs uses an
    # absolute URL that breaks under the proxy.
    app = FastAPI(
        title="wirestudio API",
        version=__version__,
        description=(
            "Read-only library + stateless render/validate over `design.json`. "
            "Pure layer over `wirestudio.generate`; no server-side state."
        ),
        docs_url=None,
        lifespan=lifespan,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Parse ALLOWED_ORIGINS from environment, fallback to defaults
    allowed_origins = os.environ.get("WIRESTUDIO_ALLOWED_ORIGINS")
    if allowed_origins:
        origins = [o.strip() for o in allowed_origins.split(",")]
    else:
        origins = ["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "Accept"],
    )

    @app.get("/docs", include_in_schema=False)
    def custom_docs() -> HTMLResponse:
        # Swagger fetches the spec from `/api/openapi.json`. Direct API
        # access works because we register that path below; proxied access
        # works because `/api/openapi.json` -> proxy strips /api ->
        # `/openapi.json` on the API (also registered, FastAPI default).
        return get_swagger_ui_html(
            openapi_url="/api/openapi.json",
            title=f"{app.title} - Swagger UI",
        )

    @app.get("/api/openapi.json", include_in_schema=False)
    def openapi_alias() -> JSONResponse:
        return JSONResponse(app.openapi())

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"ok": True, "version": __version__}

    @app.get("/library/boards", response_model=list[BoardSummary], tags=["library"])
    def list_boards(
        target: Optional[str] = Query(
            default=None,
            description="Filter to boards selectable by a generation target (esphome|lorawan)",
        ),
    ) -> list[BoardSummary]:
        if target is None:
            return _precomputed_boards
        if target not in target_ids():
            raise HTTPException(status_code=422, detail=f"unknown target {target!r}")
        allowed = set(get_target(target).board_ids(lib))
        return [b for b in _precomputed_boards if b.id in allowed]

    @app.get("/library/boards/{board_id}", response_model=LibraryBoard, tags=["library"])
    def get_board(board_id: str) -> LibraryBoard:
        try:
            return lib.board(board_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.get("/library/components", response_model=list[ComponentSummary], tags=["library"])
    def list_components(
        category: Optional[str] = Query(default=None),
        use_case: Optional[str] = Query(default=None),
        bus: Optional[str] = Query(default=None, description="Required bus, e.g. i2c, spi, uart, i2s"),
    ) -> list[ComponentSummary]:
        if not category and not use_case and not bus:
            return _precomputed_components

        out: list[ComponentSummary] = []
        for c in _precomputed_components:
            if category and c.category != category:
                continue
            if use_case and use_case not in c.use_cases:
                continue
            if bus and bus not in c.required_components:
                continue
            out.append(c)
        return out

    @app.get("/library/components/{component_id}", response_model=LibraryComponent, tags=["library"])
    def get_component(component_id: str) -> LibraryComponent:
        try:
            return lib.component(component_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.get("/library/modules", response_model=list[ModuleSummary], tags=["library"])
    def list_modules() -> list[ModuleSummary]:
        return [_module_summary(m) for m in lib.list_modules()]

    @app.get("/library/modules/{module_id}", response_model=LibraryModule, tags=["library"])
    def get_module(module_id: str) -> LibraryModule:
        try:
            return lib.module(module_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.post("/design/insert_module", tags=["design"])
    def design_insert_module(design: dict, module_id: str) -> dict:
        """Insert a composite module's components into the design.

        Adds every component the module bundles (auto-wired the same way
        a hand-added component is) and returns the updated design. The
        inserted components carry a shared `module` marker so the BOM
        collapses them to one line.
        """
        _validate_design(design)
        try:
            module = lib.module(module_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        _, updated = insert_module(design, lib, module)
        return updated

    @app.post("/design/seed_onboard", tags=["design"])
    def design_seed_onboard(design: dict) -> dict:
        """Add the design's board's built-in (onboard) peripherals.

        Reads the board's `onboard_peripherals` metadata and appends the
        matching library components plus their wiring (buses, rails, GPIO
        pins). Peripherals with no library component yet come back as
        info-level warnings on the design. Used by the connect-bootstrap
        and new-design flows so a dev board lands with its soldered-on
        parts already placed.
        """
        _validate_design(design)
        board_id = (design.get("board") or {}).get("library_id")
        try:
            board = lib.board(board_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        frag = seed_onboard_components(board, lib)
        design.setdefault("components", []).extend(frag["components"])
        design.setdefault("buses", []).extend(frag["buses"])
        design.setdefault("connections", []).extend(frag["connections"])
        design.setdefault("warnings", []).extend(frag["warnings"])
        return design

    @app.post("/design/validate", response_model=ValidateResponse, tags=["design"])
    def validate(design: dict) -> ValidateResponse:
        d = _validate_design(design)
        # Append the active target's permissive checks. esphome adds none,
        # so existing designs see no change; lorawan flags a non-radio board
        # or a missing config block. The intent-to-device automation
        # validator surfaces dangling trigger/action refs the same way
        # (warnings, not blocks) so a half-authored automation can render.
        target_warnings = get_target(d.target).validate(d, lib)
        automation_warnings = validate_automations(d, lib)
        # In strict mode, warn/error compatibility entries and design warnings
        # flip ok to false (the render/push gates refuse the same design).
        # Permissive mode always reports ok -- warnings are guidance, not blocks.
        ok = not (d.strict and strict_blockers(design, lib))
        return ValidateResponse(
            ok=ok,
            design_id=d.id,
            name=d.name,
            component_count=len(d.components),
            bus_count=len(d.buses),
            connection_count=len(d.connections),
            warnings=[
                w.model_dump()
                for w in list(d.warnings) + target_warnings + automation_warnings
            ],
            compatibility_warnings=_wire_compat(check_pin_compatibility(design, lib)),
        )

    @app.post("/design/solve_pins", response_model=SolvePinsResponse, tags=["design"])
    def solve_pins(design: dict) -> SolvePinsResponse:
        # Validate the design first so we don't try to solve over a malformed body.
        _validate_design(design)
        result = run_solve_pins(design, lib)
        return SolvePinsResponse(
            design=result.design,
            assigned=[
                PinAssignment(
                    component_id=a.component_id,
                    pin_role=a.pin_role,
                    old_target=a.old_target,
                    new_target=a.new_target,
                )
                for a in result.assigned
            ],
            unresolved=[SolverWarning(level=w.level, code=w.code, text=w.text) for w in result.unresolved],
            warnings=[SolverWarning(level=w.level, code=w.code, text=w.text) for w in result.warnings],
            compatibility_warnings=_wire_compat(check_pin_compatibility(result.design, lib)),
        )

    @app.post("/design/render", response_model=RenderResponse, tags=["design"])
    def render(design: dict, strict: bool = False) -> RenderResponse:
        """Render a design to YAML + ASCII.

        Permissive by default: compatibility warnings travel back in the
        `compatibility_warnings` field for the UI to surface non-blocking
        guidance. Strict mode -- set either via the design's `strict: true`
        field or the `?strict=true` override -- instead 422s when any
        compatibility entry of severity `warn`/`error` or any warn/error
        design warning remains. The same gate the fleet-for-esphome push
        path uses to refuse to ship a design with unresolved hardware risks.
        """
        d = _validate_design(design)
        try:
            target = get_target(d.target)
            artifacts = target.generate(d, lib)
            yaml_text = artifacts.get("firmware.yaml", "")
            ascii_text = artifacts.get("wiring.txt", "")
        except FileNotFoundError as e:
            # Unknown component / board referenced.
            raise HTTPException(status_code=422, detail=str(e)) from e
        except ValueError as e:
            # Surfaced from the generator for incomplete-but-validating designs:
            # missing bus matching a `kind: bus` connection, etc.
            raise HTTPException(status_code=422, detail=str(e)) from e
        compat = check_pin_compatibility(design, lib)
        if strict or d.strict:
            blockers = strict_blockers(design, lib)
            if blockers:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "strict_mode_blocked",
                        "message": (
                            f"strict mode rejected the render: "
                            f"{len(blockers)} issue"
                            f"{'s' if len(blockers) != 1 else ''} need attention"
                        ),
                        "blockers": [asdict(b) for b in blockers],
                    },
                )
        return RenderResponse(
            yaml=yaml_text,
            ascii=ascii_text,
            compatibility_warnings=_wire_compat(compat),
        )

    @app.post("/design/enclosure/openscad", tags=["design"])
    def design_enclosure_openscad(design: dict) -> PlainTextResponse:
        """Render a parametric OpenSCAD shell for the design's board.

        Returns the `.scad` text with a Content-Disposition header so a
        browser fetch saves it as `<design_id>.scad`. 422 when the
        board lacks `enclosure:` metadata (modules without a clear PCB
        outline -- ESP-01S etc. -- are intentional skips).
        """
        d = _validate_design(design)
        try:
            scad = generate_scad(d, lib)
        except FileNotFoundError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except EnclosureUnavailable as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        filename = f"{d.id}.scad"
        return PlainTextResponse(
            content=scad,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
            },
        )

    @app.post("/design/kicad/schematic", tags=["design"])
    def design_kicad_schematic(design: dict) -> PlainTextResponse:
        """Render a SKiDL Python script the user runs locally to produce
        `<design_id>.kicad_sch`.

        We don't import or run SKiDL ourselves -- a hard runtime dep
        would pull in numpy + EDA-toolchain weight that's wrong for
        a server. The user pipes the response through:

            curl -X POST .../design/kicad/schematic ... > design.skidl.py
            pip install skidl
            python design.skidl.py

        Components without a `kicad:` mapping render as a generic
        4-pin connector with a TODO comment; the script always runs
        and the user can patch the .py before re-running, or fill in
        the library YAML and re-export.
        """
        d = _validate_design(design)
        try:
            script = generate_skidl(d, lib)
        except FileNotFoundError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        filename = f"{d.id}.skidl.py"
        return PlainTextResponse(
            content=script,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/design/kicad/render/status", tags=["design"])
    def design_kicad_render_status() -> dict:
        """Probe whether the schematic-render pipeline (SKiDL + kicad-cli)
        is available. The web UI gates the inline preview on `available`
        and surfaces `reason` when a tool is missing."""
        return render_status()

    @app.post("/design/kicad/render", tags=["design"])
    def design_kicad_render(design: dict, format: str = "svg") -> Response:
        """Render the design's schematic to an image.

        Runs the generated SKiDL script + `kicad-cli` in a subprocess.
        `format` is `svg` (default, browser-native) or `png`. Returns
        503 when the tools aren't installed -- check
        `/design/kicad/render/status` first.
        """
        if format not in ("svg", "png"):
            raise HTTPException(status_code=422, detail="format must be 'svg' or 'png'")
        d = _validate_design(design)
        try:
            data = render_schematic(d, lib, fmt=format)
        except RenderUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except RenderError as e:
            raise HTTPException(status_code=500, detail=str(e)) from e
        media = "image/svg+xml" if format == "svg" else "image/png"
        return Response(content=data, media_type=media)

    @app.get("/design/kicad/pcb/status", tags=["design"])
    def design_kicad_pcb_status() -> dict:
        """Probe whether the .kicad_pcb export is available. Unlike the SKiDL
        script (always emittable), the board embeds real footprint geometry,
        so it needs the pinned KiCad footprint + symbol libraries on the
        server. The web UI gates the download on `available`."""
        return pcb_status()

    @app.post("/design/kicad/pcb", tags=["design"])
    def design_kicad_pcb(design: dict) -> PlainTextResponse:
        """Emit a `<design_id>.kicad_pcb`: footprints embedded + grid-placed,
        pads bound to nets, an Edge.Cuts outline, no routing. Open it in
        KiCad's PCB editor and route (or autoroute). Returns 503 when the
        footprint/symbol libraries aren't installed -- check
        `/design/kicad/pcb/status` first."""
        d = _validate_design(design)
        try:
            board = generate_kicad_pcb(d, lib)
        except PcbUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except (FileNotFoundError, ValueError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        filename = f"{d.id}.kicad_pcb"
        return PlainTextResponse(
            content=board,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/design/fab/status", tags=["design"])
    def design_fab_status() -> dict:
        """What fab outputs are available: BOM is always emittable, CPL needs
        the footprint libraries, Gerbers also need kicad-cli."""
        return fab_status()

    @app.post("/design/fab/bom", tags=["design"])
    def design_fab_bom(design: dict) -> PlainTextResponse:
        """JLCPCB BOM CSV (grouped by part). Pure -- always available."""
        d = _validate_design(design)
        return PlainTextResponse(
            content=generate_bom(d, lib), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{d.id}-bom.csv"'},
        )

    @app.post("/design/fab/cpl", tags=["design"])
    def design_fab_cpl(design: dict) -> PlainTextResponse:
        """JLCPCB CPL (pick-and-place) CSV; positions match the .kicad_pcb.
        503 when the footprint libraries aren't on the server."""
        d = _validate_design(design)
        try:
            cpl = generate_cpl(d, lib)
        except PcbUnavailable as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except (FileNotFoundError, ValueError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return PlainTextResponse(
            content=cpl, media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{d.id}-cpl.csv"'},
        )

    @app.post("/design/fab/gerbers", tags=["design"])
    def design_fab_gerbers(design: dict) -> Response:
        """Gerber + drill files as a zip. 503 when kicad-cli / the libraries
        are missing."""
        d = _validate_design(design)
        try:
            data = export_gerbers(d, lib)
        except (GerberUnavailable, PcbUnavailable) as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except (FileNotFoundError, ValueError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return Response(
            content=data, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{d.id}-gerbers.zip"'},
        )

    @app.post("/design/fab/package", tags=["design"])
    def design_fab_package(design: dict) -> Response:
        """The JLCPCB upload bundle: Gerbers + drill + CPL + BOM in one zip.
        Boards are unrouted until the routing step lands, so the Gerbers carry
        pads but no traces. 503 when kicad-cli / the libraries are missing."""
        d = _validate_design(design)
        try:
            data = export_fab_package(d, lib)
        except (GerberUnavailable, PcbUnavailable) as e:
            raise HTTPException(status_code=503, detail=str(e)) from e
        except (FileNotFoundError, ValueError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return Response(
            content=data, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{d.id}-fab.zip"'},
        )

    @app.get("/design/jlcpcb/status", tags=["design"])
    def design_jlcpcb_status() -> dict:
        """Probe the JLCPCB parts search API. The UI gates the BOM-check
        action on `available` and surfaces `reason` when it's down."""
        return jlcpcb_status()

    @app.post("/design/jlcpcb/check", tags=["design"])
    def design_jlcpcb_check(design: dict) -> dict:
        """Check the design's component BOM against JLCPCB stock + price.

        Always 200: an unreachable API comes back as `available: false`
        with a `reason`, so the caller degrades gracefully rather than
        treating a flaky third-party API as a hard failure.
        """
        d = _validate_design(design)
        return report_to_dict(check_bom(d, lib))

    @app.get("/enclosure/search/status", tags=["enclosure"])
    def enclosure_search_status() -> dict:
        """Per-source availability for the enclosure-search relay.
        Used by the UI to gate the Search tab and surface configuration
        hints when a source is unconfigured."""
        return {
            "sources": [
                {
                    "source": s.source,
                    "available": s.available,
                    "reason": s.reason,
                    "configure_hint": s.configure_hint,
                }
                for s in (src.status() for src in default_sources())
            ],
        }

    @app.get("/enclosure/search", tags=["enclosure"])
    def enclosure_search(
        library_id: str,
        query: Optional[str] = None,
        limit: int = 20,
    ) -> dict:
        """Search community-uploaded 3D enclosure models for the named
        board. Query construction: `<board_name> enclosure [<query>]`.
        Results merge across every configured source (Thingiverse only
        in v2; Printables stays deferred). 404 when library_id is
        unknown."""
        try:
            board = lib.board(library_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        full_query = query_for_board(board.name, query)
        capped = max(1, min(limit, 50))
        out = search_enclosures(full_query, limit=capped)
        return {
            "query": out.query,
            "sources": [
                {
                    "source": s.source,
                    "available": s.available,
                    "reason": s.reason,
                    "configure_hint": s.configure_hint,
                }
                for s in out.sources
            ],
            "results": [
                {
                    "source": h.source,
                    "id": h.id,
                    "title": h.title,
                    "creator": h.creator,
                    "thumbnail_url": h.thumbnail_url,
                    "model_url": h.model_url,
                    "likes": h.likes,
                    "summary": h.summary,
                }
                for h in out.results
            ],
        }

    @app.get("/examples", response_model=list[ExampleSummary], tags=["examples"])
    def list_examples() -> list[ExampleSummary]:
        return [_example_summary(p) for p in sorted(EXAMPLES_DIR.glob("*.json"))]

    @app.get("/examples/{example_id}", tags=["examples"])
    def get_example(example_id: str) -> dict:
        if "/" in example_id or "\\" in example_id:
            raise HTTPException(status_code=404, detail=f"Unknown example '{example_id}'")

        path = (EXAMPLES_DIR / f"{example_id}.json").resolve()
        if not path.is_relative_to(EXAMPLES_DIR.resolve()) or not path.exists():
            raise HTTPException(status_code=404, detail=f"Unknown example '{example_id}'")

        return json.loads(path.read_text())

    # ---------------------------------------------------------------------
    # Saved designs (file-backed at designs/<id>.json)
    # ---------------------------------------------------------------------

    @app.get("/designs", response_model=list[SavedDesignSummary], tags=["designs"])
    def list_saved_designs() -> list[SavedDesignSummary]:
        return [
            SavedDesignSummary(
                id=s.id, name=s.name, description=s.description,
                board_library_id=s.board_library_id, chip_family=s.chip_family,
                saved_at=s.saved_at, component_count=s.component_count,
            )
            for s in designs_store.list()
        ]

    @app.post("/designs", response_model=SaveDesignResponse, tags=["designs"])
    def save_design(req: SaveDesignRequest) -> SaveDesignResponse:
        # Validate the body shape first so we don't write garbage to disk.
        _validate_design(req.design)
        try:
            design_id, saved_at = designs_store.save(req.design, design_id=req.design_id)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return SaveDesignResponse(id=design_id, saved_at=saved_at)

    # `/designs/active` must register before `/designs/{design_id}` so the
    # literal path wins matching -- otherwise `active` is captured as a
    # design id and GET 404s with "no saved design with id 'active'".
    @app.get("/designs/active", tags=["designs"])
    def get_active_design() -> dict:
        """Return the currently-active design id (or null if none set).

        Drives the chat-driven UX: MCP tools fall back to this id when the
        caller doesn't supply `design_id`. The browser writes it via PUT
        whenever the user selects a saved design so a prompt like
        "add a BME280 to this design" resolves naturally.
        """
        return {"id": active.get()}

    @app.put("/designs/active", tags=["designs"])
    def set_active_design(body: dict) -> dict:
        """Set or clear the active design id. Body: `{id: string | null}`."""
        new_id = body.get("id")
        if new_id is not None and not isinstance(new_id, str):
            raise HTTPException(status_code=422, detail="`id` must be a string or null")
        active.set(new_id)
        return {"id": active.get()}

    @app.get("/designs/{design_id}", tags=["designs"])
    def get_saved_design(design_id: str) -> dict:
        try:
            return designs_store.load(design_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.delete("/designs/{design_id}", tags=["designs"])
    def delete_saved_design(design_id: str) -> dict:
        try:
            removed = designs_store.delete(design_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if not removed:
            raise HTTPException(status_code=404, detail=f"no saved design with id {design_id!r}")
        # Clear the active design pointer if it was just deleted -- a
        # dangling active id would have MCP tools fail with "no such
        # design" on every default-resolved call.
        if active.get() == design_id:
            active.clear()
        return {"deleted": True, "id": design_id}

    @app.get("/designs/{design_id}/events", tags=["designs"])
    async def design_events(design_id: str, request: Request):
        """SSE stream of writes to one design.

        Browser tabs open this once per displayed design; any save or
        delete from MCP / HTTP / CLI emits a `saved` or `deleted` event
        the client uses to re-fetch + re-render. Also emits a `: ping`
        comment every 15s to keep intermediate proxies (nginx, vite-dev,
        Cloudflare) from killing an idle connection.

        The endpoint doesn't validate that `design_id` exists -- a tab
        opening this stream for a not-yet-saved design is a legitimate
        race where the next save will be the first event the client
        ever sees.
        """
        queue = bus.subscribe(design_id)

        async def event_source():
            try:
                # Replay the current saved-at timestamp on connect so a
                # late-joining tab can reconcile against its own state
                # without an explicit fetch race.
                if designs_store.exists(design_id):
                    summary = next(
                        (s for s in designs_store.list() if s.id == design_id),
                        None,
                    )
                    if summary is not None:
                        yield (
                            "event: hello\n"
                            f"data: {json.dumps({'design_id': design_id, 'saved_at': summary.saved_at})}\n\n"
                        )
                while True:
                    if await request.is_disconnected():
                        return
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    yield (
                        f"event: {event.kind}\n"
                        f"data: {json.dumps(event.to_dict())}\n\n"
                    )
            finally:
                bus.unsubscribe(design_id, queue)

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/library/use_cases", response_model=list[UseCaseEntry], tags=["library"])
    def list_use_cases() -> list[UseCaseEntry]:
        """Distinct use_cases across the library, with the count of components
        that advertise each plus a small sample of library_ids for hover.

        Used by the **Add by function** picker so the user can browse the
        canonical capability vocabulary instead of typing free text into
        the recommender.
        """
        agg: dict[str, list[str]] = {}
        for c in lib.list_components():
            for uc in c.use_cases:
                agg.setdefault(uc, []).append(c.id)
        rows = [
            UseCaseEntry(
                use_case=uc,
                count=len(ids),
                example_components=sorted(ids)[:3],
            )
            for uc, ids in agg.items()
        ]
        # Most-supported capabilities first, ties broken alphabetically.
        rows.sort(key=lambda r: (-r.count, r.use_case))
        return rows

    @app.post("/library/recommend", response_model=RecommendResponse, tags=["library"])
    def recommend(req: RecommendRequest) -> RecommendResponse:
        constraints = Constraints(**(req.constraints or {})) if req.constraints else Constraints()
        on_hand = None
        if req.use_inventory:
            on_hand = {
                e.library_id: e.quantity
                for e in inventory_store.list()
                if e.kind == "component"
            }
        results = recommend_components(
            lib, req.query, constraints=constraints, limit=req.limit, inventory=on_hand
        )
        return RecommendResponse(
            query=req.query,
            matches=[
                RecommendationWire(
                    library_id=r.library_id, name=r.name, category=r.category,
                    use_cases=r.use_cases, aliases=r.aliases,
                    required_components=r.required_components,
                    current_ma_typical=r.current_ma_typical,
                    current_ma_peak=r.current_ma_peak,
                    vcc_min=r.vcc_min, vcc_max=r.vcc_max,
                    score=r.score, in_examples=r.in_examples,
                    rationale=r.rationale, on_hand=r.on_hand, notes=r.notes,
                )
                for r in results
            ],
        )

    # ---------------------------------------------------------------------
    # Local component inventory
    # ---------------------------------------------------------------------

    def _entry_wire(e: InventoryEntry) -> InventoryEntryModel:
        return InventoryEntryModel(
            library_id=e.library_id, kind=e.kind, quantity=e.quantity,
            min_quantity=e.min_quantity, low_stock=e.low_stock,
            location=e.location, note=e.note,
        )

    @app.get("/inventory", response_model=list[InventoryEntryModel], tags=["inventory"])
    def list_inventory() -> list[InventoryEntryModel]:
        return [_entry_wire(e) for e in inventory_store.list()]

    @app.put("/inventory/{library_id}", response_model=InventoryEntryModel, tags=["inventory"])
    def set_inventory(library_id: str, req: SetInventoryRequest) -> InventoryEntryModel:
        if req.kind not in ("component", "module"):
            raise HTTPException(status_code=422, detail=f"unknown kind {req.kind!r}")
        try:
            if req.kind == "module":
                lib.module(library_id)
            else:
                lib.component(library_id)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"no {req.kind} with library id {library_id!r}"
            )
        try:
            entry = InventoryEntry(
                library_id=library_id, kind=req.kind, quantity=req.quantity,
                min_quantity=req.min_quantity, location=req.location, note=req.note,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return _entry_wire(inventory_store.set(entry))

    @app.delete("/inventory/{library_id}", tags=["inventory"])
    def delete_inventory(library_id: str) -> dict:
        if not inventory_store.remove(library_id):
            raise HTTPException(
                status_code=404, detail=f"no inventory entry for {library_id!r}"
            )
        return {"deleted": library_id}

    @app.get("/inventory/export.csv", tags=["inventory"])
    def export_inventory() -> Response:
        return Response(
            content=entries_to_csv(inventory_store.list()),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="inventory.csv"'},
        )

    @app.post("/inventory/import", tags=["inventory"])
    def import_inventory(body: dict) -> dict:
        """Upsert entries from a CSV body ({"csv": "..."}). Rows naming a part
        not in the library are skipped (reported), not failed."""
        try:
            entries = entries_from_csv(str(body.get("csv", "")))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        imported, skipped = 0, []
        for entry in entries:
            try:
                (lib.module if entry.kind == "module" else lib.component)(entry.library_id)
            except FileNotFoundError:
                skipped.append(entry.library_id)
                continue
            inventory_store.set(entry)
            imported += 1
        return {"imported": imported, "skipped": skipped}

    @app.post("/design/inventory/check", response_model=InventoryCheckResponse,
              tags=["inventory"])
    def check_design_inventory(req: InventoryCheckRequest) -> InventoryCheckResponse:
        design = _validate_design(req.design)
        report = check_inventory(design, lib, inventory_store.list())
        return InventoryCheckResponse(
            design_id=report.design_id,
            lines=[
                InventoryCheckLine(
                    library_id=ln.library_id, kind=ln.kind, name=ln.name,
                    needed=ln.needed, on_hand=ln.on_hand, status=ln.status,
                    location=ln.location, note=ln.note,
                )
                for ln in report.lines
            ],
            summary=report.summary,
        )

    # ---------------------------------------------------------------------
    # Fleet handoff (fleet-for-esphome ha-addon)
    # ---------------------------------------------------------------------

    @app.get("/fleet/status", response_model=FleetStatus, tags=["fleet"])
    async def fleet_status() -> FleetStatus:
        fc = make_fleet()
        if not fc.is_configured():
            reason = "FLEET_URL not set" if not fc.base_url else "FLEET_TOKEN not set"
            return FleetStatus(available=False, reason=reason, url=fc.base_url or None)
        ok, reason = await fc.is_available()
        return FleetStatus(available=ok, reason=reason, url=fc.base_url or None)

    @app.post("/fleet/push", response_model=FleetPushResponse, tags=["fleet"])
    async def fleet_push(req: FleetPushRequest) -> FleetPushResponse:
        try:
            d = Design.model_validate(req.design)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors()) from e
        try:
            target = get_target(d.target)
            # When the caller supplies lorawan_secrets, render directly so the
            # literals are substituted for the !secret references in the
            # `lorawan:` block. The TargetPlugin contract stays fixed; only the
            # esphome target consumes the override today (the standalone
            # lorawan target's serial-provisioning flow doesn't need it).
            if req.lorawan_secrets and d.target == "esphome":
                from wirestudio.generate import yaml_gen
                yaml_text = yaml_gen.render_yaml(d, lib, lorawan_secrets=req.lorawan_secrets)
            else:
                artifacts = target.generate(d, lib)
                yaml_text = artifacts.get("firmware.yaml")
            if not yaml_text:
                raise ValueError(f"target '{d.target}' does not produce firmware.yaml")
        except (FileNotFoundError, ValueError, KeyError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

        # Strict push: refuse to ship when any warn/error issue remains.
        # Triggered by the design's own `strict: true` or the request flag.
        # Mirrors the /design/render strict gate so a client sees the same
        # envelope and the same blockers.
        if req.strict or d.strict:
            blockers = strict_blockers(req.design, lib)
            if blockers:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "error": "strict_mode_blocked",
                        "message": (
                            f"strict mode refused the push: "
                            f"{len(blockers)} issue"
                            f"{'s' if len(blockers) != 1 else ''} need attention"
                        ),
                        "blockers": [asdict(b) for b in blockers],
                    },
                )

        # Filename precedence: explicit override > fleet.device_name > design.id.
        device_name = (
            req.device_name
            or (d.fleet.device_name if d.fleet and d.fleet.device_name else None)
            or d.id
        )

        fc = make_fleet()
        if not fc.is_configured():
            raise HTTPException(
                status_code=503,
                detail="fleet not configured (set FLEET_URL and FLEET_TOKEN)",
            )
        try:
            result = await fc.push_device(device_name, yaml_text, compile=req.compile)
        except ValueError as e:
            # _validate_filename rejected the name.
            raise HTTPException(status_code=422, detail=str(e)) from e
        except FleetUnavailable as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return FleetPushResponse(
            filename=result.filename,
            created=result.created,
            run_id=result.run_id,
            enqueued=result.enqueued,
        )

    @app.get("/fleet/jobs/{run_id}/log", response_model=FleetJobLogResponse, tags=["fleet"])
    async def fleet_job_log(run_id: str, offset: int = 0) -> FleetJobLogResponse:
        fc = make_fleet()
        if not fc.is_configured():
            raise HTTPException(
                status_code=503,
                detail="fleet not configured (set FLEET_URL and FLEET_TOKEN)",
            )
        try:
            chunk = await fc.get_job_log(run_id, offset=offset)
        except FleetUnavailable as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return FleetJobLogResponse(
            log=chunk.log, offset=chunk.offset, finished=chunk.finished,
        )

    @app.get("/fleet/jobs/{run_id}", response_model=FleetRunStatus, tags=["fleet"])
    async def fleet_job_status(run_id: str) -> FleetRunStatus:
        """Compile verdict for a Push-to-fleet run: did the build pass?

        Aggregates the addon's job queue for `run_id`. `verdict` is
        running / passed / failed / cancelled, or `unknown` once the run
        has aged out of the addon's queue.
        """
        fc = make_fleet()
        if not fc.is_configured():
            raise HTTPException(
                status_code=503,
                detail="fleet not configured (set FLEET_URL and FLEET_TOKEN)",
            )
        try:
            status = await fc.get_run_status(run_id)
        except FleetUnavailable as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return FleetRunStatus(
            run_id=status.run_id,
            verdict=status.verdict,
            jobs=[
                FleetJobStatus(
                    job_id=j.job_id, target=j.target,
                    state=j.state, finished_at=j.finished_at,
                )
                for j in status.jobs
            ],
        )

    @app.get("/fleet/jobs/{run_id}/log/stream", tags=["fleet"])
    async def fleet_job_log_stream(run_id: str, offset: int = 0, interval_ms: int = 300):
        """Server-Sent Events relay over the addon's HTTP log endpoint.

        Polls `fc.get_job_log(run_id)` server-side at ~300ms (vs the 1.5s
        the browser-driven loop uses) and streams each chunk to the client
        as an SSE event of shape `data: {"log": "...", "offset": N,
        "finished": bool}`. The stream emits a final `event: done` frame
        when the addon reports finished and exits. Errors yield an
        `event: error` frame and exit.

        EventSource connections die on browser tab close; the polling
        loop sees the resulting transport error and exits cleanly. The
        addon's polling endpoint is idempotent so a reconnect with a
        fresh offset just resumes.
        """
        fc = make_fleet()
        if not fc.is_configured():
            raise HTTPException(
                status_code=503,
                detail="fleet not configured (set FLEET_URL and FLEET_TOKEN)",
            )
        # Cap the lower bound so a malicious / mistaken caller can't tar-pit
        # the studio + addon by polling at 1ms.
        sleep_seconds = max(0.1, interval_ms / 1000.0)

        async def _events():
            current = offset
            while True:
                try:
                    chunk = await fc.get_job_log(run_id, offset=current)
                except FleetUnavailable as e:
                    yield (
                        "event: error\n"
                        f"data: {json.dumps({'message': str(e)})}\n\n"
                    )
                    return
                payload = {
                    "log": chunk.log,
                    "offset": chunk.offset,
                    "finished": chunk.finished,
                }
                yield f"data: {json.dumps(payload)}\n\n"
                current = chunk.offset
                if chunk.finished:
                    yield "event: done\ndata: {}\n\n"
                    return
                await asyncio.sleep(sleep_seconds)

        return StreamingResponse(
            _events(),
            media_type="text/event-stream",
            # Disable any intermediate buffering so the chunks land
            # incrementally rather than getting batched at the proxy
            # layer (Vite + nginx both honour this).
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/fleet/jobs/{run_id}/firmware", tags=["fleet"])
    async def fleet_job_firmware(run_id: str, factory: bool = False) -> Response:
        """Passthrough for the fleet's compiled-firmware artifact -- the
        studio fetches it server-side with FLEET_TOKEN and streams the
        bytes to the browser's WebSerial flasher (no token in the browser).

        ``?factory=true`` returns the merged bootloader+partitions+app
        image for flashing a blank board at offset 0x0 (paired with
        ``eraseAll: true`` on the browser side); default is the app image
        for an NVS-preserving re-flash. Mirrors the standalone path's
        ``/lorawan/firmware/{cache_key}[/factory]`` so the WebSerial flow
        on the external-component path can reuse ``lib/flash.ts`` unchanged.

        Returns 404 when the run hasn't finished, has aged out of the
        addon's tracking, or the build didn't produce the requested image
        type; 503 when fleet credentials are missing; 502 when the addon
        is reachable but the call failed (e.g. the upstream artifact
        endpoint isn't implemented yet -- see
        ``docs/lorawan/fleet-firmware-flash.md``).
        """
        fc = make_fleet()
        if not fc.is_configured():
            raise HTTPException(
                status_code=503,
                detail="fleet not configured (set FLEET_URL and FLEET_TOKEN)",
            )
        try:
            data = await fc.get_firmware(run_id, factory=factory)
        except FleetUnavailable as e:
            # The client raises FleetUnavailable on both 404 (firmware not
            # available -> the dialog stops the flash flow with a clear
            # message) and transport failures (the addon being down).
            # Preserve the 404 vs 502 distinction the addon emitted so the
            # browser can tell "not ready yet" from "fleet is down".
            msg = str(e)
            if "not available" in msg:
                raise HTTPException(status_code=404, detail=msg) from e
            raise HTTPException(status_code=502, detail=msg) from e
        suffix = "-factory" if factory else ""
        return Response(
            content=data,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{run_id}{suffix}.bin"',
            },
        )

    @app.get("/agent/status", tags=["agent"])
    def agent_status() -> dict:
        ok, reason = agent_available()
        return {"available": ok, "reason": reason}

    @app.post("/agent/turn", response_model=AgentTurnResponse, tags=["agent"])
    @limiter.limit("10/minute")
    def agent_turn(request: Request, req: AgentTurnRequest) -> AgentTurnResponse:
        ok, reason = agent_available()
        if not ok:
            raise HTTPException(status_code=503, detail=reason)
        try:
            result = run_turn(
                design=req.design,
                user_message=req.message,
                session_id=req.session_id,
                library=lib,
                sessions=sessions_store,
            )
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return AgentTurnResponse(
            session_id=result.session_id,
            design=result.design,
            assistant_text=result.assistant_text,
            tool_calls=[AgentToolCall(**tc) for tc in result.tool_calls],
            stop_reason=result.stop_reason,
            usage=result.usage,
        )

    @app.post("/agent/stream", tags=["agent"])
    @limiter.limit("10/minute")
    def agent_stream(request: Request, req: AgentTurnRequest):
        """Server-Sent Events variant of /agent/turn. Emits text_delta,
        tool_use_start, tool_result, and turn_complete events as they
        happen so the UI can render progress live."""
        ok, reason = agent_available()
        if not ok:
            raise HTTPException(status_code=503, detail=reason)

        def event_source():
            try:
                for event in stream_turn_events(
                    design=req.design,
                    user_message=req.message,
                    session_id=req.session_id,
                    library=lib,
                    sessions=sessions_store,
                ):
                    yield f"data: {json.dumps(event, default=str)}\n\n"
            except Exception as e:  # pragma: no cover - defensive guard
                payload = {"type": "error", "message": str(e)}
                yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(
            event_source(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable proxy buffering
            },
        )

    @app.get("/agent/sessions/{session_id}", response_model=AgentSession, tags=["agent"])
    def get_agent_session(session_id: str) -> AgentSession:
        try:
            messages = sessions_store.load(session_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        if not messages and not sessions_store.exists(session_id):
            raise HTTPException(status_code=404, detail=f"Unknown session '{session_id}'")
        return AgentSession(
            session_id=session_id,
            messages=[AgentSessionMessage(**m) for m in messages],
        )

    # Mount each registered target's optional router under /<id> (e.g. the
    # lorawan target's /lorawan/compile endpoints). esphome returns None -- its
    # endpoints are the top-level routes above.
    for target_id in target_ids():
        target_router = get_target(target_id).router(lib)
        if target_router is not None:
            app.include_router(target_router, prefix=f"/{target_id}")

    if mcp_server is not None:
        # Streamable HTTP transport. mcp_server.streamable_http_app() registers
        # `/mcp` on its own Starlette app; we wrap it in BearerTokenMiddleware
        # and mount at root so the path stays `/mcp`. Mounting at `/mcp` would
        # land the inner route at `/mcp/mcp`, which is wrong.
        allowed_hosts = os.environ.get("WIRESTUDIO_MCP_ALLOWED_HOSTS")
        if allowed_hosts:
            mcp_server.settings.transport_security.allowed_hosts = [
                h.strip() for h in allowed_hosts.split(",") if h.strip()
            ]
        token_path_env = os.environ.get("WIRESTUDIO_MCP_TOKEN_PATH")
        token_store = load_token_store(
            token_path=Path(token_path_env) if token_path_env else None,
        )

        # Token-management endpoints for the web UI. Registered before the
        # catch-all mount below so FastAPI serves them directly -- they sit on
        # the unauthenticated API surface (the bearer token only gates /mcp),
        # which is required so the UI can show the token to a user who doesn't
        # have it yet.
        @app.get("/mcp/token", response_model=McpTokenResponse, tags=["mcp"])
        def get_mcp_token() -> McpTokenResponse:
            return McpTokenResponse(
                token=token_store.token,
                managed="env" if token_store.env_managed else "file",
            )

        @app.post("/mcp/token/rotate", response_model=McpTokenResponse, tags=["mcp"])
        def rotate_mcp_token() -> McpTokenResponse:
            try:
                new_token = token_store.rotate()
            except TokenManagedError as e:
                raise HTTPException(status_code=409, detail=str(e)) from e
            return McpTokenResponse(token=new_token, managed="file")

        mcp_app = mcp_server.streamable_http_app()
        mcp_app.add_middleware(BearerTokenMiddleware, store=token_store)
        app.mount("/", mcp_app)

    return app


app = create_app()
