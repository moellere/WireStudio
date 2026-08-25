"""MCP tools that reach hardware: workbench, ChirpStack, fleet builds.

The design/library tools stop at the artifact. These carry it the rest of
the way -- compile it, put it on a slot, register it with ChirpStack --
so a headless client can finish a bring-up without dropping to HTTP.
That mattered because the REST endpoints these wrap carry no auth of
their own: publishing them to close the gap would publish unauthenticated
flashing and provisioning, while `/mcp` is bearer-gated.

Long operations return a `job_id` rather than blocking. Compile, flash
and workbench-provision stream for minutes; the tool starts the work and
the client polls `job_status` / `job_events`. Fleet builds keep their own
`run_id` from the addon's GitHub run and are polled with
`fleet_job_status` -- that handle outlives this process, so wrapping it in
the in-memory registry would only make it more fragile.

Firmware bytes never cross the MCP boundary. `workbench_flash` takes a
`fleet_run_id` and fetches the artifact server-side, because an agent
needs the image *on the board*, not in its context window.
"""
from __future__ import annotations

import base64
from typing import Any, Callable, Optional

from mcp.server.mcpserver import MCPServer

from wirestudio.designs.active import ActiveDesignTracker
from wirestudio.designs.store import DesignStore
from wirestudio.library import Library
from wirestudio.mcp.jobs import JobNotFound, JobRegistry
from wirestudio.model import Design
from wirestudio.errors import describe

_EUI_LEN = 16

_NO_DESIGN = {
    "ok": False,
    "error": (
        "design_id was not provided and no active design is set. "
        "Either pass design_id explicitly or call set_active_design first."
    ),
}


def _err(message: str, **extra: Any) -> dict:
    return {"ok": False, "error": message, **extra}


def _valid_eui(dev_eui: str) -> bool:
    if len(dev_eui) != _EUI_LEN:
        return False
    try:
        int(dev_eui, 16)
    except ValueError:
        return False
    return True


#: An ESP-IDF partition table lives at 0x8000 inside a *merged* image and
#: starts with this magic. A bare app image is a single ESP image with
#: nothing at that offset, so its presence is what distinguishes the two.
_PARTITION_TABLE_MAGIC = b"\xaa\x50"
_PARTITION_TABLE_OFFSET = 0x8000
_ESP_IMAGE_MAGIC = 0xE9
_BOOTLOADER_OFFSETS = (0x0, 0x1000)
_DEFAULT_APP_OFFSET = 0x10000


def is_merged_image(blob: bytes) -> bool:
    """Does `blob` carry its own bootloader + partition table?

    Sniffed from the bytes rather than taken on faith from whichever
    endpoint served them. The fleet addon's ``/firmware`` publishes a
    merged image even though the client's docstring calls it the app
    image, and writing a merged image at the app offset puts a
    bootloader in the app partition -- the board then boot-loops with
    "Segment 0 ... overlaps bootloader stack / No bootable app
    partitions". Getting this from the artifact is the only way that
    stays correct across addon versions.
    """
    if len(blob) <= _PARTITION_TABLE_OFFSET + 2:
        return False
    # The bootloader is at 0x0 on the ESP32-S3/C3 family but at 0x1000 on the
    # classic ESP32, whose merged image therefore opens with 4 KiB of 0xff
    # padding. Requiring the image magic at byte 0 read that padding as "not
    # merged" and would have written the whole image to the app offset --
    # the bricking case this function exists to prevent, just one chip family
    # over.
    if not any(len(blob) > off and blob[off] == _ESP_IMAGE_MAGIC
               for off in _BOOTLOADER_OFFSETS):
        return False
    at_table = blob[_PARTITION_TABLE_OFFSET:_PARTITION_TABLE_OFFSET + 2]
    return at_table == _PARTITION_TABLE_MAGIC


