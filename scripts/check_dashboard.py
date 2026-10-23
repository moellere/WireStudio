"""Push, compile and fetch one example through a real ESPHome Device Builder.

Starts the pinned `esphome-device-builder` on a free port, twice: open, then
with a username and password. Against each, the studio's own
`DashboardClient` probes it, pushes the rendered YAML, compiles over the
`/ws` command channel and fetches the image, and this script asserts the
wire assumptions the client (and the fake in tests/test_esphome_dashboard.py)
encode:

- `devices/list` names a config by `configuration`, and a push creates it
  once;
- a protected builder refuses commands before `auth/login` and the
  client's in-band login opens the connection;
- `firmware/follow_job` ends in a `result` event with the exit code;
- `firmware/get_binaries` lists the built artifacts and a single-use
  token from `firmware/download_token` fetches one over HTTP.

Run locally (Python 3.12+):
    pip install -e . 'esphome==2026.10.0' 'esphome-device-builder==1.25.0'
    python scripts/check_dashboard.py garage-motion

`--no-compile` skips the build (seconds instead of minutes) and with it
the websocket and artifact assertions. Exit 0 = every assertion held.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from check_examples import EXAMPLES_DIR
from wirestudio.validate import write_secrets_stub
from wirestudio.esphome_dashboard import DashboardClient
from wirestudio.generate.yaml_gen import render_yaml
from wirestudio.library import default_library
from wirestudio.model import Design

ESP_IMAGE_MAGIC = 0xE9


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_dashboard(config_dir: Path, port: int, password: str | None) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "esphome_device_builder", str(config_dir),
           "--host", "127.0.0.1", "--port", str(port)]
    env = {k: v for k, v in os.environ.items() if k not in ("ESPHOME_USERNAME", "ESPHOME_PASSWORD")}
    if password:
        env.update(ESPHOME_USERNAME="ci", ESPHOME_PASSWORD=password)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f"dashboard exited early:\n{proc.stdout.read()}")
        try:
            httpx.get(url + "/ping", timeout=2.0)
            return proc
        except httpx.HTTPError:
            time.sleep(0.5)
    proc.kill()
    raise SystemExit("dashboard did not answer within 90s")


async def _exercise(url: str, example: str, yaml_text: str, password: str | None,
                    compile_: bool) -> list[str]:
    failures: list[str] = []

    def check(cond: bool, text: str) -> None:
        print(f"  {'ok  ' if cond else 'FAIL'}  {text}")
        if not cond:
            failures.append(text)

    client = DashboardClient(url, username="ci" if password else None, password=password)
    available, reason = await client.is_available()
    check(available, f"probe: devices/list answers ({reason or 'ok'})")
    if not available:
        return failures

    first = await client.push_device(example, yaml_text)
    check(first.created, f"push: {first.filename} created on first push")
    check(first.filename in await client.list_devices(), "push: devices/list lists it by `configuration`")
    second = await client.push_device(example, yaml_text)
    check(not second.created, "push: a second push updates rather than creates")
    if password:
        anon_ok, anon_reason = await DashboardClient(url).is_available()
        check(not anon_ok and "login" in (anon_reason or ""), "auth: a client without credentials is refused")
        wrong_ok, _ = await DashboardClient(url, username="ci", password="nope").is_available()
        check(not wrong_ok, "auth: a wrong password is rejected")
    if not compile_:
        return failures

    lines: list[str] = []
    done: dict | None = None
    async for event in client.compile(first.filename):
        if event["type"] == "log":
            if event["data"].strip():
                lines.append(event["data"].rstrip())
        else:
            done = event
    check(done is not None and done["ok"], "compile: follow_job ends in a successful result"
          + ("" if done and done["ok"] else "\n" + "\n".join(lines[-30:])))
    check(bool(lines), f"compile: {len(lines)} log lines relayed")

    entries = await client.downloads(first.filename)
    names = [str(e["file"]) for e in entries]
    check(bool(names), f"downloads: get_binaries lists the artifacts ({', '.join(names) or 'none'})")
    check(all(e.get("type") for e in entries), "downloads: every artifact carries a type tag")
    ota = await client.firmware(first.filename) or b""
    check(bool(ota) and ota[0] == ESP_IMAGE_MAGIC and len(ota) > 100_000,
          f"download: the ota image is an ESP app image ({len(ota)} bytes)")
    # The factory image is the flash from offset 0: bootloader, partition
    # table and the app, so it embeds the ota image and its first byte is
    # padding on chips whose bootloader sits at 0x1000.
    factory = await client.firmware(first.filename, factory=True) or b""
    check(bool(ota) and len(factory) > len(ota) and ota in factory,
          f"download: the factory image embeds the ota image ({len(factory)} bytes)")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("example", nargs="?", default="garage-motion", help="example stem")
    parser.add_argument("--no-compile", action="store_true", help="probe and push only")
    args = parser.parse_args(argv)

    path = EXAMPLES_DIR / f"{args.example}.json"
    if not path.exists():
        print(f"unknown example {args.example!r}", file=sys.stderr)
        return 2
    design = Design.model_validate(json.loads(path.read_text()))
    yaml_text = render_yaml(design, default_library())

    failures: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        for password in (None, "ci-password"):
            config_dir = Path(tmp) / ("protected" if password else "open")
            config_dir.mkdir()
            write_secrets_stub(yaml_text, config_dir / "secrets.yaml")
            port = _free_port()
            print(f"dashboard on :{port} {'with a password' if password else 'open'}")
            proc = _start_dashboard(config_dir, port, password)
            try:
                failures += asyncio.run(_exercise(
                    f"http://127.0.0.1:{port}", args.example, yaml_text, password,
                    compile_=not args.no_compile))
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
    print()
    if failures:
        print(f"{len(failures)} assertion(s) failed against the Device Builder:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("every wire assumption held against the live dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
