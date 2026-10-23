"""Agent eval harness: a fixed task list, scored.

Each task in `eval_tasks.yaml` is a natural-language ask against a bundled
example. A run hands the ask to the agent and scores the design it hands
back on three things: it validates (every pin bound and on the board, no
pin shared, every bus complete, and `esphome config` accepts the render),
the intended change is present (the task's `expect` block), and the turn
stayed within its tool-call budget. A task passes when all three hold.

`--solutions` replays each task's reference tool calls instead of calling
the model. That proves the task is solvable within its budget with the
tool surface as it is, without a key.

`--driver claude-code` runs each ask through Claude Code instead of the
embedded agent: the studio app serves its MCP endpoint on a local port,
`claude -p` connects to it with every built-in tool off, and the design
the tools leave in the store is scored. Claude Code authenticates with
`CLAUDE_CODE_OAUTH_TOKEN` (a subscription, from `claude setup-token`) or
`ANTHROPIC_API_KEY`.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import jsonschema
import yaml
from pydantic import BaseModel, ConfigDict, Field

from wirestudio.agent.agent import (
    SYSTEM_INSTRUCTIONS,
    _build_library_context,
    _build_user_message,
    _resolve_model,
    is_available,
    run_turn,
)
from wirestudio.agent.session import FileSessionStore
from wirestudio.agent.tools import TOOL_SCHEMAS, execute_tool
from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.library import Library, default_library
from wirestudio.model import Design, missing_bus_pins
from wirestudio.validate import dry_run, esphome_available, write_secrets_stub

TASKS_PATH = Path(__file__).with_name("eval_tasks.yaml")
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
_SCHEMAS = {t["name"]: t["input_schema"] for t in TOOL_SCHEMAS}

Call = tuple[str, dict]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParamExpect(_Strict):
    component: Optional[str] = None
    library: Optional[str] = None
    key: str
    value: Any


class ConnectionExpect(_Strict):
    component: Optional[str] = None
    library: Optional[str] = None
    pin: str
    target: dict


class Expect(_Strict):
    components: list[str] = []
    absent: list[str] = []
    any_of: list[str] = []
    count: dict[str, int] = {}
    board: Optional[str] = None
    params: list[ParamExpect] = []
    connections: list[ConnectionExpect] = []
    buses: list[dict] = []
    strict: Optional[bool] = None
    unchanged: bool = False


class Task(_Strict):
    id: str
    example: str
    prompt: str
    budget: int = Field(ge=1)
    setup: list[list] = []
    expect: Expect
    solution: list[list]


class Gate(_Strict):
    min_pass: int = Field(ge=0)
    claude_code_min_pass: int = Field(ge=0)


class TaskFile(_Strict):
    gate: Gate
    tasks: list[Task]


def _calls(raw: list[list]) -> list[Call]:
    out: list[Call] = []
    for entry in raw:
        if not 1 <= len(entry) <= 2 or not isinstance(entry[0], str):
            raise ValueError(f"a tool call is [name] or [name, args]: {entry!r}")
        out.append((entry[0], dict(entry[1]) if len(entry) == 2 else {}))
    return out


def load_tasks(path: Path = TASKS_PATH) -> TaskFile:
    tasks = TaskFile.model_validate(yaml.safe_load(path.read_text()))
    seen: set[str] = set()
    for t in tasks.tasks:
        if t.id in seen:
            raise ValueError(f"duplicate task id {t.id}")
        seen.add(t.id)
        if not (EXAMPLES_DIR / f"{t.example}.json").exists():
            raise ValueError(f"task {t.id}: no example {t.example}")
        _calls(t.setup)
        if len(_calls(t.solution)) > t.budget:
            raise ValueError(f"task {t.id}: solution needs more calls than its budget")
    return tasks


def apply_calls(design: dict, calls: list[Call], library: Library) -> list[dict]:
    """Run tool calls against a design in place, the way the agent loop
    does. Returns the call log in the agent's shape. Each call's arguments
    must fit the tool's schema, so a reference solution cannot use an
    argument the agent is never offered."""
    log = []
    for name, args in calls:
        schema = _SCHEMAS.get(name)
        if schema is None:
            raise RuntimeError(f"{name} is not an agent tool")
        try:
            jsonschema.validate(args, schema)
        except jsonschema.ValidationError as e:
            raise RuntimeError(f"{name}({json.dumps(args)}) does not fit its schema: {e.message}") from None
        result, is_error = execute_tool(name, args, design, library)
        if is_error:
            raise RuntimeError(f"{name}({json.dumps(args)}) failed: {result}")
        log.append({"tool": name, "input": args, "is_error": False})
    return log


def _subset(expected: Any, actual: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(_subset(v, actual.get(k)) for k, v in expected.items())
    return expected == actual


def _instances(design: dict, component: Optional[str], library: Optional[str]) -> list[dict]:
    comps = design.get("components") or []
    if component:
        return [c for c in comps if c.get("id") == component]
    return [c for c in comps if c.get("library_id") == library]


def change_failures(expect: Expect, initial: dict, final: dict) -> list[str]:
    out: list[str] = []
    libs = [c.get("library_id") for c in final.get("components") or []]
    for lid in expect.components:
        if lid not in libs:
            out.append(f"no {lid} in the design")
    for lid in expect.absent:
        if lid in libs:
            out.append(f"{lid} still in the design")
    if expect.any_of and not any(lid in libs for lid in expect.any_of):
        out.append(f"none of {', '.join(expect.any_of)} in the design")
    for lid, n in expect.count.items():
        if libs.count(lid) != n:
            out.append(f"{libs.count(lid)} x {lid}, wanted {n}")
    if expect.board and (final.get("board") or {}).get("library_id") != expect.board:
        out.append(f"board is {(final.get('board') or {}).get('library_id')}, wanted {expect.board}")
    for p in expect.params:
        insts = _instances(final, p.component, p.library)
        if not any((c.get("params") or {}).get(p.key) == p.value for c in insts):
            out.append(f"{p.component or p.library}.{p.key} != {p.value!r}")
    for c in expect.connections:
        ids = {i["id"] for i in _instances(final, c.component, c.library)}
        conns = [x for x in final.get("connections") or []
                 if x.get("component_id") in ids and x.get("pin_role") == c.pin]
        if not any(_subset(c.target, x.get("target")) for x in conns):
            out.append(f"{c.component or c.library}.{c.pin} not on {json.dumps(c.target)}")
    for b in expect.buses:
        if not any(_subset(b, bus) for bus in final.get("buses") or []):
            out.append(f"no bus matching {json.dumps(b)}")
    if expect.strict is not None and bool(final.get("strict")) != expect.strict:
        out.append(f"strict is {bool(final.get('strict'))}, wanted {expect.strict}")
    if expect.unchanged and final != initial:
        out.append("the design changed")
    return out




def structural_failures(design: dict, library: Library) -> list[str]:
    """What the `validate` tool lets through and `esphome config` would
    reject: unbound targets, pins the board does not have, a pin used
    twice, a bus missing a pin. Each line names the offender."""
    out: list[str] = []
    report = json.loads(execute_tool("validate", {}, design, library)[0])
    if not report.get("ok"):
        return [f"validate: {report.get('error') or 'strict blockers'}"]
    try:
        board = library.board((design.get("board") or {}).get("library_id"))
    except FileNotFoundError as e:
        return [str(e)]
    board_pins = set(board.gpio_capabilities)
    users: dict[str, list[str]] = defaultdict(list)
    for bus in design.get("buses") or []:
        for missing in missing_bus_pins(bus):
            out.append(f"bus {bus.get('id')} has no {missing}")
        if bus.get("type") == "uart" and not bus.get("baud_rate"):
            out.append(f"bus {bus.get('id')} has no baud_rate")
        for k in ("sda", "scl", "clk", "miso", "mosi", "rx", "tx", "pin", "lrclk", "bclk"):
            pin = bus.get(k)
            if pin and pin not in board_pins:
                out.append(f"bus {bus.get('id')}.{k} on {pin}, not a {board.id} pin")
            elif pin:
                users[pin].append(f"{bus.get('id')}.{k}")
    expander_users: dict[tuple[str, int], list[str]] = defaultdict(list)
    for conn in design.get("connections") or []:
        who = f"{conn.get('component_id')}.{conn.get('pin_role')}"
        t = conn.get("target") or {}
        kind = t.get("kind")
        if kind == "gpio":
            pin = t.get("pin")
            if not pin:
                out.append(f"{who} is unbound")
            elif pin not in board_pins:
                out.append(f"{who} on {pin}, not a {board.id} pin")
            else:
                users[pin].append(who)
        elif kind == "bus" and not t.get("bus_id"):
            out.append(f"{who} is on no bus")
        elif kind == "expander_pin":
            if not t.get("expander_id"):
                out.append(f"{who} is on no expander")
            elif t.get("number") is not None:
                expander_users[(t["expander_id"], int(t["number"]))].append(who)
    for pin, who in users.items():
        if len(who) > 1:
            out.append(f"{pin} shared by {', '.join(who)}")
    for (ex, n), who in expander_users.items():
        if len(who) > 1:
            out.append(f"{ex} pin {n} shared by {', '.join(who)}")
    return out


def esphome_failure(design: dict, library: Library, workdir: Path) -> Optional[str]:
    yaml_text = render_yaml(Design.model_validate(design), library)
    yaml_path = workdir / "design.yaml"
    yaml_path.write_text(yaml_text)
    write_secrets_stub(yaml_text, workdir / "secrets.yaml")
    ok, output = dry_run(yaml_path)
    if ok:
        return None
    lines = output.splitlines()
    start = next((i + 1 for i, ln in enumerate(lines) if ln.startswith("Failed config")), 0)
    body = [ln.strip() for ln in lines[start:] if ln.strip() and not ln.startswith("INFO")]
    return "esphome config: " + " | ".join(body[:8])


@dataclass
class TaskResult:
    task: str
    example: str
    prompt: str
    passed: bool = False
    validates: bool = False
    change: bool = False
    within_budget: bool = False
    calls: int = 0
    budget: int = 0
    tools: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    seconds: float = 0.0
    assistant_text: str = ""
    error: Optional[str] = None


Driver = Callable[[Task, dict], tuple[dict, list[dict], dict, str]]
"""(task, design) -> (final design, tool-call log, usage, assistant text)."""


def solution_driver(library: Library) -> Driver:
    def run(task: Task, design: dict):
        final = copy.deepcopy(design)
        log = apply_calls(final, _calls(task.solution), library)
        return final, log, {}, "(reference solution)"
    return run


def model_driver(library: Library, *, model: Optional[str], max_iterations: int,
                 session_root: Path) -> Driver:
    sessions = FileSessionStore(root=session_root)

    def run(task: Task, design: dict):
        result = run_turn(
            design=design, user_message=task.prompt, session_id=task.id,
            library=library, sessions=sessions, model=model, max_iterations=max_iterations,
        )
        return result.design, result.tool_calls, result.usage, result.assistant_text
    return run


MCP_PREFIX = "mcp__wirestudio__"

_CLAUDE_CODE_CONTEXT = """\

