from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Board(_Strict):
    """The board this design targets.

    `flash_size_mb` overrides the library board file's value for this design
    only. It exists for boards sold in several flash sizes under one name --
    the ESP32-S3-DevKitC-1 ships as N8/N8R2/N8R8 (8MB) and N32R16V (32MB) --
    where the board file pins the floor because no static value is right for
    every unit. Set it only from a measured size (the ESP-IDF bootloader's
    "SPI Flash Size" banner, or `esptool flash-id`): raising it past what the
    chip has boot-loops the board. Restricted to sizes both generators can
    emit a partition table for, and ignored on non-ESP32 boards.
    """
    library_id: str
    mcu: str
    framework: str = "arduino"
    flash_size_mb: Optional[Literal[4, 8, 16, 32]] = None


class Power(_Strict):
    supply: str
    rail_voltage_v: float
    regulator: Optional[str] = None
    budget_ma: Optional[int] = None


class Requirement(_Strict):
    id: str
    kind: Literal["capability", "environment", "constraint"]
    text: str


class ModuleRef(_Strict):
    """Provenance for a component inserted as part of a composite module.

    `instance` is unique per insertion so two of the same module stay
    distinct; the BOM collapses each instance to a single module line.
    """
    module_id: str
    instance: str


class Component(_Strict):
    id: str
    library_id: str
    label: str
    # Free text shown in the inspector; no generator reads it.
    role: Optional[str] = None
    params: dict = Field(default_factory=dict)
    locked_pins: dict[str, str] = Field(default_factory=dict)
    # Set when the component was inserted as part of a composite module
    # (wirestudio/library/modules/). The BOM lists the module, not this part.
    module: Optional[ModuleRef] = None


# The bus-shaped names in esphome.config_validation.RESERVED_IDS: ESPHome
# refuses them as ids because they name its own peripherals.
RESERVED_BUS_IDS = frozenset({"uart0", "uart1", "uart2", "spi0", "spi1"})


def generated_bus_id(bus_type: str, n: int) -> str:
    """The n-th generated id for a bus type: i2c0, i2c1, ... and, for the
    types whose plain names ESPHome reserves, uart_bus0, spi_bus0, ..."""
    if f"{bus_type}0" in RESERVED_BUS_IDS:
        return f"{bus_type}_bus{n}"
    return f"{bus_type}{n}"


# Per bus type, the pin fields ESPHome needs: one of each group set.
BUS_PIN_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "i2c": (("sda",), ("scl",)),
    "spi": (("clk",), ("miso", "mosi")),
    "uart": (("rx", "tx"),),
    "1wire": (("pin",),),
    "i2s": (("lrclk",), ("bclk",)),
}


def missing_bus_pins(bus: dict) -> list[str]:
    """The pin groups `bus` leaves empty, e.g. ['pin'] or ['miso/mosi']."""
    return ["/".join(group) for group in BUS_PIN_GROUPS.get(bus.get("type"), ())
            if not any(bus.get(k) for k in group)]


class Bus(_Strict):
    id: str
    type: Literal["i2c", "spi", "uart", "1wire", "i2s"]
    frequency_hz: Optional[int] = None
    baud_rate: Optional[int] = None
    sda: Optional[str] = None
    scl: Optional[str] = None
    miso: Optional[str] = None
    mosi: Optional[str] = None
    clk: Optional[str] = None
    cs: Optional[str] = None
    rx: Optional[str] = None
    tx: Optional[str] = None
    lrclk: Optional[str] = None
    bclk: Optional[str] = None
    # 1-wire data pin. Single-wire bus, so the bus carries one pin field
    # rather than the multi-pin sets the synchronous buses use.
    pin: Optional[str] = None
    # UART parity. ESPHome's cse7766 requires EVEN; most other UART
    # peripherals are happy with NONE (the default if omitted).
    parity: Optional[Literal["NONE", "EVEN", "ODD"]] = None


class RailTarget(_Strict):
    kind: Literal["rail"]
    rail: str


class GpioTarget(_Strict):
    kind: Literal["gpio"]
    pin: str


class BusTarget(_Strict):
    kind: Literal["bus"]
    bus_id: str


