"""The agent eval harness: the task list is well-formed and every task's
reference solution passes the scorer within its budget, the scorer
catches what the `validate` tool lets through, and the runner turns a
turn into a row. `esphome config` runs only where the CLI is installed;
the agent-eval workflow's `solutions` job runs the replay with it."""
from __future__ import annotations

import copy
import json
import os
from types import SimpleNamespace

import anthropic
import pytest

from wirestudio.agent import eval as ev
from wirestudio.library import Library, default_library
from wirestudio.validate import esphome_available

TASKS = ev.load_tasks()
BY_ID = {t.id: t for t in TASKS.tasks}


@pytest.fixture
def library(tmp_path) -> Library:
    return Library(default_library().root, tmp_path / "user-library")


def test_task_list_shape():
    assert 20 <= len(TASKS.tasks) <= 30
    examples = {t.example for t in TASKS.tasks}
    assert len(examples) >= 8
    prompts = [t.prompt for t in TASKS.tasks]
    assert len(set(prompts)) == len(prompts)
    kinds = {"unchanged", "components", "absent", "connections", "buses", "params", "board", "count"}
    covered = {k for t in TASKS.tasks for k, v in t.expect.model_dump().items() if v}
    assert kinds <= covered


@pytest.mark.parametrize("task_id", sorted(BY_ID))
def test_reference_solution_passes(task_id, library, tmp_path):
    task = BY_ID[task_id]
    initial = ev.load_example(task, library)
    final, log, _, _ = ev.solution_driver(library)(task, copy.deepcopy(initial))
    result = ev.score(task, initial, final, log, library,
                      esphome=esphome_available(), workdir=tmp_path)
    assert result.passed, result.reasons


def test_load_rejects_a_solution_over_budget(tmp_path):
    raw = {"gate": {"min_pass": 0, "claude_code_min_pass": 0}, "tasks": [{
        "id": "x", "example": "garage-motion", "prompt": "p", "budget": 1,
        "expect": {}, "solution": [["render"], ["render"]],
    }]}
    path = tmp_path / "t.yaml"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="budget"):
        ev.load_tasks(path)


def test_load_rejects_an_unknown_expect_key(tmp_path):
    raw = {"gate": {"min_pass": 0, "claude_code_min_pass": 0}, "tasks": [{
        "id": "x", "example": "garage-motion", "prompt": "p", "budget": 1,
        "expect": {"componets": ["bme280"]}, "solution": [["render"]],
    }]}
    path = tmp_path / "t.yaml"
    path.write_text(json.dumps(raw))
    with pytest.raises(Exception, match="componets"):
        ev.load_tasks(path)


# ---------------------------------------------------------------------------
# What the scorer catches that `validate` does not
# ---------------------------------------------------------------------------

def _garage(library) -> dict:
    return ev.load_example(BY_ID["add-oled"], library)


def test_unbound_pin_fails_validity(library):
    d = _garage(library)
    ev.apply_calls(d, [("add_component", {"library_id": "gpio_output"})], library)
    reasons = ev.structural_failures(d, library)
    assert reasons == ["gpio_output_1.OUT is unbound"]


def test_shared_pin_fails_validity(library):
    d = _garage(library)
    ev.apply_calls(d, [("set_connection", {
        "component_id": "pir1", "pin_role": "OUT", "target": {"kind": "gpio", "pin": "GPIO21"}})], library)
    assert ev.structural_failures(d, library) == ["GPIO21 shared by i2c0.sda, pir1.OUT"]


def test_pin_off_the_board_fails_validity(library):
    d = _garage(library)
    ev.apply_calls(d, [("set_board", {"library_id": "wemos-d1-mini"})], library)
    reasons = ev.structural_failures(d, library)
    assert "bus i2c0.sda on GPIO21, not a wemos-d1-mini pin" in reasons
    assert "pir1.OUT on GPIO13, not a wemos-d1-mini pin" in reasons


def test_incomplete_bus_fails_validity(library):
    d = ev.load_example(BY_ID["ds18b20-needs-bus"], library)
    ev.apply_calls(d, [("add_component", {"library_id": "ds18b20"})], library)
    assert ev.structural_failures(d, library) == ["bus 1wire_1 has no pin"]


def test_change_failures_name_each_miss(library):
    task = BY_ID["compound-oled-and-pin"]
    initial = _garage(library)
    reasons = ev.change_failures(task.expect, initial, copy.deepcopy(initial))
    assert reasons == [
        "no ssd1306 in the design",
        'pir1.OUT not on {"kind": "gpio", "pin": "GPIO27"}',
    ]