def _decode_images(raw: Optional[list[dict]]) -> list[tuple[int, bytes]]:
    """[{offset, data}] -> [(int, bytes)]; `data` is base64.

    Offsets arrive as strings like "0x10000", so base=0 rather than
    assumed decimal -- an ESP32-S3 bootloader at 0x0 and an app at
    0x10000 both have to parse correctly.
    """
    if not raw:
        raise ValueError("no images supplied")
    out: list[tuple[int, bytes]] = []
    for i, img in enumerate(raw):
        try:
            offset = int(str(img["offset"]), 0)
            data = base64.b64decode(img["data"], validate=True)
        except (KeyError, ValueError, TypeError) as e:
            raise ValueError(f"image {i}: {describe(e)}") from e
        if offset < 0:
            raise ValueError(f"image {i}: negative offset")
        if not data:
            raise ValueError(f"image {i}: empty payload")
        out.append((offset, data))
    return out


def register_hardware_tools(
    mcp: MCPServer,
    library: Library,
    designs: DesignStore,
    active: ActiveDesignTracker,
    jobs: JobRegistry,
    *,
    workbench_factory: Optional[Callable[[], Any]] = None,
    fleet_factory: Optional[Callable[[], Any]] = None,
) -> None:
    """Register the hardware tool surface on `mcp`.

    The factories exist so tests can inject fakes; production passes the
    same ones `create_app` already uses for the REST routes.
    """
    def _load(design_id: Optional[str]) -> tuple[Optional[str], Optional[dict]]:
        rid = design_id or active.get()
        if not rid:
            return None, None
        return rid, designs.load(rid)

    def _load_model(design_id: Optional[str]) -> tuple[Optional[Design], Optional[dict]]:
        """Load and validate; returns (design, error_dict) with one side None."""
        rid, raw = _load(design_id)
        if raw is None:
            return None, _NO_DESIGN
        try:
            return Design.model_validate(raw), None
        except Exception as e:
            return None, _err(f"design '{rid}' failed validation: {describe(e)}")

    def _workbench() -> Any:
        if workbench_factory is not None:
            return workbench_factory()
        from wirestudio.workbench import WorkbenchClient

        return WorkbenchClient()

    def _fleet() -> Any:
        if fleet_factory is not None:
            return fleet_factory()
        from wirestudio.fleet import FleetClient

        return FleetClient()

    _register_job_tools(mcp, jobs)
    _register_workbench_tools(mcp, jobs, _workbench, _fleet)
    _register_lorawan_tools(mcp, library, jobs, _load_model, _workbench)
    _register_fleet_tools(mcp, library, _load_model, _fleet)


# ---------------------------------------------------------------------------
# Job polling
# ---------------------------------------------------------------------------

def _register_job_tools(mcp: MCPServer, jobs: JobRegistry) -> None:
    @mcp.tool(
        name="job_status",
        description=(
            "Check a long-running job started by lorawan_compile, "
            "workbench_flash or lorawan_workbench_provision. Returns state "
            "('running' | 'done' | 'error'), event_count, the most recent "
            "event, and elapsed_s. Poll this until state leaves 'running'; "
            "use job_events for the full log. Note fleet builds are NOT "
            "these jobs -- poll a fleet run with fleet_job_status."
        ),
    )
    def job_status(job_id: str) -> dict:
        try:
            return {"ok": True, **jobs.status(job_id)}
        except JobNotFound:
            return _err(f"no such job: {job_id}")

    @mcp.tool(
        name="job_events",
        description=(
            "Read a job's event log incrementally. Pass since=0 first, then "
            "the returned next_since to get only what is new. `done` is true "
            "once the job has finished AND you have read every event."
        ),
    )
    def job_events(job_id: str, since: int = 0, limit: int = 200) -> dict:
        try:
            return {"ok": True, **jobs.events(job_id, since=since, limit=limit)}
        except JobNotFound:
            return _err(f"no such job: {job_id}")

    @mcp.tool(
        name="job_list",
        description=(
            "List jobs this server currently holds, newest last. Jobs are "
            "in-memory and are lost on restart."
        ),
    )
    def job_list() -> dict:
        return {"ok": True, "jobs": jobs.list()}


# ---------------------------------------------------------------------------
# Workbench
# ---------------------------------------------------------------------------

