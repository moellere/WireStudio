"""HTTP request / response models. Distinct from `studio.model` and
`studio.library` so the wire shapes can evolve independently.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BoardSummary(_S):
    id: str
    name: str
    mcu: str
    chip_variant: str
    framework: str
    platformio_board: str
    flash_size_mb: Optional[int] = None
    rail_names: list[str]


class ComponentSummary(_S):
    id: str
    name: str
    category: str
    use_cases: list[str]
    aliases: list[str]
    required_components: list[str]
    current_ma_typical: Optional[float] = None
    current_ma_peak: Optional[float] = None


class ExampleSummary(_S):
    id: str
    name: str
    description: str
    board_library_id: str
    chip_family: str  # esp32 / esp8266 / ...


class CompatibilityWarning(_S):
    severity: str
    code: str
    pin: str
    component_id: str
    pin_role: str
    message: str


class RenderResponse(_S):
    yaml: str
    ascii: str
    compatibility_warnings: list[CompatibilityWarning] = []


class SolverWarning(_S):
    level: str
    code: str
    text: str


class PinAssignment(_S):
    component_id: str
    pin_role: str
    old_target: dict
    new_target: dict


class SolvePinsResponse(_S):
    design: dict
    assigned: list[PinAssignment]
    unresolved: list[SolverWarning]
    warnings: list[SolverWarning]
    compatibility_warnings: list[CompatibilityWarning] = []


class ValidateResponse(_S):
    ok: bool
    design_id: str
    name: str
    component_count: int
    bus_count: int
    connection_count: int
    warnings: list[dict]
    compatibility_warnings: list[CompatibilityWarning] = []


class AgentTurnRequest(_S):
    session_id: Optional[str] = None
    design: dict
    message: str


class AgentToolCall(_S):
    tool: str
    input: dict
    is_error: bool


class AgentTurnResponse(_S):
    session_id: str
    design: dict
    assistant_text: str
    tool_calls: list[AgentToolCall]
    stop_reason: str
    usage: dict


class AgentSessionMessage(_S):
    role: str
    content: str
    timestamp: str


class AgentSession(_S):
    session_id: str
    messages: list[AgentSessionMessage]


class UseCaseEntry(_S):
    """One row of GET /library/use_cases."""
    use_case: str
    count: int  # how many library components advertise this use_case
    example_components: list[str]  # up to 3 library_ids for hover preview


class RecommendRequest(_S):
    query: str
    limit: int = 10
    constraints: Optional[dict] = None


class Recommendation(_S):
    library_id: str
    name: str
    category: str
    use_cases: list[str]
    aliases: list[str]
    required_components: list[str]
    current_ma_typical: Optional[float] = None
    current_ma_peak: Optional[float] = None
    vcc_min: Optional[float] = None
    vcc_max: Optional[float] = None
    score: float
    in_examples: int
    rationale: str
    notes: Optional[str] = None


class RecommendResponse(_S):
    query: str
    matches: list[Recommendation]


class SaveDesignRequest(_S):
    design: dict
    design_id: Optional[str] = None  # if absent, derived from design.id


class SaveDesignResponse(_S):
    id: str
    saved_at: str


class SavedDesignSummary(_S):
    id: str
    name: str
    description: str
    board_library_id: str
    chip_family: str
    saved_at: str
    component_count: int


class FleetStatus(_S):
    available: bool
    reason: Optional[str] = None
    url: Optional[str] = None  # base URL when configured (no token)


class FleetPushRequest(_S):
    design: dict
    compile: bool = False
    device_name: Optional[str] = None  # override; defaults to fleet.device_name or design.id


class FleetPushResponse(_S):
    filename: str
    created: bool
    run_id: Optional[str] = None
    enqueued: int = 0


class FleetJobLogResponse(_S):
    log: str
    offset: int
    finished: bool