class ExpanderPinTarget(_Strict):
    kind: Literal["expander_pin"]
    expander_id: str
    number: int
    mode: Optional[str] = None
    inverted: bool = False


class ComponentTarget(_Strict):
    """Connection target referencing another component instance.

    Used when a component is logically a child of a hub it shares no
    physical pins with -- e.g., an `ads1115_channel` references its
    `ads1115` hub by component id, and the generated YAML pulls the
    hub's id into the channel's sensor entry.
    """
    kind: Literal["component"]
    component_id: str


class NetTarget(_Strict):
    """A passthrough pin landing on a net another component already owns:
    the net that component's `net` role is wired to, or, for a subcircuit
    component, one of its internal nodes (`bridge` / `out_a`). Empty
    strings are the placeholder a fresh connector pin carries until the
    form or `set_connection` fills it in.
    """
    kind: Literal["net"]
    component_id: str = ""
    net: str = ""


ConnectionTarget = Annotated[
    Union[RailTarget, GpioTarget, BusTarget, ExpanderPinTarget, ComponentTarget, NetTarget],
    Field(discriminator="kind"),
]


class Connection(_Strict):
    component_id: str
    pin_role: str
    target: ConnectionTarget


class Passive(_Strict):
    id: str
    kind: Literal["resistor", "capacitor", "inductor", "diode", "transistor"]
    value: str
    between: list[str]
    purpose: Optional[str] = None


class DesignWarning(_Strict):
    level: Literal["info", "warn", "error"]
    code: str
    text: str


class AutomationTrigger(_Strict):
    """The event side of one automation: a component emits an event the
    component's library `capability.provides` declares. `component_id` is a
    design-level id (the validator checks it resolves). `channel` selects a
    sub-block on multi-channel components (e.g. `temperature` on a bme280) --
    the provides entry must match both event AND channel.

    `above` / `below` are threshold bounds for the `on_value_range` event:
    the trigger fires when the value enters the [above, below] band (either
    bound may be omitted for an open-ended range). At least one must be set
    when the event is `on_value_range`, and they may NOT be set on any other
    event -- the validator surfaces both as warnings."""
    component_id: str
    event: str
    channel: Optional[str] = None
    above: Optional[float] = None
    below: Optional[float] = None


class AutomationCondition(_Strict):
    """One predicate that gates an automation: the actions only fire when the
    condition holds. `component_id` is a design-level id; `predicate` is the
    studio-side name (e.g. `is_on`) that must appear in the component's
    `capability.checks`. Multiple conditions on one automation are combined
    as ESPHome AND (the list form of `condition:`)."""
    component_id: str
    predicate: str


class AutomationAction(_Strict):
    """The action side: a component takes an action its library
    `capability.accepts` declares. `args` are extra ESPHome action args
    (e.g. `{brightness: "50%"}`) that ride alongside the action target id.

    `transform` maps an action arg name to a C++ expression in terms of `x`
    (the value the trigger emits) -- the value→transform→action case. The
    generator lowers each entry to `<arg>: !lambda "return <expr>;"`. The
    expression is a reviewed recipe carried in design.json, not free-handed
    YAML: e.g. an encoder's count driving a stepper is
    `{"target": "(long) (x * 10)"}`.
    """
    component_id: str
    action: str
    args: dict = Field(default_factory=dict)
    transform: dict[str, str] = Field(default_factory=dict)


class Automation(_Strict):
    """One trigger→actions wiring (intent-to-device synthesis).

    The action list fires when the trigger event lands AND every entry in
    `conditions` holds. Conditions reference predicates the component declares
    via its `capability.checks`; the lowering wraps the actions in
    `if: { condition: ..., then: [...] }`. A transform on an action
    (phase 2) lowers to a `!lambda`. The periodic / stateful composition
    patterns from the design doc arrive in later phases. An automation
    referencing an unknown component / event / action / predicate surfaces as
    a permissive warning, not a hard failure (CLAUDE.md: warnings, don't block).
    """
    id: str
    trigger: AutomationTrigger
    conditions: list[AutomationCondition] = Field(default_factory=list)
    actions: list[AutomationAction]