def _register_workbench_tools(
    mcp: MCPServer,
    jobs: JobRegistry,
    workbench: Callable[[], Any],
    fleet: Callable[[], Any],
) -> None:
    @mcp.tool(
        name="workbench_status",
        description=(
            "Is a remote workbench configured and reachable? Returns "
            "available, reason and url. Check this before workbench_slots "
            "or workbench_flash."
        ),
    )
    async def workbench_status() -> dict:
        wc = workbench()
        ok, reason = await wc.is_available()
        return {
            "ok": True,
            "available": ok,
            "reason": reason,
            "url": wc.base_url or None,
            "configure_hint": (
                None if ok else
                "Set WORKBENCH_URL=http://<pi>:8080. WORKBENCH_TOKEN is "
                "optional -- only needed if the bench sits behind an "
                "authenticating proxy."
            ),
        }

    @mcp.tool(
        name="workbench_verify_boot",
        description=(
            "Assert that firmware on a slot actually started, by watching "
            "the slot's serial for a line the running firmware emits. A "
            "successful flash only proves bytes reached the chip -- a wrong "
            "flash size or an undriven front end flashes perfectly and then "
            "fails at start-up. Frameworks: esphome, lorawan (standalone "
            "RadioLib), lorawan-esphome.\n\n"
            "Set check_join=true to additionally wait for the LoRaWAN join. "
            "It is off by default and generously timed because the first "
            "join after a flash reliably fails and only the retry, one "
            "uplink interval later, succeeds -- so asserting it immediately "
            "would fail on a healthy board.\n\n"
            "Pass `since` (an epoch from just before the flash) so the slot's "
            "already-captured output is searched before waiting on new "
            "lines -- a boot marker is printed once, seconds after reset, "
            "and is usually gone by the time you ask.\n\n"
            "Returns booted=true/false rather than erroring: a board that "
            "flashed but did not boot is a result. When it did not boot, "
            "recent_output carries what it printed instead."
        ),
    )
    async def workbench_verify_boot(
        slot: str, framework: str, check_join: bool = False,
        since: Optional[float] = None,
    ) -> dict:
        wc = workbench()
        if not wc.is_configured():
            return _err("workbench not configured (set WORKBENCH_URL)")
        from wirestudio.workbench.boot import verify_boot

        try:
            return await verify_boot(wc, slot, framework,
                                     since=since, check_join=check_join)
        except Exception as e:
            return _err(f"workbench unreachable: {describe(e)}")

    @mcp.tool(
        name="workbench_slots",
        description=(
            "List the bench's USB slots: label, state, present, detected "
            "chip, product string, and whether the slot is flashable right "
            "now (with blocked_reason when it isn't). Use the label as the "
            "`slot` argument to workbench_flash."
        ),
    )
    async def workbench_slots() -> dict:
        wc = workbench()
        if not wc.is_configured():
            return _err("workbench not configured (set WORKBENCH_URL)")
        try:
            slots = await wc.slots()
        except Exception as e:
            return _err(f"workbench unreachable: {describe(e)}")
        return {
            "ok": True,
            "slots": [
                {
                    "label": s.label,
                    "state": s.state,
                    "present": s.present,
                    "chip": s.chip,
                    "product": s.product,
                    "serial_url": s.serial_url,
                    "flapping": s.flapping,
                    "last_error": s.last_error,
                    "flashable": s.flashable[0],
                    "blocked_reason": s.flashable[1],
                }
                for s in slots
            ],
        }

    @mcp.tool(
        name="workbench_flash",
        description=(
            "Flash a bench slot and return a job_id; poll it with "
            "job_status. Supply the firmware either as `fleet_run_id` (the "
            "server fetches that build's artifact itself -- preferred) or "
            "as `images`, a list of {offset, data} with base64 `data` and "
            "`offset` like '0x10000'. Set chip to match the board "
            "(esp32, esp32s3, esp32c3...). erase=true wipes flash first, "
            "which also clears LoRaWAN DevNonce counters.\n\n"
            "With fleet_run_id the offset is detected from the artifact: a "
            "merged image (bootloader + partition table + app) is written "
            "at 0x0, a bare app image at 0x10000. Pass `offset` only to "
            "override that, and only if you know which kind the build "
            "publishes -- a merged image written at the app offset "
            "boot-loops the board."
        ),
    )
    async def workbench_flash(
        slot: str,
        fleet_run_id: Optional[str] = None,
        images: Optional[list[dict]] = None,
        chip: str = "esp32",
        erase: bool = False,
        baud: int = 921600,
        factory: bool = False,
        offset: Optional[str] = None,
    ) -> dict:
        wc = workbench()
        if not wc.is_configured():
            return _err("workbench not configured (set WORKBENCH_URL)")
        if bool(fleet_run_id) == bool(images):
            return _err("supply exactly one of fleet_run_id or images")

        if fleet_run_id:
            fc = fleet()
            if not fc.is_configured():
                return _err("fleet not configured (set FLEET_URL and FLEET_TOKEN)")
            try:
                blob = await fc.get_firmware(fleet_run_id, factory=factory)
            except Exception as e:
                return _err(f"could not fetch firmware for run {fleet_run_id}: {describe(e)}")
            # The artifact kind decides the offset and getting it wrong
            # bricks the board, so read it off the bytes rather than
            # trusting which endpoint served them.
            if offset is not None:
                try:
                    where = int(offset, 0)
                except ValueError:
                    return _err(f"offset is not a number: {offset!r}")
                if where < 0:
                    return _err("offset must not be negative")
            else:
                where = 0x0 if is_merged_image(blob) else _DEFAULT_APP_OFFSET
            parsed = [(where, blob)]
        else:
            try:
                parsed = _decode_images(images)
            except ValueError as e:
                return _err(str(e))

        try:
            ok, reason = (await wc.slot(slot)).flashable
        except Exception as e:
            return _err(f"workbench unreachable: {describe(e)}")
        if not ok:
            return _err(f"slot {slot} is not flashable: {reason}")

        total = sum(len(d) for _, d in parsed)
        job_id = jobs.start(
            "flash",
            lambda: wc.flash(
                slot=slot, images=parsed, chip=chip, erase=erase, baud=baud,
            ),
            label=f"{slot} {chip} ({total} bytes)",
        )
        return {"ok": True, "job_id": job_id, "slot": slot, "bytes": total}


