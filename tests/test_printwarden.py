"""Tests for the print-warden handoff: client, enclosure submit, REST routes.

`FakeWarden` speaks the warden's wire shapes -- `/healthz`, multipart
`/upload`, and MCP over Streamable HTTP in its stateless JSON-response
mode -- behind `httpx.MockTransport`, so the real `mcp` client runs the
handshake and tool calls without a network.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from wirestudio.api.app import create_app
from wirestudio.enclosure import EnclosureUnavailable
from wirestudio.library import default_library
from wirestudio.model import Design
from wirestudio.printwarden import (
    PrintWardenClient,
    PrintWardenRejected,
    PrintWardenUnavailable,
    submit_enclosure,
    validate_tunables,
)

pytestmark = pytest.mark.anyio

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = REPO_ROOT / "wirestudio" / "examples"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _design(name: str) -> Design:
    return Design.model_validate(json.loads((EXAMPLES_DIR / f"{name}.json").read_text()))


PRINTERS = [
    {
        "name": "garagex4", "location": "covington", "state": "standby",
        "klippy": "ready", "loaded_material": "PETG",
        "materials": ["ABS", "PETG", "PLA"],
        "qualities": ["draft", "fine", "standard", "strength"],
        "bed": "clear", "auto_start": False,
    },
    {
        "name": "wyolax1", "location": "wyola", "state": "standby",
        "klippy": "shutdown", "loaded_material": "PETG",
        "materials": ["ABS", "PETG", "PLA"],
        "qualities": ["draft", "optimal", "standard"],
        "bed": "unknown", "auto_start": False,
    },
]


class FakeWarden:
    def __init__(self, *, token: str = "") -> None:
        self.token = token
        self.uploads: dict[str, bytes] = {}
        self.calls: list[tuple[str, dict]] = []
        self.jobs: dict[str, dict] = {}
        self.reject_submit: str | None = None
        self.healthy = True

    def _auth_ok(self, req: httpx.Request) -> bool:
        if not self.token:
            return True
        return req.headers.get("authorization") == f"Bearer {self.token}"

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/healthz":
            if not self.healthy:
                return httpx.Response(503, json={"ok": False})
            return httpx.Response(200, json={"ok": True, "api": 1, "version": "0.6.0", "printers": {}})
        if not self._auth_ok(req):
            return httpx.Response(401, json={"error": "unauthorized"})
        if path == "/upload" and req.method == "POST":
            body = req.read()
            # The multipart filename is quoted in the part header.
            head, _, rest = body.partition(b"\r\n\r\n")
            name = head.split(b'filename="')[1].split(b'"')[0].decode()
            data = rest.rsplit(b"\r\n--", 1)[0]
            if not name.endswith((".stl", ".scad", ".3mf")):
                return httpx.Response(400, json={"error": f"{name!r}: models must be .stl or .scad or .3mf"})
            self.uploads[name] = data
            return httpx.Response(200, json={"ok": True, "model": name})
        if path == "/mcp":
            return self._mcp(req)
        return httpx.Response(404, json={"error": "not found"})

    # -- MCP, stateless + json_response, as print-warden configures FastMCP --

    def _mcp(self, req: httpx.Request) -> httpx.Response:
        if req.method == "DELETE":
            return httpx.Response(405)
        if req.method != "POST":
            return httpx.Response(405)
        msg = json.loads(req.read())
        method = msg.get("method")
        if "id" not in msg:
            return httpx.Response(202)
        if method == "initialize":
            result = {
                "protocolVersion": msg["params"]["protocolVersion"],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "print-warden", "version": "0.6.0"},
            }
        elif method == "tools/list":
            result = {"tools": [
                {"name": n, "description": n, "inputSchema": {"type": "object"}}
                for n in ("list_printers", "submit_job", "job_status")
            ]}
        elif method == "tools/call":
            name = msg["params"]["name"]
            args = msg["params"].get("arguments") or {}
            self.calls.append((name, args))
            try:
                value = self._tool(name, args)
            except ValueError as e:
                result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
            else:
                sc = value if isinstance(value, dict) else {"result": value}
                result = {
                    "content": [{"type": "text", "text": json.dumps(value)}],
                    "structuredContent": sc,
                    "isError": False,
                }
        else:
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": msg["id"],
                "error": {"code": -32601, "message": f"unknown method {method}"},
            })
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def _tool(self, name: str, args: dict) -> Any:
        if name == "list_printers":
            return PRINTERS
        if name == "submit_job":
            if self.reject_submit:
                raise ValueError(self.reject_submit)
            if args["model"] not in self.uploads:
                raise ValueError(f"{args['model']} not found; POST it to /upload first")
            where = args["printer"]
            printer = next(
                (p["name"] for p in PRINTERS if where in (p["name"], p["location"])), None,
            )
            if printer is None:
                raise ValueError(f"no printer at {where!r}")
            job_id = f"job{len(self.jobs) + 1}"
            job = {
                "id": job_id, "printer": printer, "name": args.get("name"),
                "material": args["material"], "quality": args.get("quality", "standard"),
                "state": "staged", "est_seconds": 4260, "est_human": "1h 11m",
                "filament_g": 31.2, "preview_url": f"http://warden/files/jobs/{job_id}/preview.png",
                "warnings": [], "slice_blockers": [], "copies": args.get("copies", 1),
                "scad_defines": args.get("scad_defines"),
            }
            self.jobs[job_id] = job
            return {
                **job, "routed": printer != where, "cached": False, "history": {"prints": 0},
                "queue": {"offered": True, "why": None},
            }
        if name == "job_status":
            job = self.jobs.get(args["job_id"])
            if job is None:
                raise ValueError(f"no job {args['job_id']}")
            return {**job, "log": [], "can_start": False, "blockers": ["bed is occupied"]}
        raise ValueError(f"unknown tool {name}")


def _client(warden: FakeWarden, *, token: str = "") -> PrintWardenClient:
    return PrintWardenClient(
        base_url="http://warden:8710", token=token,
        transport=httpx.MockTransport(warden.handler),
    )


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

async def test_unconfigured_client_reports_the_missing_url():
    c = PrintWardenClient(base_url="", token="")
    assert not c.is_configured()
    ok, reason, version = await c.is_available()
    assert (ok, version) == (False, None)
    assert "PRINT_WARDEN_URL" in reason
    with pytest.raises(PrintWardenUnavailable):
        await c.call("list_printers")


async def test_is_available_reads_healthz():
    w = FakeWarden()
    ok, reason, version = await _client(w).is_available()
    assert (ok, reason, version) == (True, None, "0.6.0")
    w.healthy = False
    ok, reason, _ = await _client(w).is_available()
    assert ok is False and "503" in reason


async def test_list_printers_runs_the_mcp_handshake_and_unwraps_result():
    w = FakeWarden()
    printers = await _client(w).list_printers()
    assert [p["name"] for p in printers] == ["garagex4", "wyolax1"]
    assert w.calls == [("list_printers", {})]


async def test_token_is_sent_as_bearer_on_upload_and_mcp():
    w = FakeWarden(token="tok")
    c = _client(w, token="tok")
    assert await c.upload("x.scad", b"cube(1);") == "x.scad"
    assert await c.list_printers()
    with pytest.raises(PrintWardenUnavailable, match="unauthorized"):
        await _client(w, token="wrong").upload("x.scad", b"cube(1);")
    with pytest.raises(PrintWardenUnavailable, match="unauthorized"):
        await _client(w, token="wrong").list_printers()


async def test_tool_error_surfaces_the_wardens_words():
    w = FakeWarden()
    with pytest.raises(PrintWardenRejected, match="no job nope"):
        await _client(w).job_status("nope")


async def test_unreachable_is_reported_not_raised_raw():
    def down(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("")

    c = PrintWardenClient(base_url="http://warden:8710", token="", transport=httpx.MockTransport(down))
    ok, reason, _ = await c.is_available()
    assert ok is False and reason.startswith("unreachable:") and len(reason) > len("unreachable: ")
    with pytest.raises(PrintWardenUnavailable, match="unreachable"):
        await c.list_printers()


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

def test_validate_tunables_accepts_known_numbers_only():
    assert validate_tunables({"wall": 2, "clearance": 0.8}) == {"wall": 2.0, "clearance": 0.8}
    assert validate_tunables(None) == {}
    with pytest.raises(ValueError, match="unknown tunable"):
        validate_tunables({"$fn": 64})
    with pytest.raises(ValueError, match="must be a number"):
        validate_tunables({"wall": "2"})
    with pytest.raises(ValueError, match="must be a number"):
        validate_tunables({"wall": True})
    with pytest.raises(ValueError, match=">= 0"):
        validate_tunables({"wall": -1})


# ---------------------------------------------------------------------------
# submit_enclosure
# ---------------------------------------------------------------------------

async def test_submit_enclosure_uploads_scad_then_stages_a_job():
    w = FakeWarden()
    lib = default_library()
    job = await submit_enclosure(
        _client(w), _design("garage-motion"), lib,
        where="covington", material="PETG", quality="fine",
        tunables={"wall": 2.4, "clearance": 0.8},
    )
    assert list(w.uploads) == ["garage-motion-v1-enclosure.scad"]
    assert w.uploads["garage-motion-v1-enclosure.scad"].rstrip().endswith(b"YAPPgenerate();")
    assert b"board_l = 54.4;" in w.uploads["garage-motion-v1-enclosure.scad"]
    name, args = w.calls[-1]
    assert name == "submit_job"
    assert args["printer"] == "covington"
    assert args["model"] == "garage-motion-v1-enclosure.scad"
    assert args["material"] == "PETG" and args["quality"] == "fine"
    assert args["name"] == "garage-motion-v1-enclosure"
    assert args["scad_defines"] == {"wall": 2.4, "clearance": 0.8}
    assert args["offer"] is True
    assert "start" not in {c[0] for c in w.calls}
    assert job["id"] == "job1" and job["printer"] == "garagex4" and job["routed"] is True


async def test_submit_enclosure_omits_scad_defines_when_untouched():
    w = FakeWarden()
    await submit_enclosure(_client(w), _design("garage-motion"), default_library(),
                           where="garagex4", material="PLA")
    assert "scad_defines" not in w.calls[-1][1]


async def test_submit_enclosure_refuses_boards_without_an_outline_before_upload():
    w = FakeWarden()
    with pytest.raises(EnclosureUnavailable):
        await submit_enclosure(_client(w), _design("bluesonoff"), default_library(),
                               where="covington", material="PETG")
    assert not w.uploads and not w.calls


async def test_submit_enclosure_passes_the_wardens_refusal_through():
    w = FakeWarden()
    w.reject_submit = "model 60x40x20 does not fit the X1 bed"
    with pytest.raises(PrintWardenRejected, match="does not fit"):
        await submit_enclosure(_client(w), _design("garage-motion"), default_library(),
                               where="wyola", material="PETG")


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------

@pytest.fixture
def warden() -> FakeWarden:
    return FakeWarden()


@pytest.fixture
def api(warden: FakeWarden) -> TestClient:
    return TestClient(create_app(printwarden_client_factory=lambda: _client(warden)))


def test_status_unconfigured(monkeypatch):
    monkeypatch.delenv("PRINT_WARDEN_URL", raising=False)
    r = TestClient(create_app()).get("/enclosure/print/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "PRINT_WARDEN_URL" in body["reason"]
    assert body["printers"] == []


def test_status_lists_printers_and_locations(api):
    r = api.get("/enclosure/print/status")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True and body["version"] == "0.6.0"
    assert body["url"] == "http://warden:8710"
    assert [p["name"] for p in body["printers"]] == ["garagex4", "wyolax1"]
    assert body["printers"][0]["loaded_material"] == "PETG"
    assert body["locations"] == ["covington", "wyola"]


def test_print_route_stages_and_reports_the_job(api, warden):
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    r = api.post("/design/enclosure/print", json={
        "design": design, "where": "covington", "material": "PETG",
        "quality": "standard", "tunables": {"wall": 2.4}, "copies": 2,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_id"] == "job1"
    assert body["printer"] == "garagex4" and body["routed"] is True
    assert body["state"] == "staged"
    assert body["est_human"] == "1h 11m"
    assert body["preview_url"].endswith("/preview.png")
    assert body["queue"] == {"offered": True, "why": None}
    assert "phone" in body["starts"]
    assert warden.calls[-1][1]["copies"] == 2
    assert warden.calls[-1][1]["scad_defines"] == {"wall": 2.4}


def test_print_route_rejects_bad_tunables_before_touching_the_warden(api, warden):
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    r = api.post("/design/enclosure/print", json={
        "design": design, "where": "covington", "material": "PETG",
        "tunables": {"include": 1},
    })
    assert r.status_code == 422
    assert "unknown tunable" in r.json()["detail"]
    assert not warden.uploads and not warden.calls


def test_print_route_422_for_a_board_without_enclosure(api):
    design = json.loads((EXAMPLES_DIR / "bluesonoff.json").read_text())
    r = api.post("/design/enclosure/print", json={"design": design, "where": "covington", "material": "PETG"})
    assert r.status_code == 422
    assert "no enclosure metadata" in r.json()["detail"]


def test_print_route_422_when_the_warden_refuses(api, warden):
    warden.reject_submit = "garagex4 slicer config: filaments=['ABS', 'PETG', 'PLA']"
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    r = api.post("/design/enclosure/print", json={"design": design, "where": "covington", "material": "TPU"})
    assert r.status_code == 422
    assert "filaments" in r.json()["detail"]


def test_print_route_503_unconfigured_and_502_unreachable(monkeypatch):
    monkeypatch.delenv("PRINT_WARDEN_URL", raising=False)
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    body = {"design": design, "where": "covington", "material": "PETG"}
    r = TestClient(create_app()).post("/design/enclosure/print", json=body)
    assert r.status_code == 503

    def down(_req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("")

    app = create_app(printwarden_client_factory=lambda: PrintWardenClient(
        base_url="http://warden:8710", token="", transport=httpx.MockTransport(down)))
    r = TestClient(app).post("/design/enclosure/print", json=body)
    assert r.status_code == 502
    assert "unreachable" in r.json()["detail"]


def test_job_status_route(api, warden):
    design = json.loads((EXAMPLES_DIR / "garage-motion.json").read_text())
    job_id = api.post("/design/enclosure/print", json={
        "design": design, "where": "covington", "material": "PETG"}).json()["job_id"]
    r = api.get(f"/enclosure/print/jobs/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == job_id and body["state"] == "staged"
    assert body["can_start"] is False and body["blockers"] == ["bed is occupied"]
    r = api.get("/enclosure/print/jobs/nope")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

def _payload(result: Any) -> dict:
    text = getattr(result.content[0], "text", None)
    assert isinstance(text, str), f"unexpected content: {result.content!r}"
    return json.loads(text)


def _mcp(tmp_path: Path, warden: FakeWarden | None):
    from wirestudio.designs.store import FileDesignStore
    from wirestudio.mcp.server import build_mcp_server

    store = FileDesignStore(root=tmp_path / "designs")
    store.save(json.loads((EXAMPLES_DIR / "garage-motion.json").read_text()), design_id="garage-motion-v1")

    def factory():
        return _client(warden) if warden else PrintWardenClient(base_url="", token="")

    return build_mcp_server(default_library(), store, printwarden_factory=factory)


async def test_mcp_status_unconfigured(tmp_path):
    out = _payload(await _mcp(tmp_path, None).call_tool("print_warden_status", {}))
    assert out["available"] is False and "PRINT_WARDEN_URL" in out["reason"]
    out = _payload(await _mcp(tmp_path, None).call_tool(
        "print_enclosure", {"design_id": "garage-motion-v1", "where": "covington", "material": "PETG"}))
    assert out["ok"] is False and "PRINT_WARDEN_URL" in out["error"]


async def test_mcp_status_lists_printers(tmp_path):
    out = _payload(await _mcp(tmp_path, FakeWarden()).call_tool("print_warden_status", {}))
    assert out["available"] is True and out["version"] == "0.6.0"
    assert [p["name"] for p in out["printers"]] == ["garagex4", "wyolax1"]


async def test_mcp_print_enclosure_stages_and_status_polls(tmp_path):
    w = FakeWarden()
    server = _mcp(tmp_path, w)
    out = _payload(await server.call_tool("print_enclosure", {
        "design_id": "garage-motion-v1", "where": "wyola", "material": "PETG",
        "quality": "draft", "tunables": {"standoff_h": 5},
    }))
    assert out["ok"] is True, out
    assert out["job_id"] == "job1" and out["printer"] == "wyolax1" and out["routed"] is True
    assert "never from here" in out["starts"]
    assert w.calls[-1][1]["scad_defines"] == {"standoff_h": 5.0}
    assert "garage-motion-v1-enclosure.scad" in w.uploads

    status = _payload(await server.call_tool("print_job_status", {"job_id": "job1"}))
    assert status["ok"] is True and status["job_id"] == "job1"
    assert status["can_start"] is False and status["blockers"] == ["bed is occupied"]


async def test_mcp_print_enclosure_reports_refusals_as_errors(tmp_path):
    w = FakeWarden()
    server = _mcp(tmp_path, w)
    out = _payload(await server.call_tool("print_enclosure", {
        "design_id": "garage-motion-v1", "where": "covington", "material": "PETG",
        "tunables": {"lid": 1},
    }))
    assert out["ok"] is False and "unknown tunable" in out["error"]
    assert not w.calls
    out = _payload(await server.call_tool("print_job_status", {"job_id": "nope"}))
    assert out["ok"] is False and "no job nope" in out["error"]
