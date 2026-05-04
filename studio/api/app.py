from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import ValidationError

from studio import __version__
from studio.agent.agent import is_available as agent_available, run_turn, stream_turn_events
from studio.agent.session import SessionStore
from studio.designs.store import DesignStore
from studio.api.schemas import (
    AgentSession,
    AgentSessionMessage,
    AgentToolCall,
    AgentTurnRequest,
    AgentTurnResponse,
    BoardSummary,
    CompatibilityWarning as CompatWire,
    ComponentSummary,
    ExampleSummary,
    FleetJobLogResponse,
    FleetPushRequest,
    FleetPushResponse,
    FleetStatus,
    PinAssignment,
    Recommendation as RecommendationWire,
    RecommendRequest,
    RecommendResponse,
    RenderResponse,
    SaveDesignRequest,
    SaveDesignResponse,
    SavedDesignSummary,
    SolvePinsResponse,
    SolverWarning,
    ValidateResponse,
)
from studio.fleet.client import FleetClient, FleetUnavailable
from studio.csp.compatibility import check_pin_compatibility
from studio.csp.pin_solver import solve_pins as run_solve_pins
from studio.recommend.recommender import Constraints, recommend_components
from studio.generate.ascii_gen import render_ascii
from studio.generate.yaml_gen import render_yaml
from studio.library import Library, LibraryBoard, LibraryComponent, default_library
from studio.model import Design


def _wire_compat(warnings) -> list[CompatWire]:
    return [
        CompatWire(
            severity=w.severity, code=w.code, pin=w.pin,
            component_id=w.component_id, pin_role=w.pin_role,
            message=w.message,
        )
        for w in warnings
    ]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EXAMPLES_DIR = REPO_ROOT / "examples"


