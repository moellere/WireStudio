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
