"""The agentic loop: Claude + tool calls + design mutation."""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass
from typing import Any, Iterator, Optional

from wirestudio.agent.session import SessionStore, FileSessionStore, new_session_id
from wirestudio.agent.tools import TOOL_SCHEMAS, execute_tool
from wirestudio.library import Library, default_library

# Guard the import so the module is still importable in environments that
# haven't installed `anthropic` yet (the API endpoint will then 503).
try:
    import anthropic  # noqa: F401
    _ANTHROPIC_INSTALLED = True
except ImportError:  # pragma: no cover - exercised in deployment, not tests
    _ANTHROPIC_INSTALLED = False


SYSTEM_INSTRUCTIONS = """\
You are a helper inside wirestudio, a tool that turns a `design.json` \
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
        return False, "anthropic SDK not installed; install wirestudio[agent]."
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



def _initialize_turn(design: dict, user_message: str, session_id: Optional[str], sessions: Optional[SessionStore], library: Library):
    sessions_store = sessions or FileSessionStore()
    sid = session_id or new_session_id()
    history = sessions_store.load(sid)
    working_design = copy.deepcopy(design)
    messages: list[dict[str, Any]] = [{"role": entry["role"], "content": entry["content"]} for entry in history]
    messages.append({"role": "user", "content": _build_user_message(working_design, user_message)})
    library_block = _build_library_context(library)
    return sid, sessions_store, working_design, messages, library_block

def _process_tool_calls(response, working_design: dict, library: Library, tool_calls_log: list[dict]):
    tool_results: list[dict] = []
    events = []
    for block in response.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        tool_input = dict(block.input)
        events.append({
            "type": "tool_use_start",
            "tool_use_id": block.id,
            "tool": block.name,
            "input": tool_input,
        })
        result_str, is_error = execute_tool(block.name, tool_input, working_design, library)
        events.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "tool": block.name,
            "is_error": is_error,
        })
        tool_calls_log.append({
            "tool": block.name,
            "input": tool_input,
            "is_error": is_error,
        })
        tool_results.append({
            "type": "tool_result",
            "tool_use_id": block.id,
            "content": result_str,
            "is_error": is_error,
        })
    return tool_results, events


def stream_turn_events(
    *,
    design: dict,
    user_message: str,
    session_id: Optional[str] = None,
    library: Optional[Library] = None,
    sessions: Optional[SessionStore] = None,
    model: str = "claude-opus-4-7",
    max_iterations: int = 12,
) -> Iterator[dict]:
    """Run a single user turn and yield events as they happen."""
    available, reason = is_available()
    if not available:
        yield {"type": "error", "message": reason or "agent unavailable"}
        return

    library_instance = library or default_library()

    sid, sessions_store, working_design, messages, library_block = _initialize_turn(
        design, user_message, session_id, sessions, library_instance
    )

    yield {"type": "session_start", "session_id": sid}

    import anthropic
    client = anthropic.Anthropic()

    tool_calls_log: list[dict] = []
    accumulated_usage = {"input_tokens": 0, "output_tokens": 0,
                         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}

    final_text_pieces: list[str] = []
    stop_reason = ""

    try:
        for _ in range(max_iterations):
            with client.messages.stream(
                model=model,
                max_tokens=4096,
                thinking={"type": "adaptive"},
                system=[
                    {"type": "text", "text": SYSTEM_INSTRUCTIONS},
                    {"type": "text", "text": library_block, "cache_control": {"type": "ephemeral"}},
                ],
                tools=TOOL_SCHEMAS,
                messages=messages,
            ) as stream:
                for event in stream:
                    etype = getattr(event, "type", None)
                    if etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta is not None and getattr(delta, "type", None) == "text_delta":
                            yield {"type": "text_delta", "text": delta.text}
                response = stream.get_final_message()

            for k in accumulated_usage:
                accumulated_usage[k] += getattr(response.usage, k, 0) or 0

            stop_reason = response.stop_reason or ""

            text_pieces = [b.text for b in response.content if getattr(b, "type", None) == "text"]
            if text_pieces:
                final_text_pieces = text_pieces

            if response.stop_reason != "tool_use":
                break

            messages.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})
            tool_results, tool_events = _process_tool_calls(response, working_design, library_instance, tool_calls_log)
            for event in tool_events:
                yield event
            messages.append({"role": "user", "content": tool_results})
        else:
            if not final_text_pieces:
                final_text_pieces = ["(agent exceeded max iterations without finishing the turn)"]
    except anthropic.APIError as e:
        yield {"type": "error", "message": f"agent API call failed: {e}"}
        return

    final_text = "\n\n".join(final_text_pieces).strip() if final_text_pieces else ""

    sessions_store.append(sid, "user", user_message)
    sessions_store.append(sid, "assistant", final_text or "(no reply)")

    yield {
        "type": "turn_complete",
        "session_id": sid,
        "design": working_design,
        "assistant_text": final_text,
        "tool_calls": tool_calls_log,
        "stop_reason": stop_reason,
        "usage": accumulated_usage,
    }



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
    """Non-streaming wrapper. Consumes stream_turn_events and collapses
    its events into a TurnResult so existing callers don't change."""
    final: dict | None = None
    error_msg: str | None = None
    for event in stream_turn_events(
        design=design,
        user_message=user_message,
        session_id=session_id,
        library=library,
        sessions=sessions,
        model=model,
        max_iterations=max_iterations,
    ):
        if event["type"] == "turn_complete":
            final = event
        elif event["type"] == "error":
            error_msg = event["message"]

    if final is None:
        raise RuntimeError(error_msg or "agent turn did not complete")
    return TurnResult(
        session_id=final["session_id"],
        design=final["design"],
        assistant_text=final["assistant_text"],
        tool_calls=final["tool_calls"],
        stop_reason=final["stop_reason"],
        usage=final["usage"],
    )
