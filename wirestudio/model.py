from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Board(_Strict):
    library_id: str
    mcu: str
    framework: str = "arduino"
    pinned_esphome_version: Optional[str] = None


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
    role: Optional[str] = None
    params: dict = Field(default_factory=dict)
    locked_pins: dict[str, str] = Field(default_factory=dict)
    # Set when the component was inserted as part of a composite module
    # (wirestudio/library/modules/). The BOM lists the module, not this part.
    module: Optional[ModuleRef] = None


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


ConnectionTarget = Annotated[
    Union[RailTarget, GpioTarget, BusTarget, ExpanderPinTarget, ComponentTarget],
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

    Phase 1 is declarative event→action; phase 2 adds value→transform→action
    via `AutomationAction.transform` (lowered to a `!lambda`). Condition
    gating and the periodic / stateful composition patterns from the design
    doc arrive in later phases. The generator lowers each automation onto the
    trigger component's params, where the existing ESPHome `params.on_*`
    passthrough in the library YAML emits it. An automation referencing an
    unknown component / event / action surfaces as a permissive warning, not a
    hard failure (CLAUDE.md: warnings, don't block).
    """
    id: str
    trigger: AutomationTrigger
    actions: list[AutomationAction]


class Fleet(_Strict):
    device_name: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    secrets_ref: dict[str, str] = Field(default_factory=dict)


class Agent(_Strict):
    session_id: Optional[str] = None
    history_ref: Optional[str] = None


class GpsSerial(_Strict):
    """An external GPS module wired to a UART, for boards without an onboard
    GPS. Pins are MCU-side: the GPS module's TX wire connects to `rx_pin`, its
    RX wire to `tx_pin`. (Onboard GPS is detected from the board, not here.)
    """
    rx_pin: str          # MCU RX  <- GPS module TX
    tx_pin: str          # MCU TX  -> GPS module RX
    baud: int = 9600


class Dht22(_Strict):
    """A DHT22 / AM2302 temperature + humidity sensor on a single data GPIO."""
    pin: str


class Oled(_Strict):
    """An SSD1306 128x64 OLED on the board's I2C bus, used as a status display
    (lat/lon/battery/temp). Not a payload field -- display only."""
    enabled: bool = True


class PayloadField(_Strict):
    """One slot in the LoRaWAN uplink payload, used by the external-component
    target path (`lorawan-for-esphome`). `sensor` is a design-level
    `component_id` whose current value is packed into the uplink; the
    ChirpStack `decodeUplink` codec is generated from the same ordered list so
    device wire bytes and server-side decoding stay in lockstep. The standalone
    Arduino path doesn't use this -- its fields are the explicit `gps`,
    `dht22`, `oled` blocks below.
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

    - **Standalone Arduino (`target="lorawan"`).** Uses `gps` / `dht22` /
      `oled` for hardcoded sensor blocks, plus `provisioning` for the runtime
      serial flow. Hardware-validated; stays shipping behind the `[lorawan]`
      install extra until the new path joins on real hardware.
    - **ESPHome external component (`target="esphome"` + `lorawan:` set).**
      Uses `payload` as the ordered uplink field list; the generator emits
      ESPHome YAML referencing `lorawan-for-esphome`. Keys ride
      `fleet.secrets_ref` and the rendered config uses `!secret` references --
      keys never land in design.json.

    `dev_eui` carries the value the device will use, whichever path: the
    standalone path fills it post-runtime-serial-provision; the new path
    accepts a manual override here (per the locked decision in
    workflow-integration.md), or it's filled post-provision after the eFuse
    MAC is read over WebSerial. Keys (AppKey / NwkKey) are deliberately
    absent: they are secrets.
    """
    region: Literal["US915", "EU868", "AU915", "AS923"] = "US915"
    sub_band: int = 2
    join_eui: Optional[str] = None                   # MSB hex; defaults applied downstream
    chirpstack_application_id: Optional[str] = None  # UUID
    device_profile_id: Optional[str] = None          # UUID
    provisioning: Literal["runtime_serial", "compile_time"] = "runtime_serial"
    dev_eui: Optional[str] = None                    # device-reported (standalone) or override / post-provision (new path)
    # New path (ESPHome external component): ordered uplink payload field list.
    payload: list[PayloadField] = Field(default_factory=list)
    # Standalone path: explicit per-feature sensor blocks. Unused by the new
    # path; retire when the standalone path retires.
    gps: Optional[GpsSerial] = None
    dht22: Optional[Dht22] = None
    oled: Optional[Oled] = None


class Design(_Strict):
    schema_version: Literal["0.1"]
    id: str
    name: str
    description: Optional[str] = ""
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    board: Board
    power: Power
    requirements: list[Requirement] = Field(default_factory=list)
    components: list[Component] = Field(default_factory=list)
    buses: list[Bus] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
    passives: list[Passive] = Field(default_factory=list)
    # Behavioral graph: trigger -> actions wiring lowered into ESPHome
    # automations by the generator. Parallel to the physical `connections`
    # graph; optional, default empty so existing designs are unaffected.
    automations: list[Automation] = Field(default_factory=list)
    warnings: list[DesignWarning] = Field(default_factory=list)
    esphome_extras: dict = Field(default_factory=dict)
    fleet: Optional[Fleet] = None
    agent: Optional[Agent] = None
    # Generation target. Defaults to "esphome" so every existing design
    # keeps its current behavior without a schema bump.
    target: Literal["esphome", "lorawan"] = "esphome"
    lorawan: Optional[LoRaWAN] = None
