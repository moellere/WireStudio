from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from studio import __version__
from studio.api.schemas import (
    BoardSummary,
    ComponentSummary,
    ExampleSummary,
    RenderResponse,
    ValidateResponse,
)
from studio.generate.ascii_gen import render_ascii
from studio.generate.yaml_gen import render_yaml
from studio.library import Library, LibraryBoard, LibraryComponent, default_library
from studio.model import Design

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


def create_app(library: Optional[Library] = None) -> FastAPI:
    lib = library or default_library()

    app = FastAPI(
        title="esphome-studio API",
        version=__version__,
        description=(
            "Read-only library + stateless render/validate over `design.json`. "
            "Pure layer over `studio.generate`; no server-side state."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

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
        )

    @app.post("/design/render", response_model=RenderResponse, tags=["design"])
    def render(design: dict) -> RenderResponse:
        try:
            d = Design.model_validate(design)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors()) from e
        try:
            return RenderResponse(
                yaml=render_yaml(d, lib),
                ascii=render_ascii(d, lib),
            )
        except FileNotFoundError as e:
            # Unknown component / board referenced.
            raise HTTPException(status_code=422, detail=str(e)) from e

    @app.get("/examples", response_model=list[ExampleSummary], tags=["examples"])
    def list_examples() -> list[ExampleSummary]:
        return [_example_summary(p) for p in sorted(EXAMPLES_DIR.glob("*.json"))]

    @app.get("/examples/{example_id}", tags=["examples"])
    def get_example(example_id: str) -> dict:
        path = EXAMPLES_DIR / f"{example_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Unknown example '{example_id}'")
        return json.loads(path.read_text())

    return app


app = create_app()