def _board_summary(b: LibraryBoard) -> BoardSummary:
    return BoardSummary(
        id=b.id,
        name=b.name,
        mcu=b.mcu,
        chip_variant=b.chip_variant,
        framework=b.framework,
        platformio_board=b.platformio_board,
        flash_size_mb=b.flash_size_mb,
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


def _example_summary(path: Path) -> ExampleSummary:
    data = json.loads(path.read_text())
    return ExampleSummary(
        id=data["id"],
        name=data["name"],
        description=data.get("description", ""),
        board_library_id=data["board"]["library_id"],
        chip_family=data["board"]["mcu"],
    )


def create_app(
    library: Optional[Library] = None,
    sessions: Optional[SessionStore] = None,
    designs: Optional[DesignStore] = None,
    fleet_client_factory=None,
) -> FastAPI:
    lib = library or default_library()
    sessions_store = sessions or SessionStore()
    designs_store = designs or DesignStore()
    # Tests substitute a factory that returns a FleetClient bound to an
    # httpx.MockTransport so we never hit the network in CI.
    make_fleet: callable = fleet_client_factory or (lambda: FleetClient())

    # `docs_url=None` disables FastAPI's built-in /docs so we can serve our
    # own that points Swagger UI at /api/openapi.json -- which works whether
    # the page is reached directly (browser at :8765/docs) or via the
    # Vite dev proxy (browser at :5173/api/docs, proxied to /docs on the
    # API and stripped of the /api prefix). The default /docs uses an
    # absolute URL that breaks under the proxy.
    app = FastAPI(
        title="esphome-studio API",
        version=__version__,
        description=(
            "Read-only library + stateless render/validate over `design.json`. "
            "Pure layer over `studio.generate`; no server-side state."
        ),
        docs_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
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
    def list_boards() -> list[BoardSummary]:
        return [_board_summary(b) for b in lib.list_boards()]

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
        out: list[ComponentSummary] = []
        for c in lib.list_components():
            if category and c.category != category:
                continue
            if use_case and use_case not in c.use_cases:
                continue
            if bus and bus not in c.esphome.required_components:
                continue
            out.append(_component_summary(c))
        return out

    @app.get("/library/components/{component_id}", response_model=LibraryComponent, tags=["library"])
    def get_component(component_id: str) -> LibraryComponent:
        try:
            return lib.component(component_id)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.post("/design/validate", response_model=ValidateResponse, tags=["design"])
    def validate(design: dict) -> ValidateResponse:
        try:
            d = Design.model_validate(design)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors()) from e
        return ValidateResponse(
            ok=True,
            design_id=d.id,
            name=d.name,
            component_count=len(d.components),
            bus_count=len(d.buses),
            connection_count=len(d.connections),
            warnings=[w.model_dump() for w in d.warnings],
            compatibility_warnings=_wire_compat(check_pin_compatibility(design, lib)),
        )

    @app.post("/design/solve_pins", response_model=SolvePinsResponse, tags=["design"])
    def solve_pins(design: dict) -> SolvePinsResponse:
        # Validate the design first so we don't try to solve over a malformed body.
        try:
            Design.model_validate(design)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors()) from e
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
    def render(design: dict) -> RenderResponse:
        try:
            d = Design.model_validate(design)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors()) from e
        try:
            yaml_text = render_yaml(d, lib)
            ascii_text = render_ascii(d, lib)
        except FileNotFoundError as e:
            # Unknown component / board referenced.
            raise HTTPException(status_code=422, detail=str(e)) from e
        except ValueError as e:
            # Surfaced from the generator for incomplete-but-validating designs:
            # missing bus matching a `kind: bus` connection, etc.
            raise HTTPException(status_code=422, detail=str(e)) from e
        return RenderResponse(
            yaml=yaml_text,
            ascii=ascii_text,
            compatibility_warnings=_wire_compat(check_pin_compatibility(design, lib)),
        )

    @app.get("/examples", response_model=list[ExampleSummary], tags=["examples"])
    def list_examples() -> list[ExampleSummary]:
        return [_example_summary(p) for p in sorted(EXAMPLES_DIR.glob("*.json"))]

    @app.get("/examples/{example_id}", tags=["examples"])
    def get_example(example_id: str) -> dict:
        path = EXAMPLES_DIR / f"{example_id}.json"
        if not path.exists():
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
        try:
            Design.model_validate(req.design)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors()) from e
        try:
            design_id, saved_at = designs_store.save(req.design, design_id=req.design_id)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return SaveDesignResponse(id=design_id, saved_at=saved_at)

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
        return {"deleted": True, "id": design_id}

    @app.post("/library/recommend", response_model=RecommendResponse, tags=["library"])
    def recommend(req: RecommendRequest) -> RecommendResponse:
        constraints = Constraints(**(req.constraints or {})) if req.constraints else Constraints()
        results = recommend_components(lib, req.query, constraints=constraints, limit=req.limit)
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
                    rationale=r.rationale, notes=r.notes,
                )
                for r in results
            ],
        )

    # ---------------------------------------------------------------------
    # Fleet handoff (distributed-esphome ha-addon)
    # ---------------------------------------------------------------------

    @app.get("/fleet/status", response_model=FleetStatus, tags=["fleet"])
    def fleet_status() -> FleetStatus:
        fc = make_fleet()
        if not fc.is_configured():
            reason = "FLEET_URL not set" if not fc.base_url else "FLEET_TOKEN not set"
            return FleetStatus(available=False, reason=reason, url=fc.base_url or None)
        ok, reason = fc.is_available()
        return FleetStatus(available=ok, reason=reason, url=fc.base_url or None)

    @app.post("/fleet/push", response_model=FleetPushResponse, tags=["fleet"])
    def fleet_push(req: FleetPushRequest) -> FleetPushResponse:
        try:
            d = Design.model_validate(req.design)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors()) from e
        try:
            yaml_text = render_yaml(d, lib)
        except (FileNotFoundError, ValueError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from e

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
            result = fc.push_device(device_name, yaml_text, compile=req.compile)
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
    def fleet_job_log(run_id: str, offset: int = 0) -> FleetJobLogResponse:
        fc = make_fleet()
        if not fc.is_configured():
            raise HTTPException(
                status_code=503,
                detail="fleet not configured (set FLEET_URL and FLEET_TOKEN)",
            )
        try:
            chunk = fc.get_job_log(run_id, offset=offset)
        except FleetUnavailable as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        return FleetJobLogResponse(
            log=chunk.log, offset=chunk.offset, finished=chunk.finished,
        )

    @app.get("/agent/status", tags=["agent"])
    def agent_status() -> dict:
        ok, reason = agent_available()
        return {"available": ok, "reason": reason}

    @app.post("/agent/turn", response_model=AgentTurnResponse, tags=["agent"])
    def agent_turn(req: AgentTurnRequest) -> AgentTurnResponse:
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
    def agent_stream(req: AgentTurnRequest):
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

    return app


app = create_app()
