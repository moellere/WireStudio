"""Port compatibility validation.

Walks each `kind: gpio` connection in a design, infers direction from the
library pin's kind, and emits warnings when the assigned board pin has
restrictions that conflict with the use:

- `boot_strap_output`  -- pin must be HIGH or LOW at boot, used as output
- `input_only_as_output` -- input-only pin used as output (hard error)
- `serial_console`     -- pin shared with the USB serial console
- `voltage_limit`      -- pin has a voltage cap (e.g., D1 Mini A0 max 1.0V)
- `function_unsupported` -- pin tagged no_pwm/no_i2c/no_interrupt assigned to
                            a peripheral that depends on that capability
- `adc2_wifi_conflict`  -- analog_in landed on an `adc2`-tagged pin on a
                            classic ESP32 board; the WiFi driver claims ADC2
                            so reads return errors / stale values
- `locked_pin_invalid`  -- a component's `locked_pins[role]` points at a
                            board pin whose capabilities don't satisfy the
                            library role's required kind

Pure: doesn't mutate the design, doesn't render, doesn't hit the network.
Cheap enough to run on every render call.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from studio.library import Library, LibraryComponent


@dataclass
class CompatibilityWarning:
    severity: str   # "info" | "warn" | "error"
    code: str
    pin: str
    component_id: str
    pin_role: str
    message: str


# Library pin kinds that drive the line (output direction).
_OUTPUT_KINDS = {
    "digital_out", "i2s_dout", "uart_tx", "spi_cs",
    "spi_clk", "spi_mosi",          # the controller drives these
    "i2s_lrclk", "i2s_bclk",
}
# Library pin kinds that read the line (input direction).
_INPUT_KINDS = {
    "digital_in", "analog_in", "uart_rx", "spi_miso",
}


def _direction_for(kind: str) -> Optional[str]:
    if kind in _OUTPUT_KINDS:
        return "out"
    if kind in _INPUT_KINDS:
        return "in"
    return None  # power, ground, i2c (bidi handled at the bus layer), etc.


def check_pin_compatibility(design: dict, library: Library) -> list[CompatibilityWarning]:
    out: list[CompatibilityWarning] = []

    board_lib_id = (design.get("board") or {}).get("library_id")
    if not board_lib_id:
        return out
    try:
        board = library.board(board_lib_id)
    except FileNotFoundError:
        return out

    components_by_id = {c["id"]: c for c in design.get("components") or []}
    lib_components: dict[str, LibraryComponent] = {}
    for cid, c in components_by_id.items():
        try:
            lib_components[cid] = library.component(c["library_id"])
        except FileNotFoundError:
            continue

    for conn in design.get("connections") or []:
        target = conn.get("target") or {}
        if target.get("kind") != "gpio":
            continue
        pin_name = target.get("pin")
        if not pin_name:
            continue  # unbound; the pin solver handles that path

        comp = components_by_id.get(conn.get("component_id"))
        lib_comp = lib_components.get(comp["id"]) if comp else None
        if not comp or not lib_comp:
            continue
        lib_pin = next(
            (p for p in lib_comp.electrical.pins if p.role == conn["pin_role"]),
            None,
        )
        if not lib_pin:
            continue

        caps = set(board.gpio_capabilities.get(pin_name, []))
        if not caps:
            continue  # unknown pin; the schema validator catches that
        direction = _direction_for(lib_pin.kind)
        component_id = comp["id"]
        pin_role = lib_pin.role

        # 1. Input-only pin used as output is a hard error.
        if direction == "out" and "input_only" in caps:
            out.append(CompatibilityWarning(
                severity="error",
                code="input_only_as_output",
                pin=pin_name,
                component_id=component_id,
                pin_role=pin_role,
                message=(
                    f"{pin_name} is input-only and cannot drive an output. "
                    f"{component_id}.{pin_role} ({lib_pin.kind}) needs an output. "
                    f"Pick a different pin."
                ),
            ))

        # 2. Boot strap pin used as output -- warn.
        if direction == "out":
            if "boot_high" in caps:
                out.append(CompatibilityWarning(
                    severity="warn",
                    code="boot_strap_output",
                    pin=pin_name,
                    component_id=component_id,
                    pin_role=pin_role,
                    message=(
                        f"{pin_name} must be HIGH at boot. Driving it as an output "
                        f"({component_id}.{pin_role}) is risky -- if the line is "
                        f"LOW or floating during the bootloader phase, the chip "
                        f"won't boot. Acceptable when the wired component leaves "
                        f"this pin pulled HIGH at boot (e.g., a CS line that's "
                        f"inactive-HIGH); otherwise pick a non-strap pin."
                    ),
                ))
            elif "boot_low" in caps:
                out.append(CompatibilityWarning(
                    severity="warn",
                    code="boot_strap_output",
                    pin=pin_name,
                    component_id=component_id,
                    pin_role=pin_role,
                    message=(
                        f"{pin_name} must be LOW at boot. Driving it as an output "
                        f"({component_id}.{pin_role}) is risky -- if the line is "
                        f"HIGH during the bootloader phase, the chip may enter "
                        f"the wrong boot mode (download mode, 1.8V flash voltage, "
                        f"etc.). Pick a non-strap pin if you can."
                    ),
                ))

        # 3. Serial console pin used at all.
        if "serial_tx" in caps or "serial_rx" in caps:
            tx_or_rx = "TX" if "serial_tx" in caps else "RX"
            out.append(CompatibilityWarning(
                severity="warn",
                code="serial_console",
                pin=pin_name,
                component_id=component_id,
                pin_role=pin_role,
                message=(
                    f"{pin_name} is shared with the serial console ({tx_or_rx}). "
                    f"Connecting {component_id}.{pin_role} here conflicts with USB "
                    f"flashing/logging and can corrupt boot output. Acceptable on "
                    f"deployed devices that don't use the USB UART; otherwise "
                    f"pick a different pin."
                ),
            ))

        # 4. ADC voltage limit (informational).
        if direction == "in" and "adc_max_1v" in caps and lib_pin.kind == "analog_in":
            out.append(CompatibilityWarning(
                severity="info",
                code="voltage_limit",
                pin=pin_name,
                component_id=component_id,
                pin_role=pin_role,
                message=(
                    f"{pin_name} has a 1.0V max input ceiling (after the board's "
                    f"onboard divider mapping 3.3V -> 1.0V). Verify your sensor's "
                    f"output stays within range or readings will saturate."
                ),
            ))

        # 4b. ADC2/WiFi conflict (classic ESP32 only). The WiFi driver claims
        # ADC2 at runtime; reads on these pins return ESP_ERR_TIMEOUT under
        # IDF or undefined values under Arduino while WiFi is up. ESPHome
        # always brings WiFi up, so this is effectively a hard restriction.
        if (
            direction == "in"
            and lib_pin.kind == "analog_in"
            and "adc2" in caps
            and getattr(board, "chip_variant", None) == "esp32"
        ):
            out.append(CompatibilityWarning(
                severity="warn",
                code="adc2_wifi_conflict",
                pin=pin_name,
                component_id=component_id,
                pin_role=pin_role,
                message=(
                    f"{pin_name} is on ADC2, which the ESP32's WiFi driver "
                    f"claims at runtime. Analog reads on this pin will fail "
                    f"or return stale values while WiFi is up. Move "
                    f"{component_id}.{pin_role} to an ADC1 pin "
                    f"(GPIO32-39 on classic ESP32)."
                ),
            ))

        # 5. Functional restrictions (no_pwm, no_i2c, no_interrupt) on the pin
        # itself. We can only check these against the library pin kind today;
        # finer checks (this pin is on an I2C bus, but no_i2c-tagged) live at
        # the bus layer below.
        if direction == "out" and "no_pwm" in caps and lib_pin.kind == "i2s_dout":
            out.append(CompatibilityWarning(
                severity="warn",
                code="function_unsupported",
                pin=pin_name,
                component_id=component_id,
                pin_role=pin_role,
                message=(
                    f"{pin_name} doesn't support PWM/timer outputs, which the "
                    f"high-speed signal on {component_id}.{pin_role} typically "
                    f"requires. Pick a PWM-capable pin."
                ),
            ))

    # 6. Bus-level pin checks. The pins assigned to a bus's clk/mosi/tx/lrclk
    # are driven by the MCU as outputs and need the same boot-strap and
    # input-only treatment as direct gpio outputs. Plus the i2c-specific
    # capability (no_i2c) and serial-console pins.
    out.extend(_bus_pin_warnings(design, board))

    # 7. locked_pins capability validation. A user-locked pin should
    # actually be able to play the role's library kind (analog_in lock
    # on a non-ADC pin is a mistake worth surfacing).
    out.extend(_locked_pin_warnings(components_by_id, lib_components, board))

    return out


# Mirror of pin_solver's required-cap map. Kept local to avoid an import
# cycle and because the two modules are deliberately independent.
_LOCKED_PIN_REQUIRED_CAPS: dict[str, set[str]] = {
    "analog_in": {"adc"},
    # digital_in / digital_out / spi_cs all just need `gpio`; the lock is
    # validated against the same set the solver uses.
    "digital_in":  {"gpio"},
    "digital_out": {"gpio"},
    "spi_cs":      {"gpio"},
    "i2s_dout":    {"gpio"},
}


def _locked_pin_warnings(
    components_by_id: dict[str, dict],
    lib_components: dict[str, LibraryComponent],
    board,
) -> list[CompatibilityWarning]:
    out: list[CompatibilityWarning] = []
    for cid, comp in components_by_id.items():
        locked = comp.get("locked_pins") or {}
        if not isinstance(locked, dict) or not locked:
            continue
        lib_comp = lib_components.get(cid)
        if lib_comp is None:
            continue
        for role, pin_name in locked.items():
            lib_pin = next(
                (p for p in lib_comp.electrical.pins if p.role == role), None,
            )
            if lib_pin is None:
                # The solver already flags unknown roles; skip here.
                continue
            caps = set(board.gpio_capabilities.get(str(pin_name), []))
            if not caps:
                # Unknown pin name: solver/schema territory, not capability.
                continue
            required = _LOCKED_PIN_REQUIRED_CAPS.get(lib_pin.kind, set())
            if required and not required.issubset(caps):
                missing = ", ".join(sorted(required - caps))
                out.append(CompatibilityWarning(
                    severity="error",
                    code="locked_pin_invalid",
                    pin=str(pin_name),
                    component_id=cid,
                    pin_role=role,
                    message=(
                        f"{cid}.{role} is locked to {pin_name}, but that pin "
                        f"lacks {missing} which {lib_pin.kind} requires. "
                        f"Pick a different pin or remove the lock."
                    ),
                ))
    return out


def _bus_pin_warnings(design: dict, board) -> list[CompatibilityWarning]:
    """Run the same boot-strap / input-only / serial-console / no-i2c checks
    against the pins assigned to design.buses entries."""
    out: list[CompatibilityWarning] = []

    # role -> ("out" | "in") direction for each bus type. The MCU drives the
    # output side; serial console and no_i2c apply to any pin assigned.
    bus_roles: dict[str, dict[str, str]] = {
        "i2c":   {"sda": "io",  "scl": "out"},
        "spi":   {"clk": "out", "mosi": "out", "miso": "in", "cs": "out"},
        "uart":  {"tx": "out",  "rx": "in"},
        "i2s":   {"lrclk": "out", "bclk": "out"},
        # 1-wire is bidirectional on a single line; the master holds the
        # pull-up high and either side drops it. We tag direction "io"
        # because the boot-strap warnings on the master side still apply
        # (the host configures the pin) but input-only pins are usable
        # in slave-only configurations -- we leave that nuance for a
        # later pass and treat the pin like the i2c sda case.
        "1wire": {"pin": "io"},
    }

    for bus in design.get("buses") or []:
        bus_type = bus.get("type")
        if bus_type not in bus_roles:
            continue
        bus_id = str(bus.get("id", ""))
        for role, direction in bus_roles[bus_type].items():
            pin = bus.get(role)
            if not pin:
                continue
            caps = set(board.gpio_capabilities.get(pin, []))
            if not caps:
                continue
            role_label = role.upper()

            # i2c-specific: no_i2c-tagged pin.
            if bus_type == "i2c" and "no_i2c" in caps:
                out.append(CompatibilityWarning(
                    severity="warn",
                    code="function_unsupported",
                    pin=pin,
                    component_id=bus_id,
                    pin_role=role_label,
                    message=(
                        f"{pin} doesn't support I2C on this chip (commonly the "
                        f"GPIO16-style pin without the right input mode). The bus "
                        f"'{bus_id}' uses it as {role_label} -- the bus is unlikely "
                        f"to work."
                    ),
                ))
                continue

            # Output-side bus pin: boot strap warnings + input_only error.
            if direction == "out":
                if "input_only" in caps:
                    out.append(CompatibilityWarning(
                        severity="error",
                        code="input_only_as_output",
                        pin=pin,
                        component_id=bus_id,
                        pin_role=role_label,
                        message=(
                            f"{pin} is input-only and cannot drive an output. "
                            f"Bus '{bus_id}' uses it as {role_label}. Pick a "
                            f"different pin for this bus role."
                        ),
                    ))
                if "boot_high" in caps:
                    out.append(CompatibilityWarning(
                        severity="warn",
                        code="boot_strap_output",
                        pin=pin,
                        component_id=bus_id,
                        pin_role=role_label,
                        message=(
                            f"{pin} must be HIGH at boot. Bus '{bus_id}' drives it "
                            f"as {role_label}; if the line settles LOW during the "
                            f"bootloader phase the chip may not boot. Acceptable "
                            f"when the line is naturally HIGH at boot (e.g., a CS "
                            f"line that's inactive-HIGH); otherwise pick a "
                            f"non-strap pin."
                        ),
                    ))
                elif "boot_low" in caps:
                    out.append(CompatibilityWarning(
                        severity="warn",
                        code="boot_strap_output",
                        pin=pin,
                        component_id=bus_id,
                        pin_role=role_label,
                        message=(
                            f"{pin} must be LOW at boot. Bus '{bus_id}' drives it "
                            f"as {role_label}; if the line settles HIGH during the "
                            f"bootloader phase the chip may enter the wrong boot "
                            f"mode. Pick a non-strap pin if you can."
                        ),
                    ))

            # Any direction: serial console pin is suspicious.
            if "serial_tx" in caps or "serial_rx" in caps:
                tx_or_rx = "TX" if "serial_tx" in caps else "RX"
                out.append(CompatibilityWarning(
                    severity="warn",
                    code="serial_console",
                    pin=pin,
                    component_id=bus_id,
                    pin_role=role_label,
                    message=(
                        f"{pin} is shared with the USB serial console ({tx_or_rx}). "
                        f"Bus '{bus_id}' uses it as {role_label}; this conflicts "
                        f"with USB flashing/logging."
                    ),
                ))

    return out