# ---------------------------------------------------------------------------
# LoRaWAN / ChirpStack
# ---------------------------------------------------------------------------

def _register_lorawan_tools(
    mcp: MCPServer,
    library: Library,
    jobs: JobRegistry,
    load_model: Callable[[Optional[str]], tuple[Optional[Design], Optional[dict]]],
    workbench: Callable[[], Any],
) -> None:
    @mcp.tool(
        name="lorawan_chirpstack_status",
        description=(
            "Is ChirpStack configured and reachable? Read-only probe of the "
            "API token and endpoint. Check before any provision call."
        ),
    )
    def lorawan_chirpstack_status() -> dict:
        from wirestudio.targets.lorawan import chirpstack as cs

        return {"ok": True, **cs.chirpstack_status()}

    @mcp.tool(
        name="lorawan_compile",
        description=(
            "Build standalone LoRaWAN firmware for a design and return a "
            "job_id; poll it with job_status. This is the RadioLib "
            "standalone path, not the ESPHome external-component path. "
            "Validates the design and its board's radio block eagerly, so a "
            "bad design fails here rather than inside the job."
        ),
    )
    def lorawan_compile(design_id: Optional[str] = None) -> dict:
        design, err = load_model(design_id)
        if err:
            return err
        from wirestudio.targets import get_target
        from wirestudio.targets.lorawan.firmware import generate_firmware

        try:
            generate_firmware(design, library)  # eager: board + radio block
        except (FileNotFoundError, ValueError) as e:
            return _err(str(e))

        backend = get_target("lorawan").build_backend()
        build_id = backend.enqueue(design, library)
        job_id = jobs.start(
            "compile",
            lambda: backend.stream(build_id, design, library),
            label=design.id,
        )
        return {"ok": True, "job_id": job_id, "design_id": design.id}

    @mcp.tool(
        name="lorawan_provision",
        description=(
            "Register a device in ChirpStack for the standalone RadioLib "
            "path and issue its AppKey. Returns the DevEUI/JoinEUI/AppKey "
            "to type into the device's serial provisioning prompt. The "
            "AppKey is generated server-side, returned once, and never "
            "written to design.json. Use lorawan_provision_esphome instead "
            "for the ESPHome external-component path."
        ),
    )
    def lorawan_provision(
        dev_eui: str,
        design_id: Optional[str] = None,
        application_name: str = "wirestudio",
    ) -> dict:
        import secrets as _secrets

        dev_eui = dev_eui.lower()
        if not _valid_eui(dev_eui):
            return _err("dev_eui must be 16 hex characters")
        design, err = load_model(design_id)
        if err:
            return err

        from wirestudio.targets.lorawan import chirpstack as cs
        from wirestudio.targets.lorawan.codec import generate_codec, profile_name

        client = cs.ChirpStackClient()
        if not client.is_configured():
            return _err(
                "ChirpStack not configured "
                "(set CHIRPSTACK_API_TOKEN / CHIRPSTACK_API_URL)"
            )
        join_eui = (
            design.lorawan.join_eui
            if design.lorawan and design.lorawan.join_eui else None
        )
        app_key = _secrets.token_hex(16)
        try:
            result = client.provision_device(
                dev_eui=dev_eui,
                app_key=app_key,
                application_name=application_name,
                device_profile_name=profile_name(design, library),
                join_eui=join_eui,
                codec=generate_codec(design, library),
            )
        except cs.ChirpStackUnavailable as e:
            return _err(str(e))
        return {
            "ok": True,
            "dev_eui": dev_eui,
            "join_eui": join_eui or "0000000000000000",
            "band": "US915",
            "sub_band": 2,
            "app_key": app_key,
            "application_id": result["application_id"],
            "device_profile_id": result["device_profile_id"],
        }

    @mcp.tool(
        name="lorawan_provision_esphome",
        description=(
            "Register a device in ChirpStack for the ESPHome "
            "external-component path (lorawan-for-esphome). Returns keys "
            "formatted for secrets.yaml rather than a serial prompt. "
            "Requires design.lorawan.payload to be non-empty. The profile "
            "is created without a codec; set one afterwards once the "
            "payload format has settled."
        ),
    )
    def lorawan_provision_esphome(
        dev_eui: str,
        design_id: Optional[str] = None,
        application_name: str = "wirestudio-esphome",
    ) -> dict:
        import secrets as _secrets

        dev_eui = dev_eui.lower()
        if not _valid_eui(dev_eui):
            return _err("dev_eui must be 16 hex characters")
        design, err = load_model(design_id)
        if err:
            return err
        if design.lorawan is None or not design.lorawan.payload:
            return _err(
                "design.lorawan.payload must be non-empty for the ESPHome "
                "external-component path"
            )

        from wirestudio.targets.lorawan import chirpstack as cs

        zero = "0000000000000000"
        join_eui = design.lorawan.join_eui or zero
        client = cs.ChirpStackClient()
        if not client.is_configured():
            return _err(
                "ChirpStack not configured "
                "(set CHIRPSTACK_API_TOKEN / CHIRPSTACK_API_URL)"
            )
        app_key = _secrets.token_hex(16)
        try:
            result = client.provision_device(
                dev_eui=dev_eui,
                app_key=app_key,
                application_name=application_name,
                device_profile_name=(
                    f"wirestudio-esphome-{design.lorawan.region.lower()}"
                    f"-sub{design.lorawan.sub_band}"
                ),
                join_eui=join_eui if join_eui != zero else None,
                codec=None,
            )
        except cs.ChirpStackUnavailable as e:
            return _err(str(e))
        return {
            "ok": True,
            "secrets": {
                "dev_eui": dev_eui,
                "join_eui": join_eui,
                "app_key": app_key,
            },
            "chirpstack": {
                "application_id": result["application_id"],
                "device_profile_id": result["device_profile_id"],
            },
            "band": design.lorawan.region,
            "sub_band": design.lorawan.sub_band,
        }

    @mcp.tool(
        name="lorawan_activation",
        description=(
            "Has the device joined the network? Reads ChirpStack's "
            "activation record. Returns joined=false until the OTAA join "
            "lands -- a freshly flashed device typically waits one full "
            "uplink interval before its first join attempt, so poll rather "
            "than concluding failure from one call."
        ),
    )
    def lorawan_activation(dev_eui: str) -> dict:
        dev_eui = dev_eui.lower()
        if not _valid_eui(dev_eui):
            return _err("dev_eui must be 16 hex characters")
        from wirestudio.targets.lorawan import chirpstack as cs

        client = cs.ChirpStackClient()
        if not client.is_configured():
            return _err("ChirpStack not configured")
        try:
            act = client.get_activation(dev_eui)
        except cs.ChirpStackUnavailable as e:
            return _err(str(e))
        return {"ok": True, "dev_eui": dev_eui, "joined": act is not None, **(act or {})}

    @mcp.tool(
        name="lorawan_workbench_provision",
        description=(
            "The whole bring-up on one slot: flash, register in ChirpStack, "
            "push keys over the device's serial prompt, and verify. Returns "
            "a job_id; poll it with job_status. Supply `images` as "
            "{offset, data} with base64 `data`. erase defaults to true "
            "because a re-provisioned device must restart its DevNonce "
            "counter or the network rejects its joins as replays."
        ),
    )
    def lorawan_workbench_provision(
        slot: str,
        images: list[dict],
        design_id: Optional[str] = None,
        erase: bool = True,
        application_name: str = "wirestudio",
    ) -> dict:
        design, err = load_model(design_id)
        if err:
            return err
        try:
            parsed = _decode_images(images)
        except ValueError as e:
            return _err(str(e))

        from wirestudio.targets.lorawan import chirpstack as cs
        from wirestudio.targets.lorawan.workbench_provision import provision_events

        wb = workbench()
        if not wb.is_configured():
            return _err("workbench not configured (set WORKBENCH_URL)")
        chirp = cs.ChirpStackClient()
        if not chirp.is_configured():
            return _err(
                "ChirpStack not configured "
                "(set CHIRPSTACK_API_TOKEN / CHIRPSTACK_API_URL)"
            )
        try:
            ok, reason = wb.slot_sync(slot).flashable
        except Exception as e:
            return _err(f"workbench unreachable: {describe(e)}")
        if not ok:
            return _err(f"slot {slot} is not flashable: {reason}")

        job_id = jobs.start(
            "provision",
            lambda: provision_events(
                design, library,
                slot=slot, workbench=wb, chirpstack=chirp,
                images=parsed, erase=erase, application_name=application_name,
            ),
            label=f"{slot} {design.id}",
        )
        return {"ok": True, "job_id": job_id, "slot": slot, "design_id": design.id}


