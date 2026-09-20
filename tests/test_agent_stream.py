"""Failure-mode coverage for the agent streaming loop.

`tests/test_agent.py` covers the pure-Python tools, the session store, and
the API contract. What it does not cover is what `stream_turn_events` /
`run_turn` do when the model call goes wrong: the Anthropic API errors out,
the connection drops mid-stream, the model loops on tool calls past the
iteration cap, or a tool returns an error result. Those are exactly the
paths a live deployment hits and the unit tests never exercised, so we
fake the Anthropic client here and drive each branch.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import anthropic
import httpx
import pytest

from wirestudio.agent import agent as agent_mod
from wirestudio.agent.agent import run_turn, stream_turn_events
from wirestudio.agent.session import FileSessionStore

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


@pytest.fixture
def design() -> dict:
    return json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())


@pytest.fixture
def store(tmp_path) -> FileSessionStore:
    return FileSessionStore(root=tmp_path)


# ---------------------------------------------------------------------------
# Fakes for the Anthropic streaming client
# ---------------------------------------------------------------------------

def _text_delta(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="content_block_delta",
        delta=SimpleNamespace(type="text_delta", text=text),
    )


def _usage(**kw) -> SimpleNamespace:
    base = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def _text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def _tool_use_block(id_: str, name: str, input_: dict) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=input_)


def _message(content, stop_reason, usage=None) -> SimpleNamespace:
    return SimpleNamespace(content=content, stop_reason=stop_reason, usage=usage or _usage())


class _FakeStream:
    """Context manager standing in for `client.messages.stream(...)`."""

    def __init__(self, deltas, final_message):
        self._deltas = deltas
        self._final = final_message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(self._deltas)

    def get_final_message(self):
        return self._final


class _FakeMessages:
    """Hands out one queued stream (or raises one queued exception) per call."""

    def __init__(self, steps):
        self._steps = list(steps)
        self.calls = 0

    def stream(self, **kwargs):
        step = self._steps[self.calls] if self.calls < len(self._steps) else self._steps[-1]
        self.calls += 1
        if isinstance(step, Exception):
            raise step
        return step


class _FakeClient:
    def __init__(self, steps):
        self.messages = _FakeMessages(steps)


def _install_client(monkeypatch, steps) -> _FakeClient:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = _FakeClient(steps)
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: client)
    return client


def _collect(design, store, **kw):
    return list(
        stream_turn_events(design=design, user_message="hi", sessions=store, **kw)
    )


# ---------------------------------------------------------------------------
# Unavailable
# ---------------------------------------------------------------------------

def test_stream_errors_without_api_key(monkeypatch, design, store):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(agent_mod, "_ANTHROPIC_INSTALLED", True)
    events = _collect(design, store)
    assert events == [{"type": "error", "message": agent_mod.is_available()[1]}]
    assert "ANTHROPIC_API_KEY" in events[0]["message"]


def test_run_turn_raises_without_api_key(monkeypatch, design, store):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(agent_mod, "_ANTHROPIC_INSTALLED", True)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        run_turn(design=design, user_message="hi", sessions=store)


# ---------------------------------------------------------------------------
# API / connection failures
# ---------------------------------------------------------------------------

def test_stream_reports_connection_drop(monkeypatch, design, store):
    err = anthropic.APIConnectionError(
        message="connection dropped",
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    _install_client(monkeypatch, [err])
    events = _collect(design, store)
    # session_start fires before the model call; then the error; no completion.
    assert events[0]["type"] == "session_start"
    assert events[-1]["type"] == "error"
    assert "connection dropped" in events[-1]["message"]
    assert not any(e["type"] == "turn_complete" for e in events)


def test_run_turn_raises_on_api_error(monkeypatch, design, store):
    class _Boom(anthropic.APIError):
        def __init__(self):
            Exception.__init__(self, "rate limited")
            self.message = "rate limited"

    _install_client(monkeypatch, [_Boom()])
    with pytest.raises(RuntimeError, match="rate limited"):
        run_turn(design=design, user_message="hi", sessions=store)


def test_error_after_partial_stream_still_aborts(monkeypatch, design, store):
    # First iteration streams some text + a tool_use, second call drops.
    step1 = _FakeStream(
        [_text_delta("working on it")],
        _message([_tool_use_block("tu1", "list_boards", {})], "tool_use"),
    )
    err = anthropic.APIConnectionError(
        message="boom mid-turn",
        request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"),
    )
    _install_client(monkeypatch, [step1, err])
    events = _collect(design, store)
    assert any(e["type"] == "text_delta" for e in events)
    assert any(e["type"] == "tool_result" for e in events)
    assert events[-1]["type"] == "error"
    assert "boom mid-turn" in events[-1]["message"]
    assert not any(e["type"] == "turn_complete" for e in events)


# ---------------------------------------------------------------------------
# Iteration cap
# ---------------------------------------------------------------------------

def test_stream_max_iterations_exhausted(monkeypatch, design, store):
    # The model never stops calling tools. After max_iterations the loop
    # gives up and reports the cap message rather than spinning forever.
    looping = _FakeStream(
        [], _message([_tool_use_block("tu", "list_boards", {})], "tool_use")
    )
    client = _install_client(monkeypatch, [looping])
    events = _collect(design, store, max_iterations=3)
    complete = next(e for e in events if e["type"] == "turn_complete")
    assert "exceeded max iterations" in complete["assistant_text"]
    assert complete["stop_reason"] == "tool_use"
    assert client.messages.calls == 3
    # Each iteration ran the tool, so the log has one entry per call.
    assert len(complete["tool_calls"]) == 3


# ---------------------------------------------------------------------------
# Tool error result flows back into the turn
# ---------------------------------------------------------------------------

def test_tool_error_does_not_abort_turn(monkeypatch, design, store):
    # First the model calls an unknown tool (execute_tool returns is_error),
    # then it recovers and ends the turn with text. The error result should
    # be recorded and surfaced, not crash the loop.
    step1 = _FakeStream(
        [], _message([_tool_use_block("tu1", "no_such_tool", {})], "tool_use")
    )
    step2 = _FakeStream(
        [_text_delta("fixed it")], _message([_text_block("fixed it")], "end_turn")
    )
    _install_client(monkeypatch, [step1, step2])
    events = _collect(design, store)

    tool_results = [e for e in events if e["type"] == "tool_result"]
    assert len(tool_results) == 1
    assert tool_results[0]["is_error"] is True

    complete = next(e for e in events if e["type"] == "turn_complete")
    assert complete["assistant_text"] == "fixed it"
    assert complete["stop_reason"] == "end_turn"
    assert complete["tool_calls"][0]["is_error"] is True


# ---------------------------------------------------------------------------
# Happy path (anchors the failure tests against a known-good baseline)
# ---------------------------------------------------------------------------

def test_stream_happy_path_accumulates_usage_and_text(monkeypatch, design, store):
    step = _FakeStream(
        [_text_delta("Added "), _text_delta("a BME280.")],
        _message(
            [_text_block("Added a BME280.")],
            "end_turn",
            usage=_usage(input_tokens=100, output_tokens=20, cache_read_input_tokens=80),
        ),
    )
    _install_client(monkeypatch, [step])
    events = _collect(design, store)

    deltas = [e["text"] for e in events if e["type"] == "text_delta"]
    assert deltas == ["Added ", "a BME280."]

    complete = next(e for e in events if e["type"] == "turn_complete")
    assert complete["assistant_text"] == "Added a BME280."
    assert complete["usage"]["input_tokens"] == 100
    assert complete["usage"]["output_tokens"] == 20
    assert complete["usage"]["cache_read_input_tokens"] == 80
    # The session got the user + assistant turns persisted.
    assert [m["role"] for m in store.load(complete["session_id"])] == ["user", "assistant"]


def test_run_turn_collapses_stream_to_result(monkeypatch, design, store):
    step = _FakeStream(
        [_text_delta("done")], _message([_text_block("done")], "end_turn")
    )
    _install_client(monkeypatch, [step])
    result = run_turn(design=design, user_message="hi", sessions=store)
    assert result.assistant_text == "done"
    assert result.stop_reason == "end_turn"
    assert result.session_id


# ---------------------------------------------------------------------------
# Within-turn context compaction
# ---------------------------------------------------------------------------

def _turn(tool_id, name, input_, result):
    return [
        {"role": "assistant", "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": input_}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": result, "is_error": False}]},
    ]


def test_compact_tool_results_keeps_only_the_latest_of_each_read():
    from wirestudio.agent.agent import compact_tool_results

    big = "x" * 5000
    messages = [{"role": "user", "content": "Current design state: ..."}]
    messages += _turn("t1", "render", {}, big)
    messages += _turn("t2", "library_detail", {"library_id": "bme280"}, big)
    messages += _turn("t3", "set_param", {"instance_id": "a", "key": "k", "value": 1}, big)
    messages += _turn("t4", "render", {}, big)
    messages += _turn("t5", "library_detail", {"library_id": "adc"}, big)
    messages += _turn("t6", "validate", {}, "ok")  # small: never worth a digest

    removed = compact_tool_results(messages)
    results = {m["content"][0]["tool_use_id"]: m["content"][0]["content"]
               for m in messages if m["role"] == "user" and isinstance(m["content"], list)}
    assert results["t1"].startswith("[superseded render result trimmed (5000 chars)")
    assert results["t4"] == big  # the latest render is verbatim
    assert results["t2"] == big and results["t5"] == big  # different ids: both current
    assert results["t3"] == big  # a mutating tool's result is never touched
    assert results["t6"] == "ok"
    assert removed == 5000 - len(results["t1"])
    # Idempotent: a second pass finds nothing more to trim.
    assert compact_tool_results(messages) == 0


def test_stream_trims_superseded_renders_before_the_next_call(monkeypatch, design, store):
    """Three renders in one turn: by the final call only the last render's
    YAML and ASCII are still in the context."""
    seen: list[list[dict]] = []
    original_stream = _FakeMessages.stream

    def recording_stream(self, **kwargs):
        seen.append(copy.deepcopy(kwargs["messages"]))
        return original_stream(self, **kwargs)
    monkeypatch.setattr(_FakeMessages, "stream", recording_stream)

    steps = [
        _FakeStream([], _message([_tool_use_block(f"r{i}", "render", {})], "tool_use"))
        for i in range(3)
    ] + [_FakeStream([_text_delta("done")], _message([_text_block("done")], "end_turn"))]
    _install_client(monkeypatch, steps)
    events = _collect(design, store)
    assert events[-1]["type"] == "turn_complete"

    last = seen[-1]
    results = [b for m in last if m["role"] == "user" and isinstance(m["content"], list)
               for b in m["content"] if b["type"] == "tool_result"]
    assert len(results) == 3
    assert results[0]["content"].startswith("[superseded render result trimmed")
    assert results[1]["content"].startswith("[superseded render result trimmed")
    assert results[2]["content"].startswith("{") and "esphome" in results[2]["content"]
    full = sum(len(b["content"]) for b in results)
    untrimmed = 3 * len(results[2]["content"])
    assert full < untrimmed / 2


def test_stream_reports_a_429_with_its_status(monkeypatch, design, store):
    """The SDK retries 429s itself; once it gives up the stream reports it
    as an error event rather than raising through the SSE generator."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.RateLimitError(
        "rate limited", response=httpx.Response(429, request=request), body=None,
    )
    _install_client(monkeypatch, [err])
    events = _collect(design, store)
    assert events[-1]["type"] == "error"
    assert "agent API call failed" in events[-1]["message"]
    assert "429" in events[-1]["message"] or "rate limited" in events[-1]["message"]
    with pytest.raises(RuntimeError):
        run_turn(design=design, user_message="hi", sessions=store)
