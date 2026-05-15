"""HTTP request / response models. Distinct from `wirestudio.model` and
`wirestudio.library` so the wire shapes can evolve independently.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class _S(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BoardSummary(_S):
    id: str = Field(description="Board library id, e.g. 'esp32-devkitc-v4'.")
    name: str = Field(description="Human-readable board name.")
    mcu: str = Field(description="MCU family, e.g. 'esp32' or 'esp8266'.")
    chip_variant: str = Field(description="Specific chip variant, e.g. 'esp32c3'.")
    framework: str = Field(description="Default build framework ('arduino' or 'esp-idf').")
    platformio_board: str = Field(description="PlatformIO board key used in the generated YAML.")
    flash_size_mb: Optional[int] = Field(default=None, description="Onboard flash size in MB, if known.")
    rail_names: list[str] = Field(description="Power rail names the board exposes, e.g. ['3V3', 'GND'].")


class ComponentSummary(_S):
    id: str = Field(description="Component library id, e.g. 'bme280'.")
    name: str = Field(description="Human-readable component name.")
    category: str = Field(description="Component category, e.g. 'sensor' or 'display'.")
    use_cases: list[str] = Field(description="Capability tags the recommender matches queries against.")
    aliases: list[str] = Field(description="Alternative names/part numbers the component is known by.")
    required_components: list[str] = Field(
        description="Library ids this component depends on, e.g. an I2C bus."
    )
    current_ma_typical: Optional[float] = Field(
        default=None, description="Typical current draw in mA, if characterised."
    )
    current_ma_peak: Optional[float] = Field(
        default=None, description="Peak current draw in mA, if characterised."
    )


class ExampleSummary(_S):
    id: str = Field(description="Bundled example id, e.g. 'garage-motion'.")
    name: str = Field(description="Human-readable example name.")
    description: str = Field(description="One-line description of what the example builds.")
    board_library_id: str = Field(description="Library id of the board the example targets.")
    chip_family: str = Field(description="Chip family of the example's board ('esp32', 'esp8266', ...).")


class CompatibilityWarning(_S):
    severity: str = Field(description="Severity level: 'info', 'warn', or 'error'.")
    code: str = Field(description="Stable machine-readable warning code.")
    pin: str = Field(description="Pin the warning concerns.")
    component_id: str = Field(description="Design component id the warning concerns.")
    pin_role: str = Field(description="Component pin role the warning concerns.")
    message: str = Field(description="Human-readable explanation of the issue.")


class RenderResponse(_S):
    yaml: str = Field(description="Rendered ESPHome YAML.")
    ascii: str = Field(description="ASCII wiring diagram and BOM.")
    compatibility_warnings: list[CompatibilityWarning] = Field(
        default_factory=list, description="Pin/electrical compatibility warnings raised while rendering."
    )


class SolverWarning(_S):
    level: str = Field(description="Severity level: 'info', 'warn', or 'error'.")
    code: str = Field(description="Stable machine-readable warning code.")
    text: str = Field(description="Human-readable explanation.")


class PinAssignment(_S):
    component_id: str = Field(description="Design component id whose pin was assigned.")
    pin_role: str = Field(description="Component pin role that was assigned.")
    old_target: dict = Field(description="Connection target before the solver ran.")
    new_target: dict = Field(description="Connection target the solver chose.")


class SolvePinsResponse(_S):
    design: dict = Field(description="The design with solver-assigned pins applied.")
    assigned: list[PinAssignment] = Field(description="Pin assignments the solver made.")
    unresolved: list[SolverWarning] = Field(
        description="Connections the solver could not assign a legal pin to."
    )
    warnings: list[SolverWarning] = Field(description="Non-fatal issues raised during solving.")
    compatibility_warnings: list[CompatibilityWarning] = Field(
        default_factory=list, description="Pin/electrical compatibility warnings for the solved design."
    )


class ValidateResponse(_S):
    ok: bool = Field(description="True when the design has no error-level warnings.")
    design_id: str = Field(description="Id of the validated design.")
    name: str = Field(description="Name of the validated design.")
    component_count: int = Field(description="Number of components in the design.")
    bus_count: int = Field(description="Number of buses in the design.")
    connection_count: int = Field(description="Number of connections in the design.")
    warnings: list[dict] = Field(description="Design-level warnings carried in design.json.")
    compatibility_warnings: list[CompatibilityWarning] = Field(
        default_factory=list, description="Pin/electrical compatibility warnings for the design."
    )


class AgentTurnRequest(_S):
    session_id: Optional[str] = Field(
        default=None, description="Existing session to continue; omit to start a new one."
    )
    design: dict = Field(description="The current design.json the agent should operate on.")
    message: str = Field(description="The user's natural-language message for this turn.")


class AgentToolCall(_S):
    tool: str = Field(description="Name of the tool the agent invoked.")
    input: dict = Field(description="Arguments the agent passed to the tool.")
    is_error: bool = Field(description="True when the tool call returned an error.")


class AgentTurnResponse(_S):
    session_id: str = Field(description="Session id (newly created if none was supplied).")
    design: dict = Field(description="The design.json after the agent's edits this turn.")
    assistant_text: str = Field(description="The agent's natural-language reply.")
    tool_calls: list[AgentToolCall] = Field(description="Tools the agent invoked during the turn.")
    stop_reason: str = Field(description="Why the turn ended, e.g. 'end_turn'.")
    usage: dict = Field(description="Token usage reported by the model.")


class AgentSessionMessage(_S):
    role: str = Field(description="Message author: 'user' or 'assistant'.")
    content: str = Field(description="Message text.")
    timestamp: str = Field(description="ISO 8601 timestamp the message was recorded.")


class AgentSession(_S):
    session_id: str = Field(description="Session id.")
    messages: list[AgentSessionMessage] = Field(description="Conversation history, oldest first.")


class UseCaseEntry(_S):
    """One row of GET /library/use_cases."""
    use_case: str = Field(description="The capability tag.")
    count: int = Field(description="How many library components advertise this use_case.")
    example_components: list[str] = Field(
        description="Up to 3 library ids advertising the use_case, for hover preview."
    )


class RecommendRequest(_S):
    query: str = Field(description="Free-text capability query, e.g. 'temperature humidity'.")
    limit: int = Field(default=10, description="Maximum number of matches to return.")
    constraints: Optional[dict] = Field(
        default=None, description="Optional filters (voltage, max current, bus, excluded categories)."
    )


class Recommendation(_S):
    library_id: str = Field(description="Recommended component's library id.")
    name: str = Field(description="Human-readable component name.")
    category: str = Field(description="Component category.")
    use_cases: list[str] = Field(description="Capability tags the component advertises.")
    aliases: list[str] = Field(description="Alternative names/part numbers.")
    required_components: list[str] = Field(description="Library ids this component depends on.")
    current_ma_typical: Optional[float] = Field(
        default=None, description="Typical current draw in mA, if characterised."
    )
    current_ma_peak: Optional[float] = Field(
        default=None, description="Peak current draw in mA, if characterised."
    )
    vcc_min: Optional[float] = Field(default=None, description="Minimum supply voltage in volts, if known.")
    vcc_max: Optional[float] = Field(default=None, description="Maximum supply voltage in volts, if known.")
    score: float = Field(description="Recommender score; higher ranks first.")
    in_examples: int = Field(description="Number of bundled examples that use this component.")
    rationale: str = Field(description="Human-readable explanation of why it was recommended.")
    notes: Optional[str] = Field(default=None, description="Extra caveats or usage notes, if any.")


class RecommendResponse(_S):
    query: str = Field(description="The query that was matched.")
    matches: list[Recommendation] = Field(description="Recommended components, highest score first.")


class SaveDesignRequest(_S):
    design: dict = Field(description="The design.json to persist.")
    design_id: Optional[str] = Field(
        default=None, description="Id to save under; if absent, derived from design.id."
    )


class SaveDesignResponse(_S):
    id: str = Field(description="Id the design was saved under.")
    saved_at: str = Field(description="ISO 8601 timestamp the design was saved.")


class SavedDesignSummary(_S):
    id: str = Field(description="Saved design id.")
    name: str = Field(description="Design name.")
    description: str = Field(description="Design description.")
    board_library_id: str = Field(description="Library id of the design's board.")
    chip_family: str = Field(description="Chip family of the design's board.")
    saved_at: str = Field(description="ISO 8601 timestamp the design was last saved.")
    component_count: int = Field(description="Number of components in the design.")


class FleetStatus(_S):
    available: bool = Field(description="True when the fleet addon is configured and reachable.")
    reason: Optional[str] = Field(
        default=None, description="Why the fleet is unavailable, when available is false."
    )
    url: Optional[str] = Field(
        default=None, description="Configured fleet base URL (token is never returned)."
    )


class FleetPushRequest(_S):
    design: dict = Field(description="The design.json to push to the fleet addon.")
    compile: bool = Field(default=False, description="Enqueue an OTA compile after pushing the YAML.")
    device_name: Optional[str] = Field(
        default=None, description="Override device name; defaults to fleet.device_name or design.id."
    )
    strict: bool = Field(
        default=False, description="Refuse the push when warn/error compatibility entries remain."
    )


class FleetPushResponse(_S):
    filename: str = Field(description="Filename the YAML was stored under on the fleet addon.")
    created: bool = Field(description="True if a new device file was created, false if updated.")
    run_id: Optional[str] = Field(default=None, description="Compile run id, when compile was requested.")
    enqueued: int = Field(default=0, description="Number of compile jobs enqueued.")


class FleetJobLogResponse(_S):
    log: str = Field(description="Compile log text from the requested offset.")
    offset: int = Field(description="Byte offset to pass on the next poll to resume the log.")
    finished: bool = Field(description="True when the compile job has finished.")