def test_unchanged_expect_fails_on_any_edit(library):
    task = BY_ID["unknown-part"]
    initial = _garage(library)
    edited = copy.deepcopy(initial)
    ev.apply_calls(edited, [("set_strict", {"enabled": True})], library)
    assert ev.change_failures(task.expect, initial, edited) == ["the design changed"]
    assert ev.change_failures(task.expect, initial, copy.deepcopy(initial)) == []


# ---------------------------------------------------------------------------
# The runner
# ---------------------------------------------------------------------------

def test_run_tasks_scores_a_driver_that_does_nothing(library, tmp_path):
    tasks = [BY_ID["add-oled"], BY_ID["describe-design"]]

    def noop(task, design):
        return design, [], {"input_tokens": 10, "output_tokens": 2}, "sure"

    results = ev.run_tasks(tasks, library, noop, esphome=False, workdir=tmp_path, log=lambda s: None)
    by_id = {r.task: r for r in results}
    assert by_id["add-oled"].validates and not by_id["add-oled"].change
    assert by_id["add-oled"].reasons == ["no ssd1306 in the design", 'ssd1306.address != \'0x3C\'']
    assert by_id["describe-design"].passed
    assert by_id["describe-design"].usage == {"input_tokens": 10, "output_tokens": 2}


def test_run_tasks_turns_a_driver_error_into_a_failed_row(library, tmp_path):
    def boom(task, design):
        raise RuntimeError("agent API call failed: 529 overloaded")

    [r] = ev.run_tasks([BY_ID["strict-on"]], library, boom, esphome=False, workdir=tmp_path,
                       log=lambda s: None)
    assert not r.passed
    assert r.error == "RuntimeError: agent API call failed: 529 overloaded"


def test_budget_overrun_fails_the_task(library, tmp_path):
    task = BY_ID["set-address"]

    def chatty(t, design):
        final = copy.deepcopy(design)
        log = ev.apply_calls(final, [("render", {})] * 3 + ev._calls(t.solution), library)
        return final, log, {}, ""

    [r] = ev.run_tasks([task], library, chatty, esphome=False, workdir=tmp_path, log=lambda s: None)
    assert r.validates and r.change and not r.within_budget
    assert r.reasons == ["4 tool calls, budget 2"]


def test_summary_markdown_has_one_row_per_task():
    rows = [
        ev.TaskResult(task="a", example="e", prompt="p", passed=True, validates=True, change=True,
                      within_budget=True, calls=1, budget=2, usage={"input_tokens": 5}),
        ev.TaskResult(task="b", example="e", prompt="p", calls=3, budget=2,
                      reasons=["no x | y in the design"]),
    ]
    md = ev.summary_markdown(rows, title="T", min_pass=1)
    assert md.startswith("## T: 1/2 passed (gate 1)\n")
    assert "| a | e | yes | yes | 1/2 | pass |  |" in md
    assert "| b | e | no | no | 3/2 | FAIL | no x \\| y in the design |" in md


# ---------------------------------------------------------------------------
# The model driver, against a fake Anthropic client
# ---------------------------------------------------------------------------

class _Stream:
    def __init__(self, final):
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        return iter(())

    def get_final_message(self):
        return self._final


def _usage():
    return SimpleNamespace(input_tokens=100, output_tokens=10,
                           cache_creation_input_tokens=0, cache_read_input_tokens=0)


def _scripted_client(calls: list[tuple[str, dict]]):
    """A model that issues one tool call per turn, in order, then stops."""
    steps = [
        SimpleNamespace(content=[SimpleNamespace(type="tool_use", id=f"t{i}", name=name, input=args)],
                        stop_reason="tool_use", usage=_usage())
        for i, (name, args) in enumerate(calls)
    ] + [SimpleNamespace(content=[SimpleNamespace(type="text", text="Done.")],
                         stop_reason="end_turn", usage=_usage())]
    it = iter(steps)
    return SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: _Stream(next(it))))


def test_model_driver_runs_the_turn_and_scores_it(monkeypatch, library, tmp_path):
    task = BY_ID["set-address"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = _scripted_client(ev._calls(task.solution))
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: client)
    driver = ev.model_driver(library, model="fake-model", max_iterations=4,
                             session_root=tmp_path / "sessions")
    [r] = ev.run_tasks([task], library, driver, esphome=False, workdir=tmp_path, log=lambda s: None)
    assert r.passed, r.reasons
    assert r.tools == ["set_param"]
    assert r.usage["input_tokens"] == 200
    assert r.assistant_text == "Done."
    assert (tmp_path / "sessions" / "set-address.jsonl").exists()


