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


class LoRaWAN(_Strict):
    """LoRaWAN target parameters. Region/sub-band are hard-pinned to the
    gateway (US915 sub-band 2); a mismatch makes the device transmit joins
    on channels the gateway never hears. `dev_eui` is device-authoritative
    and filled after runtime serial provisioning, not authored by hand.
    Keys (AppKey/NwkKey) are deliberately absent: they are secrets and
    never live in design.json.
    """
    region: Literal["US915"] = "US915"
    sub_band: int = 2
    join_eui: Optional[str] = None                   # MSB hex; defaults applied downstream
    chirpstack_application_id: Optional[str] = None  # UUID
    device_profile_id: Optional[str] = None          # UUID (US915 sub-2 profile)
    provisioning: Literal["runtime_serial", "compile_time"] = "runtime_serial"
    dev_eui: Optional[str] = None                    # device-reported, post-provision
    gps: Optional[GpsSerial] = None                  # external GPS on a UART
    dht22: Optional[Dht22] = None                    # DHT22 temp/humidity sensor
    oled: Optional[Oled] = None                      # SSD1306 status display


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
    warnings: list[DesignWarning] = Field(default_factory=list)
    esphome_extras: dict = Field(default_factory=dict)
    fleet: Optional[Fleet] = None
    agent: Optional[Agent] = None
    # Generation target. Defaults to "esphome" so every existing design
    # keeps its current behavior without a schema bump.
    target: Literal["esphome", "lorawan"] = "esphome"
    lorawan: Optional[LoRaWAN] = None