Every wirestudio design tool acts on the current design when `design_id` \
is omitted; leave it out.
"""


def claude_code_available() -> tuple[bool, Optional[str]]:
    if not shutil.which("claude"):
        return False, "claude CLI not found; npm install -g @anthropic-ai/claude-code"
    if not (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")):
        return False, "set CLAUDE_CODE_OAUTH_TOKEN (claude setup-token) or ANTHROPIC_API_KEY"
    return True, None


def parse_stream(lines: list[str]) -> tuple[list[dict], dict, str]:
    """The tool-call log, usage and final text from `claude -p
    --output-format stream-json`. Raises when the run ended in an error."""
    log: list[dict] = []
    result: Optional[dict] = None
    for line in lines:
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    name = block["name"]
                    log.append({"tool": name.removeprefix(MCP_PREFIX),
                                "input": block.get("input", {}), "is_error": False})
        elif event.get("type") == "result":
            result = event
    if result is None:
        raise RuntimeError("claude exited without a result event")
    if result.get("is_error"):
        raise RuntimeError(f"claude: {result.get('result') or result.get('subtype')}")
    return log, result.get("usage") or {}, result.get("result") or ""


@contextlib.contextmanager
def claude_code_driver(library: Library, *, model: Optional[str], workdir: Path,
                       claude: str = "claude", timeout: float = 600):
    import uvicorn

    token = secrets.token_urlsafe(32)
    # Importing wirestudio.api.app builds its module-level app, so the
    # environment has to point at the workdir first or that app writes a
    # token file and stores under the user's home.
    env = {"WIRESTUDIO_MCP_TOKEN": token,
           "INVENTORY_PATH": str(workdir / "inventory.json"),
           "DESIGNS_DIR": str(workdir / "designs"),
           "SESSIONS_DIR": str(workdir / "sessions")}
    saved_env = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    server: Optional[uvicorn.Server] = None
    try:
        from wirestudio.api.app import create_app
        from wirestudio.designs.active import ActiveDesignTracker
        from wirestudio.designs.store import FileDesignStore

        store = FileDesignStore(root=workdir / "designs")
        active = ActiveDesignTracker()
        app = create_app(library=library, designs=store, active_design=active,
                         sessions=FileSessionStore(root=workdir / "sessions"))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 30
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("the studio app did not start")
            time.sleep(0.05)

        config = workdir / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {"wirestudio": {
            "type": "http", "url": f"http://127.0.0.1:{port}/mcp",
            "headers": {"Authorization": f"Bearer {token}"},
        }}}))
        system = workdir / "system.md"
        system.write_text(SYSTEM_INSTRUCTIONS + _CLAUDE_CODE_CONTEXT + "\n"
                          + _build_library_context(library))
        cwd = workdir / "claude-cwd"
        cwd.mkdir(exist_ok=True)

        def run(task: Task, design: dict):
            design_id, _ = store.save(design, design_id=task.id)
            active.set(design_id)
            cmd = [claude, "-p", "--output-format", "stream-json", "--verbose",
                   "--tools", "", "--strict-mcp-config", "--mcp-config", str(config),
                   "--allowedTools", "mcp__wirestudio", "--append-system-prompt-file", str(system),
                   "--no-session-persistence"]
            if model:
                cmd += ["--model", model]
            proc = subprocess.run(cmd, input=_build_user_message(design, task.prompt), cwd=cwd,
                                  capture_output=True, text=True, timeout=timeout, check=False)
            try:
                log, usage, text = parse_stream(proc.stdout.splitlines())
            except RuntimeError as e:
                raise RuntimeError(
                    f"{e} (exit {proc.returncode}): {proc.stderr.strip()[-500:]}") from None
            return store.load(design_id), log, usage, text

        yield run
    finally:
        if server is not None:
            server.should_exit = True
            thread.join(timeout=10)
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def load_example(task: Task, library: Library) -> dict:
    design = json.loads((EXAMPLES_DIR / f"{task.example}.json").read_text())
    apply_calls(design, _calls(task.setup), library)
    return design


def score(task: Task, initial: dict, final: dict, log: list[dict], library: Library,
          *, esphome: bool, workdir: Path) -> TaskResult:
    r = TaskResult(task=task.id, example=task.example, prompt=task.prompt,
                   calls=len(log), budget=task.budget, tools=[c["tool"] for c in log])
    r.reasons = structural_failures(final, library)
    if not r.reasons and esphome:
        failure = esphome_failure(final, library, workdir)
        if failure:
            r.reasons.append(failure)
    r.validates = not r.reasons
    changes = change_failures(task.expect, initial, final)
    r.change = not changes
    r.reasons.extend(changes)
    r.within_budget = r.calls <= task.budget
    if not r.within_budget:
        r.reasons.append(f"{r.calls} tool calls, budget {task.budget}")
    r.passed = r.validates and r.change and r.within_budget
    return r


def run_tasks(tasks: list[Task], library: Library, driver: Driver, *, esphome: bool,
              workdir: Path, log=print) -> list[TaskResult]:
    results: list[TaskResult] = []
    for task in tasks:
        initial = load_example(task, library)
        t0 = time.monotonic()
        try:
            final, call_log, usage, text = driver(task, copy.deepcopy(initial))
        except Exception as e:  # noqa: BLE001 - one task's failure is a row, not the run's end
            r = TaskResult(task=task.id, example=task.example, prompt=task.prompt,
                           budget=task.budget, error=f"{type(e).__name__}: {e}",
                           reasons=[f"{type(e).__name__}: {e}"], seconds=time.monotonic() - t0)
        else:
            task_dir = workdir / task.id
            task_dir.mkdir(parents=True, exist_ok=True)
            r = score(task, initial, final, call_log, library, esphome=esphome, workdir=task_dir)
            r.usage = usage
            r.assistant_text = text
            r.seconds = round(time.monotonic() - t0, 1)
        results.append(r)
        log(f"  {'PASS' if r.passed else 'FAIL'}  {task.id:<24} {r.calls}/{task.budget} calls"
            + (f"  {'; '.join(r.reasons)}" if r.reasons else ""))
    return results


def _tokens(usage: dict) -> int:
    return sum(int(usage.get(k) or 0) for k in
               ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))


def summary_markdown(results: list[TaskResult], *, title: str, min_pass: int) -> str:
    passed = sum(r.passed for r in results)
    tokens = sum(_tokens(r.usage) for r in results)
    seconds = sum(r.seconds for r in results)
    lines = [
        f"## {title}: {passed}/{len(results)} passed (gate {min_pass})",
        "",
        f"{tokens:,} tokens, {seconds:.0f}s.",
        "",
        "| task | example | validates | change | calls | result | why |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        why = "; ".join(r.reasons).replace("|", "\\|")
        lines.append(
            f"| {r.task} | {r.example} | {'yes' if r.validates else 'no'} | "
            f"{'yes' if r.change else 'no'} | {r.calls}/{r.budget} | "
            f"{'pass' if r.passed else 'FAIL'} | {why} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", default="", help="comma-separated task ids (default: all)")
    parser.add_argument("--tasks-file", type=Path, default=TASKS_PATH)
    parser.add_argument("--driver", choices=["agent", "claude-code"], default="agent",
                        help="the embedded agent (ANTHROPIC_API_KEY) or Claude Code over MCP")
    parser.add_argument("--model", default=None, help="agent model (default: the agent's)")
    parser.add_argument("--max-iterations", type=int, default=8)
    parser.add_argument("--solutions", action="store_true",
                        help="replay each task's reference tool calls instead of the model")
    parser.add_argument("--no-esphome", action="store_true",
                        help="skip `esphome config` on the final design")
    parser.add_argument("--min-pass", type=int, default=None,
                        help="override gate.min_pass from the tasks file")
    parser.add_argument("--out", type=Path, default=None, help="write results as JSON")
    parser.add_argument("--summary", type=Path, default=None,
                        help="write the markdown summary (default: $GITHUB_STEP_SUMMARY if set)")
    args = parser.parse_args(argv)

    tasks_file = load_tasks(args.tasks_file)
    tasks = tasks_file.tasks
    if args.tasks:
        wanted = [t.strip() for t in args.tasks.split(",") if t.strip()]
        unknown = sorted(set(wanted) - {t.id for t in tasks})
        if unknown:
            print(f"unknown task(s): {unknown}", file=sys.stderr)
            return 2
        tasks = [t for t in tasks if t.id in wanted]

    esphome = not args.no_esphome
    if esphome and not esphome_available():
        print("esphome CLI not found; install esphome or pass --no-esphome", file=sys.stderr)
        return 2
    if not args.solutions:
        ok, reason = claude_code_available() if args.driver == "claude-code" else is_available()
        if not ok:
            print(reason, file=sys.stderr)
            return 2

    with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
        workdir = Path(tmp)
        library = Library(default_library().root, workdir / "user-library")
        if args.solutions:
            driver = solution_driver(library)
            title = "Agent eval, reference solutions"
            min_pass = len(tasks)
        elif args.driver == "claude-code":
            driver = stack.enter_context(claude_code_driver(library, model=args.model, workdir=workdir))
            title = f"Agent eval, Claude Code over MCP ({args.model or 'default model'})"
            min_pass = tasks_file.gate.claude_code_min_pass if args.min_pass is None else args.min_pass
        else:
            driver = model_driver(library, model=args.model, max_iterations=args.max_iterations,
                                  session_root=workdir / "sessions")
            title = f"Agent eval, {_resolve_model(args.model)}"
            min_pass = tasks_file.gate.min_pass if args.min_pass is None else args.min_pass
        print(f"{title}; esphome config {'on' if esphome else 'off'}; {len(tasks)} tasks\n")
        results = run_tasks(tasks, library, driver, esphome=esphome, workdir=workdir)

    passed = sum(r.passed for r in results)
    print(f"\n{passed}/{len(results)} passed; gate {min_pass}")
    summary = summary_markdown(results, title=title, min_pass=min_pass)
    summary_path = args.summary or (
        Path(os.environ["GITHUB_STEP_SUMMARY"]) if os.environ.get("GITHUB_STEP_SUMMARY") else None)
    if summary_path:
        with summary_path.open("a") as f:
            f.write(summary)
    if args.out:
        args.out.write_text(json.dumps({
            "title": title, "min_pass": min_pass, "passed": passed, "total": len(results),
            "results": [asdict(r) for r in results],
        }, indent=2))
    return 0 if passed >= min_pass else 1


if __name__ == "__main__":
    sys.exit(main())