# ---------------------------------------------------------------------------
# The CLI
# ---------------------------------------------------------------------------

def test_main_solutions_writes_results_and_summary(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    out = tmp_path / "r.json"
    summary = tmp_path / "s.md"
    code = ev.main(["--solutions", "--no-esphome", "--tasks", "set-address,strict-on",
                    "--out", str(out), "--summary", str(summary)])
    assert code == 0
    data = json.loads(out.read_text())
    assert data["passed"] == data["total"] == 2
    assert [r["task"] for r in data["results"]] == ["set-address", "strict-on"]
    assert summary.read_text().startswith("## Agent eval, reference solutions: 2/2 passed (gate 2)")


def test_main_without_a_key_exits_2(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ev.main(["--no-esphome", "--tasks", "set-address"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_main_rejects_an_unknown_task(capsys):
    assert ev.main(["--solutions", "--no-esphome", "--tasks", "nope"]) == 2
    assert "nope" in capsys.readouterr().err


def test_main_holds_the_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = _scripted_client([])
    monkeypatch.setattr(anthropic, "Anthropic", lambda *a, **k: client)
    assert ev.main(["--no-esphome", "--tasks", "set-address", "--min-pass", "1"]) == 1
    assert ev.main(["--no-esphome", "--tasks", "set-address", "--min-pass", "0"]) == 0


_FAKE_CLAUDE = '''#!{python}
import asyncio, json, sys
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

args = sys.argv[1:]
assert args[args.index("--tools") + 1] == ""
assert "--strict-mcp-config" in args
server = json.load(open(args[args.index("--mcp-config") + 1]))["mcpServers"]["wirestudio"]
assert "Current design state" in sys.stdin.read()


async def main():
    async with httpx.AsyncClient(headers=server["headers"]) as http:
        async with streamable_http_client(server["url"], http_client=http) as (r, w, *_):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool("add_component", {{"library_id": "ssd1306",
                                                           "params": {{"address": "0x3C"}}}})
                assert not res.is_error, res
                res = await s.call_tool("solve_pins", {{}})
                assert not res.is_error, res

asyncio.run(main())
for event in [
    {{"type": "system", "subtype": "init"}},
    {{"type": "assistant", "message": {{"content": [
        {{"type": "tool_use", "name": "mcp__wirestudio__add_component", "input": {{"library_id": "ssd1306"}}}},
        {{"type": "tool_use", "name": "mcp__wirestudio__solve_pins", "input": {{}}}}]}}}},
    {{"type": "result", "subtype": "success", "is_error": False, "result": "Added the OLED.",
      "usage": {{"input_tokens": 10, "output_tokens": 5}}}},
]:
    print(json.dumps(event))
'''


def test_claude_code_driver_scores_what_the_mcp_tools_left_in_the_store(library, tmp_path, monkeypatch):
    """The driver serves the studio's MCP endpoint, hands `claude` a config
    that reaches it with the token, and scores the design the tool calls
    wrote, with the calls read back from the stream."""
    import sys
    monkeypatch.delenv("WIRESTUDIO_MCP_TOKEN", raising=False)
    monkeypatch.delenv("INVENTORY_PATH", raising=False)
    fake = tmp_path / "claude"
    fake.write_text(_FAKE_CLAUDE.format(python=sys.executable))
    fake.chmod(0o755)
    task = BY_ID["add-oled"]
    with ev.claude_code_driver(library, model=None, workdir=tmp_path, claude=str(fake)) as driver:
        [r] = ev.run_tasks([task], library, driver, esphome=False, workdir=tmp_path / "runs",
                           log=lambda *_: None)
    assert r.passed, r.reasons
    assert r.tools == ["add_component", "solve_pins"]
    assert r.usage == {"input_tokens": 10, "output_tokens": 5}
    assert r.assistant_text == "Added the OLED."
    assert "WIRESTUDIO_MCP_TOKEN" not in os.environ
    assert "INVENTORY_PATH" not in os.environ


def test_parse_stream_raises_on_an_error_result():
    lines = [json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True})]
    with pytest.raises(RuntimeError, match="error_max_turns"):
        ev.parse_stream(lines)
    with pytest.raises(RuntimeError, match="without a result"):
        ev.parse_stream([json.dumps({"type": "system"})])