class Fleet(_Strict):
    device_name: Optional[str] = None
    # Labels shown in the inspector; not passed to fleet-for-esphome or
    # ChirpStack.
    tags: list[str] = Field(default_factory=list)
    secrets_ref: dict[str, str] = Field(default_factory=dict)


class PayloadField(_Strict):
    """One slot in the LoRaWAN uplink payload, used by the external-component
    target path (`lorawan-for-esphome`). `sensor` is a design-level
    `component_id` whose current value is packed into the uplink; the
    ChirpStack `decodeUplink` codec is generated from the same ordered list so
    device wire bytes and server-side decoding stay in lockstep. The standalone
    Arduino path doesn't use this -- it packs the design's components.
    """
    sensor: str


class LoRaWAN(_Strict):
    """LoRaWAN target parameters. Region/sub-band must match the gateway; a
    mismatch makes the device transmit joins on channels the gateway never
    hears. Region defaults to US915 -- the only band exercised end-to-end at
    time of writing.

    Two generation paths share this block during the transition documented in
    `docs/lorawan/esphome-component-pivot.md` /
    `docs/lorawan/workflow-integration.md`:

    - **Standalone Arduino (`target="lorawan"`).** Reads the design's
      components, buses and connections like every other generator.
      Hardware-validated; stays shipping behind the `[lorawan]` install
      extra until the new path joins on real hardware.
    - **ESPHome external component (`target="esphome"` + `lorawan:` set).**
      Uses `payload` as the ordered uplink field list; the generator emits
      ESPHome YAML referencing `lorawan-for-esphome`. Keys ride
      `fleet.secrets_ref` and the rendered config uses `!secret` references --
      keys never land in design.json.

    `join_eui` is the only identity here: both paths default it to the zero
    EUI. The DevEUI is device-authoritative (read over serial, or passed to
    the provision endpoints by the caller) and the AppKey is minted at
    provision time, so neither is a design field.
    """
    region: Literal["US915", "EU868", "AU915", "AS923"] = "US915"
    sub_band: int = 2
    join_eui: Optional[str] = None                   # MSB hex; defaults applied downstream
    # New path (ESPHome external component): ordered uplink payload field list.
    payload: list[PayloadField] = Field(default_factory=list)


class Design(_Strict):
    # Every version `wirestudio.migrate` can read; a document is brought to
    # `migrate.CURRENT_SCHEMA_VERSION` before it is validated here.
    schema_version: Literal["0.1", "0.2", "0.3", "1.0"]
    id: str
    name: str
    description: Optional[str] = ""
    board: Board
    # `budget_ma` is the only power field the solver and generators read;
    # `supply`, `rail_voltage_v` and `regulator` record the supply the
    # design was made for and appear in no artifact.
    power: Power
    # The intent the design was built to meet. Edited in the inspector and
    # by the agent; no generator reads it.
    requirements: list[Requirement] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    buses: list[Bus] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    passives: list[Passive] = Field(default_factory=list)
    # Drawer substitutions accepted for subcircuit parts: "<component id>.
    # <part id>" -> MPN. Only the value printed on the part changes; the
    # symbol and footprint stay, which is what same-package substitution
    # means. The validator records each one with what was not compared.
    part_overrides: dict[str, str] = Field(default_factory=dict)
    # Behavioral graph: trigger -> actions wiring lowered into ESPHome
    # automations by the generator. Parallel to the physical `connections`
    # graph; optional, default empty so existing designs are unaffected.
    automations: list[Automation] = Field(default_factory=list)
    warnings: list[DesignWarning] = Field(default_factory=list)
    esphome_extras: dict = Field(default_factory=dict)
    fleet: Optional[Fleet] = None
    # Generation target. Defaults to "esphome" so every existing design
    # keeps its current behavior without a schema bump.
    target: Literal["esphome", "lorawan"] = "esphome"
    lorawan: Optional[LoRaWAN] = None
    # Strict mode. Permissive (default): electrical/CSP violations surface in
    # warnings but generation proceeds. Strict: any warn/error compatibility
    # entry or design warning blocks generation. Lives on the design so
    # generation stays a pure function of design.json.
    strict: bool = False