# ---------------------------------------------------------------------------
# Fleet
# ---------------------------------------------------------------------------

def _register_fleet_tools(
    mcp: MCPServer,
    library: Library,
    load_model: Callable[[Optional[str]], tuple[Optional[Design], Optional[dict]]],
    fleet: Callable[[], Any],
) -> None:
    @mcp.tool(
        name="fleet_status",
        description=(
            "Is the ESPHome fleet addon configured and reachable? Check "
            "before fleet_push."
        ),
    )
    async def fleet_status() -> dict:
        fc = fleet()
        if not fc.is_configured():
            return {
                "ok": True, "available": False,
                "reason": "FLEET_URL not set" if not fc.base_url else "FLEET_TOKEN not set",
                "url": fc.base_url or None,
            }
        ok, reason = await fc.is_available()
        return {"ok": True, "available": ok, "reason": reason, "url": fc.base_url or None}

    @mcp.tool(
        name="fleet_push",
        description=(
            "Render a design to ESPHome YAML and push it to the fleet "
            "addon, optionally starting a compile. Returns run_id -- poll "
            "it with fleet_job_status, then pass it to workbench_flash as "
            "fleet_run_id. This is a fleet run handle, not a job_id: it "
            "belongs to the addon and survives a wirestudio restart."
        ),
    )
    async def fleet_push(
        design_id: Optional[str] = None,
        device_name: Optional[str] = None,
        compile: bool = True,
    ) -> dict:
        design, err = load_model(design_id)
        if err:
            return err
        from wirestudio.targets import get_target

        try:
            artifacts = get_target(design.target).generate(design, library)
            yaml_text = artifacts.get("firmware.yaml")
        except (FileNotFoundError, ValueError, KeyError) as e:
            return _err(str(e))
        if not yaml_text:
            return _err(f"target '{design.target}' does not produce firmware.yaml")

        name = (
            device_name
            or (design.fleet.device_name if design.fleet and design.fleet.device_name else None)
            or design.id
        )
        fc = fleet()
        if not fc.is_configured():
            return _err("fleet not configured (set FLEET_URL and FLEET_TOKEN)")
        try:
            result = await fc.push_device(name, yaml_text, compile=compile)
        except ValueError as e:
            return _err(str(e))
        except Exception as e:
            return _err(f"fleet unreachable: {describe(e)}")
        return {
            "ok": True,
            "filename": result.filename,
            "created": result.created,
            "run_id": result.run_id,
            "enqueued": result.enqueued,
        }

    @mcp.tool(
        name="fleet_job_status",
        description=(
            "Compile verdict for a fleet run: running | passed | failed | "
            "cancelled | unknown. A run that has aged out of the addon's "
            "queue comes back 'unknown', which means 'no longer tracked', "
            "not 'failed'."
        ),
    )
    async def fleet_job_status(run_id: str) -> dict:
        fc = fleet()
        if not fc.is_configured():
            return _err("fleet not configured (set FLEET_URL and FLEET_TOKEN)")
        try:
            status = await fc.get_run_status(run_id)
        except Exception as e:
            return _err(f"fleet unreachable: {describe(e)}")
        return {
            "ok": True,
            "run_id": status.run_id,
            "verdict": status.verdict,
            "jobs": [
                {
                    "job_id": j.job_id,
                    "target": j.target,
                    "state": j.state,
                    "finished_at": j.finished_at,
                }
                for j in status.jobs
            ],
        }

    @mcp.tool(
        name="fleet_job_log",
        description=(
            "Read a fleet build log incrementally. Pass offset=0 first, "
            "then the returned offset to fetch only what is new."
        ),
    )
    async def fleet_job_log(run_id: str, offset: int = 0) -> dict:
        fc = fleet()
        if not fc.is_configured():
            return _err("fleet not configured (set FLEET_URL and FLEET_TOKEN)")
        try:
            chunk = await fc.get_job_log(run_id, offset=offset)
        except Exception as e:
            return _err(f"fleet unreachable: {describe(e)}")
        return {
            "ok": True, "run_id": run_id,
            "log": chunk.log, "offset": chunk.offset, "finished": chunk.finished,
        }

    @mcp.tool(
        name="fleet_firmware_info",
        description=(
            "Report whether a fleet run's compiled firmware is available "
            "and how large it is. Deliberately does NOT return the bytes -- "
            "pass the run_id to workbench_flash as fleet_run_id and the "
            "server moves the image to the board directly."
        ),
    )
    async def fleet_firmware_info(run_id: str, factory: bool = False) -> dict:
        fc = fleet()
        if not fc.is_configured():
            return _err("fleet not configured (set FLEET_URL and FLEET_TOKEN)")
        try:
            blob = await fc.get_firmware(run_id, factory=factory)
        except Exception as e:
            return _err(f"firmware not available for run {run_id}: {describe(e)}")
        return {"ok": True, "run_id": run_id, "factory": factory, "bytes": len(blob)}
