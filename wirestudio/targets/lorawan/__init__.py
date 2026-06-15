from __future__ import annotations

from wirestudio.library import Library
from wirestudio.model import Design, DesignWarning
from wirestudio.targets.base import TargetPlugin, register


class LorawanTarget(TargetPlugin):
    """LoRaWAN firmware target.

    Today it constrains board selection to boards carrying a LoRa radio and
    runs a couple of permissive design checks. Firmware generation, ChirpStack
    provisioning, browser flashing, and the join/uplink confirmation endpoints
    arrive in later phases and lazy-import their heavy deps then.

    The ChirpStack gRPC client lives in ``wirestudio.targets.lorawan.chirpstack``
    and is imported on demand, never here -- importing this target must not pull
    in grpcio/chirpstack-api.
    """

    id = "lorawan"

    def board_ids(self, library: Library) -> list[str]:
        return sorted(b.id for b in library.list_boards() if b.has_radio)

    def component_ids(self, library: Library) -> list[str]:
        return sorted(c.id for c in library.list_components() if c.lorawan is not None)

    def generate(self, design: Design, library: Library) -> dict[str, str]:
        from wirestudio.generate.ascii_gen import render_ascii
        from wirestudio.targets.lorawan.firmware_gen import generate_firmware

        artifacts = generate_firmware(design, library)
        # The wiring/BOM diagram is framework-neutral; emit it too so the
        # design-preview endpoint (/design/render) shows the pinout for a
        # lorawan design instead of nothing.
        artifacts["wiring.txt"] = render_ascii(design, library)
        return artifacts

    def router(self, library: Library):
        # Lazy: keeps the firmware/compile imports out of the target's import path.
        from wirestudio.targets.lorawan.api import build_router

        return build_router(library)

    def validate(self, design: Design, library: Library) -> list[DesignWarning]:
        warnings: list[DesignWarning] = []
        try:
            board = library.board(design.board.library_id)
        except FileNotFoundError:
            # An unknown board is surfaced by the core validators; not our job.
            return warnings
        if not board.has_radio:
            warnings.append(
                DesignWarning(
                    level="error",
                    code="lorawan_board_no_radio",
                    text=(
                        f"board {board.id!r} has no LoRa radio; the lorawan "
                        "target needs an SX127x or SX126x board"
                    ),
                )
            )
        if design.lorawan is None:
            warnings.append(
                DesignWarning(
                    level="warn",
                    code="lorawan_unconfigured",
                    text=(
                        "target is 'lorawan' but no lorawan config is set; "
                        "US915 sub-band 2 defaults will be assumed"
                    ),
                )
            )
        # On the classic ESP32, U0RXD/U0TXD are GPIO3/GPIO1 -- the USB-serial
        # console the provisioning prompt reads. A GPS UART there floods the
        # prompt with garbage and the device never joins.
        gps = design.lorawan.gps if design.lorawan else None
        if gps and board.chip_variant == "esp32" and (
            {gps.rx_pin, gps.tx_pin} & {"GPIO1", "GPIO3"}
        ):
            warnings.append(
                DesignWarning(
                    level="warn",
                    code="lorawan_gps_on_console_uart",
                    text=(
                        f"GPS UART on {gps.rx_pin}/{gps.tx_pin} overlaps the USB-serial "
                        "console (U0RXD/U0TXD) on the classic ESP32 -- the GPS floods the "
                        "provisioning prompt and the device can't join. Use other pins "
                        "(e.g. GPIO23/GPIO17)."
                    ),
                )
            )
        return warnings


register(LorawanTarget())
