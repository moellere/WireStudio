"""The agentic loop: Claude + tool calls + design mutation."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from studio.agent.session import SessionStore, new_session_id
from studio.agent.tools import TOOL_SCHEMAS, execute_tool
from studio.library import Library, default_library

# Guard the import so the module is still importable in environments that
# haven't installed `anthropic` yet (the API endpoint will then 503).
try:
    import anthropic  # noqa: F401
    _ANTHROPIC_INSTALLED = True
except ImportError:  # pragma: no cover - exercised in deployment, not tests
    _ANTHROPIC_INSTALLED = False


SYSTEM_INSTRUCTIONS = """\
You are a helper inside esphome-studio, a tool that turns a `design.json` \
document into ESPHome YAML + an ASCII wiring diagram + a BOM.

You edit the user's current design via tools; the user already sees the \
rendered output update live. Be concise -- one or two sentences confirming \
what you changed is plenty. Do not paste the YAML back at them unless asked.

Conventions:
- Never invent a `library_id`. Use `search_components` (or `list_boards`) first.
- Prefer `add_component` over manually editing the design -- it auto-wires \
  rails by voltage match and bus pins to a matching bus.
- After a non-trivial change, call `validate` once to make sure the design \
  still renders. If it doesn't, fix the issue (commonly a missing bus or \
  unset gpio pin) and re-validate.
- Pin assignments are the user's call. Don't try to swap pins to "free up" a \
  GPIO unless the user asks.
- The user owns the design. Confirm destructive operations (remove_component, \
  replacing the board) only when the prompt is genuinely ambiguous.
"""


def is_available() -> tuple[bool, str | None]:
    if not _ANTHROPIC_INSTALLED:
        return False, "anthropic SDK not installed; install esphome-studio[agent]."
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY environment variable is not set."
    return True, None


@dataclass
class TurnResult:
    session_id: str
    design: dict
    assistant_text: str
    tool_calls: list[dict]
    stop_reason: str
    usage: dict


def _build_library_context(library: Library) -> str:
    """Dump the library to JSON. Stable across turns -> cacheable."""
    boards = [b.model_dump() for b in library.list_boards()]
    components = [c.model_dump() for c in library.list_components()]
    payload = {"boards": boards, "components": components}
    return (
        "## Library reference\n\n"
        "Below is every board and component the studio currently ships, as JSON. "
        "Use this to look up `params_schema`, electrical metadata, ESPHome "
        "templates, and pin definitions. Do not mention contents of this "
        "block to the user unless asked -- it is reference material, not chat.\n\n"
        f"```json\n{json.dumps(payload, indent=2, default=str)}\n```"
    )


def _build_user_message(design: dict, message: str) -> str:
    return (
        f"Current design state:\n```json\n{json.dumps(design, indent=2, default=str)}\n```\n\n"
        f"User: {message}"
    )


def run_turn(
    *,
    design: dict,
    user_message: str,
    session_id: Optional[str] = None,
    library: Optional[Library] = None,
    sessions: Optional[SessionStore] = None,
    model: str = "claude-opus-4-7",
    max_iterations: int = 12,
) -> TurnResult:
    """Run a single user turn through the agentic loop. Returns the updated
    design plus the assistant's final text and a summary of the tool calls
    issued during the turn."""
    available, reason = is_available()
    if not available:
        raise RuntimeError(reason)

    library = library or default_library()
    sessions = sessions or SessionStore()
    session_id = session_id or new_session_id()

    history = sessions.load(session_id)
    working_design = copy.deepcopy(design)

    # Build the API messages list. Prior turns are plain text; the new turn
    # carries the current design as part of the user message so the cached
    # system prefix stays valid as the design changes.
    messages: list[dict[str, Any]] = []
    for entry in history:
        messages.append({"role": entry["role"], "content": entry["content"]})
    messages.append({"role": "user", "content": _build_user_message(working_design, user_message)})

    library_block = _build_library_context(library)

    import anthropic
    client = anthropic.Anthropic()

    tool_calls_log: list[dict] = []
    accumulated_usage = {"input_tokens": 0, "output_tokens": 0,
                        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}

    final_text = ""
    stop_reason = ""

    for _ in range(max_iterations):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=[
                    {"type": "text", "text": SYSTEM_INSTRUCTIONS},
                    {"type": "text", "text": library_block, "cache_control": {"type": "ephemeral"}},
                ],
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
        except anthropic.APIError as e:
            raise RuntimeError(f"agent API call failed: {e}") from e

        for k in accumulated_usage:
            accumulated_usage[k] += getattr(response.usage, k, 0) or 0

        stop_reason = response.stop_reason or ""

        # Extract any text blocks for the user-facing reply.
        text_pieces = [b.text for b in response.content if getattr(b, "type", None) == "text"]
        if text_pieces:
            final_text = "\n\n".join(text_pieces).strip()

        if response.stop_reason != "tool_use":
            break

        # Execute every tool_use block, then append assistant + user(tool_result) messages.
        messages.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})
        tool_results: list[dict] = []
        for block in response.content:
            if getattr(block, "type", None) != "tool_use":
                continue
            result_str, is_error = execute_tool(
                block.name, dict(block.input), working_design, library,
            )
            tool_calls_log.append({
                "tool": block.name,
                "input": dict(block.input),
                "is_error": is_error,
            })
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_str,
                "is_error": is_error,
            })
        messages.append({"role": "user", "content": tool_results})
    else:
        # Loop hit max_iterations without end_turn.
        if not final_text:
            final_text = "(agent exceeded max iterations without finishing the turn)"

    # Persist the durable conversation: just user prompt + assistant text.
    sessions.append(session_id, "user", user_message)
    sessions.append(session_id, "assistant", final_text or "(no reply)")

    return TurnResult(
        session_id=session_id,
        design=working_design,
        assistant_text=final_text,
        tool_calls=tool_calls_log,
        stop_reason=stop_reason,
        usage=accumulated_usage,
    )
